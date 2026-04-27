"""
항공권검색 Blueprint - /api/flights/*

외부 항공권 데이터 프로바이더(Travelpayouts 기본, Amadeus fallback) 프록시.
프론트는 절대 외부 API 직접 호출 금지. 활성 프로바이더는 FLIGHT_PROVIDER 환경변수.
모든 라우트는 @token_required (사내 직원만 접근).

엔드포인트:
    GET  /api/flights/airports?keyword=...
    GET  /api/flights/search?origin=...&destination=...&departureDate=...&...
    GET  /api/flights/cheapest-dates?origin=...&destination=...&departureDateRange=...
    GET  /api/flights/inspiration?origin=...&maxPrice=...
    POST /api/flights/multi-city  body: { originDestinations: [...], adults, ... }
    GET  /api/flights/health  활성 프로바이더 / 자격증명 상태
"""
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, jsonify, request

from routes.auth import token_required
from services import flight_provider as provider

flights_bp = Blueprint('flights', __name__)


# ---------- 간이 LRU 캐시 (5분) ----------

_CACHE_TTL = 300  # 5분
_CACHE_MAX = 128
_cache: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
_cache_lock = Lock()


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > _CACHE_TTL:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return value


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


# ---------- 헬퍼 ----------

def _bool_param(name: str) -> Optional[bool]:
    raw = request.args.get(name)
    if raw is None or raw == '':
        return None
    return raw.lower() in ('1', 'true', 'yes', 'y')


