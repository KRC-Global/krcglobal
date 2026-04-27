"""
Travelpayouts (Aviasales) Data API 클라이언트.

amadeus.py 와 동일한 함수 시그니처/응답 형태를 제공한다.
프로바이더 교체 시 routes/flights.py 를 수정하지 않아도 되도록 인터페이스 호환.

함수:
    is_configured() -> bool
    get_last_error() -> str
    search_airports(keyword, limit) -> list | None
    search_flight_offers(...) -> {offers, currency, count, dictionaries} | None
    search_multi_city(origin_destinations, ...) -> {offers, currency, count, dictionaries} | None
    search_cheapest_dates(origin, destination, ...) -> {items, currency, count} | None
    search_inspiration(origin, ...) -> {items, currency, count} | None

엔드포인트:
    Autocomplete (인증 불필요): {AUTOCOMPLETE_URL}/places2
    Flight prices for dates    : {BASE_URL}/aviasales/v3/prices_for_dates
    Calendar (월별 매트릭스)    : {BASE_URL}/v2/prices/month-matrix
    Anywhere (latest cheap)    : {BASE_URL}/v2/prices/latest

응답 정규화 정책:
- Travelpayouts 는 segment 단위 정보(터미널·기종·경유 공항)를 제공하지 않음.
  → 단일 segment 로 응답을 만들고 stops 카운트만 transfers 값으로 채움.
  프론트의 카드 표시는 그대로 동작 (stops 텍스트 + 출도착 IATA + 시간만 사용).
"""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import requests


HTTP_TIMEOUT = 15
DEFAULT_BASE_URL = 'https://api.travelpayouts.com'
DEFAULT_AUTOCOMPLETE_URL = 'https://autocomplete.travelpayouts.com'

_last_error_lock = threading.Lock()
_last_error: str = ''


# ────────────── 설정 ──────────────

def _get_config() -> Tuple[str, str, str, str]:
    token = os.environ.get('TRAVELPAYOUTS_TOKEN', '').strip()
    marker = os.environ.get('TRAVELPAYOUTS_MARKER', '').strip()
    base = os.environ.get('TRAVELPAYOUTS_BASE_URL', DEFAULT_BASE_URL).strip().rstrip('/')
    ac = os.environ.get('TRAVELPAYOUTS_AUTOCOMPLETE_URL', DEFAULT_AUTOCOMPLETE_URL).strip().rstrip('/')
    return token, marker, base, ac


def is_configured() -> bool:
    token, _, _, _ = _get_config()
    return bool(token)


def get_last_error() -> str:
    with _last_error_lock:
        return _last_error


def _set_error(msg: str) -> None:
    global _last_error
    with _last_error_lock:
        _last_error = msg
    print(f'[travelpayouts] {msg}')


# ────────────── 공통 요청 ──────────────

