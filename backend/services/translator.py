"""
HuggingFace Inference API 기반 다국어 → 한국어 번역.

- 모델: facebook/nllb-200-distilled-600M (200개 언어, 한국어 출력 지원)
- 언어 감지: langdetect (서버 로컬, 외부 호출 없음)
- 환경변수: HF_TOKEN (HuggingFace Read 토큰 필수)
- 실패/타임아웃 시 None 반환 → 호출자가 원문 유지

Vercel Lambda 50~200MB 제약 때문에 transformers/torch 직접 사용 불가.
"""
import os
import time
from typing import Optional, List

import requests

try:
    from langdetect import detect, DetectorFactory, LangDetectException
    DetectorFactory.seed = 0  # 결과 재현 가능
    _LANGDETECT_OK = True
except Exception:
    _LANGDETECT_OK = False

HF_API_BASE = 'https://router.huggingface.co/hf-inference/models/'
# mBART-50 — 다국어 번역 (50개 언어, HF Inference warm 모델)
HF_MODEL = 'facebook/mbart-large-50-many-to-many-mmt'
TARGET_LANG = 'ko_KR'  # mBART 한국어 코드
HTTP_TIMEOUT = 30      # mBART 은 NLLB 보다 클 수 있어 여유 확보
MAX_INPUT_CHARS = 800  # mBART 토큰 제한 보수적 적용

# langdetect ISO-639-1 → mBART-50 코드 (XX 접미사)
# 누락된 언어는 영어로 가정 (대부분 국제 공고가 영문)
LANG_MAP = {
    'en': 'en_XX',
    'es': 'es_XX',
    'fr': 'fr_XX',
    'pt': 'pt_XX',
    'ru': 'ru_RU',
    'ar': 'ar_AR',
    'zh-cn': 'zh_CN',
    'zh-tw': 'zh_CN',
    'ja': 'ja_XX',
    'vi': 'vi_VN',
    'th': 'th_TH',
    'id': 'id_ID',
    'de': 'de_DE',
    'it': 'it_IT',
    'tr': 'tr_TR',
    'nl': 'nl_XX',
    'pl': 'pl_PL',
    'sw': 'sw_KE',
    'fa': 'fa_IR',
    'uk': 'uk_UA',
    'hi': 'hi_IN',
    'bn': 'bn_IN',
    'ur': 'ur_PK',
    'ne': 'ne_NP',
    'ta': 'ta_IN',
    'te': 'te_IN',
    'ml': 'ml_IN',
    'gu': 'gu_IN',
    'mr': 'mr_IN',
    'mn': 'mn_MN',
    'my': 'my_MM',
    'ka': 'ka_GE',
    'km': 'km_KH',
    'si': 'si_LK',
    'lt': 'lt_LT',
    'lv': 'lv_LV',
    'et': 'et_EE',
    'fi': 'fi_FI',
    'ro': 'ro_RO',
    'cs': 'cs_CZ',
    'hr': 'hr_HR',
    'sl': 'sl_SI',
    'af': 'af_ZA',
    'xh': 'xh_ZA',
}


def _detect_src_lang(text: str) -> Optional[str]:
    """원문 언어 감지 → mBART src_lang 코드 반환. 한국어면 None (번역 불필요)."""
    if not text:
        return None
    if not _LANGDETECT_OK:
        return 'en_XX'  # langdetect 없으면 영어로 가정
    try:
        code = detect(text)
    except LangDetectException:
        return 'en_XX'
    if code == 'ko':
        return None
    return LANG_MAP.get(code, 'en_XX')


def translate_to_korean(text: str, retries: int = 2) -> Optional[str]:
    """단일 텍스트 → 한국어. 실패 시 None.

    HF Inference API 무료 티어는 모델 cold-start 시 503 + estimated_time 응답을
    반환할 수 있어 재시도 로직 필수.
    """
    global _last_translate_error

    token = os.environ.get('HF_TOKEN')
    if not token:
        _last_translate_error = 'HF_TOKEN 환경변수 미설정'
        print(f'[translate] {_last_translate_error}')
        return None
    if not text:
        return None

    src_lang = _detect_src_lang(text)
    if src_lang is None:
        return None  # 이미 한국어

    api_url = HF_API_BASE + HF_MODEL
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    # mBART-50 다국어 모델 — src_lang + tgt_lang 파라미터 필요
    payload = {
        'inputs': text[:MAX_INPUT_CHARS],
        'parameters': {
            'src_lang': src_lang,
            'tgt_lang': TARGET_LANG,
        },
        'options': {'wait_for_model': True},
    }

    last_error = ''
    for attempt in range(retries + 1):
        try:
            r = requests.post(api_url, headers=headers, json=payload,
                              timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            last_error = f'네트워크 오류: {e}'
            print(f'[translate] {last_error} (attempt {attempt+1})')
            if attempt < retries:
                time.sleep(2)
                continue
            _last_translate_error = last_error
            return None

        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                last_error = f'JSON 파싱 실패: {r.text[:200]}'
                print(f'[translate] {last_error}')
                _last_translate_error = last_error
                return None
            if isinstance(data, list) and data and isinstance(data[0], dict):
                out = data[0].get('translation_text')
                if out:
                    return out.strip()
            last_error = f'예기치 않은 응답 형식: {str(data)[:200]}'
            print(f'[translate] {last_error}')
            _last_translate_error = last_error
            return None

        if r.status_code in (503, 524):
            last_error = f'모델 로딩 중 HTTP {r.status_code}'
            print(f'[translate] {last_error} (attempt {attempt+1})')
            if attempt < retries:
                time.sleep(3)
                continue
            _last_translate_error = last_error
            return None

        # 401/403/429 등 즉시 포기
        last_error = f'HF API HTTP {r.status_code}: {r.text[:300]}'
        print(f'[translate] {last_error}')
        _last_translate_error = last_error
        return None

    _last_translate_error = last_error
    return None


# 모듈 레벨 — 마지막 에러 원인 저장 (외부에서 읽어갈 수 있도록)
_last_translate_error = ''


def get_last_error() -> str:
    return _last_translate_error


def translate_batch(texts: List[str], sleep_between: float = 0.4) -> List[Optional[str]]:
    """순차 번역. 실패 항목은 None. rate-limit 보호용 sleep 포함."""
    results: List[Optional[str]] = []
    for t in texts:
        results.append(translate_to_korean(t))
        if sleep_between:
            time.sleep(sleep_between)
    return results
