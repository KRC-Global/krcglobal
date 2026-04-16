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
    'consulting', 'consultancy', 'consultant', 'technical assistance',
    'advisory', 'supervision', 'feasibility', 'project management', 'pmc',
    'f/s', 'design', 'capacity building', 'study', 'assessment', 'planning',
    'engineering services', 'detailed design',
]

# 한국어 키워드 (KOICA nebid 등 국문 공고용)
AGRI_KEYWORDS_KO = [
    '농업', '농촌', '관개', '식량', '작물', '수산', '산림', '농지',
    '용수', '양식', '축산', '수자원', '간척', '개간',
]

CONSULTING_KEYWORDS_KO = [
    '용역', '기술용역', '컨설팅', '자문', '기술협력', '타당성',
    '기술지원', '기술조사', '사업관리', '조사연구', '기본설계', '실시설계',
    'PMC', 'PMO', 'TA',
]


def _is_agri_ko(text: str) -> bool:
    return any(kw in (text or '') for kw in AGRI_KEYWORDS_KO)


def _is_consulting_ko(text: str) -> bool:
    return any(kw in (text or '') for kw in CONSULTING_KEYWORDS_KO)

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


# 수집 공통 최근성 컷오프 — 게시 후 이 기간 지나면 "과거 사업"으로 간주하고 제외
DEFAULT_FRESHNESS_DAYS = 90


def _is_stale_date(date_str: str, days: int = DEFAULT_FRESHNESS_DAYS) -> bool:
    """범용 날짜 문자열(ISO, YYYY-MM-DD, YYYY.MM.DD, 'Month DD, YYYY' 등) 기준
    N일 이전에 게시됐으면 True. 파싱 실패 시 False(유지 — 과잉 제외 방지).
    """
    if not date_str:
        return False
    d = _parse_date_any(date_str)
    if d is None:
        # 'April 15, 2026' 형식 재시도
        for fmt in ('%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y'):
            try:
                d = datetime.strptime(str(date_str).strip(), fmt).date()
                break
            except ValueError:
                continue
    if d is None:
        return False
    age = (datetime.utcnow().date() - d).days
    return age > days


def _is_current_year_or_recent(url_or_text: str, max_years_back: int = 1) -> bool:
    """URL 또는 텍스트에서 연도를 추출해 '현재 연도 - max_years_back' 이상이면 True.
    현재 연도보다 오래된 공고(아카이브)를 걸러내기 위한 빠른 체크."""
    current_year = datetime.utcnow().year
    threshold = current_year - max_years_back
    for ym in re.findall(r'\b(20\d{2})\b', url_or_text or ''):
        if int(ym) >= threshold:
            return True
    # 연도 표기가 없으면 보수적으로 통과(= True)
    return True


def _clean_html(text: str) -> str:
    """RSS description 등에서 HTML 태그 제거."""
    if not text:
        return ''
    return re.sub(r'<[^>]+>', ' ', str(text))


# 통화 코드 화이트리스트 — ISO 4217 주요 + 개도국 통화
_CURRENCY_CODES = (
    'USD|US\\$|EUR|€|GBP|£|JPY|¥|CNY|RMB|KRW'
    r'|INR|IDR|PHP|THB|VND|MYR|SGD|HKD|TWD|PKR|BDT|LKR|NPR|MVR'
    r'|NGN|EGP|ZAR|KES|UGX|TZS|ETB|GHS|MAD|DZD|TND|XOF|XAF|MZN'
    r'|BRL|MXN|ARS|COP|CLP|PEN|USCOL'
    r'|AUD|NZD|CAD|CHF'
    r'|RUB|TRY|SAR|AED|QAR|KWD|OMR|BHD|IQD'
    r'|KZT|KGS|UZS|TJS|AZN|GEL|AMD|LSL|BWP'
    r'|UA'  # AfDB 계산단위
)

_VALUE_RX = re.compile(
    rf'({_CURRENCY_CODES})\s*([\d,\.]+)\s*(million|billion|trillion|mln|bn|M|B|K)?',
    re.IGNORECASE,
)

