"""
발주공고 수집 봇
World Bank API / UNGM API / ADB RSS / AfDB RSS / KOICA data.go.kr
농업 관련 기술용역 공고($1M 이상)를 병렬 수집 → bid_notices 테이블 저장
"""
import os
import re
import json
import hmac
import hashlib
import threading
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from flask import Blueprint, request, jsonify, current_app
from models import db, BidNotice, ScrapingRun

collector_bp = Blueprint('collector', __name__)

# ── 필터 키워드 ──────────────────────────────────────────────────────────────
AGRI_KEYWORDS = [
    'agriculture', 'agricultural', 'agri', 'farming', 'farm',
    'irrigation', 'rural', 'food security', 'food and agriculture',
    'crop', 'livestock', 'rice', 'grain', 'seed', 'fisheries',
    'forestry', 'water resource', 'drainage', 'land reclamation',
    'watershed', 'aquaculture', 'paddy', 'horticulture',
]

CONSULTING_KEYWORDS = [
    'consulting', 'technical assistance', 'advisory', 'supervision',
    'feasibility', 'project management', 'pmc', 'f/s', 'design',
    'capacity building', 'study', 'assessment', 'planning',
]

MIN_VALUE_USD = 1_000_000   # $1M


# ── 공통 유틸 ────────────────────────────────────────────────────────────────
def _is_agri(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in AGRI_KEYWORDS)


def _is_consulting(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in CONSULTING_KEYWORDS)


def _parse_value_usd(value_str: str) -> float:
    """'$2.3M', '2,300,000', '2300000 USD' → float (파싱 불가 시 0)"""
    if not value_str:
        return 0.0
    try:
        s = str(value_str).replace('$', '').replace(',', '').replace('USD', '').strip().upper()
        if 'M' in s:
            return float(s.replace('M', '')) * 1_000_000
        elif 'K' in s:
            return float(s.replace('K', '')) * 1_000
        elif 'B' in s:
            return float(s.replace('B', '')) * 1_000_000_000
        return float(s)
    except Exception:
        return 0.0


def _fmt_value(raw) -> str:
    """숫자 → '$2.3M' 표시용 문자열"""
    if not raw:
        return ''
    try:
        v = float(raw)
        if v >= 1_000_000:
            return f'${v/1_000_000:.1f}M'
        if v >= 1_000:
            return f'${v/1_000:.0f}K'
        return f'${v:,.0f}'
    except Exception:
        return str(raw)


# ── 상태/마감일 공통 헬퍼 ────────────────────────────────────────────────────
_DATE_RX = re.compile(r'(\d{4})[-./\s년]\s*(\d{1,2})[-./\s월]\s*(\d{1,2})')


def _parse_date_any(s: str):
    """YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD / 'YYYY년 MM월 DD일' / ISO datetime → date.
    파싱 실패 시 None."""
    if not s:
        return None
    raw = str(s).strip()
    try:
        iso = raw.replace('Z', '+00:00').split('T')[0]
        return datetime.fromisoformat(iso).date()
    except Exception:
        pass
    m = _DATE_RX.search(raw)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d).date()
    except Exception:
        return None


def _is_deadline_passed(deadline_str: str) -> bool:
    """마감일이 오늘(UTC)보다 이전이면 True. 파싱 실패 시 False(유지)."""
    d = _parse_date_any(deadline_str)
    if not d:
        return False
    return d < datetime.utcnow().date()


def _is_stale_pub(pub_date_str: str, days: int = 60) -> bool:
    """RSS pubDate(RFC 822) 기준 N일 이전이면 True. 파싱 실패 시 False."""
    if not pub_date_str:
        return False
    try:
        dt = parsedate_to_datetime(pub_date_str)
        if dt is None:
            return False
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        age = datetime.utcnow() - dt
        return age.days > days
    except Exception:
        return False


def _clean_html(text: str) -> str:
    """RSS description 등에서 HTML 태그 제거."""
    if not text:
        return ''
    return re.sub(r'<[^>]+>', ' ', str(text))


_VALUE_RX = re.compile(
    r'(?:USD|US\$|\$|UA|EUR|€)\s*([\d,\.]+)\s*(million|billion|M|B|K)?',
    re.IGNORECASE,
)


def _extract_value_from_text(text: str) -> str:
    """설명 텍스트에서 'USD 2.5 million' 같은 금액을 추출 → '$2.5M' 형식."""
    if not text:
        return ''
    m = _VALUE_RX.search(_clean_html(text))
    if not m:
        return ''
    try:
        num = float(m.group(1).replace(',', ''))
    except (TypeError, ValueError):
        return ''
    unit = (m.group(2) or '').lower()
    if unit in ('billion', 'b'):
        num *= 1_000_000_000
    elif unit in ('million', 'm'):
        num *= 1_000_000
    elif unit == 'k':
        num *= 1_000
    return _fmt_value(num)


