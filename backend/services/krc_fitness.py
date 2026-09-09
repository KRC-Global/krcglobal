"""한국농어촌공사(KRC) 주력사업 적합도 — 상/중/하.

주력: 농업관개, 농업용수, 저수지·농업용 댐, 용수로, 배수·양수, 경지정리, 농지기반.
하수처리·도시상수도·단순 물품구매·일반 농촌개발은 주력이 아니다.
수집은 상만 저장한다.
"""
from __future__ import annotations

import re

GRADE_HIGH = '상'
GRADE_MID = '중'
GRADE_LOW = '하'

# 핵심 관개·농업용수 (하나라도 있으면 상 후보)
_CORE_KO = (
    '관개', '농업용수', '용수로', '관개시설', '관개배수', '관개지구',
    '배수장', '양수장', '배수개선', '경지정리', '농지기반', '생산기반정비',
    '농업생산기반', '농업용댐', '농업용 댐', '농업용저수지', '농업용 저수지',
    '저수지 개보수', '저수지둑', '간척', '개간', '방조제',
)

_CORE_EN = re.compile(
    r'\b(?:'
    r'irrigation|irrigated|irrigat(?:e|ion|ing)|'
    r'command area|irrigation scheme|irrigation canal|'
    r'agricultural water|farm(?:er)?s? water|'
    r'paddy (?:field|irrigation)|lift irrigation|'
    r'water user association|canal lining|'
    r'land reclamation|farmland consolidation|'
    r'irrigation (?:drain|rehabilitat|moderni)'
    r')\b',
    re.I,
)

# 댐·저수지·보·운하는 농업관개와  ind을 때만 상
_WATER_STRUCT_EN = re.compile(
    r'\b(?:reservoirs?|dams?|weirs?|barrages?|canals?)\b', re.I,
)
_AGRI_CONTEXT_EN = re.compile(
    r'\b(?:irrigat|agricultur|paddy|farm(?:land|er)?s?|rural water)\b', re.I,
)
_WATER_STRUCT_KO = ('저수지', '농업용댐', '취입보', '취수보')
_AGRI_CONTEXT_KO = ('농업', '농지', '농촌', '관개', '용수', '논', '밭')

# 즉시 하 — 하수·도시위생·단순구매·비핵심 시설
_LOW_KO = (
    '하수처리', '하수도', '오수', '오폐수', '폐수',
    '기자재', '물품공급', '물품 공급', '물품구매', '물품 구매',
    '납품', '가구', '시범농장',
    '병원', '학교', '항공', '사이버', '교육원', '지식재산',
    '교량', '도로사업', '도로 개선', '도로개선',
)
_LOW_EN = re.compile(
    r'\b(?:sewage|wastewater|sewer(?:age)?|sanitation|'
    r'furniture|goods|hospital|school|airport|cyber|'
    r'bridge|highway|road(?:s|work)?)\b',
    re.I,
)
_GOODS_EN = re.compile(
    r'\b(?:supply and (?:install|delivery|installation)|'
    r'procurement of goods|goods (?:supply|contract)|'
    r'supply of (?:goods|equipment|furniture|inputs))\b',
    re.I,
)

# 농업·농촌·물이지만 관개 기반이 아니면 중
_MID_KO = (
    '농업', '농촌', '식량', '농민', '가치사슬', '작물', '축산',
    '정수장', '정수', '상수도', '취수원', '식수', '홍수',
    '수자원', '물 안보', '물안보', '기후', '산림',
)
_MID_EN = re.compile(
    r'\b(?:agriculture|agricultural|rural|food security|'
    r'livelihood|value chain|water (?:supply|security|treatment)|'
    r'drinking water|flood|climate|forestry|livestock)\b',
    re.I,
)


def _norm(text: str) -> str:
    return ' '.join((text or '').split())


def classify_krc_fit(text: str, *, item_kind: str = '') -> tuple[str, str]:
    """KRC 주력(농업관개) 적합도를 (상|중|하, 이유)로 반환."""
    blob = _norm(f'{text} {item_kind}')
    kind = (item_kind or '').strip()

    if kind in ('물품', 'goods', 'Goods'):
        return GRADE_LOW, '단순 물품 구매'
    if any(k in blob for k in _LOW_KO) or _LOW_EN.search(blob) or _GOODS_EN.search(blob):
        if '관개' in blob and not any(k in blob for k in (
            '기자재', '물품', '납품', '하수', '오수', '교량', '도로',
        )):
            pass  # 관개 본사업이면 하 키워드가 약할 수 있어 아래로
        else:
            reason = '하수·도시위생' if any(k in blob for k in ('하수', '오수', '폐수')) or re.search(
                r'sewage|wastewater|sewer', blob, re.I) else (
                '단순 물품·기자재' if any(k in blob for k in ('기자재', '물품', '납품', '가구'))
                or _GOODS_EN.search(blob) else '주력 외 시설·공사'
            )
            return GRADE_LOW, reason

    if any(k in blob for k in _CORE_KO) or _CORE_EN.search(blob):
        return GRADE_HIGH, '농업관개·농업용수 기반'

    struct_ko = any(k in blob for k in _WATER_STRUCT_KO)
    agri_ko = any(k in blob for k in _AGRI_CONTEXT_KO)
    if struct_ko and agri_ko:
        return GRADE_HIGH, '농업 맥락의 댐·저수지'
    if _WATER_STRUCT_EN.search(blob) and _AGRI_CONTEXT_EN.search(blob):
        return GRADE_HIGH, '농업 맥락의 댐·저수지'

    if any(k in blob for k in _MID_KO) or _MID_EN.search(blob):
        return GRADE_MID, '농업·농촌·물이지만 관개기반 아님'

    return GRADE_LOW, 'KRC 주력과 무관'


def is_krc_core(text: str, *, item_kind: str = '') -> bool:
    return classify_krc_fit(text, item_kind=item_kind)[0] == GRADE_HIGH
