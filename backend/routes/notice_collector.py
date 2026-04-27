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
from sqlalchemy import or_
from models import db, BidNotice, ScrapingRun

collector_bp = Blueprint('collector', __name__)

# ── 필터 키워드 ──────────────────────────────────────────────────────────────
AGRI_KEYWORDS = [
    'agriculture', 'agricultural', 'agri', 'farming', 'farm',
    'irrigation', 'rural', 'food security', 'food and agriculture',
    'crop', 'livestock', 'rice', 'grain', 'seed', 'fisheries',
    'forestry', 'water resource', 'drainage', 'land reclamation',
    'watershed', 'aquaculture', 'paddy', 'horticulture',
    # 수자원 인프라 / 기후변화 (2026-04 추가)
    'climate change', 'climate adaptation',
    'reservoir', 'dam', 'dams',
    'rehabilitation', 'refurbishment',
]

CONSULTING_KEYWORDS = [
    'consulting', 'consultancy', 'consultant', 'technical assistance',
    'advisory', 'supervision', 'feasibility', 'project management', 'pmc',
    'f/s', 'capacity building', 'assessment', 'planning',
    'engineering services', 'detailed design', 'design review',
    'design and supervision', 'preliminary design',
]

# 한국어 키워드 (KOICA nebid 등 국문 공고용)
AGRI_KEYWORDS_KO = [
    '농업', '농촌', '관개', '식량', '작물', '수산', '산림', '농지',
    '용수', '양식', '축산', '수자원', '간척', '개간',
    # 수자원 인프라 / 기후변화 (2026-04 추가)
    '기후변화', '저수지', '댐', '개보수',
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


def _fmt_value(raw, currency: str = 'USD') -> str:
    """숫자 → 'USD 2.3M' 표시용 — 전역 통일 포맷(_format_compact_money 위임).

    과거에는 '$2.3M' 식의 단축 기호를 썼으나, 다수 통화(INR/EUR/LSL 등)가
    섞이는 수집 환경에서 일관되게 ISO 통화코드 + 숫자로 통일.
    """
    if raw is None or raw == '':
        return ''
    return _format_compact_money(currency, str(raw), '')


# ── 상태/마감일 공통 헬퍼 ────────────────────────────────────────────────────
_DATE_RX = re.compile(r'(\d{4})[-./\s년]\s*(\d{1,2})[-./\s월]\s*(\d{1,2})')


def _parse_date_any(s: str):
    """YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD / 'YYYY년 MM월 DD일' / ISO datetime
    / 'April 15, 2026' / '15 April 2026' / RFC 822 pubDate → date.
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
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d).date()
        except Exception:
            pass
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return dt.date()
    except (TypeError, ValueError):
        pass
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
DEFAULT_FRESHNESS_DAYS = 60


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
    # 'USDUSD' / 'USDUSDUSD' 같이 중복 prefix 생길 수 있어 정리
    cur_raw = re.sub(r'(USD)+', 'USD', cur_raw)
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

    # 소수점 1자리로 통일 — '2.34M' 보다 '2.3M' 이 더 깔끔한 일람 표시
    if num >= 1_000_000_000:
        amt = f'{num/1_000_000_000:.1f}B'
    elif num >= 1_000_000:
        amt = f'{num/1_000_000:.1f}M'
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
    """하위호환 래퍼 — 공통 _format_compact_money 로 위임.
    ('LSL', '1418732.00') → 'LSL 1.4M'.
    """
    return _format_compact_money(currency or 'USD', amount_str, '')


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


_TITLE_NORMALIZE_RX = re.compile(r'[\s\W_]+', re.UNICODE)
_BRACKETED_RX = re.compile(r'[\[\(\{][^\]\)\}]*[\]\)\}]')
# notice_type 류 키워드 (제목 정규화 시 제거)
_NOTICE_TYPE_TOKENS_RX = re.compile(
    r'\b(?:request\s+for\s+(?:bids?|proposals?|expression\s+of\s+interest|'
    r'expressions?\s+of\s+interest|quotations?|eoi)|rfp|rfb|rfq|reoi|'
    r'general\s+procurement\s+notice|specific\s+procurement\s+notice|'
    r'gpn|spn|eoi|pqn|pre[- ]?qualification|addend(?:um|a)|amendment|'
    r'invitation\s+for\s+(?:bids?|tenders?)|ifb|ift|contract\s+award(?:\s+notice)?|'
    r'procurement\s+plan|notices?|early\s+market\s+engagement(?:\s+notice)?)\b',
    re.IGNORECASE,
)


def _normalize_title(title: str) -> str:
    """제목 정규화 — 대소문자/공백/특수문자/괄호내용/공고유형 표기 무시.

    중복 판정용 키에 사용. 예:
      'Nigeria Rural Water Project (P123) [Request for Bids]'
      'NIGERIA RURAL WATER PROJECT  [Addenda]'
      'Nigeria Rural Water Project — EOI'
    → 모두 'nigeriaruralwaterproject' 로 수렴.
    """
    if not title:
        return ''
    t = title.lower()
    t = _BRACKETED_RX.sub(' ', t)        # [...] (...) {...} 전부 제거
    t = _NOTICE_TYPE_TOKENS_RX.sub(' ', t)  # RFP/EOI/GPN 등 키워드 제거
    t = _TITLE_NORMALIZE_RX.sub('', t)   # 공백/특수문자 전부 제거
    return t[:120]


def _normalize_country(country: str) -> str:
    """국가명 정규화 — 대소문자/공백 무시. 'Türkiye' ↔ 'Turkey' 등은 별도 처리 안 함."""
    if not country:
        return ''
    return _TITLE_NORMALIZE_RX.sub('', country.lower())[:50]


_existing_fingerprints_cache = None  # 수집 배치 시작 시 1회 빌드, 매 건마다 재사용


def _build_fingerprint_cache():
    """DB 의 기존 BidNotice 를 (title_norm, country_norm) set 으로 빌드.
    _save_notice 에서 매 건마다 query.all() 하지 않도록 1회만 호출."""
    global _existing_fingerprints_cache
    cache = set()
    url_set = set()
    for n in BidNotice.query.all():
        if n.source_url:
            url_set.add(n.source_url)
        tn = _normalize_title(n.title or '')
        cn = _normalize_country(n.country or '')
        if tn:
            cache.add((tn, cn))
    _existing_fingerprints_cache = (cache, url_set)


def _save_notice(source, title, country, client, sector,
                 contract_value, deadline, source_url, raw_data) -> bool:
    """중복 확인 후 BidNotice 저장. 신규면 True.

    중복 판정은 인메모리 캐시 기반 (DB 전체 스캔 매번 안 함):
      1) source_url 캐시 일치
      2) (정규화 title, 정규화 country) 캐시 일치
    """
    global _existing_fingerprints_cache
    if not source_url or not title:
        return False

    # 캐시 미빌드 시 (단독 호출 등) DB 직접 체크 — 느리지만 안전
    if _existing_fingerprints_cache is None:
        _build_fingerprint_cache()

    fp_cache, url_cache = _existing_fingerprints_cache

    # 1단계: source_url 일치
    if source_url in url_cache:
        return False

    # 2단계: (title_norm, country_norm) 일치
    norm_new = _normalize_title(title)
    country_norm_new = _normalize_country(country or '')
    if norm_new and (norm_new, country_norm_new) in fp_cache:
        return False

    # 저장 + 캐시 업데이트 (같은 배치 내 후속 건의 중복 체크에 반영)
    url_cache.add(source_url)
    if norm_new:
        fp_cache.add((norm_new, country_norm_new))

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

            # 최근성 필터 (두 조건 모두 충족해야 통과):
            #   ① 마감일이 미래(또는 파싱불가) 여야 함 — 마감된 공고 제외
            #   ② 공고 게시일(noticedate)이 DEFAULT_FRESHNESS_DAYS 이내 — "60일 내 발주" 의미
            # 기존엔 deadline 있으면 게시일을 체크 안 해서, '공고 2년 전·마감 미래'
            # 같은 장기 공고가 통과되는 구멍이 있었음.
            if _is_deadline_passed(deadline):
                continue
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

                # 게시일(Published) 60일 이전이면 제외
                posted = (item.get('PublishedDate') or item.get('Published')
                          or item.get('publishedDate') or '')
                if _is_stale_date(posted, days=DEFAULT_FRESHNESS_DAYS):
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


# ── Tier 2: ADB / AfDB via UNGM Public Search ──────────────────────────────
#
# ADB·AfDB 자체 RSS/HTML이 Cloudflare로 완전 차단(404/403)됨.
# UNGM(UN Global Marketplace)이 두 기관 공고를 게시하며,
# POST /Public/Notice/Search 엔드포인트가 인증 없이 동작함을 확인(2026-04).
#
# UNGM Agency ID: ADB=85, AfDB=84, FAO=49, IFAD=65, UNDP=1
# 응답: HTML (테이블 행) → BeautifulSoup 파싱.
#
# Cell 구조 (0-indexed):
#   0: buttons (skip)
#   1: 제목 (.resultTitle a[href=/Public/Notice/{id}])
#   2: 마감일 (.deadline)  — "06-May-2026 12:00\n(GMT 00.00)..."
#   3: 게시일              — "13-Apr-2026"
#   4: 기관 (.resultAgency)
#   5: 공고 유형           — "Request for proposal"
#   6: 참조번호            — "ADB/RFP/..."
#   7: 국가                — "Philippines" / "Multiple destinations"

_UNGM_SEARCH_URL = 'https://www.ungm.org/Public/Notice/Search'
_UNGM_AGENCY_IDS = {
    'adb':  '85',
    'afdb': '84',
}


def _collect_via_ungm(source_key: str) -> list:
    """UNGM 공개 검색으로 ADB 또는 AfDB 공고 수집.

    - 인증 불필요 (Public 엔드포인트)
    - 농업/컨설팅 키워드 필터 적용
    - 마감 지난 건 제외, DEFAULT_FRESHNESS_DAYS 이내만
    """
    import requests as req
    from bs4 import BeautifulSoup

    agency_id = _UNGM_AGENCY_IDS.get(source_key)
    if not agency_id:
        return []

    results = []
    page = 0
    max_pages = 5  # 15건×5 = 최대 75건

    while page < max_pages:
        payload = {
            'PageIndex': page,
            'PageSize': 15,
            'Title': '',
            'Description': '',
            'Reference': '',
            'PublishedFrom': '',
            'PublishedTo': '',
            'DeadlineFrom': '',
            'DeadlineTo': '',
            'Countries': [],
            'Agencies': [agency_id],
            'UNSPSCs': [],
            'NoticeTypes': [],
            'SortField': 'Deadline',
            'SortAscending': True,
            'isPicker': False,
            'IsSustainable': False,
            'IsActive': True,
            'NoticeDisplayType': None,
            'TypeOfCompetitions': [],
        }
        try:
            r = req.post(_UNGM_SEARCH_URL, json=payload, timeout=15,
                         headers={
                             **_browser_headers(referer='https://www.ungm.org/Public/Notice'),
                             'Content-Type': 'application/json',
                             'X-Requested-With': 'XMLHttpRequest',
                             'Accept': '*/*',
                         })
            if r.status_code != 200:
                print(f'[{source_key}-UNGM] HTTP {r.status_code} on page {page}')
                break
        except req.RequestException as e:
            print(f'[{source_key}-UNGM] 요청 실패: {e}')
            break

        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.select('.dataRow.notice-table')
        if not rows:
            break

        for row in rows:
            cells = row.select('.tableCell')
            if len(cells) < 8:
                continue

            notice_id = row.get('data-noticeid', '')

            # 제목: .ungm-title span (실제 공고명) → fallback: anchor text
            title_span = cells[1].select_one('.ungm-title')
            if title_span:
                title = title_span.get_text(strip=True)
            else:
                title = cells[1].get_text(strip=True)
            title = re.sub(r'Open in a new window', '', title).strip()
            # tooltip 텍스트 제거
            tooltip = cells[1].select_one('.info-tooltip__text')
            if tooltip:
                title = title.replace(tooltip.get_text(strip=True), '').strip()
            if not title:
                continue

            link_el = cells[1].select_one('a[href*="/Public/Notice/"]')
            href = link_el.get('href', '') if link_el else f'/Public/Notice/{notice_id}'
            source_url = f'https://www.ungm.org{href}' if href.startswith('/') else href

            # 마감일: "06-May-2026 12:00\n(GMT 00.00)..." → "2026-05-06"
            deadline_raw = cells[2].get_text(strip=True).split('\n')[0].strip()
            deadline = _normalize_date_str(deadline_raw.split(' ')[0] if deadline_raw else '')

            # 마감일 지난 건 제외
            if _is_deadline_passed(deadline):
                continue

            # 게시일
            posted_raw = cells[3].get_text(strip=True)
            if _is_stale_date(posted_raw, days=DEFAULT_FRESHNESS_DAYS):
                continue

            agency = cells[4].get_text(strip=True)
            notice_type = cells[5].get_text(strip=True)
            reference = cells[6].get_text(strip=True)
            country = cells[7].get_text(strip=True)
            if country == 'Multiple destinations':
                country = ''

            combined = f'{title} {notice_type} {reference}'
            if not _is_agri(combined) and not _is_consulting(combined):
                continue

            sector = 'consulting' if _is_consulting(combined) and not _is_agri(combined) else 'agriculture'

            results.append({
                'source': source_key,
                'title': _decorate_title(title, notice_type),
                'country': country,
                'client': agency,
                'sector': sector,
                'contract_value': _extract_value_from_text(title),
                'deadline': deadline,
                'source_url': source_url,
                'raw_data': {
                    'ungm_id': notice_id,
                    'title': title,
                    'notice_type': notice_type,
                    'reference': reference,
                    'posted': posted_raw,
                    'agency': agency,
                },
            })

        if len(rows) < 15:
            break
        page += 1

    print(f'[{source_key}-UNGM] {len(results)} items collected')
    return results


def _collect_adb() -> list:
    """ADB — UNGM 공개 검색 경유 (ADB 자체 RSS/HTML Cloudflare 차단됨)"""
    return _collect_via_ungm('adb')


def _collect_afdb() -> list:
    """AfDB — UNGM 공개 검색 경유 (AfDB 자체 RSS/HTML Cloudflare 차단됨)"""
    return _collect_via_ungm('afdb')


# ── ADB/AfDB 상세 페이지 보강 (WB _wb_extract_details 패턴) ─────────────────

# 날짜 패턴: 2026-05-30, 30 May 2026, May 30, 2026, 30/05/2026
_DATE_PATTERNS = [
    r'(\d{4}-\d{2}-\d{2})',                              # 2026-05-30
    r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',  # 30 May 2026
    r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',  # May 30, 2026
    r'(\d{1,2}/\d{1,2}/\d{4})',                           # 30/05/2026
]

_DEADLINE_LABELS = [
    r'Submission\s+Deadline',
    r'Closing\s+Date',
    r'Deadline\s+(?:for\s+)?Submission',
    r'Date\s+of\s+Deadline',
    r'Due\s+Date',
    r'Expressions?\s+of\s+Interest.*?(?:before|by|deadline)',
    r'Bid\s+Closing\s+Date',
]

_AMOUNT_LABELS = [
    r'Estimated\s+(?:Cost|Value|Budget|Amount)',
    r'Contract\s+(?:Amount|Value|Price)',
    r'Project\s+(?:Cost|Amount|Budget)',
    r'Total\s+(?:Cost|Value)',
    r'Loan\s+Amount',
    r'Financing\s+Amount',
    r'Approved\s+Amount',
]


def _extract_labeled_date(text: str, labels: list) -> str:
    """라벨 키워드 주변에서 날짜 추출."""
    for label in labels:
        for dp in _DATE_PATTERNS:
            pat = rf'{label}\s*[:\-–]\s*{dp}'
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return _normalize_date_str(m.group(1))
    return ''


def _extract_any_date(text: str) -> str:
    """텍스트 내 첫 번째 파싱 가능한 날짜."""
    for dp in _DATE_PATTERNS:
        m = re.search(dp, text, re.IGNORECASE)
        if m:
            return _normalize_date_str(m.group(1))
    return ''


def _normalize_date_str(raw: str) -> str:
    """다양한 날짜 형식을 ISO (YYYY-MM-DD)로 변환."""
    from datetime import datetime as dt_cls
    if not raw:
        return ''
    raw = raw.strip().replace(',', '')
    for fmt in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y', '%B %d %Y', '%b %d %Y',
                '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return dt_cls.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return raw[:10]


def _fetch_adb_detail(source_url: str) -> dict:
    """ADB 공고 상세 페이지에서 마감일·금액·발주처·조달방식 등 추출.

    ADB는 Drupal CMS 기반 — .field-content, .pane-content, meta 태그 등 탐색.
    403 / 타임아웃 시 빈 dict 반환 (호출자가 graceful 처리).
    """
    import requests as req

    if not source_url:
        return {}
    try:
        r = req.get(source_url, timeout=12,
                    headers=_browser_headers(referer='https://www.adb.org/projects/tenders'))
        if r.status_code != 200:
            print(f'[ADB-detail] HTTP {r.status_code}: {source_url}')
            return {}
    except req.RequestException as e:
        print(f'[ADB-detail] 요청 실패: {e}')
        return {}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}

    soup = BeautifulSoup(r.text, 'html.parser')
    plain = soup.get_text(' ', strip=True)
    details = {}

    # 마감일
    deadline = _extract_labeled_date(plain, _DEADLINE_LABELS)
    if deadline:
        details['deadline'] = deadline

    # 금액 — 라벨 있는 금액 우선
    for label_rx in _AMOUNT_LABELS:
        m = re.search(
            rf'{label_rx}\s*[:\-–]?\s*({_CURRENCY_CODES})\s*([\d,]+(?:\.\d+)?)\s*'
            rf'(million|billion|mln|bn|M|B|K)?',
            plain, re.IGNORECASE
        )
        if m:
            val = _format_compact_money(m.group(1), m.group(2), m.group(3),
                                        min_threshold=_MIN_CONTRACT_USD_THRESHOLD)
            if val:
                details['contract_value'] = val
                break

    # 국가
    cm = re.search(r'Country\s*[:\-–]\s*([A-Z][A-Za-z ,\-]+)', plain)
    if cm:
        details['country'] = cm.group(1).strip().rstrip('.,')[:100]

    # 발주처 / Executing Agency
    ea = re.search(r'(?:Executing\s+Agency|Borrower|Employer|Client)\s*[:\-–]\s*([^\n<;]{3,200})', plain)
    if ea:
        details['client'] = ea.group(1).strip()[:200]

    # 조달방식
    pm = re.search(r'(?:Procurement\s+Method|Type\s+of\s+Contract|Selection\s+Method)\s*[:\-–]\s*([^\n<;]+)', plain)
    if pm:
        details['procurement_method'] = pm.group(1).strip()[:200]

    # 참조번호
    ref = re.search(r'(?:Reference\s+No\.?|Package\s+No\.?|Tender\s+No\.?|CSRN\s+No\.?)\s*[:\-–]?\s*([A-Z0-9][\w\-/]+)', plain, re.IGNORECASE)
    if ref:
        details['reference_no'] = ref.group(1).strip()[:100]

    # 본문 발췌
    if plain:
        details['text_excerpt'] = plain[:1200]

    return details


def _fetch_afdb_detail(source_url: str) -> dict:
    """AfDB 공고 상세 페이지에서 마감일·금액·국가·조달방식 등 추출.

    AfDB는 Drupal/Liferay 기반 — .field-items, .content-body, meta 태그 등 탐색.
    """
    import requests as req

    if not source_url:
        return {}
    try:
        r = req.get(source_url, timeout=12,
                    headers=_browser_headers(referer='https://www.afdb.org/en/'))
        if r.status_code != 200:
            print(f'[AfDB-detail] HTTP {r.status_code}: {source_url}')
            return {}
    except req.RequestException as e:
        print(f'[AfDB-detail] 요청 실패: {e}')
        return {}

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}

    soup = BeautifulSoup(r.text, 'html.parser')
    plain = soup.get_text(' ', strip=True)
    details = {}

    # 마감일
    deadline = _extract_labeled_date(plain, _DEADLINE_LABELS)
    if deadline:
        details['deadline'] = deadline

    # 금액
    for label_rx in _AMOUNT_LABELS:
        m = re.search(
            rf'{label_rx}\s*[:\-–]?\s*({_CURRENCY_CODES})\s*([\d,]+(?:\.\d+)?)\s*'
            rf'(million|billion|mln|bn|M|B|K)?',
            plain, re.IGNORECASE
        )
        if m:
            val = _format_compact_money(m.group(1), m.group(2), m.group(3),
                                        min_threshold=_MIN_CONTRACT_USD_THRESHOLD)
            if val:
                details['contract_value'] = val
                break

    # 국가 — AfDB 문서는 다양한 형식으로 국가 표시
    cm = re.search(r'(?:Country|Pays|Location)\s*[:\-–]\s*([A-Z][A-Za-zÀ-ÿ ,\-]+)', plain)
    if cm:
        details['country'] = cm.group(1).strip().rstrip('.,')[:100]

    # 발주처
    ea = re.search(r'(?:Executing\s+Agency|Borrower|Client|Agence\s+d.ex[ée]cution)\s*[:\-–]\s*([^\n<;]{3,200})', plain)
    if ea:
        details['client'] = ea.group(1).strip()[:200]

    # 조달방식
    pm = re.search(r'(?:Procurement\s+Method|M[ée]thode\s+de\s+passation|Type\s+of\s+Contract)\s*[:\-–]\s*([^\n<;]+)', plain)
    if pm:
        details['procurement_method'] = pm.group(1).strip()[:200]

    # 참조번호
    ref = re.search(r'(?:Reference|Réf[ée]rence|Tender\s+No\.?|Notice\s+No\.?)\s*[:\-–]?\s*([A-Z0-9][\w\-/]+)', plain, re.IGNORECASE)
    if ref:
        details['reference_no'] = ref.group(1).strip()[:100]

    # 본문 발췌
    if plain:
        details['text_excerpt'] = plain[:1200]

    return details


def _enrich_pending_notices(limit: int = 15) -> dict:
    """ADB/AfDB 공고 중 상세 정보가 없는 건을 source_url 방문으로 보강.

    raw_data 에 adb_details/afdb_details 키가 없는 건을 대상으로
    상세 페이지를 fetch 해 마감일·금액·발주처 등을 채운다.
    """
    import time as t

    detail_fetchers = {
        'adb': _fetch_adb_detail,
        'afdb': _fetch_afdb_detail,
    }

    # adb/afdb 이면서 details 키가 없는 건
    candidates = (BidNotice.query
                  .filter(BidNotice.source.in_(['adb', 'afdb']))
                  .order_by(BidNotice.created_at.desc())
                  .limit(limit * 3)  # details 있는 건도 포함되므로 여유 있게
                  .all())

    pending = []
    for n in candidates:
        detail_key = f'{n.source}_details'
        rd = n.raw_data if isinstance(n.raw_data, dict) else {}
        if detail_key not in rd:
            pending.append(n)
        if len(pending) >= limit:
            break

    if not pending:
        return {'attempted': 0, 'enriched': 0}

    enriched = 0
    for n in pending:
        fetcher = detail_fetchers.get(n.source)
        if not fetcher:
            continue
        try:
            details = fetcher(n.source_url)
        except Exception as e:
            print(f'[enrich] {n.source} #{n.id} 실패: {e}')
            details = {}

        if details:
            rd = dict(n.raw_data) if isinstance(n.raw_data, dict) else {}
            detail_key = f'{n.source}_details'
            rd[detail_key] = details
            n.raw_data = rd

            # 본문 결과로 DB 필드 보강 (기존 값이 비어있을 때만)
            if details.get('deadline') and (not n.deadline or n.deadline == n.created_at.strftime('%Y-%m-%d') if n.created_at else True):
                n.deadline = details['deadline']
            if details.get('contract_value') and not n.contract_value:
                n.contract_value = details['contract_value']
            if details.get('country') and not n.country:
                n.country = details['country']
            if details.get('client') and n.client in ('ADB', 'AfDB'):
                n.client = details['client']

            enriched += 1

        t.sleep(0.5)  # rate-limit 보호

    if enriched:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[enrich] commit 실패: {e}')
            return {'attempted': len(pending), 'enriched': 0, 'error': str(e)}

    print(f'[enrich] {enriched}/{len(pending)} 보강 완료')
    return {'attempted': len(pending), 'enriched': enriched}


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

                # 게시일 최근성: 공고일 DEFAULT_FRESHNESS_DAYS 이전이면 제외
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

            # 공고일(마지막 컬럼) DEFAULT_FRESHNESS_DAYS 이상 지났으면 제외
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
    stale_cutoff_days = DEFAULT_FRESHNESS_DAYS  # 공통 컷오프 — 최근 공고만

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
            # 다큐 없으면 project + country + type 해시 fragment 로 고유화
            # (모든 no-doc 공고가 같은 URL 로 저장돼 중복 skip 되는 문제 방지)
            fp = hashlib.md5(
                f'{project}|{country}|{notice_type}|{posted}'.encode('utf-8')
            ).hexdigest()[:12]
            source_url = (
                'https://www.aiib.org/en/opportunities/business/'
                f'project-procurement/list.html#{fp}'
            )

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
            # IsDB 는 농업 관련 필수 — consulting 단독 매칭은 비농업 오탐 빈발
            # (변전소 Design, 냉동창고 Construction 등). 농업 키워드 포함 시에만 수집.
            if not _is_agri(combined):
                continue

            # 마감일 — 목록 텍스트에서 추출 + 다양한 포맷 시도
            deadline = ''
            # YYYY-MM-DD
            dm = re.search(r'(\d{4}-\d{2}-\d{2})', row_text)
            if dm:
                deadline = dm.group(1)
            # "DD Month YYYY" / "Month DD, YYYY"
            if not deadline:
                dm2 = re.search(
                    r'(?:Closing|Deadline|Close)\s*(?:Date)?[:\s]*'
                    r'(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s*\d{4})',
                    row_text, re.IGNORECASE)
                if dm2:
                    d = _parse_date_any(dm2.group(1))
                    if d:
                        deadline = d.isoformat()
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
                # 마감일 — 목록에서 못 구했으면 상세에서 추출
                if not item.get('deadline'):
                    dm = re.search(
                        r'(?:Closing|Deadline|Submission|Close)\s*(?:Date)?[:\s]*'
                        r'(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s*\d{4})',
                        main_text, re.IGNORECASE)
                    if dm:
                        d = _parse_date_any(dm.group(1))
                        if d:
                            item['deadline'] = d.isoformat()
                            if _is_deadline_passed(item['deadline']):
                                keep = False
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


# ── 정리(Cleanup) — 오래된/마감 공고 삭제 ───────────────────────────────────
# raw_data 딕셔너리에서 '게시일'로 해석할 수 있는 키 후보들(수집기마다 포맷 상이)
_POSTED_KEYS = (
    'noticedate', 'submission_date',          # World Bank
    'pubDate', 'pub_date', 'posted', 'published_at',
    'bidPblancDt', 'postDt',                  # KOICA API
    'id',                                     # AIIB: 게시일
    'period',                                 # KOICA nebid: "2026-02-19 ~ 2026-02-24"
)


def _effective_posted_date(notice) -> datetime:
    """BidNotice 의 '게시일' 추정값을 datetime 으로 반환.

    우선순위: raw_data 내부 게시일 후보 → created_at.
    raw_data 에서 첫 파싱 성공한 값을 사용한다.
    """
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    for key in _POSTED_KEYS:
        val = raw.get(key)
        if not val:
            continue
        d = _parse_date_any(str(val))
        if d is not None:
            return datetime(d.year, d.month, d.day)
    return notice.created_at or datetime.utcnow()


def _sync_db_to_latest(fetched_urls_by_source: dict, errors: dict) -> dict:
    """최신 수집 결과에 없는 DB 레코드 삭제 — DB 를 수집기 출력과 동기화.

    각 source 별로:
      - 해당 source 가 이번 run 에서 에러 없이 동작했고 (errors 에 없음)
      - 1건 이상 fetch 했으면 (0건 = 소스 일시 장애 가능성 → 보호)
      → DB 의 해당 source 레코드 중 fetched_urls 에 없는 것을 DELETE.

    안전장치:
      - 에러 소스 보호 (예: ADB WAF 실패 → 기존 ADB 레코드 유지)
      - 0건 소스 보호 (예: KOICA 현재 공고 0건 → 기존 KOICA 레코드 유지)
      - 에러+0건 소스는 synced_sources 에 포함 안 됨

    Returns: {deleted, synced_sources, skipped_sources}
    """
    deleted = 0
    synced = []
    skipped = []

    for src, urls in fetched_urls_by_source.items():
        if src in errors:
            skipped.append(f'{src}(error)')
            continue
        if not urls:
            skipped.append(f'{src}(0건)')
            continue

        # 이 source 의 DB 레코드 중 이번 run 에서 fetch 안 된 것 삭제
        db_records = BidNotice.query.filter_by(source=src).all()
        to_delete = [n.id for n in db_records if n.source_url not in urls]

        if to_delete:
            try:
                cnt = (BidNotice.query
                       .filter(BidNotice.id.in_(to_delete))
                       .delete(synchronize_session=False))
                db.session.commit()
                deleted += cnt
                print(f'[sync] {src}: {cnt}건 삭제 (DB {len(db_records)} → {len(db_records)-cnt})')
            except Exception as e:
                db.session.rollback()
                print(f'[sync] {src} 삭제 실패: {e}')
                skipped.append(f'{src}(db error)')
                continue
        synced.append(src)

    return {
        'deleted': deleted,
        'synced_sources': synced,
        'skipped_sources': skipped,
    }


def _cleanup_stale_notices(days: int = DEFAULT_FRESHNESS_DAYS) -> dict:
    """DB 에 저장된 BidNotice 중 '과거 사업'에 해당하는 것 삭제.

    기준 (OR 로 하나라도 해당하면 삭제):
      1) created_at 이 현재로부터 `days` 일 이상 지난 레코드
      2) raw_data 내부 게시일(noticedate/pubDate/posted 등)이 `days` 일 이상 지난 레코드
      3) deadline 필드가 파싱 가능한 날짜이면서 오늘(UTC) 이전인 레코드

    Returns:
        dict: {deleted_by_age, deleted_by_posted, deleted_by_deadline, total}
    """
    from datetime import timedelta

    cutoff_dt = datetime.utcnow() - timedelta(days=days)

    all_notices = BidNotice.query.all()
    stale_age_ids = set()
    stale_posted_ids = set()
    stale_deadline_ids = set()

    for n in all_notices:
        # 1) created_at 기준
        if n.created_at and n.created_at < cutoff_dt:
            stale_age_ids.add(n.id)
            continue
        # 2) raw_data 게시일 기준
        posted_dt = _effective_posted_date(n)
        if posted_dt < cutoff_dt:
            stale_posted_ids.add(n.id)
            continue
        # 3) deadline 기준
        if n.deadline and _is_deadline_passed(n.deadline):
            stale_deadline_ids.add(n.id)

    deleted_age = 0
    deleted_posted = 0
    deleted_deadline = 0
    try:
        if stale_age_ids:
            deleted_age = (BidNotice.query
                           .filter(BidNotice.id.in_(stale_age_ids))
                           .delete(synchronize_session=False))
        if stale_posted_ids:
            deleted_posted = (BidNotice.query
                              .filter(BidNotice.id.in_(stale_posted_ids))
                              .delete(synchronize_session=False))
        if stale_deadline_ids:
            deleted_deadline = (BidNotice.query
                                .filter(BidNotice.id.in_(stale_deadline_ids))
                                .delete(synchronize_session=False))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'[cleanup] DB 삭제 실패: {e}')
        return {'deleted_by_age': 0, 'deleted_by_posted': 0,
                'deleted_by_deadline': 0, 'total': 0, 'error': str(e)}

    total = deleted_age + deleted_posted + deleted_deadline

    # 추가 — 중복 레코드 제거 (기준: source + 정규화 title + country 가 같으면
    # 최신 created_at 하나만 남기고 나머지 삭제)
    deleted_dup = _dedupe_existing_notices()

    total += deleted_dup
    if total:
        print(f'[cleanup] 삭제: age={deleted_age} + posted={deleted_posted} '
              f'+ deadline={deleted_deadline} + duplicates={deleted_dup} = {total}')
    return {
        'deleted_by_age': deleted_age,
        'deleted_by_posted': deleted_posted,
        'deleted_by_deadline': deleted_deadline,
        'deleted_duplicates': deleted_dup,
        'total': total,
        'cutoff_days': days,
    }


def _dedupe_existing_notices() -> int:
    """기존 BidNotice 중 (정규화 title, 정규화 country) 조합이 같은 레코드
    중에서 가장 최신 created_at 을 가진 1건만 남기고 나머지 삭제.
    source 는 무시 — 서로 다른 기관이 같은 사업을 공고해도 중복으로 처리.

    Returns: 삭제된 건수.
    """
    groups = {}
    for n in BidNotice.query.all():
        key = (_normalize_title(n.title or ''),
               _normalize_country(n.country or ''))
        if not key[0]:
            continue  # 정규화 제목이 비면 판정 보류
        groups.setdefault(key, []).append(n)

    to_delete_ids = []
    for key, notices in groups.items():
        if len(notices) < 2:
            continue
        # 최신 created_at 을 남김 — None 은 맨 뒤로
        notices.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
        keeper = notices[0]
        for dup in notices[1:]:
            to_delete_ids.append(dup.id)

    if not to_delete_ids:
        return 0
    try:
        deleted = (BidNotice.query
                   .filter(BidNotice.id.in_(to_delete_ids))
                   .delete(synchronize_session=False))
        db.session.commit()
        return deleted
    except Exception as e:
        db.session.rollback()
        print(f'[dedupe] DB 삭제 실패: {e}')
        return 0


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

    try:
        return _do_collect()
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'success': False, 'message': f'수집 중 오류: {e}'}), 500


def _do_collect():
    """collect_notices 의 실제 작업 — 예외 시 호출자가 500 응답 처리."""
    global _existing_fingerprints_cache
    _existing_fingerprints_cache = None  # 매 수집 run 마다 캐시 리셋

    all_items, errors = _run_all_collectors()

    # 캐시 1회 빌드 — _save_notice 에서 매번 query.all() 안 하도록
    _build_fingerprint_cache()

    # 배치 내 선제 중복 제거 — 같은 수집 run 에서 URL 중복 또는
    # (정규화 title, 정규화 country) 중복인 항목 제거 (DB 저장 전).
    # source 는 무시 — 서로 다른 기관이 같은 사업을 공고해도 중복으로 처리.
    deduped = []
    seen_urls = set()
    seen_fingerprints = set()
    for it in all_items:
        url = it.get('source_url', '')
        fp = (_normalize_title(it.get('title', '')),
              _normalize_country(it.get('country', '')))
        if url and url in seen_urls:
            continue
        if fp[0] and fp in seen_fingerprints:
            continue
        seen_urls.add(url)
        if fp[0]:
            seen_fingerprints.add(fp)
        deduped.append(it)
    all_items = deduped

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

    # DB 동기화 — 이번 run 에서 수집되지 않은 기존 레코드 삭제
    fetched_urls_by_source = {}
    for item in all_items:
        fetched_urls_by_source.setdefault(item['source'], set()).add(item['source_url'])
    sync_result = _sync_db_to_latest(fetched_urls_by_source, errors)

    # 수집 완료 후 자동 정리 — 60일 초과 또는 마감된 공고 삭제
    cleanup_result = _cleanup_stale_notices(days=DEFAULT_FRESHNESS_DAYS)

    # ADB/AfDB 상세 페이지 보강 — 마감일·금액·발주처 추출
    enrich_result = _enrich_pending_notices(limit=15)

    # 한국어 번역 — title_ko 비어있는 건만 일괄 처리
    # Vercel Lambda 60s 제약 고려해 1회당 최대 30건만 처리,
    # 나머지는 다음 cron 또는 /translate 엔드포인트로 백필
    translate_result = _translate_pending(limit=30)

    return jsonify({
        'success': True,
        'created': created,
        'skipped': skipped,
        'total_fetched': len(all_items),
        'by_source': created_by_source,
        'errors': errors,
        'sync': sync_result,
        'cleanup': cleanup_result,
        'enrich': enrich_result,
        'translate': translate_result,
        'collected_at': datetime.utcnow().isoformat() + 'Z',
    })


def _extract_excerpt(raw_data) -> str:
    """raw_data 의 details 딕셔너리에서 text_excerpt 추출."""
    if not isinstance(raw_data, dict):
        return ''
    details = (raw_data.get('wb_details')
               or raw_data.get('adb_details')
               or raw_data.get('afdb_details'))
    if not isinstance(details, dict):
        return ''
    return (details.get('text_excerpt') or '').strip()


def _translate_pending(limit: int = 30) -> dict:
    """title_ko / text_excerpt_ko 가 NULL 인 BidNotice 를 HF mBART 로 번역 → DB 저장.

    title 은 단일 호출, text_excerpt(최대 1200자)는 청크 분할 번역.
    HF 호출 횟수 = 미번역 title 수 + sum(excerpt 청크 수).
    limit 은 처리 대상 공고 수 (호출 수 아님).

    Returns:
        {attempted, succeeded_title, succeeded_excerpt, error?, hf_token_set}
    """
    hf_token_set = bool(os.environ.get('HF_TOKEN'))
    if not hf_token_set:
        msg = 'HF_TOKEN 환경변수 미설정 — 번역 불가. Vercel 환경변수에 HuggingFace Read 토큰을 추가하세요.'
        print(f'[translate] {msg}')
        return {'attempted': 0, 'succeeded_title': 0, 'succeeded_excerpt': 0,
                'hf_token_set': False, 'error': msg}

    try:
        from services.translator import (translate_to_korean,
                                          translate_long_to_korean,
                                          get_last_error)
    except Exception as e:
        print(f'[translate] import 실패: {e}')
        return {'attempted': 0, 'succeeded_title': 0, 'succeeded_excerpt': 0,
                'hf_token_set': True, 'error': f'translator import 실패: {e}'}

    pending = (BidNotice.query
               .filter(or_(BidNotice.title_ko.is_(None),
                           BidNotice.text_excerpt_ko.is_(None)))
               .order_by(BidNotice.created_at.desc())
               .limit(limit)
               .all())
    if not pending:
        return {'attempted': 0, 'succeeded_title': 0, 'succeeded_excerpt': 0,
                'hf_token_set': True}

    print(f'[translate] 미번역 {len(pending)}건 번역 시작...')
    succeeded_title = 0
    succeeded_excerpt = 0
    first_error = ''
    for n in pending:
        if n.title_ko is None:
            try:
                ko = translate_to_korean(n.title)
            except Exception as e:
                ko = None
                if not first_error:
                    first_error = str(e)
            if ko:
                n.title_ko = ko[:500]
                succeeded_title += 1
            elif not first_error:
                first_error = get_last_error()

        if n.text_excerpt_ko is None:
            excerpt = _extract_excerpt(n.raw_data)
            if not excerpt:
                n.text_excerpt_ko = ''  # 발췌 없음 — 재시도 방지
            else:
                try:
                    ko_long = translate_long_to_korean(excerpt)
                except Exception as e:
                    ko_long = None
                    if not first_error:
                        first_error = str(e)
                if ko_long:
                    n.text_excerpt_ko = ko_long
                    succeeded_excerpt += 1
                elif not first_error:
                    first_error = get_last_error()
    print(f'[translate] 결과: title {succeeded_title} / excerpt {succeeded_excerpt} 성공')

    if succeeded_title or succeeded_excerpt:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {'attempted': len(pending), 'succeeded_title': 0,
                    'succeeded_excerpt': 0, 'hf_token_set': True,
                    'error': f'commit 실패: {e}'}
    else:
        # 발췌 없음 표시(text_excerpt_ko='') 만 일어났을 수 있음 → 그것도 commit
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    result = {
        'attempted': len(pending),
        'succeeded_title': succeeded_title,
        'succeeded_excerpt': succeeded_excerpt,
        'hf_token_set': True,
    }
    if first_error:
        result['first_error'] = first_error[:500]
    return result


@collector_bp.route('/translate', methods=['POST'])
def translate_pending_endpoint():
    """미번역 공고 백필 — 수동/스케줄 호출.
    쿼리: ?limit=N (기본 30, 최대 100)
    인증: COLLECT_SECRET (collect 와 동일).
    """
    if not _check_collect_auth():
        return jsonify({'success': False, 'message': '인증 실패'}), 401
    try:
        limit = int(request.args.get('limit', 30))
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 100))
    return jsonify({'success': True, **_translate_pending(limit=limit)})


@collector_bp.route('/enrich', methods=['POST'])
def enrich_notices_endpoint():
    """ADB/AfDB 상세 페이지 보강 — 수동 백필.
    쿼리: ?limit=N (기본 15, 최대 50)
    인증: COLLECT_SECRET.
    """
    if not _check_collect_auth():
        return jsonify({'success': False, 'message': '인증 실패'}), 401
    try:
        limit = int(request.args.get('limit', 15))
    except (TypeError, ValueError):
        limit = 15
    limit = max(1, min(limit, 50))
    return jsonify({'success': True, **_enrich_pending_notices(limit=limit)})


@collector_bp.route('/cleanup', methods=['POST'])
def cleanup_notices():
    """오래된·마감된 공고 수동 정리 엔드포인트.
    인증은 collect 와 동일(COLLECT_SECRET) — 관리자 전용.
    쿼리 파라미터 ?days=N 으로 기준일 조정 가능 (기본 60일).
    """
    if not _check_collect_auth():
        return jsonify({'success': False, 'message': '인증 실패'}), 401

    try:
        days = int(request.args.get('days', DEFAULT_FRESHNESS_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_FRESHNESS_DAYS
    days = max(1, min(days, 365))  # 과도한 삭제 방지

    result = _cleanup_stale_notices(days=days)
    return jsonify({'success': True, **result})


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