def _decorate_title(title: str, notice_type: str) -> str:
    """제목에 [유형] 태그 부착 — 이미 포함되어 있으면 중복 방지."""
    title = (title or '').strip()
    notice_type = (notice_type or '').strip()
    if not notice_type:
        return title
    tag = f'[{notice_type}]'
    if tag.lower() in title.lower():
        return title
    return f'{title} {tag}'


# ── World Bank notice_text 파서 ──────────────────────────────────────────────
_WB_STOP_LABELS = [
    'Scope of Contract', 'Notice Version No', 'Procurement Method',
    'Loan/Credit/TF Info', 'Awarded Bidder(s)', 'Evaluated Bidder(s)',
    'Rejected Bidder(s)', 'Duration of Contract', 'Bid/Contract Reference No',
    'Date Notification', 'Contract Title', 'Grant No', 'Bid Price at Opening',
    'Contract Award', 'Project:', 'Country:',
]

_WB_PRICE_RX = re.compile(
    r'(?:Signed Contract price|Evaluated Bid Price|Awarded Price|Contract Price|Bid Price at Opening)'
    r'\s*[:\s]\s*([A-Z]{3}|US\$|USD|\$)\s*([\d,]+(?:\.\d+)?)',
    re.IGNORECASE,
)


def _wb_grab(plain: str, label: str) -> str:
    """notice_text 평문에서 label 다음 내용을 다음 라벨 전까지 추출."""
    stops_alt = '|'.join(re.escape(s) for s in _WB_STOP_LABELS if s != label)
    pat = rf'{re.escape(label)}\s*:?\s*(.+?)(?=\s+(?:{stops_alt})\s*[:\s]|$)'
    m = re.search(pat, plain, re.IGNORECASE)
    return m.group(1).strip()[:300] if m else ''


def _fmt_currency_amount(currency: str, amount_str: str) -> str:
    """('LSL', '1418732.00') → 'LSL 1.4M'. USD 계열은 'USD' 접두사."""
    try:
        v = float(amount_str.replace(',', ''))
    except (TypeError, ValueError):
        return ''
    cur = (currency or 'USD').upper().replace('US$', 'USD').replace('$', 'USD')
    if v >= 1_000_000:
        num = f'{v/1_000_000:.2f}M'
    elif v >= 1_000:
        num = f'{v/1_000:.1f}K'
    else:
        num = f'{v:,.0f}'
    return f'{cur} {num}'


def _wb_extract_details(raw_html: str) -> dict:
    """World Bank notice_text HTML에서 구조화된 필드 추출.
    Contract Award 공고에서 금액 / 낙찰자 / scope 등을 뽑는다."""
    if not raw_html:
        return {}
    plain = re.sub(r'\s+', ' ', _clean_html(raw_html)).strip()
    details = {}

    for key, label in [
        ('scope', 'Scope of Contract'),
        ('procurement_method', 'Procurement Method'),
        ('duration', 'Duration of Contract'),
        ('reference_no', 'Bid/Contract Reference No'),
        ('loan_credit', 'Loan/Credit/TF Info'),
        ('awarded_bidder', 'Awarded Bidder(s)'),
        ('contract_title', 'Contract Title'),
    ]:
        val = _wb_grab(plain, label)
        if val:
            details[key] = val

    m = _WB_PRICE_RX.search(plain)
    if m:
        formatted = _fmt_currency_amount(m.group(1), m.group(2))
        if formatted:
            details['contract_amount'] = formatted

    if plain:
        details['text_excerpt'] = plain[:1200]

    return details


def _save_notice(source, title, country, client, sector,
                 contract_value, deadline, source_url, raw_data) -> bool:
    """중복(source_url) 확인 후 BidNotice 저장. 신규면 True."""
    if not source_url or not title:
        return False
    existing = BidNotice.query.filter_by(source_url=source_url).first()
    if existing:
        return False
    n = BidNotice(
        source=source,
        title=title[:500],
        country=(country or '')[:100] or None,
        client=(client or '')[:200] or None,
        sector=(sector or '')[:100] or None,
        contract_value=(contract_value or '')[:100] or None,
        deadline=(deadline or '')[:50] or None,
        source_url=source_url[:500],
        status='new',
        raw_data=raw_data,
    )
    db.session.add(n)
    return True


