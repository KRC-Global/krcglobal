"""
항공권 프로바이더 스위처.

환경변수 FLIGHT_PROVIDER 로 활성 프로바이더 선택:
    - 'travelpayouts' (기본): Travelpayouts (Aviasales) Data API
    - 'amadeus'              : Amadeus Self-Service (2026-07-17 단종 예정)

routes/flights.py 는 amadeus 모듈 대신 이 모듈을 import 한다.
프로바이더 모듈은 동일한 함수 시그니처를 제공해야 한다:
    is_configured(), get_last_error(),
    search_airports, search_flight_offers, search_multi_city,
    search_cheapest_dates, search_inspiration
"""
import os
from types import ModuleType
from typing import Optional

from . import travelpayouts, amadeus


_PROVIDERS = {
    'travelpayouts': travelpayouts,
    'amadeus': amadeus,
}
_DEFAULT = 'travelpayouts'


def get_provider_name() -> str:
    raw = (os.environ.get('FLIGHT_PROVIDER') or _DEFAULT).strip().lower()
    return raw if raw in _PROVIDERS else _DEFAULT


def get_provider() -> ModuleType:
    return _PROVIDERS[get_provider_name()]


# ── 프로바이더 함수를 동적으로 위임 ──
# 매 호출마다 환경변수를 다시 읽어 런타임 전환을 허용한다.

def is_configured() -> bool:
    return get_provider().is_configured()


def get_last_error() -> str:
    return get_provider().get_last_error()


def search_airports(*args, **kwargs):
    return get_provider().search_airports(*args, **kwargs)


def search_flight_offers(*args, **kwargs):
    return get_provider().search_flight_offers(*args, **kwargs)


def search_multi_city(*args, **kwargs):
    return get_provider().search_multi_city(*args, **kwargs)


def search_cheapest_dates(*args, **kwargs):
    return get_provider().search_cheapest_dates(*args, **kwargs)


def search_inspiration(*args, **kwargs):
    return get_provider().search_inspiration(*args, **kwargs)


# 디버그/health 라우트용
def get_diagnostics() -> dict:
    name = get_provider_name()
    mod = _PROVIDERS[name]
    return {
        'provider': name,
        'configured': mod.is_configured(),
        'last_error': mod.get_last_error() or None,
    }