# 라벨 키워드 뒤 금액 — 통화코드 또는 규모단위(million/billion) 중 하나는 필수
# (단순 'Financing No. 1028' 같은 ID 번호와 구분하기 위함)
_VALUE_LABELED_RX = re.compile(
    rf'(?:Total\s+(?:Project\s+)?Cost|Contract\s+(?:Price|Value|Amount)|'
    rf'Estimated\s+(?:Cost|Value|Budget|Amount)|Loan\s+Amount|'
    rf'Project\s+(?:Budget|Cost)|Budget\s+Amount)'
    rf'[^\d\n]{{0,30}}?({_CURRENCY_CODES})\s*([\d,]+(?:\.\d+)?)\s*'
    rf'(million|billion|trillion|mln|bn|M|B|K)?',
    re.IGNORECASE,
)

_MIN_CONTRACT_USD_THRESHOLD = 10_000  # 1만 USD 미만은 noise(참조번호 등)로 간주


def _format_compact_money(currency: str, raw_amount: str, unit: str = '',
                          min_threshold: float = 0) -> str:
    """('USD', '1,234,567', 'M') → 'USD 1.23M' 형식. 통화 USD 계열은 '$' 사용.

    min_threshold: USD 환산 대략적 최소값. 참조번호(1028 같은 것)를 금액으로
    잘못 인식하는 것을 막기 위해 사용. 0 이면 비활성.
    """
    try:
        num = float(raw_amount.replace(',', ''))
    except (TypeError, ValueError):
        return ''
    unit_lower = (unit or '').lower()
    if unit_lower in ('billion', 'bn', 'b'):
        num *= 1_000_000_000
    elif unit_lower in ('million', 'mln', 'm'):
        num *= 1_000_000
    elif unit_lower in ('k',):
        num *= 1_000

    # 임계값 검사 — 단, 통화가 IDR/VND/UZS 같이 단위가 작은 경우는 예외 허용
    cur_raw = (currency or '').upper().replace('US$', 'USD').replace('$', 'USD')
    small_unit_currencies = {'IDR', 'VND', 'UZS', 'KRW', 'JPY', 'PKR', 'NGN',
                             'PHP', 'KGS', 'KZT', 'MVR', 'UGX', 'TZS', 'RWF',
                             'LKR', 'NPR', 'BDT', 'MGA', 'LSL', 'ETB', 'MNT'}
    threshold = min_threshold
    if cur_raw in small_unit_currencies and threshold:
        # 현지 통화는 USD 환산 시 훨씬 큰 값 → 임계값 적용 완화
        threshold = threshold * 10  # 약식: 100K 로컬통화는 대개 1만 USD 미만
    if threshold and num < threshold:
        return ''

    if cur_raw in ('€', 'EURO'):
        cur_raw = 'EUR'
    elif cur_raw == '£':
        cur_raw = 'GBP'
    elif cur_raw == '¥':
        cur_raw = 'JPY'

    if num >= 1_000_000_000:
        amt = f'{num/1_000_000_000:.2f}B'
    elif num >= 1_000_000:
        amt = f'{num/1_000_000:.2f}M'
    elif num >= 1_000:
        amt = f'{num/1_000:.1f}K'
    else:
        amt = f'{num:,.0f}'

    return f'{cur_raw} {amt}'.strip() if cur_raw else amt


def _extract_value_from_text(text: str) -> str:
    """설명·본문 텍스트에서 금액을 추출해 압축 표시.
    최소 임계값(1만 USD 상당) 이상만 채택해 참조번호·파일크기 등 noise 제거.
    """
    if not text:
        return ''
    clean = _clean_html(text)
    # 1) 라벨 있는 금액 우선 — 단위가 명시된 큰 금액일 가능성 높음
    m = _VALUE_LABELED_RX.search(clean)
    if m:
        val = _format_compact_money(m.group(1), m.group(2), m.group(3),
                                    min_threshold=_MIN_CONTRACT_USD_THRESHOLD)
        if val:
            return val
    # 2) 일반 패턴 — 임계값 적용
    m = _VALUE_RX.search(clean)
    if m:
        return _format_compact_money(m.group(1), m.group(2), m.group(3),
                                     min_threshold=_MIN_CONTRACT_USD_THRESHOLD)
    return ''


