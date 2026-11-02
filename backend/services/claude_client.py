"""Anthropic Claude API 클라이언트.

SDK 를 쓰지 않고 requests 로 REST 를 직접 호출한다. requests 는 수집기가
이미 쓰고 있어 의존성이 늘지 않고, Vercel 번들도 가벼워진다.

모델은 Sonnet 계열 최신을 자동으로 고른다(ANTHROPIC_MODEL 로 고정 가능).
새 Sonnet 이 나오면 /v1/models 조회 결과가 바뀌면서 자동으로 옮겨 간다.
조회에 실패하면 PINNED_MODEL 로 떨어지므로 호출 자체가 막히지는 않는다.

이 모듈은 '없어도 시스템이 도는' 선택적 부품이다. 키가 없거나 API 가
실패하면 ClaudeUnavailable 을 올리고, 호출자는 기존 규칙 기반 경로로
되돌아간다. 공고 수집이 LLM 때문에 멈추면 안 된다.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

API_URL = 'https://api.anthropic.com/v1/messages'
MODELS_URL = 'https://api.anthropic.com/v1/models?limit=100'
API_VERSION = '2023-06-01'

# 자동 조회가 실패했을 때 쓰는 기준 모델. 조회가 되면 이보다 새 Sonnet 으로 간다.
PINNED_MODEL = 'claude-sonnet-5-5'
MODEL_FAMILY = 'claude-sonnet-'

_MODEL_TTL = 6 * 3600          # 모델 목록 재조회 주기(초)
_model_cache = {'id': '', 'at': 0.0}
_model_lock = threading.Lock()


class ClaudeUnavailable(RuntimeError):
    """키 미설정·네트워크 실패·API 오류. 호출자는 규칙 기반으로 되돌아간다."""


def api_key() -> str:
    """ANTHROPIC_API_KEY 를 쓴다. 과거 이름(CLAUDE_321)도 받아 준다."""
    for name in ('ANTHROPIC_API_KEY', 'CLAUDE_321', 'CLAUDE_API_KEY'):
        val = (os.environ.get(name) or '').strip()
        if val:
            return val
    return ''


def is_enabled() -> bool:
    return bool(api_key()) and (os.environ.get('CLAUDE_DISABLED', '').strip() != '1')


def _headers() -> dict:
    key = api_key()
    if not key:
        raise ClaudeUnavailable(
            'ANTHROPIC_API_KEY 가 없습니다. Vercel 환경변수에 등록해야 '
            '서버에서 쓸 수 있습니다.'
        )
    return {
        'x-api-key': key,
        'anthropic-version': API_VERSION,
        'content-type': 'application/json',
    }


def _sonnet_rank(model: dict) -> tuple:
    """최신 판별 — created_at 우선, 없으면 id 안의 버전 숫자."""
    created = str(model.get('created_at') or '')
    nums = tuple(int(n) for n in re.findall(r'\d+', model.get('id', '')))
    return (created, nums)


def resolve_model(force: bool = False) -> str:
    """쓸 모델 id. ANTHROPIC_MODEL 이 있으면 그대로, 없으면 최신 Sonnet."""
    pinned = (os.environ.get('ANTHROPIC_MODEL') or '').strip()
    if pinned:
        return pinned

    now = time.time()
    with _model_lock:
        if not force and _model_cache['id'] and now - _model_cache['at'] < _MODEL_TTL:
            return _model_cache['id']

    chosen = PINNED_MODEL
    try:
        import requests as req
        r = req.get(MODELS_URL, headers=_headers(), timeout=15)
        if r.status_code == 200:
            rows = (r.json() or {}).get('data') or []
            sonnets = [m for m in rows
                       if str(m.get('id', '')).startswith(MODEL_FAMILY)]
            if sonnets:
                newest = max(sonnets, key=_sonnet_rank)
                # 고정 모델보다 오래된 것으로 내려가지 않는다
                pinned_row = next(
                    (m for m in sonnets if m.get('id') == PINNED_MODEL), None)
                if (pinned_row is None
                        or _sonnet_rank(newest) >= _sonnet_rank(pinned_row)):
                    chosen = newest.get('id') or PINNED_MODEL
    except ClaudeUnavailable:
        raise
    except Exception as e:
        print(f'[claude] 모델 목록 조회 실패, {PINNED_MODEL} 사용: {str(e)[:90]}')

    with _model_lock:
        _model_cache['id'] = chosen
        _model_cache['at'] = now
    if chosen != PINNED_MODEL:
        print(f'[claude] 모델 자동 선택: {chosen} (고정값 {PINNED_MODEL} 보다 최신)')
    return chosen


def complete(system: str, user: str, *, max_tokens: int = 1500,
             temperature: float | None = None, timeout: float = 90.0,
             retries: int = 2) -> str:
    """메시지 1회 왕복. 실패하면 ClaudeUnavailable.

    temperature 는 기본으로 보내지 않는다 — Sonnet 5.5 부터 지원이 끊겨
    값을 실으면 400 이 돌아온다. 구형 모델을 ANTHROPIC_MODEL 로 고정해
    쓸 때만 명시한다.
    """
    import requests as req

    payload = {
        'model': resolve_model(),
        'max_tokens': max_tokens,
        'system': system,
        'messages': [{'role': 'user', 'content': user}],
    }
    if temperature is not None:
        payload['temperature'] = temperature
    last = ''
    for attempt in range(retries + 1):
        try:
            r = req.post(API_URL, headers=_headers(),
                         data=json.dumps(payload).encode('utf-8'), timeout=timeout)
        except Exception as e:
            last = f'요청 실패: {str(e)[:120]}'
        else:
            if r.status_code == 200:
                body = r.json() or {}
                parts = [b.get('text', '') for b in (body.get('content') or [])
                         if b.get('type') == 'text']
                text = ''.join(parts).strip()
                if text:
                    return text
                last = '빈 응답'
            elif r.status_code in (429, 500, 502, 503, 529):
                last = f'HTTP {r.status_code}'   # 일시적 — 재시도
            else:
                raise ClaudeUnavailable(f'HTTP {r.status_code} {r.text[:200]}')
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise ClaudeUnavailable(f'Claude 호출 실패: {last}')


_JSON_BLOCK = re.compile(r'```(?:json)?\s*(.+?)```', re.S)


def complete_json(system: str, user: str, *, max_tokens: int = 1500,
                  temperature: float | None = None, timeout: float = 90.0):
    """JSON 응답을 받아 파싱한다. 코드펜스·앞뒤 설명이 섞여도 건져낸다."""
    text = complete(system, user, max_tokens=max_tokens,
                    temperature=temperature, timeout=timeout)
    for candidate in _json_candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ClaudeUnavailable(f'JSON 파싱 실패: {text[:200]}')


def _json_candidates(text: str):
    text = (text or '').strip()
    yield text
    m = _JSON_BLOCK.search(text)
    if m:
        yield m.group(1).strip()
    # 바깥 설명이 붙은 경우 — 첫 '{' 또는 '[' 부터 마지막 짝까지
    for open_ch, close_ch in (('{', '}'), ('[', ']')):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if 0 <= start < end:
            yield text[start:end + 1]