# ── Tier 1: World Bank API ───────────────────────────────────────────────────
def _collect_worldbank() -> list:
    """World Bank Procurement Notices JSON API
    https://search.worldbank.org/api/procnotices — 인증 불필요
    응답 키: procnotices[], 최상위 total
    주요 필드: id, project_name, bid_description, notice_type, notice_status,
              project_ctry_name, contact_organization, submission_date, noticedate,
              procurement_method_name
    """
    import requests as req

    url = 'https://search.worldbank.org/api/procnotices'
    results = []
    offset = 0
    page_size = 100
    max_total = 500  # 농업 필터링 전 스캔 상한

    while offset < max_total:
        params = {
            'format': 'json',
            'apilang': 'en',
            'rows': page_size,
            'os': offset,
            'srt': 'submission_date',
            'strdesc': 'desc',   # 최신순
        }
        r = req.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        raw = data.get('procnotices') or []
        items = list(raw.values()) if isinstance(raw, dict) else raw
        if not items:
            break

        for item in items:
            title = (item.get('project_name') or item.get('bid_description') or '').strip()
            if not title:
                continue

            notice_type = (item.get('notice_type') or '').strip()
            # Contract Award 는 이미 낙찰 완료된 건이라 응찰 기회가 아님 → 수집 제외
            if notice_type.lower() == 'contract award':
                continue

            bid_desc = item.get('bid_description') or ''
            combined = f"{title} {bid_desc}"
            if not _is_agri(combined):
                continue

            # notice_status 가 Closed/Cancelled면 스킵 (Published/Revised/Draft은 유효)
            status = (item.get('notice_status') or '').lower()
            if status in ('closed', 'cancelled', 'canceled'):
                continue

            nid = (item.get('id') or '').strip()
            if not nid:
                continue
            source_url = f'https://projects.worldbank.org/en/projects-operations/procurement-detail/{nid}'

            # 마감일: submission_deadline_date > submission_date > noticedate
            deadline_raw = (item.get('submission_deadline_date')
                            or item.get('submission_date')
                            or item.get('noticedate') or '')
            deadline = deadline_raw[:10] if deadline_raw else ''

            # notice_text 파싱 — 금액 / scope / 낙찰자 등
            wb_details = _wb_extract_details(item.get('notice_text', ''))

            # contract_value: 파싱된 금액 > text에서 USD 추출 > 없음
            contract_value = (wb_details.get('contract_amount')
                              or _extract_value_from_text(item.get('notice_text', '')))

            # project_id 추가
            if item.get('project_id'):
                wb_details['project_id'] = item['project_id']
            # 연락처 정보
            for ck in ('contact_name', 'contact_email', 'contact_phone_no', 'contact_web_url'):
                if item.get(ck):
                    wb_details[ck] = item[ck]

            display_title = _decorate_title(title, notice_type)

            # raw_data 는 추출 결과만 저장 (용량 절감 — 원본 notice_text는 text_excerpt만)
            raw_light = {k: v for k, v in item.items() if k != 'notice_text'}
            raw_light['wb_details'] = wb_details

            results.append({
                'source': 'worldbank',
                'title': display_title,
                'country': (item.get('project_ctry_name') or '').strip(),
                'client': (item.get('contact_organization') or '').strip() or 'World Bank',
                'sector': 'agriculture',
                'contract_value': contract_value,
                'deadline': deadline,
                'source_url': source_url,
                'raw_data': raw_light,
            })

        total_raw = data.get('total')
        try:
            total = int(total_raw) if total_raw is not None else 0
        except (TypeError, ValueError):
            total = 0
        offset += len(items)
        if total and offset >= total:
            break

    return results