def _compact_currency_phrase(raw: str) -> str:
    """AIIB 의 pc 필드처럼 이미 통화코드 + 숫자가 들어있는 문자열을 압축.
    예: 'INR 3,341,462,535.35' → 'INR 3.34B'
        'Lot 1: USD 1,234 Lot 2: USD 5,678' → 'USD 1.2K (외 1건)'
    """
    if not raw:
        return ''
    s = raw.strip()
    # 여러 줄/여러 조각이면 첫 매치만 + '외 N건' 표기
    parts = re.split(r'[\n;]+', s)
    first_match = None
    extra = 0
    for part in parts:
        m = _VALUE_RX.search(part)
        if m:
            if first_match is None:
                first_match = m
            else:
                extra += 1
    if not first_match:
        return s[:60]  # 매칭 실패 시 원문 앞 60자만

    compact = _format_compact_money(first_match.group(1),
                                    first_match.group(2),
                                    first_match.group(3))
    if extra > 0:
        compact += f' (외 {extra}건)'
    return compact


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


def _browser_headers(referer: str = '') -> dict:
    """WAF(Cloudflare 등) 우회 시도용 실제 브라우저 유사 헤더 세트.
    데이터센터 IP 차단은 피하지 못할 수 있으나 UA-only 차단은 회피 가능."""
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    }
    if referer:
        headers['Referer'] = referer
        headers['Sec-Fetch-Site'] = 'same-origin'
    return headers


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

            # 최근성 필터: 마감일이 과거이거나, 마감일 없으면 공고일이 90일 이전이면 제외
            if _is_deadline_passed(deadline):
                continue
            if not deadline:
                posted = (item.get('noticedate') or item.get('submission_date') or '')
                if _is_stale_date(posted, days=DEFAULT_FRESHNESS_DAYS):
                    continue

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
    """UNGM — developer.ungm.org API 전용.

    과거의 공개 POST 스크래핑(/Public/Notice/Search)은 2025~2026년 사이에
    서버 측 에러 페이지(/Home/InternalError)로 리다이렉트되도록 변경되어 완전 사용 불가.
    UNGM 은 이제 Angular SPA 로 전환됐고 서버 HTML에 목록 데이터가 포함되지 않음.

    수집 가능 조건: 환경변수 UNGM_API_KEY 설정 + developer.ungm.org 접근 가능.
    (IFAD / FAO / WFP 등 다수 UN 기관 발주공고가 이 경로로 수집됨)
    """
    api_key = os.environ.get('UNGM_API_KEY', '')

    if not api_key:
        print('[UNGM] UNGM_API_KEY 환경변수 미설정 — 공개 스크래핑 경로가 사라져 수집 불가. '
              'developer.ungm.org 에서 API 키 발급 후 설정 필요.')
        return []

    try:
        import requests as req
    except ImportError:
        return []

    # developer.ungm.org API (유일한 유효 경로)
    if True:
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