def _request(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    auth_required: bool = True,
    retries: int = 2,
) -> Optional[Any]:
    token, _, _, _ = _get_config()
    if auth_required and not token:
        _set_error('TRAVELPAYOUTS_TOKEN 환경변수 미설정')
        return None

    headers = {'Accept-Encoding': 'gzip, deflate'}
    if auth_required:
        headers['X-Access-Token'] = token

    for attempt in range(retries + 1):
        try:
            resp = requests.request(
                method.upper(), url,
                params=params, headers=headers, timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            _set_error(f'네트워크 오류: {e} (attempt {attempt + 1})')
            if attempt < retries:
                time.sleep(1.2)
                continue
            return None

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                _set_error(f'JSON 파싱 실패: {resp.text[:200]}')
                return None

        if resp.status_code in (500, 502, 503, 504) and attempt < retries:
            _set_error(f'Travelpayouts 일시 오류 HTTP {resp.status_code} (attempt {attempt + 1})')
            time.sleep(1.2)
            continue

        try:
            err = resp.json()
        except ValueError:
            err = {'raw': resp.text[:300]}
        _set_error(f'Travelpayouts HTTP {resp.status_code}: {str(err)[:400]}')
        return None

    return None


# ────────────── 응답 정규화 ──────────────

# 자주 등장하는 항공사 IATA → 한국어/영어 이름 매핑.
# Travelpayouts 가 항공사 풀네임을 응답에 포함하지 않으므로 보강 사전.
# 누락된 코드는 그대로 코드 표시(폴백).
_CARRIER_NAMES: Dict[str, str] = {
    # 한국
    'KE': '대한항공', 'OZ': '아시아나항공', 'BX': '에어부산',
    '7C': '제주항공', 'LJ': '진에어', 'TW': '티웨이항공',
    'ZE': '이스타항공', 'RS': '에어서울', 'YP': '에어프레미아', 'RF': '에어로케이',
    # 일본
    'JL': '일본항공', 'NH': '전일본공수', 'MM': '피치항공', 'GK': '지프스타재팬',
    # 중국·홍콩·대만
    'CA': '에어차이나', 'CZ': '중국남방항공', 'MU': '중국동방항공',
    'HU': '하이난항공', 'CX': '캐세이퍼시픽', 'KA': '캐세이드래곤',
    'HX': '홍콩항공', 'BR': '에바항공', 'CI': '중화항공',
    # 동남아
    'SQ': '싱가포르항공', 'MI': '실크에어', 'TR': '스쿠트',
    'MH': '말레이시아항공', 'AK': '에어아시아', 'TG': '타이항공',
    'PG': '방콕에어웨이', 'FD': '타이에어아시아',
    'VN': '베트남항공', 'VJ': '비엣젯항공', 'PR': '필리핀항공',
    'GA': '가루다인도네시아', 'QZ': '인도네시아에어아시아', 'JT': '라이언에어',
    # 중동
    'EK': '에미레이트항공', 'EY': '에티하드항공', 'QR': '카타르항공',
    'TK': '터키항공', 'SV': '사우디아', 'WY': '오만에어',
    # 유럽
    'LH': '루프트한자', 'LX': '스위스국제항공', 'OS': '오스트리아항공',
    'AF': '에어프랑스', 'KL': 'KLM', 'BA': '브리티시에어웨이즈',
    'IB': '이베리아항공', 'AY': '핀에어', 'SK': 'SAS',
    'AZ': 'ITA항공', 'LO': 'LOT폴란드항공', 'TP': 'TAP포르투갈',
    # 북미
    'UA': '유나이티드항공', 'AA': '아메리칸항공', 'DL': '델타항공',
    'AC': '에어캐나다', 'AS': '알래스카항공', 'B6': '제트블루',
    'WN': '사우스웨스트', 'NK': '스피릿', 'F9': '프론티어',
    'HA': '하와이안항공',
    # 오세아니아·기타
    'QF': '콴타스', 'NZ': '뉴질랜드항공', 'VA': '버진오스트레일리아',
    'FJ': '피지에어웨이즈',
    # 인도·중앙아
    'AI': '에어인디아', '6E': '인디고', 'UK': '비스타라', 'SG': '스파이스젯',
    'KC': '에어아스타나', 'HY': '우즈베키스탄항공',
    # 아프리카·기타
    'ET': '에티오피아항공', 'KQ': '케냐항공', 'MS': '이집트에어',
    'SA': '남아프리카항공',
}


def carrier_display_name(code: Optional[str]) -> str:
    if not code:
        return ''
    return _CARRIER_NAMES.get(code.upper(), code.upper())


def _make_segment(
    *, origin: str, destination: str,
    departure_iso: Optional[str], arrival_iso: Optional[str],
    duration_minutes: int, carrier: Optional[str], flight_number: Optional[str],
) -> Dict[str, Any]:
    return {
        'carrier': carrier,
        'carrier_name': carrier_display_name(carrier),
        'flight_number': flight_number,
        'from': origin,
        'from_terminal': None,
        'to': destination,
        'to_terminal': None,
        'departure': departure_iso,
        'arrival': arrival_iso,
        'duration_minutes': duration_minutes,
        'aircraft': None,
        'cabin': None,
    }


def _add_minutes(iso: Optional[str], minutes: int) -> Optional[str]:
    if not iso:
        return None
    try:
        # 'YYYY-MM-DDTHH:MM:SS+09:00' 형식 가정
        from datetime import datetime, timezone, timedelta
        # 타임존 보존 위해 fromisoformat 사용 (Python 3.7+)
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        dt2 = dt + timedelta(minutes=int(minutes or 0))
        return dt2.isoformat()
    except Exception:
        return None


def _build_offer_from_v3(item: Dict[str, Any], currency: str) -> Dict[str, Any]:
    """aviasales/v3/prices_for_dates 의 1개 row → 정규화 offer."""
    origin = item.get('origin') or item.get('origin_airport')
    destination = item.get('destination') or item.get('destination_airport')
    price_total = float(item.get('price') or 0)
    airline = item.get('airline')
    flight_number = item.get('flight_number')
    transfers = int(item.get('transfers') or 0)
    return_transfers = int(item.get('return_transfers') or 0)
    duration_to = int(item.get('duration_to') or item.get('duration') or 0)
    duration_back = int(item.get('duration_back') or 0)
    departure_at = item.get('departure_at')
    return_at = item.get('return_at')

    out_segs = [
        _make_segment(
            origin=origin, destination=destination,
            departure_iso=departure_at,
            arrival_iso=_add_minutes(departure_at, duration_to),
            duration_minutes=duration_to,
            carrier=airline, flight_number=flight_number,
        )
    ]
    itineraries = [{
        'duration_minutes': duration_to,
        'segments': out_segs,
        'stops': transfers,
    }]
    if return_at:
        back_segs = [
            _make_segment(
                origin=destination, destination=origin,
                departure_iso=return_at,
                arrival_iso=_add_minutes(return_at, duration_back),
                duration_minutes=duration_back,
                carrier=airline, flight_number=None,
            )
        ]
        itineraries.append({
            'duration_minutes': duration_back,
            'segments': back_segs,
            'stops': return_transfers,
        })

    return {
        'id': f"tp:{origin}-{destination}:{departure_at or ''}:{int(price_total)}:{airline or ''}:{flight_number or ''}",
        'price': {
            'total': price_total,
            'base': price_total,
            'currency': currency.upper(),
        },
        'itineraries': itineraries,
        'travelers': 1,
        'class': 'ECONOMY',
        'seats_available': None,
        'last_ticketing_date': item.get('expires_at'),
        'validating_carriers': [airline] if airline else [],
        # 외부 OTA 링크 (예약은 외부에서)
        'external_link': item.get('link'),
    }


# ────────────── 검색 함수 ──────────────

def search_airports(keyword: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
    """공항/도시 자동완성 (Travelpayouts places2, 인증 불필요)."""
    if not keyword or len(keyword.strip()) < 2:
        return []
    _, _, _, ac = _get_config()
    url = f'{ac}/places2'
    data = _request('GET', url, params={
        'term': keyword.strip(),
        'locale': 'ko',
        'types[]': ['airport', 'city'],
    }, auth_required=False)
    if data is None:
        return None
    if not isinstance(data, list):
        return []

    out: List[Dict[str, Any]] = []
    for loc in data[:limit]:
        kind = (loc.get('type') or '').lower()  # 'airport' | 'city'
        iata = loc.get('code')
        if not iata:
            continue
        out.append({
            'iata': iata,
            'name': loc.get('name') or '',
            'detailed_name': loc.get('name') or '',
            'city': loc.get('city_name') or loc.get('name'),
            'city_code': loc.get('city_code') or iata,
            'country': loc.get('country_name'),
            'country_code': loc.get('country_code'),
            'subtype': 'CITY' if kind == 'city' else 'AIRPORT',
            'latitude': (loc.get('coordinates') or {}).get('lat'),
            'longitude': (loc.get('coordinates') or {}).get('lon'),
        })
    return out


def _market_param() -> str:
    """Travelpayouts 'market' 파라미터.

    기본값을 'us' 로 둔다. 그대로 두면 API 가 'ru' 로 동작해 한국 시장 데이터가
    빈약해지는 경향이 있음. TRAVELPAYOUTS_MARKET 으로 덮어쓸 수 있다.
    """
    return os.environ.get('TRAVELPAYOUTS_MARKET', 'us').strip().lower() or 'us'


def _v3_prices_for_dates(
    *, base: str,
    origin: str,
    destination: str,
    departure_at: str,        # 'YYYY-MM-DD' 또는 'YYYY-MM'
    return_at: Optional[str] = None,
    one_way: bool,
    currency: str,
    non_stop: Optional[bool],
    sorting: str = 'price',
    unique: bool = False,
    limit: int = 1000,
) -> Optional[List[Dict[str, Any]]]:
    """aviasales/v3/prices_for_dates 단일 호출. 결과 row 배열만 반환."""
    url = f'{base}/aviasales/v3/prices_for_dates'
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'destination': destination.upper(),
        'departure_at': departure_at,
        'currency': currency.lower(),
        'market': _market_param(),
        'unique': 'true' if unique else 'false',
        'sorting': sorting,
        'limit': max(1, min(int(limit), 1000)),
        'page': 1,
        'one_way': 'true' if one_way else 'false',
    }
    if return_at:
        params['return_at'] = return_at
    if non_stop is True:
        params['direct'] = 'true'

    data = _request('GET', url, params=params)
    if data is None:
        return None
    if isinstance(data, dict) and data.get('success') is False:
        _set_error(f"prices_for_dates success=false: {str(data)[:200]}")
        return []
    return (data or {}).get('data') or []


def search_flight_offers(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,           # Travelpayouts는 인원 분리 미지원 (1인 가격) → 곱하기로 대응
    infants: int = 0,
    travel_class: Optional[str] = None,
    non_stop: Optional[bool] = None,
    max_price: Optional[int] = None,
    currency: str = 'KRW',
    max_results: int = 50,
) -> Optional[Dict[str, Any]]:
    """편도/왕복 검색.

    Travelpayouts prices_for_dates 의 캐시 특성상 *정확한 날짜* 로만 조회하면
    인기 노선이라도 0건이 자주 나온다. 따라서 두 단계로 폴백한다:
        1차: departure_at='YYYY-MM-DD' (사용자 지정 날짜)
        2차: 1차가 비었으면 departure_at='YYYY-MM' 월 단위 조회 → 사용자 날짜 ±3일 우선,
             그 다음 같은 월 내 가격 순으로 보충
    """
    _, _, base, _ = _get_config()
    one_way = not return_date
    return_month = (return_date or '')[:7] if return_date else None

    # ───── 1차: 정확 날짜 ─────
    rows = _v3_prices_for_dates(
        base=base, origin=origin, destination=destination,
        departure_at=departure_date,
        return_at=return_date,
        one_way=one_way, currency=currency, non_stop=non_stop,
        sorting='price', unique=False, limit=max_results,
    )
    if rows is None:
        return None

    # ───── 2차: 월 단위 폴백 (1차 결과 비었을 때) ─────
    used_fallback = False
    if not rows:
        used_fallback = True
        month = departure_date[:7]
        month_rows = _v3_prices_for_dates(
            base=base, origin=origin, destination=destination,
            departure_at=month,
            return_at=return_month,
            one_way=one_way, currency=currency, non_stop=non_stop,
            sorting='price', unique=False, limit=1000,
        ) or []

        # 사용자가 원한 날짜 ±3일 → 가까운 순 정렬
        try:
            from datetime import datetime, timedelta
            target = datetime.strptime(departure_date, '%Y-%m-%d')

            def _diff(r):
                dep = (r.get('departure_at') or '')[:10]
                try:
                    d = datetime.strptime(dep, '%Y-%m-%d')
                    return abs((d - target).days)
                except ValueError:
                    return 999
            month_rows.sort(key=lambda r: (_diff(r), float(r.get('price') or 0)))
        except Exception:
            pass

        rows = month_rows[:max(1, int(max_results))]
        if not rows:
            _set_error(f"Travelpayouts 응답: {origin.upper()}→{destination.upper()} {departure_date} 인근 데이터 없음")

    offers: List[Dict[str, Any]] = []
    pax = max(1, int(adults or 1)) + max(0, int(children or 0))
    for r in rows:
        offer = _build_offer_from_v3(r, currency=currency)
        offer['price']['total'] = round(offer['price']['total'] * pax)
        offer['price']['base'] = round(offer['price']['base'] * pax)
        offer['travelers'] = pax
        if max_price and offer['price']['total'] > int(max_price):
            continue
        if travel_class:
            offer['class'] = travel_class.upper()
        offers.append(offer)

    # 캐리어 사전: IATA 코드 → 한국어 명칭 (없으면 코드 그대로)
    carriers: Dict[str, str] = {}
    for o in offers:
        for c in o.get('validating_carriers') or []:
            carriers.setdefault(c, carrier_display_name(c))
        for it in o.get('itineraries') or []:
            for s in it.get('segments') or []:
                if s.get('carrier'):
                    carriers.setdefault(s['carrier'], carrier_display_name(s['carrier']))

    return {
        'offers': offers,
        'currency': currency.upper(),
        'count': len(offers),
        'dictionaries': {'carriers': carriers, 'aircraft': {}},
        'fallback': used_fallback,
        'requested_date': departure_date,
    }


def search_multi_city(
    origin_destinations: List[Dict[str, str]],
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    travel_class: Optional[str] = None,
    currency: str = 'KRW',
    max_results: int = 50,
) -> Optional[Dict[str, Any]]:
    """다구간(멀티시티) 검색.

    Travelpayouts 는 진짜 멀티시티를 지원하지 않으므로 각 구간을 병렬 조회한 뒤
    구간별 최저가 후보를 조합해서 합쳐진 offer 를 만든다.
    """
    if not origin_destinations or len(origin_destinations) < 2:
        _set_error('멀티시티는 최소 2개 구간 필요')
        return None

    legs: List[Dict[str, Any]] = []

    def _fetch_leg(idx: int, od: Dict[str, str]) -> Tuple[int, Optional[Dict[str, Any]]]:
        try:
            res = search_flight_offers(
                origin=od.get('origin', ''),
                destination=od.get('destination', ''),
                departure_date=od.get('date', ''),
                adults=adults, children=children, infants=infants,
                travel_class=travel_class, currency=currency,
                max_results=10,
            )
            return idx, res
        except Exception as e:
            _set_error(f'구간 {idx + 1} 조회 실패: {e}')
            return idx, None

    with ThreadPoolExecutor(max_workers=min(6, len(origin_destinations))) as pool:
        futures = [pool.submit(_fetch_leg, i, od) for i, od in enumerate(origin_destinations)]
        legs_raw: List[Optional[Dict[str, Any]]] = [None] * len(origin_destinations)
        for fut in as_completed(futures):
            idx, res = fut.result()
            legs_raw[idx] = res

    # 모든 구간이 비어 있으면 실패 처리
    if all((not r) or (not r.get('offers')) for r in legs_raw):
        if not get_last_error():
            _set_error('각 구간에서 항공편을 찾지 못했습니다.')
        return None

    # 구간별 상위 3개 후보로 조합 (3^N 폭주 방지)
    top_per_leg = []
    for r in legs_raw:
        if r and r.get('offers'):
            top_per_leg.append(r['offers'][:3])
        else:
            top_per_leg.append([])

    # 누락 구간이 있어도 가능한 부분만 조합
    if any(not lst for lst in top_per_leg):
        # 가능한 부분만 카드로 노출 (각 leg 의 최저가만 제시)
        offers = []
        for i, lst in enumerate(top_per_leg):
            if lst:
                offers.append(lst[0])
        carriers: Dict[str, str] = {}
        for o in offers:
            for c in o.get('validating_carriers') or []:
                carriers.setdefault(c, carrier_display_name(c))
        return {
            'offers': offers,
            'currency': currency.upper(),
            'count': len(offers),
            'dictionaries': {'carriers': carriers, 'aircraft': {}},
            'synthesized': True,
            'partial': True,
        }

    # 모든 구간이 결과 있음 → 데카르트 조합 후 가격순
    from itertools import product
    combinations = list(product(*top_per_leg))
    combined: List[Dict[str, Any]] = []
    for combo in combinations:
        total = sum(c['price']['total'] for c in combo)
        itineraries = []
        for c in combo:
            itineraries.extend(c['itineraries'])
        carriers_in = []
        for c in combo:
            for v in (c.get('validating_carriers') or []):
                if v and v not in carriers_in:
                    carriers_in.append(v)
        combined.append({
            'id': 'tp-multi:' + ':'.join(c['id'] for c in combo),
            'price': {'total': total, 'base': total, 'currency': currency.upper()},
            'itineraries': itineraries,
            'travelers': max(c.get('travelers') or 1 for c in combo),
            'class': travel_class.upper() if travel_class else 'ECONOMY',
            'seats_available': None,
            'last_ticketing_date': None,
            'validating_carriers': carriers_in,
            'external_link': None,
        })

    combined.sort(key=lambda x: x['price']['total'])
    combined = combined[:max(1, min(int(max_results), 100))]

    carriers_dict: Dict[str, str] = {}
    for o in combined:
        for c in o.get('validating_carriers') or []:
            carriers_dict.setdefault(c, carrier_display_name(c))

    return {
        'offers': combined,
        'currency': currency.upper(),
        'count': len(combined),
        'dictionaries': {'carriers': carriers_dict, 'aircraft': {}},
        'synthesized': True,
    }


def _months_in_range(start: str, end: str) -> List[str]:
    """'YYYY-MM-DD' start~end 사이 모든 월(YYYY-MM) 반환."""
    from datetime import date
    try:
        sy, sm, _ = start.split('-')
        ey, em, _ = end.split('-')
    except ValueError:
        return []
    months: List[str] = []
    y, m = int(sy), int(sm)
    ey_i, em_i = int(ey), int(em)
    while (y, m) <= (ey_i, em_i):
        months.append(f'{y:04d}-{m:02d}')
        m += 1
        if m > 12:
            m = 1
            y += 1
        if len(months) > 24:  # safety
            break
    return months


def _calendar_v1(
    base: str,
    origin: str,
    destination: str,
    depart_month: str,           # 'YYYY-MM'
    return_month: Optional[str],  # 'YYYY-MM' or None
    currency: str,
    non_stop: Optional[bool],
) -> Optional[List[Dict[str, Any]]]:
    """`/v1/prices/calendar` — 월 단위 일자별 최저가 (1차 소스)."""
    url = f'{base}/v1/prices/calendar'
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'destination': destination.upper(),
        'depart_date': depart_month,
        'calendar_type': 'departure_date',
        'currency': currency.lower(),
        'market': _market_param(),
    }
    if return_month:
        params['return_date'] = return_month

    data = _request('GET', url, params=params)
    if data is None:
        return None
    if not data.get('success', True):
        # v1 은 success:false 도 200 으로 줄 수 있음
        return []

    rows: List[Dict[str, Any]] = []
    raw = data.get('data')
    if isinstance(raw, dict):
        # {date: {price, ...}} 형태
        for date_key, val in raw.items():
            if not isinstance(val, dict):
                continue
            if non_stop and (val.get('transfers') or 0) > 0:
                continue
            price = val.get('price') or val.get('value')
            if not price:
                continue
            rows.append({
                'origin': val.get('origin') or origin.upper(),
                'destination': val.get('destination') or destination.upper(),
                'departure_date': date_key,
                'return_date': (val.get('return_at') or '').split('T')[0] or None,
                'price_total': float(price),
            })
    elif isinstance(raw, list):
        for val in raw:
            if not isinstance(val, dict):
                continue
            if non_stop and (val.get('transfers') or val.get('number_of_changes') or 0) > 0:
                continue
            price = val.get('price') or val.get('value')
            if not price:
                continue
            dep = val.get('depart_date') or val.get('departure_at') or ''
            rows.append({
                'origin': val.get('origin') or origin.upper(),
                'destination': val.get('destination') or destination.upper(),
                'departure_date': dep.split('T')[0] if dep else None,
                'return_date': (val.get('return_date') or val.get('return_at') or '').split('T')[0] or None,
                'price_total': float(price),
            })
    return rows


