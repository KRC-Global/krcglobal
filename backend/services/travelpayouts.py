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
    """편도/왕복 검색."""
    _, _, base, _ = _get_config()
    url = f'{base}/aviasales/v3/prices_for_dates'
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'destination': destination.upper(),
        'departure_at': departure_date,
        'currency': currency.lower(),
        'unique': 'false',
        'sorting': 'price',
        'limit': max(1, min(int(max_results), 1000)),
        'page': 1,
        'one_way': 'true' if not return_date else 'false',
    }
    if return_date:
        params['return_at'] = return_date
    if non_stop is True:
        params['direct'] = 'true'

    data = _request('GET', url, params=params)
    if data is None:
        return None
    if not isinstance(data, dict) or not data.get('success', True):
        # success: false 인 경우도 있음
        _set_error(f"Travelpayouts 응답 success=false: {str(data)[:200]}")
        return None

    rows = data.get('data') or []
    offers: List[Dict[str, Any]] = []
    pax = max(1, int(adults or 1)) + max(0, int(children or 0))
    for r in rows:
        offer = _build_offer_from_v3(r, currency=currency)
        # 인원 곱하기 (Travelpayouts 가격은 1인 기준이 일반적)
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
    """가격 캘린더용. Travelpayouts 는 prices_for_dates 로 날짜 범위 조회."""
    _, _, base, _ = _get_config()

    # 날짜 결정: range 가 있으면 시작일을 기준으로, 없으면 departure_date 의 해당 월
    start_date = None
    end_date = None
    if departure_date_range and ',' in departure_date_range:
        s, e = departure_date_range.split(',', 1)
        start_date = s.strip()
        end_date = e.strip()
    elif departure_date:
        start_date = departure_date

    if not start_date:
        _set_error('출발일 또는 출발일 범위가 필요합니다.')
        return None

    url = f'{base}/aviasales/v3/prices_for_dates'
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'destination': destination.upper(),
        'departure_at': start_date,
        'currency': currency.lower(),
        'unique': 'true',  # 날짜별 1개씩
        'sorting': 'price',
        'limit': 60,
        'one_way': 'true' if one_way else 'false',
    }
    if non_stop is True:
        params['direct'] = 'true'

    data = _request('GET', url, params=params)
    if data is None:
        return None

    rows = data.get('data') or []
    items: List[Dict[str, Any]] = []
    for r in rows:
        dep = r.get('departure_at') or ''
        ret = r.get('return_at') or ''
        # ISO datetime → date 부분만
        dep_date = dep.split('T')[0] if dep else None
        ret_date = ret.split('T')[0] if ret else None
        if end_date and dep_date and (dep_date < start_date or dep_date > end_date):
            continue
        price = float(r.get('price') or 0)
        if max_price and price > int(max_price):
            continue
        items.append({
            'origin': r.get('origin'),
            'destination': r.get('destination'),
            'departure_date': dep_date,
            'return_date': ret_date,
            'price_total': price,
            'currency': currency.upper(),
        })
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