# ── Tier 2: ADB RSS ──────────────────────────────────────────────────────────
def _collect_adb() -> list:
    """ADB — RSS 우선, 실패 시 HTML 스크래핑"""
    try:
        import requests as req
    except ImportError:
        return []

    results = []
    attempts_errors = []

    # RSS 시도 — 2025~2026년 기준 ADB RSS 피드 URL 모두 미검증.
    # Cloudflare 가 데이터센터 IP를 자주 차단하므로 실 브라우저 헤더로 재시도.
    rss_urls = [
        'https://www.adb.org/rss/projects-tenders.xml',
        'https://www.adb.org/projects/tenders.rss',
    ]
    rss_ok = False
    for rss_url in rss_urls:
        try:
            r = req.get(rss_url, timeout=10,
                        headers=_browser_headers(referer='https://www.adb.org/projects/tenders'))
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
                        headers=_browser_headers(referer='https://www.adb.org/'))
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
                        headers=_browser_headers(referer='https://www.afdb.org/en/projects-and-operations/procurement'))
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
                        headers=_browser_headers(referer='https://www.afdb.org/'))
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

                # 게시일 최근성: 공고일 90일 이전이면 제외
                posted = (item.get('bidPblancDt') or item.get('postDt') or '')[:10]
                if _is_stale_date(posted, days=DEFAULT_FRESHNESS_DAYS):
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

    # ── API 키 없는 경우: nebid.koica.go.kr 전자조달 HTML 스크래핑 ─────────
    # 기존 www.koica.go.kr/koica_kr/bid/selectBidList.do 는 K2WebWizard
    # 'Alert' 에러 페이지만 반환 — 실제 공고는 nebid(전자조달) 서브도메인에 존재.
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    list_url = 'https://nebid.koica.go.kr/oep/bepb/beffatPblancList.do'
    results  = []
    seen     = set()
    attempts_errors = []

    try:
        r = req.get(list_url,
                    headers=_browser_headers(referer='https://nebid.koica.go.kr/'),
                    timeout=20, verify=False)
        if r.status_code != 200:
            raise RuntimeError(f'KOICA nebid HTTP {r.status_code}')
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.select('tr.row[onclick]') or soup.select('tbody tr[onclick]')
        print(f'[KOICA-nebid] rows found: {len(rows)}')

        for row in rows:
            # 상세 URL: onclick="beffatPblancInfoDetailInqire('W202600009');"
            onclick = row.get('onclick', '')
            m = re.search(r"beffatPblancInfoDetailInqire\('([^']+)'\)", onclick)
            if not m:
                continue
            bid_no = m.group(1)
            detail_url = (f'https://nebid.koica.go.kr/oep/bepb/'
                          f'beffatPblancInfoDetailInqire.do?pblancNo={bid_no}')
            if detail_url in seen:
                continue
            seen.add(detail_url)

            cols = [c.get_text(' ', strip=True) for c in row.select('td')]
            # 컬럼 구조: [순번, 공고번호, 공고구분, 품목구분, 공고명, 공고기간, 조달팀, 공고일]
            if len(cols) < 6:
                continue

            bid_kind = cols[2]   # 국내입찰 / 국제입찰
            item_kind = cols[3]  # 용역 / 물품 / 공사
            # 제목은 title 속성이 축약되지 않은 원본
            title_td = row.select_one('td.left_T, td[title]')
            title = (title_td.get('title') if title_td and title_td.get('title')
                     else (cols[4] if len(cols) > 4 else ''))
            if not title:
                continue

            # 공고기간 "2026-02-19 ~ 2026-02-24" 에서 마감일 추출
            period = cols[5] if len(cols) > 5 else ''
            deadline_match = re.findall(r'\d{4}-\d{2}-\d{2}', period)
            deadline = deadline_match[-1] if deadline_match else ''
            # 마감된 공고는 제외
            if _is_deadline_passed(deadline):
                continue

            # 공고일(마지막 컬럼) 90일 이상 지났으면 제외
            posted = cols[-1] if cols else ''
            if _is_stale_date(posted, days=DEFAULT_FRESHNESS_DAYS):
                continue

            # 농업·기술용역 키워드 필터 (한글·영문 병행)
            combined = f"{title} {bid_kind} {item_kind}"
            agri_hit = _is_agri(combined) or _is_agri_ko(combined)
            cons_hit = (_is_consulting(combined) or _is_consulting_ko(combined)
                        or item_kind == '용역')
            if not agri_hit and not cons_hit:
                continue

            sector = 'consulting' if cons_hit and not agri_hit else 'agriculture'

            results.append({
                'source': 'koica',
                'title': _decorate_title(title, bid_kind or item_kind),
                'country': '',
                'client': 'KOICA',
                'sector': sector,
                'contract_value': '',
                'deadline': deadline,
                'source_url': detail_url,
                'raw_data': {
                    'bid_no': bid_no,
                    'title': title,
                    'bid_kind': bid_kind,
                    'item_kind': item_kind,
                    'period': period,
                    'posted': cols[-1] if cols else '',
                },
            })
    except Exception as e:
        attempts_errors.append(f'nebid: {e}')
        print(f'[KOICA-nebid] 요청 오류: {e}')

    if not results and attempts_errors:
        raise RuntimeError('KOICA 수집 실패: ' + ' | '.join(attempts_errors))

    return results


