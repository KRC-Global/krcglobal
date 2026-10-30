"""한국농어촌공사(KRC) 주력사업 적합도 — 상/중/하.

주력: 농업관개, 농업용수, 저수지·농업용 댐, 용수로, 배수·양수, 경지정리, 농지기반.
하수처리·도시상수도·단순 물품구매·일반 농촌개발은 주력이 아니다.
수집은 상만 저장한다.
"""
from __future__ import annotations

import re
import unicodedata

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

# ── 프랑스어 (AfDB) ─────────────────────────────────────────────────────────
# AfDB 는 영·불 병행 공고다. 아래 패턴은 _norm 이 악센트를 벗긴
# 문자열에 대해 돌아가므로 악센트 없이 쓴다(perimetre, elevage ...).
_CORE_FR = re.compile(
    r'\b(?:'
    r'irrigue\w*|perimetres?\s+irrigue\w*|'
    r'hydro[\s-]?agricole|amenagement\s+hydro[\s-]?agricole|'
    r'canal\s+d.irrigation|canaux\s+d.irrigation|'
    r'bas[\s-]fonds?|'                       # 저지대 논 — 서아프리카 관개 정형
    r'eau\s+agricole|eaux\s+agricoles|'
    r'maitrise\s+de\s+l.eau|'
    r'retenues?\s+d.eau'
    r')\b',
    re.I,
)
_WATER_STRUCT_FR = re.compile(
    # 'seuil'(문턱·기준치)은 불어 일반어라 넣지 않는다 — 수리 구조물로 쓰이는
    # 경우보다 'seuil de rentabilite' 같은 관용 표현이 훨씬 많다.
    r'\b(?:barrages?|retenues?\s+d.eau|canaux|digues?)\b', re.I,
)
_AGRI_CONTEXT_FR = re.compile(
    r'\b(?:irrigat\w*|agricoles?|agriculture|agro\w*|rural\w*|'
    r'paysans?|riziculture|rizicoles?)\b',
    re.I,
)
# 즉시 하 — 하수·도시위생·단순구매·비핵심 시설 (불어)
_LOW_FR = re.compile(
    r'\b(?:eaux\s+usees|assainissement|egouts?|'
    r'mobiliers?|vehicules?|ordinateurs?|'
    r'hopitaux?|hopital|ecoles?|aeroports?|'
    r'routes?|routiers?|ponts?|bitumage|voiries?)\b',
    re.I,
)
_GOODS_FR = re.compile(
    # 'Fourniture, installation et montage d'equipements' 처럼 쉼표로 열거하는
    # 표기가 흔하다. 'et' 만 보면 비켜가므로 구분자를 쉼표까지 넓힌다.
    r'\b(?:fourniture\s*[,et]+\s*(?:installation|livraison|montage|pose)|'
    r'acquisition\s+(?:de|des|d.)\s|'
    r'fourniture\s+(?:de|des|d.)\s+(?:biens|equipements|materiels?|mobiliers?|'
    r'tracteurs?|vehicules?|pompes?|groupes?)|'
    r'livraison\s+(?:de|des|d.)\s|'
    r'equipements?\s+de\s+mecanisation)',
    re.I,
)
_STAFFING_FR = re.compile(
    r'\b(?:consultants?\s+individuels?|consultante?\s*\(e\)\s*individuel|'
    r'experts?\s+individuels?|'
    r'recrutement\s+d.un\s+consultant\s+individuel|'
    r'mise\s+a\s+disposition\s+de\s+personnel)\b',
    re.I,
)
_RURAL_FR = re.compile(
    r'\b(?:agricoles?|agriculture|agro\w*|rural\w*|elevage|'
    r'peches?|peche\s+artisanale|forets?|forestiers?|sylvicoles?|'
    r'securite\s+alimentaire|filieres?|semences?|'
    r'cultures?|cooperatives?\s+agricoles?|'
    r'riz|riziculture|rizicoles?|betail|pastoral\w*)\b',
    re.I,
)
_WATER_CLIMATE_FR = re.compile(
    r'\b(?:eau\s+potable|adduction\s+d.eau|alimentation\s+en\s+eau|'
    r'inondations?|climat\w*|ressources?\s+en\s+eau|hydraulique)\b',
    re.I,
)

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
    # 철도도 '농촌과 무관한 토목'이라 도로·교량과 같이 둔다.
    # AfDB 는 아프리카 철도 사업을 자주 공고한다.
    r'bridge|highway|road(?:s|work)?|rail|railways?|railroads?)\b',
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
    if (any(k in blob for k in _STAFFING_KO) or _STAFFING_EN.search(blob)
            or _STAFFING_FR.search(blob)):
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


def fold_accents(text: str) -> str:
    """라틴 악센트를 벗긴다 — 수집기의 키워드 매칭도 같은 기준을 쓰도록 공개."""
    return _norm(text)