def _int_param(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _err(message: str, status: int = 400) -> Tuple[Any, int]:
    return jsonify({'success': False, 'message': message}), status


def _meta_base(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """모든 응답 meta 에 공통으로 포함할 정보."""
    base = {'provider': provider.get_provider_name()}
    if extra:
        base.update(extra)
    return base


def _service_error_response() -> Tuple[Any, int]:
    """프로바이더 호출 실패 시 표준 에러."""
    last = provider.get_last_error() or '항공권 정보 제공처에서 응답을 받지 못했습니다.'
    # 자격증명 미설정 케이스는 구체 메시지로 안내
    if 'TOKEN' in last or 'CLIENT_ID' in last or 'CLIENT_SECRET' in last:
        return _err('항공권 API 자격증명이 설정되지 않았습니다. 관리자에게 문의해 주세요.', 503)
    return _err(f'항공권 정보를 불러오지 못했습니다. ({last[:200]})', 502)


# ---------- 라우트 ----------

@flights_bp.route('/health', methods=['GET'])
@token_required
def health(current_user):
    """설정 상태 확인 (디버그용). 비밀값은 노출하지 않음."""
    return jsonify({
        'success': True,
        'data': provider.get_diagnostics(),
    })


@flights_bp.route('/airports', methods=['GET'])
@token_required
def airports(current_user):
    """공항/도시 자동완성."""
    keyword = (request.args.get('keyword') or '').strip()
    if len(keyword) < 2:
        return jsonify({'success': True, 'data': [], 'meta': {'count': 0}})

    cache_key = f'airports::{keyword.lower()}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify({'success': True, 'data': cached, 'meta': _meta_base({'count': len(cached), 'cached': True})})

    result = provider.search_airports(keyword, limit=10)
    if result is None:
        return _service_error_response()

    _cache_set(cache_key, result)
    return jsonify({'success': True, 'data': result, 'meta': _meta_base({'count': len(result)})})


@flights_bp.route('/search', methods=['GET'])
@token_required
def search(current_user):
    """편도/왕복 검색."""
    origin = (request.args.get('origin') or '').strip()
    destination = (request.args.get('destination') or '').strip()
    departure_date = (request.args.get('departureDate') or '').strip()
    return_date = (request.args.get('returnDate') or '').strip() or None

    if not origin or not destination or not departure_date:
        return _err('출발지, 도착지, 출발일은 필수입니다.', 400)

    adults = _int_param('adults', 1) or 1
    children = _int_param('children', 0) or 0
    infants = _int_param('infants', 0) or 0
    travel_class = (request.args.get('travelClass') or '').strip() or None
    non_stop = _bool_param('nonStop')
    max_price = _int_param('maxPrice')
    currency = (request.args.get('currency') or 'KRW').strip().upper() or 'KRW'
    max_results = _int_param('max', 50) or 50

    if adults < 1 or adults > 9:
        return _err('성인 인원은 1~9명 사이여야 합니다.', 400)

    cache_key = '::'.join([
        'search', origin.upper(), destination.upper(), departure_date, str(return_date),
        str(adults), str(children), str(infants), str(travel_class), str(non_stop),
        str(max_price), currency, str(max_results),
    ])
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify({
            'success': True,
            'data': cached['offers'],
            'meta': _meta_base({
                'count': cached['count'],
                'currency': cached['currency'],
                'dictionaries': cached.get('dictionaries', {}),
                'cached': True,
            })
        })

    result = provider.search_flight_offers(
        origin=origin, destination=destination,
        departure_date=departure_date, return_date=return_date,
        adults=adults, children=children, infants=infants,
        travel_class=travel_class, non_stop=non_stop, max_price=max_price,
        currency=currency, max_results=max_results,
    )
    if result is None:
        return _service_error_response()

    _cache_set(cache_key, result)
    return jsonify({
        'success': True,
        'data': result['offers'],
        'meta': _meta_base({
            'count': result['count'],
            'currency': result['currency'],
            'dictionaries': result.get('dictionaries', {}),
        })
    })


@flights_bp.route('/cheapest-dates', methods=['GET'])
@token_required
def cheapest_dates(current_user):
    """가격 캘린더 데이터."""
    origin = (request.args.get('origin') or '').strip()
    destination = (request.args.get('destination') or '').strip()
    if not origin or not destination:
        return _err('출발지와 도착지는 필수입니다.', 400)

    departure_date = (request.args.get('departureDate') or '').strip() or None
    departure_date_range = (request.args.get('departureDateRange') or '').strip() or None
    duration = (request.args.get('duration') or '').strip() or None
    one_way = _bool_param('oneWay') or False
    currency = (request.args.get('currency') or 'KRW').strip().upper() or 'KRW'
    max_price = _int_param('maxPrice')
    non_stop = _bool_param('nonStop')

    cache_key = '::'.join([
        'cheapest', origin.upper(), destination.upper(),
        str(departure_date), str(departure_date_range), str(duration),
        str(one_way), currency, str(max_price), str(non_stop),
    ])
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify({
            'success': True,
            'data': cached['items'],
            'meta': _meta_base({'count': cached['count'], 'currency': cached['currency'], 'cached': True})
        })

    result = provider.search_cheapest_dates(
        origin=origin, destination=destination,
        departure_date=departure_date, departure_date_range=departure_date_range,
        duration=duration, one_way=one_way, currency=currency,
        max_price=max_price, non_stop=non_stop,
    )
    if result is None:
        return _service_error_response()

    _cache_set(cache_key, result)
    return jsonify({
        'success': True,
        'data': result['items'],
        'meta': _meta_base({'count': result['count'], 'currency': result['currency']})
    })


@flights_bp.route('/inspiration', methods=['GET'])
@token_required
def inspiration(current_user):
    """어디로든(Anywhere) 검색."""
    origin = (request.args.get('origin') or '').strip()
    if not origin:
        return _err('출발지(origin)는 필수입니다.', 400)

    max_price = _int_param('maxPrice')
    departure_date = (request.args.get('departureDate') or '').strip() or None
    departure_date_range = (request.args.get('departureDateRange') or '').strip() or None
    duration = (request.args.get('duration') or '').strip() or None
    one_way = _bool_param('oneWay') or False
    currency = (request.args.get('currency') or 'KRW').strip().upper() or 'KRW'
    non_stop = _bool_param('nonStop')

    cache_key = '::'.join([
        'inspire', origin.upper(), str(max_price), str(departure_date),
        str(departure_date_range), str(duration), str(one_way), currency, str(non_stop),
    ])
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify({
            'success': True,
            'data': cached['items'],
            'meta': _meta_base({'count': cached['count'], 'currency': cached['currency'], 'cached': True})
        })

    result = provider.search_inspiration(
        origin=origin, max_price=max_price,
        departure_date=departure_date, departure_date_range=departure_date_range,
        duration=duration, one_way=one_way, currency=currency, non_stop=non_stop,
    )
    if result is None:
        return _service_error_response()

    _cache_set(cache_key, result)
    return jsonify({
        'success': True,
        'data': result['items'],
        'meta': _meta_base({'count': result['count'], 'currency': result['currency']})
    })


@flights_bp.route('/multi-city', methods=['POST'])
@token_required
def multi_city(current_user):
    """멀티시티(다구간) 검색."""
    payload = request.get_json(silent=True) or {}
    od_list = payload.get('originDestinations') or payload.get('origin_destinations') or []
    if not isinstance(od_list, list) or len(od_list) < 2:
        return _err('최소 2개 이상의 구간(originDestinations)을 입력해 주세요.', 400)

    cleaned = []
    for od in od_list:
        if not isinstance(od, dict):
            continue
        origin = (od.get('origin') or od.get('originLocationCode') or '').strip()
        destination = (od.get('destination') or od.get('destinationLocationCode') or '').strip()
        date = (od.get('date') or od.get('departureDate') or '').strip()
        if not origin or not destination or not date:
            return _err('각 구간은 origin, destination, date(YYYY-MM-DD)가 필요합니다.', 400)
        cleaned.append({'origin': origin, 'destination': destination, 'date': date})

    if len(cleaned) < 2:
        return _err('유효한 구간이 2개 이상 필요합니다.', 400)
    if len(cleaned) > 6:
        return _err('최대 6개 구간까지 지원합니다.', 400)

    adults = int(payload.get('adults') or 1)
    children = int(payload.get('children') or 0)
    infants = int(payload.get('infants') or 0)
    travel_class = (payload.get('travelClass') or payload.get('cabin') or '').strip() or None
    currency = (payload.get('currency') or 'KRW').strip().upper() or 'KRW'
    max_results = int(payload.get('max') or 50)

    if adults < 1 or adults > 9:
        return _err('성인 인원은 1~9명 사이여야 합니다.', 400)

    result = provider.search_multi_city(
        origin_destinations=cleaned,
        adults=adults, children=children, infants=infants,
        travel_class=travel_class, currency=currency, max_results=max_results,
    )
    if result is None:
        return _service_error_response()

    return jsonify({
        'success': True,
        'data': result['offers'],
        'meta': _meta_base({
            'count': result['count'],
            'currency': result['currency'],
            'dictionaries': result.get('dictionaries', {}),
            'synthesized': bool(result.get('synthesized')),
            'partial': bool(result.get('partial')),
        })
    })
