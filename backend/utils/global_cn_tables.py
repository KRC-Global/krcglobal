"""
global_cn_tables.py — ESA WorldCover v2.0 × Hydrologic Soil Group (HSG) → CN 룩업 테이블

출처:
  - TR-55 (USDA 1986) Table 2-2
  - GCN250 (Jaafar et al. 2019, Scientific Data) — HYSOGs250m + GlobeLand30 기반 전지구 CN
  - NEH Section 4 (USDA-NRCS 2004)

ESA WorldCover v2.0 2021 클래스:
  10  = Tree cover (폐쇄·개방 산림)
  20  = Shrubland (관목지)
  30  = Grassland (초지)
  40  = Cropland (농경지)
  50  = Built-up (시가지)
  60  = Bare / Sparse vegetation (나지·희박식생)
  70  = Snow and Ice (빙설)
  80  = Permanent water bodies (영구수체)
  90  = Herbaceous wetland (초본습지)
  95  = Mangroves (맹그로브)
  100 = Moss and Lichen (이끼·지의류, 툰드라)

설계 결정 사항:
  - Cropland(40): row crops, straight rows, poor hydrologic condition (TR-55 Table 2-2)
    → 보수적 최악 조건 적용. 보고서에 현장검증 권고사항 표시.
  - Built-up(50): 65% 불투수율 (중밀도 시가지) 기준 (TR-55 Table 2-2 1/4 acre lots 보간)
  - Snow/Ice(70), Water(80): CN=100 (완전 불투수, 전량 유출)
  - Herbaceous wetland(90): CN=92 (습지, 상시 포화에 준하는 D군 조건)
  - Mangroves(95): 열대 밀림 조건으로 CN 적용 (GCN250 기준)
  - Dual HSG (A/D, B/D): 계절성 수위 변동 토양 → 배수 양호 쪽(A, B) 채택 (SCS 표준)
"""

# ──────────────────────────────────────────────────────────────
# WORLDCOVER_CN[lc_class][hsg] = CN_II 값
# ──────────────────────────────────────────────────────────────
WORLDCOVER_CN = {
    10:  {'A': 36, 'B': 60, 'C': 73, 'D': 79},   # Tree cover      — woods, good condition
    20:  {'A': 35, 'B': 56, 'C': 70, 'D': 77},   # Shrubland       — brush-weed-grass, fair
    30:  {'A': 39, 'B': 61, 'C': 74, 'D': 80},   # Grassland       — pasture/range, fair
    40:  {'A': 67, 'B': 78, 'C': 85, 'D': 89},   # Cropland        — row crops, poor condition
    50:  {'A': 77, 'B': 85, 'C': 90, 'D': 92},   # Built-up        — ~65% impervious
    60:  {'A': 68, 'B': 79, 'C': 86, 'D': 89},   # Bare/sparse     — fallow, poor condition
    70:  {'A': 100,'B': 100,'C': 100,'D': 100},  # Snow/Ice        — no infiltration
    80:  {'A': 100,'B': 100,'C': 100,'D': 100},  # Water bodies    — fully impervious
    90:  {'A': 78, 'B': 86, 'C': 91, 'D': 92},   # Herbaceous wetland
    95:  {'A': 45, 'B': 66, 'C': 77, 'D': 83},   # Mangroves       — dense tropical forest
    100: {'A': 30, 'B': 58, 'C': 71, 'D': 78},   # Moss/Lichen     — tundra, sparse vegetation
}

# ──────────────────────────────────────────────────────────────
# WorldCover 클래스 한글/영문 명칭
# ──────────────────────────────────────────────────────────────
WORLDCOVER_NAMES = {
    10:  {'ko': '산림',              'en': 'Tree cover'},
    20:  {'ko': '관목지',            'en': 'Shrubland'},
    30:  {'ko': '초지',              'en': 'Grassland'},
    40:  {'ko': '농경지',            'en': 'Cropland'},
    50:  {'ko': '시가지',            'en': 'Built-up'},
    60:  {'ko': '나지/희박식생',     'en': 'Bare / Sparse vegetation'},
    70:  {'ko': '빙설',              'en': 'Snow and Ice'},
    80:  {'ko': '수체',              'en': 'Permanent water bodies'},
    90:  {'ko': '초본습지',          'en': 'Herbaceous wetland'},
    95:  {'ko': '맹그로브',          'en': 'Mangroves'},
    100: {'ko': '이끼/지의류(툰드라)','en': 'Moss and Lichen'},
}

# ──────────────────────────────────────────────────────────────
# HYSOGs250m 래스터 픽셀 값 → HSG 문자 변환
# Ross et al. (2018): 1=A, 2=B, 3=C, 4=D, 5=A/D, 6=B/D, 12=Water, 14=NoData
# ──────────────────────────────────────────────────────────────
HYSOGS_VALUE_TO_LETTER = {
    1:  'A',
    2:  'B',
    3:  'C',
    4:  'D',
    5:  'A',    # dual A/D → A (배수 양호 쪽, SCS 표준)
    6:  'B',    # dual B/D → B
    12: None,   # 수체 (open water) → 제외
    14: None,   # NoData → 제외
}

# ──────────────────────────────────────────────────────────────
# 보고서용 주의사항 (클래스별)
# ──────────────────────────────────────────────────────────────
WORLDCOVER_DISCLAIMERS = {
    40: '농경지(Cropland) CN은 row crops 최악 수문 조건(TR-55 Table 2-2) 적용값입니다. '
        '실제 작물 종류, 경작 방식, 수문 조건에 따라 값이 달라질 수 있으므로 현장 검증을 권장합니다.',
    50: '시가지(Built-up) CN은 불투수율 약 65%(중밀도 도시) 가정 적용값입니다. '
        '실제 불투수율 자료가 있는 경우 해당 값으로 보정하십시오.',
}

# ──────────────────────────────────────────────────────────────
# 데이터 소스 메타데이터
# ──────────────────────────────────────────────────────────────
DATA_SOURCES = {
    'hsg': {
        'name': 'HYSOGs250m',
        'full_name': 'Global Hydrologic Soil Groups (HYSOGs250m)',
        'resolution': '250m',
        'reference': 'Ross et al. (2018), Scientific Data, doi:10.1038/sdata.2018.91',
        'url': 'https://www.hydroshare.org/resource/4ebe4cd6d8ed48d7afd1ba42f73b9b8f/',
        'license': 'CC BY 4.0',
    },
    'landcover': {
        'name': 'ESA WorldCover v2.0',
        'full_name': 'ESA WorldCover 10m 2021 v200',
        'resolution': '10m',
        'reference': 'Zanaga et al. (2022), doi:10.5281/zenodo.7254221',
        'url': 'https://esa-worldcover.org/',
        'license': 'CC BY 4.0',
    },
    'cn_method': {
        'name': 'GCN250 방법론',
        'reference': 'Jaafar et al. (2019), Scientific Data, doi:10.1038/s41597-019-0155-x',
        'note': '독립 HSG × LC 분포 비례 결합 방법으로 CN 산정',
    },
}