# ── Tier 2: AIIB (Asian Infrastructure Investment Bank) ─────────────────────
def _collect_aiib() -> list:
    """AIIB — /project-procurement/_common/ppo-data-all.js 의 정적 배열을 파싱.

    해당 JS 파일에 ppoData = [ {id:..., cd:..., mb:...(country), pj:...(project),
    ds:...(desc), cr:...(contractor), sd:..., pc:...(price), st:...(sector),
    ct:...(category), tp:...(type), dc:...(document_url)}, ... ] 배열로 전체 공고가 들어있음.
    Angular SPA 런타임이 이 파일을 로드해서 테이블을 렌더링함.
    """
    try:
        import requests as req
    except ImportError:
        return []

    data_url = ('https://www.aiib.org/en/opportunities/business/'
                'project-procurement/_common/ppo-data-all.js')
    try:
        r = req.get(data_url,
                    headers=_browser_headers(referer='https://www.aiib.org/'),
                    timeout=15)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        raise RuntimeError(f'AIIB ppo-data 요청 실패: {e}') from e

    # var ppoData = [ { ... }, { ... } ];  → 배열 부분만 추출
    m = re.search(r'ppoData\s*=\s*\[(.*)\]\s*;?\s*$', text, re.DOTALL)
    if not m:
        m = re.search(r'ppoData\s*=\s*\[(.*?)\];', text, re.DOTALL)
    if not m:
        raise RuntimeError('AIIB ppoData 배열을 찾지 못함')

    body = m.group(1)
    # 항목 하나를 { ... } 단위로 분리 (객체 안에는 중첩 중괄호가 없음 — 평면 구조)
    # JS 객체 키는 따옴표 없음 → 정규식으로 키:값 쌍 추출
    results = []
    obj_rx = re.compile(r'\{([^{}]+)\}')
    field_rx = re.compile(r'(\w+)\s*:\s*"((?:[^"\\]|\\.)*)"')

    today = datetime.utcnow().date()
    stale_cutoff_days = DEFAULT_FRESHNESS_DAYS  # 90일 — 최근 공고만

    for obj_match in obj_rx.finditer(body):
        fields = {k: v for k, v in field_rx.findall(obj_match.group(1))}
        if not fields:
            continue

        category = (fields.get('ct') or '').strip()
        # Contract Awards 는 농업 기술용역 기회가 아니므로 제외
        if category == 'Contract Awards':
            continue

        project = (fields.get('pj') or '').strip()
        desc = (fields.get('ds') or '').strip()
        country = (fields.get('mb') or '').strip()
        sector_raw = (fields.get('st') or '').strip()
        notice_type = (fields.get('tp') or '').strip()
        posted = (fields.get('id') or '').strip()
        deadline = (fields.get('cd') or '').strip()
        price = (fields.get('pc') or '').strip()
        doc_path = (fields.get('dc') or '').strip()

        combined = f'{project} {desc} {sector_raw} {notice_type}'
        # AIIB 섹터는 Water/Energy/Transport/Urban 등 다양 — agri 또는 인프라 중 농업 관련만
        agri_hit = _is_agri(combined) or sector_raw.lower() in ('water', 'rural')
        cons_hit = _is_consulting(combined)
        if not agri_hit and not cons_hit:
            continue

        # 등록일 기준 오래된 것 제외 ("April 15, 2026" / "Dec 27, 2016" 등 복수 포맷 지원)
        if _is_stale_date(posted, days=stale_cutoff_days):
            continue

        # 마감일 파싱 — "April 15, 2026" / "Dec 27, 2016" 형식
        deadline_iso = ''
        if deadline:
            dd = None
            for fmt in ('%B %d, %Y', '%b %d, %Y'):
                try:
                    dd = datetime.strptime(deadline, fmt).date()
                    break
                except ValueError:
                    continue
            if dd:
                deadline_iso = dd.isoformat()
                if dd < today:
                    continue

        if doc_path:
            source_url = ('https://www.aiib.org' + doc_path
                          if doc_path.startswith('/') else doc_path)
        else:
            # 다큐 없으면 project procurement 목록 페이지로
            source_url = 'https://www.aiib.org/en/opportunities/business/project-procurement/list.html'

        title = project or desc[:200] or notice_type
        if not title:
            continue

        sector = 'consulting' if cons_hit and not agri_hit else 'agriculture'

        results.append({
            'source': 'aiib',
            'title': _decorate_title(title, notice_type),
            'country': country,
            'client': 'AIIB',
            'sector': sector,
            'contract_value': _compact_currency_phrase(price),
            'deadline': deadline_iso,
            'source_url': source_url,
            'raw_data': fields,
        })

    return results