def _prices_for_dates_fallback(
    base: str,
    origin: str,
    destination: str,
    start_date: str,
    one_way: bool,
    currency: str,
    non_stop: Optional[bool],
) -> List[Dict[str, Any]]:
    """`/aviasales/v3/prices_for_dates` — 폴백. 단일 호출, unique 제거."""
    url = f'{base}/aviasales/v3/prices_for_dates'
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'destination': destination.upper(),
        'departure_at': start_date[:7],  # 'YYYY-MM' 형태로 월 전체 조회
        'currency': currency.lower(),
        'market': _market_param(),
        'sorting': 'price',
        'limit': 1000,
        'one_way': 'true' if one_way else 'false',
    }
    if non_stop is True:
        params['direct'] = 'true'

    data = _request('GET', url, params=params)
    if data is None:
        return []

    rows = data.get('data') or []
    out: List[Dict[str, Any]] = []
    for r in rows:
        dep = r.get('departure_at') or ''
        ret = r.get('return_at') or ''
        out.append({
            'origin': r.get('origin'),
            'destination': r.get('destination'),
            'departure_date': dep.split('T')[0] if dep else None,
            'return_date': ret.split('T')[0] if ret else None,
            'price_total': float(r.get('price') or 0),
        })
    return out


def search_cheapest_dates(
    origin: str,
    destination: str,
    departure_date: Optional[str] = None,
    departure_date_range: Optional[str] = None,  # 'YYYY-MM-DD,YYYY-MM-DD'
    duration: Optional[str] = None,
    one_way: bool = False,
    currency: str = 'KRW',
    max_price: Optional[int] = None,
    non_stop: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """가격 캘린더 데이터.

    1차: `/v1/prices/calendar` (월 단위, 일자별 최저가) — 캘린더 UI 에 최적
    2차: `/aviasales/v3/prices_for_dates` (월 단위, sorting=price) 폴백
    범위가 2개월에 걸치면 월별로 호출 후 머지. 동일 날짜 중복은 최저가만 유지.
    """
    _, _, base, _ = _get_config()

    start_date = None
    end_date = None
    if departure_date_range and ',' in departure_date_range:
        s, e = departure_date_range.split(',', 1)
        start_date = s.strip()
        end_date = e.strip()
    elif departure_date:
        start_date = departure_date
        # 출발일 단독 — ±15일 범위로 자동 확장
        try:
            from datetime import datetime, timedelta
            d0 = datetime.strptime(departure_date, '%Y-%m-%d')
            start_date = (d0 - timedelta(days=15)).strftime('%Y-%m-%d')
            end_date = (d0 + timedelta(days=15)).strftime('%Y-%m-%d')
        except ValueError:
            pass

    if not start_date:
        _set_error('출발일 또는 출발일 범위가 필요합니다.')
        return None
    if not end_date:
        end_date = start_date

    months = _months_in_range(start_date, end_date) or [start_date[:7]]
    return_month = None
    if not one_way and departure_date:
        # 라운드트립 시: depart_date 의 +N일 후를 return_date 월로 사용
        return_month = months[-1]  # 단순화

    # ───── 1차: v1/prices/calendar ─────
    aggregated: Dict[str, Dict[str, Any]] = {}  # date → cheapest item
    for m in months:
        rows = _calendar_v1(base, origin, destination, m, return_month,
                            currency, non_stop)
        if rows is None:
            break  # 네트워크/인증 오류 → 폴백
        for r in rows:
            d = r.get('departure_date')
            if not d:
                continue
            if d < start_date or d > end_date:
                continue
            cur = aggregated.get(d)
            if cur is None or r['price_total'] < cur['price_total']:
                aggregated[d] = r

    # ───── 2차: prices_for_dates (1차가 비었거나 sparse 한 경우) ─────
    if len(aggregated) < max(7, (len(months) * 7)):
        for m in months:
            month_start = f'{m}-01'
            rows = _prices_for_dates_fallback(
                base, origin, destination, month_start, one_way,
                currency, non_stop)
            for r in rows:
                d = r.get('departure_date')
                if not d:
                    continue
                if d < start_date or d > end_date:
                    continue
                cur = aggregated.get(d)
                if cur is None or r['price_total'] < cur['price_total']:
                    aggregated[d] = r

    # max_price 필터
    items = list(aggregated.values())
    if max_price:
        items = [x for x in items if x['price_total'] <= int(max_price)]
    items.sort(key=lambda x: x.get('departure_date') or '')
    for x in items:
        x['currency'] = currency.upper()

    return {'items': items, 'currency': currency.upper(), 'count': len(items)}


def search_inspiration(
    origin: str,
    max_price: Optional[int] = None,
    departure_date: Optional[str] = None,
    departure_date_range: Optional[str] = None,
    duration: Optional[str] = None,
    one_way: bool = False,
    currency: str = 'KRW',
    non_stop: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """어디로든(Anywhere) 검색.

    /v2/prices/latest 는 출발지 기준으로 어떤 도착지가 싼지 캐시된 결과를 돌려준다.
    """
    _, _, base, _ = _get_config()
    url = f'{base}/v2/prices/latest'
    params: Dict[str, Any] = {
        'currency': currency.lower(),
        'origin': origin.upper(),
        'period_type': 'year',
        'page': 1,
        'limit': 30,
        'show_to_affiliates': 'true',
        'sorting': 'price',
        'market': _market_param(),
        'one_way': 'true' if one_way else 'false',
    }
    if departure_date:
        params['beginning_of_period'] = departure_date
    if non_stop is True:
        params['direct'] = 'true'

    data = _request('GET', url, params=params)
    if data is None:
        return None

    rows = (data or {}).get('data') or []
    items: List[Dict[str, Any]] = []
    for r in rows:
        price = float(r.get('value') or 0)
        if max_price and price > int(max_price):
            continue
        dep = r.get('depart_date')
        ret = r.get('return_date')
        items.append({
            'origin': r.get('origin'),
            'destination': r.get('destination'),
            'departure_date': dep,
            'return_date': ret,
            'price_total': price,
            'currency': currency.upper(),
            'links': {},
        })
    items.sort(key=lambda x: x['price_total'])
    return {'items': items, 'currency': currency.upper(), 'count': len(items)}
