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
# Helsinki-NLP opus-mt 계열 — 단방향 경량 모델 (HF Inference API 지원 확인됨)
HF_MODEL_EN_KO = 'Helsinki-NLP/opus-mt-en-ko'
HF_MODEL_MULTI = 'Helsinki-NLP/opus-mt-tc-big-en-ko'  # fallback (en→ko, transformer-big)
HTTP_TIMEOUT = 25
MAX_INPUT_CHARS = 1000

# langdetect ISO-639-1 → NLLB Flores-200 코드
# 누락된 언어는 영어로 가정 (대부분 국제 공고가 영문)
LANG_MAP = {
    'en': 'eng_Latn',
    'es': 'spa_Latn',
    'fr': 'fra_Latn',
    'pt': 'por_Latn',
    'ru': 'rus_Cyrl',
    'ar': 'arb_Arab',
    'zh-cn': 'zho_Hans',
    'zh-tw': 'zho_Hant',
    'ja': 'jpn_Jpan',
    'vi': 'vie_Latn',
    'th': 'tha_Thai',
    'id': 'ind_Latn',
    'de': 'deu_Latn',
    'it': 'ita_Latn',
    'tr': 'tur_Latn',
    'nl': 'nld_Latn',
    'pl': 'pol_Latn',
    'sw': 'swh_Latn',
    'fa': 'pes_Arab',
    'uk': 'ukr_Cyrl',
    'mn': 'khk_Cyrl',
    'tl': 'tgl_Latn',
    'ne': 'npi_Deva',
    'hi': 'hin_Deva',
    'bn': 'ben_Beng',
    'my': 'mya_Mymr',
    'km': 'khm_Khmr',
    'lo': 'lao_Laoo',
    'ur': 'urd_Arab',
    'am': 'amh_Ethi',
    'ha': 'hau_Latn',
    'so': 'som_Latn',
    'yo': 'yor_Latn',
}


def _detect_src_lang(text: str) -> Optional[str]:
    """원문 언어 감지 → NLLB src_lang 반환. 한국어면 None (번역 불필요)."""
    if not text:
        return None
    if not _LANGDETECT_OK:
        return 'eng_Latn'  # langdetect 없으면 영어로 가정
    try:
        code = detect(text)
    except LangDetectException:
        return 'eng_Latn'
    if code == 'ko':
        return None
    return LANG_MAP.get(code, 'eng_Latn')


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

    # opus-mt-en-ko 는 영어 전용. 비영어 텍스트는 스킵 (향후 다국어 체인 추가 가능)
    if src_lang != 'eng_Latn':
        return None

    api_url = HF_API_BASE + HF_MODEL_EN_KO
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    # opus-mt 계열은 src_lang/tgt_lang 파라미터 불필요 — 모델 자체가 단방향
    payload = {
        'inputs': text[:MAX_INPUT_CHARS],
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