# ── Tier 1: UNGM API ────────────────────────────────────────────────────────
def _collect_ungm() -> list:
    """UNGM — API 키 있으면 developer.ungm.org, 없으면 공개 POST AJAX 스크래핑"""
    api_key = os.environ.get('UNGM_API_KEY', '')

    try:
        import requests as req
    except ImportError:
        return []

    # ── API 키 있는 경우: developer.ungm.org ──────────────────────────────
    if api_key:
        url = 'https://developer.ungm.org/api/v1/notices'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/json',
        }
        results = []
        page = 0
        page_size = 50

        while True:
            params = {
                'TenderStatusCode': 'AC',
                'DeadlineFrom': datetime.utcnow().strftime('%Y-%m-%d'),
                'Keywords': 'agriculture irrigation rural food consulting technical',
                'PageSize': page_size,
                'PageIndex': page,
            }
            try:
                r = req.get(url, headers=headers, params=params, timeout=12)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                print(f'[UNGM-API] page {page} 요청 오류: {e}')
                break

            items = data.get('Notices') or data.get('notices') or []
            if not items:
                break

            for item in items:
                title = (item.get('Title') or item.get('title') or '').strip()
                desc = item.get('Description') or item.get('description') or ''
                combined = f"{title} {desc}"

                if not _is_agri(combined) and not _is_consulting(combined):
                    continue

                value_raw = item.get('EstimatedValue') or item.get('estimatedValue') or 0
                if value_raw and _parse_value_usd(str(value_raw)) < MIN_VALUE_USD:
                    continue

                deadline_raw = item.get('Deadline') or item.get('deadline') or ''
                deadline = deadline_raw[:10] if deadline_raw else ''
                if _is_deadline_passed(deadline):
                    continue

                source_url = (item.get('NoticeUrl') or item.get('noticeUrl') or
                              item.get('Url') or '').strip()
                if not source_url:
                    notice_id = item.get('Id') or item.get('id') or ''
                    source_url = f'https://www.ungm.org/Public/Notice/{notice_id}'

                country = (item.get('Country') or item.get('country') or '').strip()
                org = (item.get('AgencyName') or item.get('agencyName')
                       or item.get('Beneficiary') or 'UN')
                notice_type = (item.get('TypeName') or item.get('NoticeType')
                               or item.get('typeName') or '')
                sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

                results.append({
                    'source': 'ungm',
                    'title': _decorate_title(title, notice_type),
                    'country': country,
                    'client': org,
                    'sector': sector,
                    'contract_value': _fmt_value(value_raw) if value_raw else '',
                    'deadline': deadline,
                    'source_url': source_url,
                    'raw_data': item,
                })

            if len(items) < page_size:
                break
            page += 1

        return results

    # ── API 키 없는 경우: 공개 POST AJAX 스크래핑 (무인증) ─────────────────
    results = []
    search_url = 'https://www.ungm.org/Public/Notice/Search'
    payload = {
        'Keywords': 'agriculture irrigation rural farming consulting technical',
        'NoticeTypes': [3, 4],  # RFQ=3, RFP=4
        'PageIndex': 0,
        'PageSize': 50,
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)',
    }
    r = req.post(search_url, json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f'UNGM Search POST {r.status_code}')
    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(f'UNGM 응답 JSON 파싱 실패: {e}') from e

    for item in data.get('Notices', []):
        title = (item.get('Title') or '').strip()
        nid   = item.get('NoticeId', '')
        if not title or not nid:
            continue
        combined = title
        if not _is_agri(combined) and not _is_consulting(combined):
            continue
        deadline = (item.get('DeadlineDate') or '')[:10]
        if _is_deadline_passed(deadline):
            continue

        status_code = (item.get('NoticeStatusCode') or item.get('Status') or '').strip().upper()
        if status_code and status_code not in ('AC', 'ACTIVE', 'PUB', 'PUBLISHED', ''):
            continue

        notice_type = (item.get('NoticeTypeName') or item.get('TypeName')
                       or item.get('NoticeType') or '')
        if isinstance(notice_type, int):
            notice_type = {3: 'RFQ', 4: 'RFP'}.get(notice_type, '')
        org = (item.get('AgencyName') or item.get('Beneficiary') or 'UN').strip()
        sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

        results.append({
            'source': 'ungm',
            'title': _decorate_title(title, notice_type),
            'country': (item.get('Country') or '').strip(),
            'client': org,
            'sector': sector,
            'contract_value': '',
            'deadline': deadline,
            'source_url': f'https://www.ungm.org/Public/Notice/{nid}',
            'raw_data': item,
        })

    return results


