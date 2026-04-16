"""
발주공고 수집 봇
World Bank API / UNGM API / ADB RSS / AfDB RSS / KOICA data.go.kr
농업 관련 기술용역 공고($1M 이상)를 병렬 수집 → bid_notices 테이블 저장
"""
import os
import json
import hmac
import hashlib
import threading
from datetime import datetime
from xml.etree import ElementTree
from flask import Blueprint, request, jsonify, current_app
from models import db, BidNotice

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
    """World Bank Procurement Notices JSON API (인증 불필요)"""
    try:
        import requests as req
    except ImportError:
        return []

    url = 'https://search.worldbank.org/api/procnotices'
    results = []
    offset = 0
    page_size = 100

    while True:
        params = {
            'format': 'json',
            'apilang': 'en',
            'displayconttype_exact': 'Consulting Services',
            'rows': page_size,
            'os': offset,
        }
        try:
            r = req.get(url, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        notices_raw = data.get('notices', {})
        # API가 dict(id→obj) 또는 list 형식으로 반환할 수 있음
        if isinstance(notices_raw, dict):
            items = list(notices_raw.values())
        elif isinstance(notices_raw, list):
            items = notices_raw
        else:
            break

        if not items:
            break

        for item in items:
            title = (item.get('project_name') or item.get('notice_title') or '').strip()
            notice_type = item.get('noticeType') or item.get('notice_type') or ''
            if notice_type:
                title = f"{title} [{notice_type}]" if title else notice_type

            sector = item.get('sector') or item.get('majorsector') or ''
            desc = item.get('description') or ''
            combined = f"{title} {sector} {desc}"

            if not _is_agri(combined):
                continue

            raw_value = (item.get('totalcontractamount') or
                         item.get('estimatedamount') or
                         item.get('noticevalue') or '')
            value_usd = _parse_value_usd(str(raw_value))
            if raw_value and value_usd < MIN_VALUE_USD:
                continue

            source_url = (item.get('url') or item.get('noticeid') or '').strip()
            if not source_url:
                continue
            # URL이 상대경로인 경우 절대경로로
            if source_url.startswith('/'):
                source_url = 'https://projects.worldbank.org' + source_url

            country = (item.get('country_name') or item.get('countryname') or '').strip()
            client = (item.get('contact_agency') or item.get('borrower') or '').strip()
            deadline = (item.get('deadline') or item.get('submissiondate') or '').strip()

            results.append({
                'source': 'worldbank',
                'title': title,
                'country': country,
                'client': client or 'World Bank',
                'sector': sector,
                'contract_value': _fmt_value(raw_value) if raw_value else '',
                'deadline': deadline,
                'source_url': source_url,
                'raw_data': item,
            })

        total_raw = data.get('total', {})
        total = total_raw.get('value', 0) if isinstance(total_raw, dict) else int(total_raw or 0)
        offset += len(items)
        if offset >= total or offset >= 500:
            break

    return results


# ── Tier 1: UNGM API ────────────────────────────────────────────────────────
def _collect_ungm() -> list:
    """UNGM API — UNDP, IFAD, FAO, UNOPS 등 22개 UN기관 통합 (API 키 필요)"""
    api_key = os.environ.get('UNGM_API_KEY', '')
    if not api_key:
        return []

    try:
        import requests as req
    except ImportError:
        return []

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
            'TenderStatusCode': 'AC',  # Active
            'DeadlineFrom': datetime.utcnow().strftime('%Y-%m-%d'),
            'Keywords': 'agriculture irrigation rural food',
            'PageSize': page_size,
            'PageIndex': page,
        }
        try:
            r = req.get(url, headers=headers, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()
        except Exception:
            break

        items = data.get('Notices') or data.get('notices') or []
        if not items:
            break

        for item in items:
            title = (item.get('Title') or item.get('title') or '').strip()
            desc = item.get('Description') or item.get('description') or ''
            combined = f"{title} {desc}"

            if not _is_agri(combined):
                continue

            value_raw = item.get('EstimatedValue') or item.get('estimatedValue') or 0
            if value_raw and _parse_value_usd(str(value_raw)) < MIN_VALUE_USD:
                continue

            source_url = (item.get('NoticeUrl') or item.get('noticeUrl') or
                          item.get('Url') or '').strip()
            if not source_url:
                notice_id = item.get('Id') or item.get('id') or ''
                source_url = f'https://www.ungm.org/Public/Notice/{notice_id}'

            country = (item.get('Country') or item.get('country') or '').strip()
            deadline_raw = item.get('Deadline') or item.get('deadline') or ''
            deadline = deadline_raw[:10] if deadline_raw else ''
            org = item.get('AgencyName') or item.get('agencyName') or 'UN'

            results.append({
                'source': 'ungm',
                'title': title,
                'country': country,
                'client': org,
                'sector': 'agriculture',
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

    # RSS 시도
    rss_urls = [
        'https://www.adb.org/rss/projects-tenders.xml',
        'https://www.adb.org/projects/tenders.rss',
    ]
    rss_ok = False
    for rss_url in rss_urls:
        try:
            r = req.get(rss_url, timeout=10)
            if r.status_code == 200:
                root = ElementTree.fromstring(r.content)
                for item in root.findall('.//item'):
                    title = item.findtext('title') or ''
                    link = item.findtext('link') or ''
                    desc = item.findtext('description') or ''
                    combined = f"{title} {desc}"

                    if not _is_agri(combined):
                        continue
                    if not _is_consulting(combined):
                        continue
                    if not link:
                        continue

                    pub_date = item.findtext('pubDate') or ''

                    results.append({
                        'source': 'adb',
                        'title': title,
                        'country': '',
                        'client': 'ADB',
                        'sector': 'agriculture',
                        'contract_value': '',
                        'deadline': pub_date[:10] if pub_date else '',
                        'source_url': link,
                        'raw_data': {'title': title, 'link': link, 'description': desc},
                    })
                rss_ok = True
                break
        except Exception:
            continue

    # RSS 실패 시 HTML 스크래핑 (beautifulsoup4)
    if not rss_ok:
        try:
            from bs4 import BeautifulSoup
            html_url = 'https://www.adb.org/projects/tenders?type=Consulting+Services'
            r = req.get(html_url, timeout=12,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)'})
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for row in soup.select('table.tender-table tbody tr, .views-row'):
                    title_el = row.select_one('td.views-field-title a, .views-field-title a')
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    href = title_el.get('href', '')
                    if href.startswith('/'):
                        href = 'https://www.adb.org' + href

                    combined = title + ' ' + row.get_text()
                    if not _is_agri(combined):
                        continue

                    results.append({
                        'source': 'adb',
                        'title': title,
                        'country': '',
                        'client': 'ADB',
                        'sector': 'agriculture',
                        'contract_value': '',
                        'deadline': '',
                        'source_url': href,
                        'raw_data': {'title': title, 'url': href},
                    })
        except Exception:
            pass

    return results


# ── Tier 2: AfDB RSS ────────────────────────────────────────────────────────
def _collect_afdb() -> list:
    """AfDB — RSS 우선, 실패 시 HTML 스크래핑"""
    try:
        import requests as req
    except ImportError:
        return []

    results = []

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
            if r.status_code == 200 and r.content:
                root = ElementTree.fromstring(r.content)
                for item in root.findall('.//item'):
                    title = item.findtext('title') or ''
                    link = item.findtext('link') or ''
                    desc = item.findtext('description') or ''
                    combined = f"{title} {desc}"

                    if not _is_agri(combined):
                        continue
                    if not link:
                        continue

                    pub_date = item.findtext('pubDate') or ''
                    country_el = item.find('{http://purl.org/dc/elements/1.1/}subject')
                    country = country_el.text.strip() if country_el is not None else ''

                    results.append({
                        'source': 'afdb',
                        'title': title,
                        'country': country,
                        'client': 'AfDB',
                        'sector': 'agriculture',
                        'contract_value': '',
                        'deadline': pub_date[:10] if pub_date else '',
                        'source_url': link,
                        'raw_data': {'title': title, 'link': link, 'description': desc},
                    })
                rss_ok = True
                break
        except Exception:
            continue

    # RSS 실패 시 HTML 스크래핑
    if not rss_ok:
        try:
            from bs4 import BeautifulSoup
            html_url = ('https://www.afdb.org/en/documents/project-related-procurement'
                        '/procurement-notices/specific-procurement-notices')
            r = req.get(html_url, timeout=12,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; GBMSBot/1.0)'})
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.select('.field-content a, .views-field-title a'):
                    title = a.get_text(strip=True)
                    href = a.get('href', '')
                    if not title or not href:
                        continue
                    if href.startswith('/'):
                        href = 'https://www.afdb.org' + href

                    if not _is_agri(title):
                        continue

                    results.append({
                        'source': 'afdb',
                        'title': title,
                        'country': '',
                        'client': 'AfDB',
                        'sector': 'agriculture',
                        'contract_value': '',
                        'deadline': '',
                        'source_url': href,
                        'raw_data': {'title': title, 'url': href},
                    })
        except Exception:
            pass

    return results


# ── Tier 2: KOICA / data.go.kr ──────────────────────────────────────────────
def _collect_koica() -> list:
    """KOICA — 공공데이터포털 API (KOICA_API_KEY 환경변수 필요)"""
    service_key = os.environ.get('KOICA_API_KEY', '')
    if not service_key:
        return []

    try:
        import requests as req
    except ImportError:
        return []

    results = []
    # KOICA ODA 사업 공고 (data.go.kr 제공)
    # 실제 엔드포인트는 data.go.kr 에서 발급받은 서비스키로 접근
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
            if not _is_agri(combined):
                continue

            source_url = item.get('bidUrl') or item.get('url') or ''
            bid_no = item.get('bidNo') or item.get('id') or ''
            if not source_url and bid_no:
                source_url = f'https://www.koica.go.kr/koica_kr/bid/view/{bid_no}'
            if not source_url:
                continue

            results.append({
                'source': 'koica',
                'title': title,
                'country': (item.get('country') or '').strip(),
                'client': 'KOICA',
                'sector': 'agriculture',
                'contract_value': (item.get('bidAmt') or '').strip(),
                'deadline': (item.get('bidClseDt') or '')[:10],
                'source_url': source_url,
                'raw_data': item,
            })
    except Exception:
        pass

    return results


# ── 수집 실행 ────────────────────────────────────────────────────────────────
COLLECTORS = {
    'worldbank': _collect_worldbank,
    'ungm':      _collect_ungm,
    'adb':       _collect_adb,
    'afdb':      _collect_afdb,
    'koica':     _collect_koica,
}


def _run_all_collectors() -> tuple[list, dict]:
    """모든 수집기를 ThreadPoolExecutor로 병렬 실행"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

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
            except Exception as e:
                errors[name] = str(e)

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
    source_counts = {}

    for item in all_items:
        saved = _save_notice(
            source=item['source'],
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
            source_counts[item['source']] = source_counts.get(item['source'], 0) + 1
        else:
            skipped += 1

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
        'by_source': source_counts,
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
