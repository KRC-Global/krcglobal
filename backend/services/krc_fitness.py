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

# 중 등급의 두 갈래 — 통과 여부가 달라 사유를 상수로 둔다
REASON_RURAL = '농촌개발(관개 외)'
REASON_URBAN_WATER = '도시 물·기후 일반'

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

# ── 발송 제외 유형 ──────────────────────────────────────────────────────────
# 단순 인력파견·물품구매는 KRC 가 기관으로 수주할 사업이 아니다.
# 전 소스 공통으로 '하' 처리해 카드 생성·카톡 발송에서 제외한다.
#
# item_kind 는 소스가 알려주는 조달 유형이다:
#   KOICA 나라장터  '물품' / '공사' / '용역'
#   World Bank      procurement_method_code 로 세팅('개인컨설턴트' 등)
# 코드가 있으면 키워드보다 정확하므로 먼저 본다.
_EXCLUDED_KINDS = {
    '물품': '단순 물품 구매',
    'goods': '단순 물품 구매',
    'Goods': '단순 물품 구매',
    '개인컨설턴트': '단순 인력파견(개인 컨설턴트)',
}

_STAFFING_KO = (
    '인력파견', '인력 파견', '파견인력', '파견 인력',
    '인력공급', '인력 공급', '전문가 파견', '자문관 파견',
    '단순노무', '단순 노무', '용역원',
)
# 'individual consultant' 처럼 개인 모집임이 명시된 경우만 잡는다.
# 'Consulting Firm' / 'Design and Supervision Consultant' 같은 기관 용역은
# KRC 주력이므로 걸리지 않아야 한다.
_STAFFING_EN = re.compile(
    r'\b(?:individual\s+(?:consultant|consultancy|selection|expert|specialist)'
    r'|recruitment\s+of\s+(?:an?\s+)?(?:individual\s+|national\s+|international\s+)?'
    r'(?:consultant|expert|specialist|advisers?|advisors?)'
    r'|staffing|secondment|manpower|personnel\s+(?:supply|services?))\b',
    re.I,
)


def excluded_procurement(text: str, item_kind: str = '') -> tuple[bool, str]:
    """단순 인력파견·물품구매인지 판정. (제외여부, 사유)를 반환."""
    kind = (item_kind or '').strip()
    if kind in _EXCLUDED_KINDS:
        return True, _EXCLUDED_KINDS[kind]

    blob = _norm(f'{text} {item_kind}')
    if any(k in blob for k in _STAFFING_KO) or _STAFFING_EN.search(blob):
        return True, '단순 인력파견'
    return False, ''

# ── 중 등급 ── 관개 기반은 아니지만 관련은 있는 영역.
# 성격이 둘로 갈려 취급이 다르다:
#   (가) 농촌개발 — 농업·농촌·식량·임업 등. KRC 사업 영역이므로 수집·발송한다.
#   (나) 도시 물·기후 일반 — 도시상수도·정수장·도시홍수 등. 농촌 연계가
#        확인되지 않으면 수집하지 않는다.
# (가)를 먼저 보므로 'Rural Water Supply' 처럼 둘 다 걸리는 건 농촌개발로 본다.
_RURAL_KO = (
    '농업', '농촌', '식량', '농민', '가치사슬', '작물', '축산',
    '산림', '농식품', '영농', '농가', '임업', '수산',
)
_RURAL_EN = re.compile(
    r'\b(?:agricultur\w*|rural|agro\w*|farm(?:er|ing|land)?s?|'
    r'food security|livelihood|value chain|forestry|livestock|'
    r'fisher(?:y|ies)|crop|horticultur\w*)\b',
    re.I,
)

_WATER_CLIMATE_KO = (
    '정수장', '정수', '상수도', '취수원', '식수', '홍수',
    '수자원', '물 안보', '물안보', '기후',
)
_WATER_CLIMATE_EN = re.compile(
    r'\b(?:water (?:supply|security|treatment)|drinking water|'
    r'flood|climate)\b',
    re.I,
)


def _norm(text: str) -> str:
    return ' '.join((text or '').split())


def classify_krc_fit(text: str, *, item_kind: str = '') -> tuple[str, str]:
    """KRC 주력(농업관개) 적합도를 (상|중|하, 이유)로 반환."""
    blob = _norm(f'{text} {item_kind}')
    kind = (item_kind or '').strip()

    # 단순 인력파견·물품구매는 어떤 소스든 먼저 걸러낸다
    is_excluded, why = excluded_procurement(text, item_kind)
    if is_excluded:
        return GRADE_LOW, why

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

    if any(k in blob for k in _RURAL_KO) or _RURAL_EN.search(blob):
        return GRADE_MID, REASON_RURAL
    if any(k in blob for k in _WATER_CLIMATE_KO) or _WATER_CLIMATE_EN.search(blob):
        return GRADE_MID, REASON_URBAN_WATER

    return GRADE_LOW, 'KRC 주력과 무관'


def is_krc_core(text: str, *, item_kind: str = '') -> bool:
    return classify_krc_fit(text, item_kind=item_kind)[0] == GRADE_HIGH
