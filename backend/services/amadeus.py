"""
Amadeus Self-Service API 클라이언트.

- OAuth2 Client Credentials Flow → access_token 메모리 캐시
- 항공권 Offers/Cheapest Dates/Inspiration/Locations/Multi-city 래퍼
- 응답 정규화: 프론트가 그대로 렌더 가능한 단순 dict 반환

설정(필수 환경변수):
    AMADEUS_CLIENT_ID
    AMADEUS_CLIENT_SECRET
    AMADEUS_BASE_URL  (선택, 기본 https://test.api.amadeus.com)

translator.py 와 같은 패턴(모듈 레벨 캐시, 재시도, last_error 캡처)을 따른다.
"""
import os
import time
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests


HTTP_TIMEOUT = 20  # Amadeus 응답 평균 1~3초, 멀티시티는 좀 더 걸릴 수 있음
DEFAULT_BASE_URL = 'https://test.api.amadeus.com'
TOKEN_PATH = '/v1/security/oauth2/token'
TOKEN_REFRESH_MARGIN = 30  # 만료 30초 전에 미리 갱신

_token_lock = threading.Lock()
_token_cache: Dict[str, Any] = {'access_token': None, 'expires_at': 0.0}
_last_error: str = ''


# ---------- 설정 헬퍼 ----------

def _get_config() -> Tuple[str, str, str]:
    client_id = os.environ.get('AMADEUS_CLIENT_ID', '').strip()
    client_secret = os.environ.get('AMADEUS_CLIENT_SECRET', '').strip()
    base_url = os.environ.get('AMADEUS_BASE_URL', DEFAULT_BASE_URL).strip().rstrip('/')
    return client_id, client_secret, base_url


def is_configured() -> bool:
    cid, secret, _ = _get_config()
    return bool(cid and secret)


def get_last_error() -> str:
    return _last_error


def _set_error(msg: str) -> None:
    global _last_error
    _last_error = msg
    print(f'[amadeus] {msg}')


# ---------- 토큰 ----------

def _get_access_token(force_refresh: bool = False) -> Optional[str]:
    """Client Credentials Flow 로 access_token 획득 + 캐시."""
    cid, secret, base_url = _get_config()
    if not cid or not secret:
        _set_error('AMADEUS_CLIENT_ID/SECRET 환경변수 미설정')
        return None

    with _token_lock:
        now = time.time()
        cached = _token_cache.get('access_token')
        expires_at = _token_cache.get('expires_at', 0.0)
        if not force_refresh and cached and expires_at - TOKEN_REFRESH_MARGIN > now:
            return cached

        try:
            resp = requests.post(
                base_url + TOKEN_PATH,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': cid,
                    'client_secret': secret,
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            _set_error(f'토큰 발급 네트워크 오류: {e}')
            return None

        if resp.status_code != 200:
            _set_error(f'토큰 발급 실패 HTTP {resp.status_code}: {resp.text[:300]}')
            return None

        try:
            data = resp.json()
        except ValueError:
            _set_error(f'토큰 응답 JSON 파싱 실패: {resp.text[:200]}')
            return None

        token = data.get('access_token')
        expires_in = int(data.get('expires_in', 1799))
        if not token:
            _set_error(f'토큰 응답에 access_token 없음: {str(data)[:200]}')
            return None

        _token_cache['access_token'] = token
        _token_cache['expires_at'] = now + expires_in
        return token


# ---------- 공통 요청 ----------

def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    retries: int = 2,
) -> Optional[Dict[str, Any]]:
    """Amadeus API 호출. 401 은 1회 토큰 재발급 후 재시도, 5xx 는 retries 회 재시도."""
    _, _, base_url = _get_config()
    url = base_url + path

    auth_retried = False
    for attempt in range(retries + 1):
        token = _get_access_token()
        if not token:
            return None

        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
        }
        if json_body is not None:
            headers['Content-Type'] = 'application/json'

        try:
            resp = requests.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as e:
            _set_error(f'네트워크 오류: {e} (attempt {attempt + 1})')
            if attempt < retries:
                time.sleep(1.5)
                continue
            return None

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                _set_error(f'JSON 파싱 실패: {resp.text[:200]}')
                return None

        if resp.status_code == 401 and not auth_retried:
            # 토큰 강제 갱신 후 재시도
            auth_retried = True
            _get_access_token(force_refresh=True)
            continue

        if resp.status_code in (500, 502, 503, 504) and attempt < retries:
            _set_error(f'Amadeus 일시 오류 HTTP {resp.status_code} (attempt {attempt + 1})')
            time.sleep(1.5)
            continue

        # 4xx 등은 본문에 errors 배열이 있음
        try:
            err_payload = resp.json()
        except ValueError:
            err_payload = {'raw': resp.text[:300]}
        _set_error(f'Amadeus HTTP {resp.status_code}: {str(err_payload)[:400]}')
        return None

    return None


# ---------- 응답 정규화 ----------