# ── Tier 2: ADB RSS ──────────────────────────────────────────────────────────
def _collect_adb() -> list:
    """ADB — RSS 우선, 실패 시 HTML 스크래핑"""
    try:
        import requests as req
    except ImportError:
        return []

    results = []
    attempts_errors = []

    # RSS 시도
    rss_urls = [
        'https://www.adb.org/rss/projects-tenders.xml',
        'https://www.adb.org/projects/tenders.rss',
    ]
    rss_ok = False
    for rss_url in rss_urls:
        try:
            r = req.get(rss_url, timeout=10)
            if r.status_code != 200:
                attempts_errors.append(f'RSS {rss_url} HTTP {r.status_code}')
                continue
            root = ElementTree.fromstring(r.content)
            for item in root.findall('.//item'):
                title = item.findtext('title') or ''
                link = item.findtext('link') or ''
                desc = item.findtext('description') or ''
                desc_text = _clean_html(desc)
                combined = f"{title} {desc_text}"

                if not _is_agri(combined) and not _is_consulting(combined):
                    continue
                if not link:
                    continue

                pub_date = item.findtext('pubDate') or ''
                # 60일 이상 경과한 공고 제외
                if _is_stale_pub(pub_date, days=60):
                    continue

                # notice type: <category> 또는 description 의 "Consulting Services" 류
                category = item.findtext('category') or ''
                notice_type = category.strip() if category else ''
                if not notice_type and 'consulting' in desc_text.lower():
                    notice_type = 'Consulting'

                # country: description 에서 'Country: XXX' 패턴 추출
                country = ''
                m = re.search(r'Country\s*[:\-]\s*([A-Z][A-Za-z ,\-]+)', desc_text)
                if m:
                    country = m.group(1).strip().rstrip('.,')[:100]

                # client: 'Executing Agency: XXX' / 'Borrower: XXX' 패턴
                client = 'ADB'
                m = re.search(r'(?:Executing Agency|Borrower)\s*[:\-]\s*([^\n<;]+)', desc_text)
                if m:
                    client = m.group(1).strip()[:200]

                sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

                results.append({
                    'source': 'adb',
                    'title': _decorate_title(title, notice_type),
                    'country': country,
                    'client': client,
                    'sector': sector,
                    'contract_value': _extract_value_from_text(desc_text),
                    'deadline': pub_date[:10] if pub_date else '',
                    'source_url': link,
                    'raw_data': {'title': title, 'link': link, 'description': desc},
                })
            rss_ok = True
            break
        except Exception as e:
            attempts_errors.append(f'RSS {rss_url}: {e}')
            continue

    # RSS 실패 시 HTML 스크래핑 (beautifulsoup4)
    html_ok = False
    if not rss_ok:
        try:
            from bs4 import BeautifulSoup
            html_url = 'https://www.adb.org/projects/tenders?type=Consulting+Services'
            r = req.get(html_url, timeout=12,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)'})
            if r.status_code != 200:
                attempts_errors.append(f'HTML HTTP {r.status_code}')
            else:
                html_ok = True
                soup = BeautifulSoup(r.text, 'html.parser')
                # 다중 셀렉터 — 사이트 구조 변경 대비
                rows = (soup.select('table.tender-table tbody tr')
                        or soup.select('.views-row')
                        or soup.select('article.node, .search-result'))
                print(f'[ADB-HTML] rows found: {len(rows)}')
                for row in rows:
                    title_el = (row.select_one('td.views-field-title a')
                                or row.select_one('.views-field-title a')
                                or row.select_one('h2 a, h3 a, a.title'))
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    href = title_el.get('href', '')
                    if href.startswith('/'):
                        href = 'https://www.adb.org' + href

                    row_text = row.get_text(' ', strip=True)
                    combined = title + ' ' + row_text
                    if not _is_agri(combined) and not _is_consulting(combined):
                        continue

                    sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'
                    results.append({
                        'source': 'adb',
                        'title': title,
                        'country': '',
                        'client': 'ADB',
                        'sector': sector,
                        'contract_value': _extract_value_from_text(row_text),
                        'deadline': '',
                        'source_url': href,
                        'raw_data': {'title': title, 'url': href},
                    })
        except Exception as e:
            attempts_errors.append(f'HTML: {e}')

    if attempts_errors:
        print(f'[ADB] attempt errors: {attempts_errors}')
    if not rss_ok and not html_ok:
        raise RuntimeError('ADB 모든 수집 경로 실패: ' + ' | '.join(attempts_errors))

    return results