def _norm(text: str) -> str:
    """공백 정리 + 라틴 악센트 제거.

    AfDB 공고의 절반 가까이가 프랑스어다('AMI - Tunisie - ...').
    악센트를 벗겨 두면 périmètre/perimetre, élevage/elevage 를 한 패턴으로
    잡을 수 있어 아래 _*_FR 들을 악센트 없이 쓴다. 한글은 NFD 분해되면
    자모가 쪼개져 'in' 검사가 깨지므로, 라틴 결합문자만 골라 지운다.
    """
    s = ' '.join((text or '').split())
    if s.isascii():
        return s
    out = []
    for ch in unicodedata.normalize('NFD', s):
        # 라틴 문자에 붙은 결합 악센트(U+0300~U+036F)만 제거
        if unicodedata.combining(ch) and '̀' <= ch <= 'ͯ':
            continue
        out.append(ch)
    return unicodedata.normalize('NFC', ''.join(out))


def classify_krc_fit(text: str, *, item_kind: str = '') -> tuple[str, str]:
    """KRC 주력(농업관개) 적합도를 (상|중|하, 이유)로 반환."""
    blob = _norm(f'{text} {item_kind}')
    kind = (item_kind or '').strip()

    # 단순 인력파견·물품구매는 어떤 소스든 먼저 걸러낸다
    is_excluded, why = excluded_procurement(text, item_kind)
    if is_excluded:
        return GRADE_LOW, why

    if (any(k in blob for k in _LOW_KO) or _LOW_EN.search(blob)
            or _GOODS_EN.search(blob)
            or _LOW_FR.search(blob) or _GOODS_FR.search(blob)):
        # 관개 본사업이면 하 키워드가 약할 수 있어 아래로 보낸다.
        # 불어 공고도 같다 — 'amenagement de perimetres irrigues' 안에
        # 'routes d'acces' 가 섞여 있어도 본사업은 관개다.
        # _CORE_EN 은 여기 넣지 않는다. blob 에는 제목뿐 아니라 긴 설명문이
        # 들어가, 철도·공항 사업 설명에 'irrigation' 이 한 번 스쳐도 하→상 으로
        # 뒤집힌다(실측: #215 철도, #338 공항). 하 분기를 먼저 두는 원래 설계가
        # 그 오분류를 막고 있다. 불어 쪽도 제목에 쓰이는 표현만 좁게 본다.
        core_hit = ('관개' in blob) or bool(_CORE_FR.search(blob))
        low_hard_ko = any(k in blob for k in (
            '기자재', '물품', '납품', '하수', '오수', '교량', '도로',
        ))
        low_hard_fr = bool(re.search(
            r'\b(?:eaux\s+usees|assainissement|mobiliers?|vehicules?|'
            r'ponts?|bitumage|acquisition)\b', blob, re.I))
        if core_hit and not low_hard_ko and not low_hard_fr:
            pass
        else:
            if (any(k in blob for k in ('하수', '오수', '폐수'))
                    or re.search(r'sewage|wastewater|sewer', blob, re.I)
                    or re.search(r'eaux\s+usees|assainissement|egouts?', blob, re.I)):
                reason = '하수·도시위생'
            elif (any(k in blob for k in ('기자재', '물품', '납품', '가구'))
                    or _GOODS_EN.search(blob) or _GOODS_FR.search(blob)
                    or re.search(r'\bmobiliers?\b', blob, re.I)):
                reason = '단순 물품·기자재'
            else:
                reason = '주력 외 시설·공사'
            return GRADE_LOW, reason

    if (any(k in blob for k in _CORE_KO) or _CORE_EN.search(blob)
            or _CORE_FR.search(blob)):
        return GRADE_HIGH, '농업관개·농업용수 기반'

    struct_ko = any(k in blob for k in _WATER_STRUCT_KO)
    agri_ko = any(k in blob for k in _AGRI_CONTEXT_KO)
    if struct_ko and agri_ko:
        return GRADE_HIGH, '농업 맥락의 댐·저수지'
    if _WATER_STRUCT_EN.search(blob) and _AGRI_CONTEXT_EN.search(blob):
        return GRADE_HIGH, '농업 맥락의 댐·저수지'
    if _WATER_STRUCT_FR.search(blob) and _AGRI_CONTEXT_FR.search(blob):
        return GRADE_HIGH, '농업 맥락의 댐·저수지'

    if (any(k in blob for k in _RURAL_KO) or _RURAL_EN.search(blob)
            or _RURAL_FR.search(blob)):
        return GRADE_MID, REASON_RURAL
    if (any(k in blob for k in _WATER_CLIMATE_KO) or _WATER_CLIMATE_EN.search(blob)
            or _WATER_CLIMATE_FR.search(blob)):
        return GRADE_MID, REASON_URBAN_WATER

    return GRADE_LOW, 'KRC 주력과 무관'


def is_krc_core(text: str, *, item_kind: str = '') -> bool:
    return classify_krc_fit(text, item_kind=item_kind)[0] == GRADE_HIGH