def _parse_iso_duration(iso: Optional[str]) -> int:
    """'PT12H45M' → 765 (분)."""
    if not iso or not iso.startswith('PT'):
        return 0
    s = iso[2:]
    minutes = 0
    num = ''
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch == 'H':
            minutes += int(num or '0') * 60
            num = ''
        elif ch == 'M':
            minutes += int(num or '0')
            num = ''
        else:
            num = ''
    return minutes


def _carrier_name(code: Optional[str], dictionaries: Dict[str, Any]) -> str:
    if not code:
        return ''
    carriers = (dictionaries or {}).get('carriers', {}) or {}
    return carriers.get(code, code)


def _normalize_offer(offer: Dict[str, Any], dictionaries: Dict[str, Any]) -> Dict[str, Any]:
    """Amadeus Flight Offer 객체를 프론트 친화 형태로 단순화."""
    price = offer.get('price', {}) or {}
    itineraries_out: List[Dict[str, Any]] = []

    for it in offer.get('itineraries', []) or []:
        segs_out: List[Dict[str, Any]] = []
        for seg in it.get('segments', []) or []:
            dep = seg.get('departure', {}) or {}
            arr = seg.get('arrival', {}) or {}
            segs_out.append({
                'carrier': seg.get('carrierCode'),
                'carrier_name': _carrier_name(seg.get('carrierCode'), dictionaries),
                'flight_number': seg.get('number'),
                'from': dep.get('iataCode'),
                'from_terminal': dep.get('terminal'),
                'to': arr.get('iataCode'),
                'to_terminal': arr.get('terminal'),
                'departure': dep.get('at'),
                'arrival': arr.get('at'),
                'duration_minutes': _parse_iso_duration(seg.get('duration')),
                'aircraft': (seg.get('aircraft') or {}).get('code'),
                'cabin': None,  # travelerPricings 에서 채움
            })
        itineraries_out.append({
            'duration_minutes': _parse_iso_duration(it.get('duration')),
            'segments': segs_out,
            'stops': max(0, len(segs_out) - 1),
        })

    # 좌석 등급은 첫 traveler 기준
    traveler_pricings = offer.get('travelerPricings', []) or []
    cabin = None
    if traveler_pricings:
        fdsegs = traveler_pricings[0].get('fareDetailsBySegment', []) or []
        if fdsegs:
            cabin = fdsegs[0].get('cabin')

    return {
        'id': offer.get('id'),
        'price': {
            'total': float(price.get('grandTotal') or price.get('total') or 0),
            'base': float(price.get('base') or 0),
            'currency': price.get('currency') or 'KRW',
        },
        'itineraries': itineraries_out,
        'travelers': len(traveler_pricings) or 1,
        'class': cabin or 'ECONOMY',
        'seats_available': offer.get('numberOfBookableSeats'),
        'last_ticketing_date': offer.get('lastTicketingDate'),
        'validating_carriers': offer.get('validatingAirlineCodes', []) or [],
    }


# ---------- 검색 함수 ----------