# ── Tier 2: AfDB RSS ────────────────────────────────────────────────────────
def _collect_afdb() -> list:
    """AfDB — RSS 우선, 실패 시 HTML 스크래핑"""
    try:
        import requests as req
    except ImportError:
        return []

    results = []
    attempts_errors = []

    # RSS 시도
    rss_urls = [
        'https://www.afdb.org/en/news-and-events/rss/tenders.xml',
        'https://www.afdb.org/en/rss/tenders',
    ]
    rss_ok = False
    for rss_url in rss_urls:
        try:
            r = req.get(rss_url, timeout=10,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)'})
            if r.status_code != 200 or not r.content:
                attempts_errors.append(f'RSS {rss_url} HTTP {r.status_code}')
                continue
            root = ElementTree.fromstring(r.content)
            for item in root.findall('.//item'):
                title = item.findtext('title') or ''
                link = item.findtext('link') or ''
                desc = item.findtext('description') or ''
                desc_text = _clean_html(desc)
                combined = f"{title} {desc_text}"

                if not _is_agri(combined):
                    continue
                if not link:
                    continue
                # tenders 피드가 아닌 news/success-stories 항목 제외
                if any(p in link for p in ('/success-stories/', '/news-and-events/', '/projects-and-operations/')):
                    if not _is_consulting(combined):
                        continue

                pub_date = item.findtext('pubDate') or ''
                if _is_stale_pub(pub_date, days=60):
                    continue

                # country: dc:subject 중 지명만 채택 (쉼표/세미콜론 분리 후 첫 값)
                country_el = item.find('{http://purl.org/dc/elements/1.1/}subject')
                raw_country = country_el.text.strip() if country_el is not None else ''
                country = ''
                if raw_country:
                    parts = re.split(r'[;,/]', raw_country)
                    country = parts[0].strip()[:100]

                # notice type: dc:type 또는 category
                type_el = item.find('{http://purl.org/dc/elements/1.1/}type')
                notice_type = type_el.text.strip() if type_el is not None else ''
                if not notice_type:
                    notice_type = (item.findtext('category') or '').strip()

                sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

                results.append({
                    'source': 'afdb',
                    'title': _decorate_title(title, notice_type),
                    'country': country,
                    'client': 'AfDB',
                    'sector': sector,
                    'contract_value': _extract_value_from_text(desc_text),
                    'deadline': pub_date[:10] if pub_date else '',
                    'source_url': link,
                    'raw_data': {'title': title, 'link': link, 'description': desc},
                })
            rss_ok = True
            break
        except Exception as e:
            attempts_errors.append(f'RSS {rss_url}: {e}')
            continue

    # RSS 실패 시 HTML 스크래핑
    html_ok = False
    if not rss_ok:
        try:
            from bs4 import BeautifulSoup
            html_url = ('https://www.afdb.org/en/documents/project-related-procurement'
                        '/procurement-notices/specific-procurement-notices')
            r = req.get(html_url, timeout=12,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)'})
            if r.status_code != 200:
                attempts_errors.append(f'HTML HTTP {r.status_code}')
            else:
                html_ok = True
                soup = BeautifulSoup(r.text, 'html.parser')
                anchors = (soup.select('.field-content a')
                           or soup.select('.views-field-title a')
                           or soup.select('article h2 a, article h3 a, .search-result a'))
                print(f'[AfDB-HTML] anchors found: {len(anchors)}')
                for a in anchors:
                    title = a.get_text(strip=True)
                    href = a.get('href', '')
                    if not title or not href:
                        continue
                    if href.startswith('/'):
                        href = 'https://www.afdb.org' + href

                    if not _is_agri(title) and not _is_consulting(title):
                        continue

                    sector = 'consulting' if _is_consulting(title) and not _is_agri(title) else 'agriculture'
                    results.append({
                        'source': 'afdb',
                        'title': title,
                        'country': '',
                        'client': 'AfDB',
                        'sector': sector,
                        'contract_value': '',
                        'deadline': '',
                        'source_url': href,
                        'raw_data': {'title': title, 'url': href},
                    })
        except Exception as e:
            attempts_errors.append(f'HTML: {e}')

    if attempts_errors:
        print(f'[AfDB] attempt errors: {attempts_errors}')
    if not rss_ok and not html_ok:
        raise RuntimeError('AfDB 모든 수집 경로 실패: ' + ' | '.join(attempts_errors))

    return results


# ── Tier 2: KOICA / data.go.kr ──────────────────────────────────────────────

# 농업 + 해외기술용역 통합 키워드
_KOICA_KEYWORDS = [
    # 농업
    '농업', '농촌', '관개', '식량', '작물', '수산', '산림', '농지', '용수',
    # 해외기술용역
    '기술용역', '컨설팅', '자문', '기술협력', '용역', '타당성',
    '기술지원', '기술조사', '사업관리', 'PMC', 'PMO', '조사연구',
]


