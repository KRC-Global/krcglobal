"""
문서 파일명 표준화 유틸리티
다운로드 파일명: {사업연도}_{사업명}_{문서유형}.ext
디스크 저장명:  {사업연도}_{사업명}_{문서유형}_{타임스탬프}.ext
"""
import re
from datetime import datetime


def make_overseas_tech_filename(doc_type, ext, project=None,
                                 fallback_title=None, fallback_year=None):
    """표준 다운로드 파일명 생성: 사업연도_사업명_문서유형.ext

    Args:
        doc_type: 문서 유형 문자열 (예: 'TOR', 'RFP', '기술제안서', '준공증명서')
        ext: 확장자 (예: 'pdf' 또는 '.pdf')
        project: ConsultingProject 인스턴스 (없으면 None)
        fallback_title: project가 없을 때 사용할 사업명
        fallback_year: project에 contract_year가 없을 때 사용할 연도 (int)
    """
    # 연도 결정
    if project and project.contract_year:
        year = str(project.contract_year)
    elif fallback_year:
        year = str(fallback_year)
    else:
        year = '연도미상'

    # 사업명 결정
    if project and project.title_kr:
        title = project.title_kr
    elif fallback_title:
        title = fallback_title
    else:
        title = '사업명미상'

    # 파일명에 허용되지 않는 특수문자 제거, 공백→_
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip()
    safe = re.sub(r'\s+', '_', safe)
    if not safe:
        safe = '사업명미상'

    # 확장자 정규화
    if not ext.startswith('.'):
        ext = '.' + ext

    return f"{year}_{safe}_{doc_type}{ext}"


def make_overseas_tech_disk_filename(doc_type, ext, project=None,
                                      fallback_title=None, fallback_year=None):
    """디스크 저장용 파일명 생성 (타임스탬프 포함, 충돌 방지)

    반환 예시: 2024_인도네시아스마트팜_TOR_20240315143022.pdf
    """
    base = make_overseas_tech_filename(doc_type, ext, project, fallback_title, fallback_year)
    # 확장자 분리
    dot_idx = base.rfind('.')
    name = base[:dot_idx]
    extension = base[dot_idx:]
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"{name}_{ts}{extension}"


# ODA 보고서 유형 라벨
ODA_REPORT_TYPE_NAMES = {
    'pcp': 'PCP',
    'implementation_plan': '시행계획',
    'fs': 'FS',
    'rod': 'ROD',
    'proposal': '제안서',
    'pmc': '실적보고',
    'performance': '성과관리',
    'post_evaluation': '사후평가',
}


def _parse_oda_start_year(period):
    """ODA 프로젝트 period에서 시작연도 파싱.
    예: "'20-'25" → 2020, "22-25" → 2022
    """
    if not period:
        return None
    m = re.search(r"['\u2018\u2019]?(\d{2})", period)
    if m:
        yr = int(m.group(1))
        return 2000 + yr if yr < 80 else 1900 + yr
    return None


def make_oda_report_filename(report_type, ext, project=None):
    """ODA 보고서 다운로드용 표준 파일명: {연도}_{사업명}_{보고서유형}.ext"""
    # 연도
    year = None
    if project:
        year = _parse_oda_start_year(getattr(project, 'period', None))
    if not year:
        year = datetime.now().year
    year = str(year)

    # 사업명
    title = getattr(project, 'title', None) if project else None
    if not title:
        title = '사업명미상'

    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip()
    safe = re.sub(r'\s+', '_', safe)
    if not safe:
        safe = '사업명미상'

    # 보고서 유형 라벨
    type_label = ODA_REPORT_TYPE_NAMES.get(report_type, report_type.upper())

    if not ext.startswith('.'):
        ext = '.' + ext

    return f"{year}_{safe}_{type_label}{ext}"


def make_oda_report_disk_filename(report_type, ext, project=None):
    """ODA 보고서 디스크 저장용 파일명 (타임스탬프 추가, 충돌 방지)"""
    base = make_oda_report_filename(report_type, ext, project)
    dot_idx = base.rfind('.')
    name = base[:dot_idx]
    extension = base[dot_idx:]
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"{name}_{ts}{extension}"