def search_airports(keyword: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
    """공항/도시 자동완성. /v1/reference-data/locations"""
    if not keyword or len(keyword.strip()) < 2:
        return []
    data = _request(
        'GET', '/v1/reference-data/locations',
        params={
            'subType': 'AIRPORT,CITY',
            'keyword': keyword.strip(),
            'page[limit]': max(1, min(limit, 30)),
            'sort': 'analytics.travelers.score',
            'view': 'LIGHT',
        },
    )
    if data is None:
        return None

    out: List[Dict[str, Any]] = []
    for loc in data.get('data', []) or []:
        addr = loc.get('address', {}) or {}
        geo = loc.get('geoCode', {}) or {}
        out.append({
            'iata': loc.get('iataCode'),
            'name': loc.get('name'),
            'detailed_name': loc.get('detailedName'),
            'city': addr.get('cityName'),
            'city_code': addr.get('cityCode'),
            'country': addr.get('countryName'),
            'country_code': addr.get('countryCode'),
            'subtype': loc.get('subType'),
            'latitude': geo.get('latitude'),
            'longitude': geo.get('longitude'),
        })
    return out


def search_flight_offers(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    travel_class: Optional[str] = None,  # ECONOMY/PREMIUM_ECONOMY/BUSINESS/FIRST
    non_stop: Optional[bool] = None,
    max_price: Optional[int] = None,
    currency: str = 'KRW',
    max_results: int = 50,
) -> Optional[Dict[str, Any]]:
    """편도/왕복 검색. /v2/shopping/flight-offers (GET)"""
    params: Dict[str, Any] = {
        'originLocationCode': origin.upper(),
        'destinationLocationCode': destination.upper(),
        'departureDate': departure_date,
        'adults': max(1, int(adults)),
        'currencyCode': currency,
        'max': max(1, min(int(max_results), 100)),
    }
    if return_date:
        params['returnDate'] = return_date
    if children and int(children) > 0:
        params['children'] = int(children)
    if infants and int(infants) > 0:
        params['infants'] = int(infants)
    if travel_class:
        params['travelClass'] = travel_class.upper()
    if non_stop is True:
        params['nonStop'] = 'true'
    if max_price and int(max_price) > 0:
        params['maxPrice'] = int(max_price)

    data = _request('GET', '/v2/shopping/flight-offers', params=params)
    if data is None:
        return None

    dictionaries = data.get('dictionaries', {}) or {}
    offers = [_normalize_offer(o, dictionaries) for o in (data.get('data') or [])]
    return {
        'offers': offers,
        'currency': currency,
        'count': len(offers),
        'dictionaries': {
            'carriers': (dictionaries.get('carriers') or {}),
            'aircraft': (dictionaries.get('aircraft') or {}),
        },
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
    """멀티시티(다구간) 검색. /v2/shopping/flight-offers (POST).

    origin_destinations: [{ origin, destination, date }, ...]
    """
    if not origin_destinations or len(origin_destinations) < 2:
        _set_error('멀티시티는 최소 2개 구간 필요')
        return None

    od_list = []
    for idx, od in enumerate(origin_destinations, start=1):
        od_list.append({
            'id': str(idx),
            'originLocationCode': (od.get('origin') or '').upper(),
            'destinationLocationCode': (od.get('destination') or '').upper(),
            'departureDateTimeRange': {'date': od.get('date')},
        })

    travelers: List[Dict[str, Any]] = []
    tid = 1
    for _ in range(int(adults or 0)):
        travelers.append({'id': str(tid), 'travelerType': 'ADULT'})
        tid += 1
    for _ in range(int(children or 0)):
        travelers.append({'id': str(tid), 'travelerType': 'CHILD'})
        tid += 1
    for _ in range(int(infants or 0)):
        travelers.append({
            'id': str(tid),
            'travelerType': 'HELD_INFANT',
            'associatedAdultId': '1',
        })
        tid += 1

    body: Dict[str, Any] = {
        'currencyCode': currency,
        'originDestinations': od_list,
        'travelers': travelers,
        'sources': ['GDS'],
        'searchCriteria': {
            'maxFlightOffers': max(1, min(int(max_results), 100)),
        },
    }
    if travel_class:
        body['searchCriteria']['flightFilters'] = {
            'cabinRestrictions': [{
                'cabin': travel_class.upper(),
                'coverage': 'MOST_SEGMENTS',
                'originDestinationIds': [str(i + 1) for i in range(len(od_list))],
            }]
        }

    data = _request('POST', '/v2/shopping/flight-offers', json_body=body)
    if data is None:
        return None

    dictionaries = data.get('dictionaries', {}) or {}
    offers = [_normalize_offer(o, dictionaries) for o in (data.get('data') or [])]
    return {
        'offers': offers,
        'currency': currency,
        'count': len(offers),
        'dictionaries': {
            'carriers': (dictionaries.get('carriers') or {}),
            'aircraft': (dictionaries.get('aircraft') or {}),
        },
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
    """가격 캘린더용. /v1/shopping/flight-dates"""
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'destination': destination.upper(),
        'currencyCode': currency,
        'oneWay': 'true' if one_way else 'false',
    }
    if departure_date:
        params['departureDate'] = departure_date
    elif departure_date_range:
        params['departureDate'] = departure_date_range
    if duration:
        params['duration'] = duration
    if max_price and int(max_price) > 0:
        params['maxPrice'] = int(max_price)
    if non_stop is True:
        params['nonStop'] = 'true'

    data = _request('GET', '/v1/shopping/flight-dates', params=params)
    if data is None:
        return None

    items: List[Dict[str, Any]] = []
    for d in data.get('data', []) or []:
        price = d.get('price', {}) or {}
        items.append({
            'origin': d.get('origin'),
            'destination': d.get('destination'),
            'departure_date': d.get('departureDate'),
            'return_date': d.get('returnDate'),
            'price_total': float(price.get('total') or 0),
            'currency': currency,
        })
    return {'items': items, 'currency': currency, 'count': len(items)}


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
    """어디로든(Anywhere) 검색. /v1/shopping/flight-destinations"""
    params: Dict[str, Any] = {
        'origin': origin.upper(),
        'currencyCode': currency,
        'oneWay': 'true' if one_way else 'false',
    }
    if max_price and int(max_price) > 0:
        params['maxPrice'] = int(max_price)
    if departure_date:
        params['departureDate'] = departure_date
    elif departure_date_range:
        params['departureDate'] = departure_date_range
    if duration:
        params['duration'] = duration
    if non_stop is True:
        params['nonStop'] = 'true'

    data = _request('GET', '/v1/shopping/flight-destinations', params=params)
    if data is None:
        return None

    items: List[Dict[str, Any]] = []
    for d in data.get('data', []) or []:
        price = d.get('price', {}) or {}
        items.append({
            'origin': d.get('origin'),
            'destination': d.get('destination'),
            'departure_date': d.get('departureDate'),
            'return_date': d.get('returnDate'),
            'price_total': float(price.get('total') or 0),
            'currency': currency,
            'links': d.get('links', {}),
        })
    return {'items': items, 'currency': currency, 'count': len(items)}