def _collect_koica() -> list:
    """KOICA — API 키 있으면 data.go.kr, 없으면 HTML 스크래핑 fallback"""
    service_key = os.environ.get('KOICA_API_KEY', '')

    try:
        import requests as req
    except ImportError:
        return []

    # ── API 키 있는 경우: data.go.kr ─────────────────────────────────────
    if service_key:
        results = []
        url = 'https://apis.data.go.kr/1390802/koica_bid/koicaBidList'
        params = {
            'serviceKey': service_key,
            'pageNo': 1,
            'numOfRows': 100,
            'type': 'json',
        }
        try:
            r = req.get(url, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
            items = (data.get('response', {})
                         .get('body', {})
                         .get('items', {})
                         .get('item', []))
            if isinstance(items, dict):
                items = [items]

            for item in items:
                title = (item.get('bidNm') or item.get('title') or '').strip()
                combined = title + ' ' + str(item)
                if not _is_agri(combined) and not _is_consulting(combined):
                    continue

                # 상태 필터: '공고중' 이외(마감/취소) 제외
                status = (item.get('bidPblancSttusCode')
                          or item.get('bidPblancSttusNm')
                          or item.get('status') or '').strip()
                if status and not (status in ('01', '공고중', 'OPEN', 'ACTIVE')
                                   or '공고' in status):
                    continue

                deadline = (item.get('bidClseDt') or '')[:10]
                if _is_deadline_passed(deadline):
                    continue

                source_url = item.get('bidUrl') or item.get('url') or ''
                bid_no = item.get('bidNo') or item.get('id') or ''
                if not source_url and bid_no:
                    source_url = f'https://www.koica.go.kr/koica_kr/bid/view/{bid_no}'
                if not source_url:
                    continue

                notice_type = (item.get('bidPblancKndNm')
                               or item.get('bidKndNm') or '').strip()
                sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

                results.append({
                    'source': 'koica',
                    'title': _decorate_title(title, notice_type),
                    'country': (item.get('country') or '').strip(),
                    'client': 'KOICA',
                    'sector': sector,
                    'contract_value': (item.get('bidAmt') or '').strip(),
                    'deadline': deadline,
                    'source_url': source_url,
                    'raw_data': item,
                })
        except Exception as e:
            print(f'[KOICA-API] 요청 오류: {e}')
        return results

    # ── API 키 없는 경우: HTML 스크래핑 fallback ──────────────────────────
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    list_url = 'https://www.koica.go.kr/koica_kr/bid/selectBidList.do'
    headers  = {'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)'}
    results  = []
    seen     = set()
    errors_per_kw = []
    success_count = 0

    # 키워드별로 수집 대분류를 구분 (농업 키워드 vs 기술용역 키워드)
    _AGRI_KW = {'농업', '농촌', '관개', '식량', '작물', '수산', '산림', '농지', '용수'}

    for kw in _KOICA_KEYWORDS:
        kw_sector = 'agriculture' if kw in _AGRI_KW else 'consulting'
        for page in range(1, 4):  # 최대 3페이지까지 순회
            try:
                r = req.get(list_url,
                            params={'pageIndex': page, 'searchWrd': kw},
                            headers=headers, timeout=20)
                if r.status_code != 200:
                    errors_per_kw.append(f'{kw}p{page}:HTTP{r.status_code}')
                    break
                if page == 1:
                    success_count += 1
                soup = BeautifulSoup(r.text, 'html.parser')

                rows = (soup.select('table tbody tr')
                        or soup.select('.board-list tr, .list-type tr, .bbs-list tr'))
                if not rows:
                    break

                page_added = 0
                for row in rows:
                    title_el = row.select_one('td a, td .title a')
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    if not title:
                        continue

                    href = title_el.get('href', '')
                    url  = ('https://www.koica.go.kr' + href
                            if href.startswith('/') else href)
                    if url in seen:
                        continue
                    seen.add(url)

                    cols = row.select('td')
                    col_texts = [c.get_text(strip=True) for c in cols]

                    # 상태 컬럼 ('공고중' / '마감' / '취소' 등) — 존재하면 필터
                    status_text = ''
                    for t in col_texts:
                        if t in ('공고중', '마감', '취소', '재공고', '일반공고', '긴급공고'):
                            status_text = t
                            break
                    if status_text in ('마감', '취소'):
                        continue

                    # 마지막 컬럼을 마감일로 가정 — 지난 날짜면 skip
                    deadline = col_texts[-1] if col_texts else ''
                    if _is_deadline_passed(deadline):
                        continue

                    # 유형 태그 (재공고/긴급공고/일반공고)
                    notice_type = ''
                    for t in col_texts:
                        if t in ('재공고', '긴급공고', '일반공고'):
                            notice_type = t
                            break

                    page_added += 1
                    results.append({
                        'source': 'koica',
                        'title': _decorate_title(title, notice_type),
                        'country': '',
                        'client': 'KOICA',
                        'sector': kw_sector,
                        'contract_value': '',
                        'deadline': deadline,
                        'source_url': url,
                        'raw_data': {'title': title, 'keyword': kw, 'page': page},
                    })

                # 이 페이지에서 유효 행이 하나도 없으면 다음 페이지로 안 넘어감
                if page_added == 0:
                    break
            except Exception as e:
                errors_per_kw.append(f'{kw}p{page}:{type(e).__name__}')
                break

    if errors_per_kw:
        print(f'[KOICA-HTML] 실패 키워드: {errors_per_kw[:10]}')
    # 모든 키워드 요청이 실패했으면 에러로 표면화
    if success_count == 0 and errors_per_kw:
        raise RuntimeError('KOICA 모든 키워드 요청 실패: ' + ', '.join(errors_per_kw[:5]))

    return results


# ── 수집 실행 ────────────────────────────────────────────────────────────────
COLLECTORS = {
    'worldbank': _collect_worldbank,
    'ungm':      _collect_ungm,
    'adb':       _collect_adb,
    'afdb':      _collect_afdb,
    'koica':     _collect_koica,
}

SOURCE_DISPLAY = {
    'worldbank': 'World Bank',
    'ungm':      'UNGM',
    'adb':       'ADB',
    'afdb':      'AfDB',
    'koica':     'KOICA',
}


def _run_all_collectors() -> tuple[list, dict]:
    """모든 수집기를 ThreadPoolExecutor로 병렬 실행"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import traceback

    all_items = []
    errors = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_name = {executor.submit(fn): name
                          for name, fn in COLLECTORS.items()}
        for future in as_completed(future_to_name, timeout=55):
            name = future_to_name[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f'[collector] {name}: fetched {len(items)} items')
            except Exception as e:
                errors[name] = str(e)
                print(f'[collector] {name}: FAILED — {e}')
                traceback.print_exc()

    return all_items, errors


# ── 엔드포인트 ───────────────────────────────────────────────────────────────
def _check_collect_auth() -> bool:
    """COLLECT_SECRET 환경변수로 인증 확인
    - Vercel Cron: Authorization: Bearer $CRON_SECRET (환경변수와 동일)
    - 수동 호출: 같은 헤더 전송
    - 개발환경(secret 미설정): 통과
    """
    secret = os.environ.get('COLLECT_SECRET', '')
    if not secret:
        return True  # 개발 환경
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {secret}'


@collector_bp.route('/collect', methods=['POST'])
def collect_notices():
    """
    발주공고 수집 트리거
    - Vercel Cron이 매일 UTC 01:00에 자동 호출
    - 관리자가 프론트엔드 버튼으로 수동 호출
    인증: Authorization: Bearer <COLLECT_SECRET>
    """
    if not _check_collect_auth():
        return jsonify({'success': False, 'message': '인증 실패'}), 401

    all_items, errors = _run_all_collectors()

    created = 0
    skipped = 0
    created_by_source = {}
    fetched_by_source = {}

    for item in all_items:
        src = item['source']
        fetched_by_source[src] = fetched_by_source.get(src, 0) + 1
        saved = _save_notice(
            source=src,
            title=item['title'],
            country=item.get('country', ''),
            client=item.get('client', ''),
            sector=item.get('sector', ''),
            contract_value=item.get('contract_value', ''),
            deadline=item.get('deadline', ''),
            source_url=item['source_url'],
            raw_data=item.get('raw_data'),
        )
        if saved:
            created += 1
            created_by_source[src] = created_by_source.get(src, 0) + 1
        else:
            skipped += 1

    # 실행 이력 기록 — Vercel Cron / 관리자 수동 모두 이 경로
    trigger = (request.args.get('trigger') or 'scheduled').strip()[:20]
    sources_summary = [
        {
            'name':  SOURCE_DISPLAY.get(key, key),
            'count': fetched_by_source.get(key, 0),
            'error': errors.get(key),
        }
        for key in COLLECTORS.keys()
    ]
    db.session.add(ScrapingRun(
        trigger=trigger,
        total_found=len(all_items),
        total_created=created,
        total_skipped=skipped,
        sources=sources_summary,
    ))

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'DB 저장 실패: {e}'}), 500

    return jsonify({
        'success': True,
        'created': created,
        'skipped': skipped,
        'total_fetched': len(all_items),
        'by_source': created_by_source,
        'errors': errors,
        'collected_at': datetime.utcnow().isoformat() + 'Z',
    })


@collector_bp.route('/collect/status', methods=['GET'])
def collect_status():
    """수집 현황 — 소스별 공고 수 조회 (인증 토큰 필요)"""
    from routes.auth import token_required

    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return jsonify({'success': False, 'message': '인증 필요'}), 401

    try:
        rows = (db.session.query(BidNotice.source, db.func.count(BidNotice.id))
                .group_by(BidNotice.source)
                .all())
        by_source = {src: cnt for src, cnt in rows}
        total = sum(by_source.values())
        new_count = BidNotice.query.filter_by(status='new').count()
        latest = (BidNotice.query
                  .order_by(BidNotice.created_at.desc())
                  .first())
        return jsonify({
            'success': True,
            'total': total,
            'new': new_count,
            'by_source': by_source,
            'last_collected': latest.created_at.isoformat() + 'Z' if latest else None,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