# ── Tier 2: IsDB (Islamic Development Bank) ─────────────────────────────────
# 실제 현재(Active) 공고가 있는 카테고리 페이지
_ISDB_PAGES = [
    ('https://www.isdb.org/project-procurement/taxonomy/term/207', 'GPN'),  # General Procurement Notice
    ('https://www.isdb.org/project-procurement/taxonomy/term/210', 'SPN'),  # Specific Procurement Notice
    ('https://www.isdb.org/project-procurement/taxonomy/term/211', 'SPN'),  # Specific Procurement Notice (Civil Works)
]


def _collect_isdb() -> list:
    """IsDB — 카테고리 페이지(taxonomy term)에서 현재 활성 공고 수집.

    /project-procurement/tenders 기본 페이지는 2025년 마감된 EOI/PQN 위주라 부적합.
    taxonomy/term/207 (GPN) 과 /210 (SPN) 에 현재 연도 활성 공고 존재.
    """
    try:
        import requests as req
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    results = []
    seen = set()
    attempts_errors = []

    type_map = {
        'eoi': 'EOI', 'gpn': 'GPN', 'spn': 'SPN',
        'ca': 'Contract Award', 'pq': 'Pre-Qualification',
        'pqn': 'Pre-Qualification',
    }

    for list_url, default_type in _ISDB_PAGES:
        try:
            r = req.get(list_url,
                        headers=_browser_headers(referer='https://www.isdb.org/'),
                        timeout=20)
            r.raise_for_status()
        except Exception as e:
            attempts_errors.append(f'{list_url}: {e}')
            continue

        soup = BeautifulSoup(r.text, 'html.parser')
        # taxonomy 페이지는 간단한 링크 리스트 구조 — 모든 공고 링크 수집
        anchors = soup.select('a[href*="/project-procurement/tenders/"]')
        print(f'[IsDB-{default_type}] anchors: {len(anchors)}')

        for a in anchors:
            href = a.get('href', '')
            title = a.get_text(strip=True)
            if not title or not href:
                continue
            if href.startswith('/'):
                href = 'https://www.isdb.org' + href
            if href in seen:
                continue
            seen.add(href)

            # URL 에서 연도·notice type 추출
            url_year = None
            ym = re.search(r'/tenders/(\d{4})/([a-z\-]+)/', href)
            notice_type = default_type
            if ym:
                url_year = int(ym.group(1))
                notice_type = type_map.get(ym.group(2).lower(), notice_type)

            # 최근성 필터: URL 연도가 (현재 연도 - 1) 미만이면 아카이브로 간주하고 제외
            current_year = datetime.utcnow().year
            if url_year and url_year < current_year - 1:
                continue

            if notice_type == 'Contract Award':
                continue

            # 주변 텍스트 수집 — 최근접 상위 블록에서
            parent = a.find_parent(['article', 'div', 'li']) or a.parent
            row_text = parent.get_text(' ', strip=True) if parent else title

            if re.search(r'\b(Closed|Fermé|Ferm\u00e9)\b', row_text, re.IGNORECASE):
                continue

            combined = f'{title} {row_text}'
            if not _is_agri(combined) and not _is_consulting(combined):
                continue

            # 마감일
            deadline = ''
            dm = re.search(r'(\d{4}-\d{2}-\d{2})', row_text)
            if dm:
                deadline = dm.group(1)
            if _is_deadline_passed(deadline):
                continue

            country = ''
            for kw in ('Bangladesh', 'Uganda', 'Togo', 'Benin', 'Mauritania',
                       'Guinea', 'Morocco', 'Kyrgyzstan', 'Uzbekistan',
                       'Tajikistan', 'Turkey', 'Türkiye', 'Pakistan',
                       'Indonesia', 'Jordan', 'Sierra Leone', 'Suriname',
                       'Azerbaijan', 'Saudi Arabia', 'Kazakhstan', 'Egypt',
                       'Nigeria', 'Senegal', 'Mali', 'Burkina Faso', 'Niger',
                       'Cameroon', 'Chad', 'Mozambique', 'Oman', 'Tanzania'):
                if kw in row_text or kw in title:
                    country = kw
                    break

            sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

            contract_value = _extract_value_from_text(row_text)

            results.append({
                'source': 'isdb',
                'title': _decorate_title(title, notice_type),
                'country': country,
                'client': 'IsDB',
                'sector': sector,
                'contract_value': contract_value,
                'deadline': deadline,
                'source_url': href,
                'raw_data': {'title': title, 'url': href, 'type': notice_type},
            })

    # 목록에서 금액을 못 구한 항목에 대해 상세 페이지 조회로 보강 + 최근성 검증
    # (최대 15건 제한 — 요청수 폭증 방지)
    detail_budget = 15
    filtered = []
    for item in results:
        if detail_budget <= 0 or item.get('contract_value'):
            # 상세 조회 안 하는 항목은 그대로 통과 (목록 단계 필터만 적용됨)
            filtered.append(item)
            continue
        keep = True
        try:
            dr = req.get(item['source_url'],
                         headers=_browser_headers(referer='https://www.isdb.org/project-procurement/tenders'),
                         timeout=15)
            if dr.status_code == 200:
                dsoup = BeautifulSoup(dr.text, 'html.parser')
                main_text = dsoup.get_text(' ', strip=True)
                # 금액
                val = _extract_value_from_text(main_text)
                if val:
                    item['contract_value'] = val
                # 게시일 탐색 — "Published on YYYY-MM-DD" / "Posted: DD Month YYYY" 등
                pm = re.search(
                    r'(?:Published|Posted|Publish Date|Date Posted|Publication Date)\s*(?:on)?\s*[:\-]?\s*'
                    r'(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s*\d{4})',
                    main_text, re.IGNORECASE,
                )
                if pm and _is_stale_date(pm.group(1), days=DEFAULT_FRESHNESS_DAYS):
                    keep = False
        except Exception:
            pass
        detail_budget -= 1
        if keep:
            filtered.append(item)
    results = filtered

    if attempts_errors:
        print(f'[IsDB] attempt errors: {attempts_errors}')
    if not results and attempts_errors and len(attempts_errors) >= len(_ISDB_PAGES):
        raise RuntimeError('IsDB 전체 페이지 요청 실패: ' + ' | '.join(attempts_errors))

    return results


# ── 수집 실행 ────────────────────────────────────────────────────────────────
COLLECTORS = {
    'worldbank': _collect_worldbank,
    'ungm':      _collect_ungm,
    'adb':       _collect_adb,
    'afdb':      _collect_afdb,
    'aiib':      _collect_aiib,
    'isdb':      _collect_isdb,
    'koica':     _collect_koica,
}

SOURCE_DISPLAY = {
    'worldbank': 'World Bank',
    'ungm':      'UNGM',
    'adb':       'ADB',
    'afdb':      'AfDB',
    'aiib':      'AIIB',
    'isdb':      'IsDB',
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
