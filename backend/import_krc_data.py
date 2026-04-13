#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
해외기술용역 데이터 Import 스크립트
Excel 파일에서 ConsultingProject 테이블로 데이터를 임포트합니다.

Usage:
    python import_krc_data.py              # Excel에서 임포트 (기존 데이터 삭제 후)
    python import_krc_data.py --no-delete  # 기존 데이터 유지하고 추가
"""

import os
import sys
from pathlib import Path

import pandas as pd

from app import app
from models import db, ConsultingProject, ConsultingPersonnel, Proposal, \
    PerformanceRecord, Contract, TorRfp, Eoi, BoardPost, ProjectLifecycle


# ── Excel 파일 경로 ──
EXCEL_FILE = Path(__file__).parent / 'database' / "#260114 DB 260107해외기술컨설팅('72-'25).xlsx"


# ── 국가별 수도 좌표 (위경도 없을 때 fallback) ──
CAPITAL_COORDINATES = {
    '베트남': (21.0285, 105.8542),
    '필리핀': (14.5995, 120.9842),
    '인도네시아': (-6.2088, 106.8456),
    '태국': (13.7563, 100.5018),
    '미얀마': (19.7633, 96.0785),
    '캄보디아': (11.5564, 104.9282),
    '라오스': (17.9757, 102.6331),
    '말레이시아': (3.1390, 101.6869),
    '스리랑카': (6.9271, 79.8612),
    '방글라데시': (23.8103, 90.4125),
    '파키스탄': (33.6844, 73.0479),
    '네팔': (27.7172, 85.3240),
    '인도': (28.6139, 77.2090),
    '몽골': (47.8864, 106.9057),
    '중국': (39.9042, 116.4074),
    '우즈베키스탄': (41.2995, 69.2401),
    '투르크메니스탄': (37.9601, 58.3261),
    '카자흐스탄': (51.1694, 71.4491),
    '키르기스스탄': (42.8746, 74.5698),
    '타지키스탄': (38.5598, 68.7740),
    '아제르바이잔': (40.4093, 49.8671),
    '이란': (35.6892, 51.3890),
    '이라크': (33.3152, 44.3661),
    '사우디아라비아': (24.7136, 46.6753),
    '아랍에미리트': (24.4539, 54.3773),
    '오만': (23.5859, 58.4059),
    '예멘': (15.3694, 44.1910),
    '요르단': (31.9454, 35.9284),
    '터키': (39.9334, 32.8597),
    '에티오피아': (8.9806, 38.7578),
    '케냐': (-1.2921, 36.8219),
    '탄자니아': (-6.1659, 35.7516),
    '우간다': (0.3476, 32.5825),
    '르완다': (-1.9403, 29.8739),
    '콩고': (-4.4419, 15.2663),
    '나이지리아': (9.0765, 7.3986),
    '수단': (15.5007, 32.5599),
    '남수단': (4.8594, 31.5713),
    '이집트': (30.0444, 31.2357),
    '모로코': (33.9716, -6.8498),
    '알제리': (36.7538, 3.0588),
    '튀니지': (36.8065, 10.1815),
    '리비아': (32.8872, 13.1913),
    '세네갈': (14.7167, -17.4677),
    '코트디부아르': (6.8276, -5.2893),
    '가나': (5.6037, -0.1870),
    '카메룬': (3.8480, 11.5021),
    '모잠비크': (-25.9692, 32.5732),
    '마다가스카르': (-18.8792, 47.5079),
    '짐바브웨': (-17.8252, 31.0335),
    '잠비아': (-15.3875, 28.3228),
    '말라위': (-13.9626, 33.7741),
    '에콰도르': (-0.1807, -78.4678),
    '페루': (-12.0464, -77.0428),
    '볼리비아': (-19.0196, -65.2619),
    '파라과이': (-25.2637, -57.5759),
    '콜롬비아': (4.7110, -74.0721),
    '과테말라': (14.6349, -90.5069),
    '니카라과': (12.1149, -86.2362),
    '도미니카공화국': (18.4861, -69.9312),
    '엘살바도르': (13.6929, -89.2182),
    '온두라스': (14.0723, -87.1921),
    '아이티': (18.5944, -72.3074),
    '파나마': (8.9824, -79.5199),
    '피지': (-18.1416, 178.4419),
    '파푸아뉴기니': (-6.3147, 143.9555),
    '솔로몬제도': (-9.4438, 159.9729),
    '동티모르': (-8.5569, 125.5603),
    '아프가니스탄': (34.5553, 69.2075),
    '시리아': (33.5138, 36.2765),
    '레바논': (33.8938, 35.5018),
    '팔레스타인': (31.9522, 35.2332),
    '가봉': (0.4162, 9.4673),
    '세이셸': (-4.6796, 55.4920),
    '부탄': (27.4728, 89.6393),
    '몰디브': (4.1755, 73.5093),
    '통가': (-21.2175, -175.1624),
}


# ── 사업형태 키워드 → boolean 필드 매핑 ──
SERVICE_TYPE_KEYWORDS = {
    'type_feasibility': ['타당성', 'F/S', 'FS'],
    'type_masterplan': ['마스터플랜', '기본계획', 'M/P', 'MP'],
    'type_basic_design': ['기본설계', 'B/D', 'BD'],
    'type_detailed_design': ['실시설계', '세부설계', 'D/D', 'DD'],
    'type_construction': ['시공감리', '공사감독', '감리', 'C/S', 'CS'],
    'type_pmc': ['사업관리', 'PMC'],
}


def parse_service_types(type_str):
    """사업형태 문자열을 boolean 필드들로 파싱"""
    result = {k: False for k in SERVICE_TYPE_KEYWORDS}
    result['project_type_etc'] = None

    if pd.isna(type_str) or not type_str:
        return result

    text = str(type_str).strip()
    matched_any = False

    for field, keywords in SERVICE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                result[field] = True
                matched_any = True
                break

    if not matched_any:
        result['project_type_etc'] = text

    return result


def parse_date(date_str):
    """착수일/준공일 파싱 ('YY-MM 형식)"""
    if pd.isna(date_str) or date_str is None:
        return None

    date_str = str(date_str).strip()
    if not date_str:
        return None

    date_str = date_str.replace("\u2018", "").replace("\u2019", "").replace("'", "")

    if '-' in date_str:
        parts = date_str.split('-')
        if len(parts) >= 2:
            try:
                year = int(parts[0])
                month = int(parts[1])
                if year < 100:
                    year = year + 1900 if year > 50 else year + 2000
                return f"{year}-{month:02d}-01"
            except (ValueError, IndexError):
                pass

    return None


def get_coordinates(row):
    """좌표 가져오기 (없으면 수도 좌표 사용)"""
    x = row.get('X')
    y = row.get('Y')

    if pd.notna(x) and pd.notna(y):
        try:
            return float(y), float(x)  # latitude, longitude
        except (ValueError, TypeError):
            pass

    country = str(row.get('국가별', '')).strip()
    if country in CAPITAL_COORDINATES:
        return CAPITAL_COORDINATES[country]

    return None, None


def map_status(status_str):
    """진행상황 매핑"""
    if pd.isna(status_str) or status_str is None:
        return '준공'

    s = str(status_str).strip()

    if '완료' in s or '준공' in s:
        return '준공'
    if '진행' in s or '시행' in s:
        return '시행중'
    if 'EOI' in s.upper():
        return 'EOI제출'
    if '제안' in s:
        return '제안서제출'

    return s


def safe_float(val):
    """안전하게 float 변환 (NaN/None → None)"""
    if pd.isna(val) or val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_str(val):
    """안전하게 문자열 변환 (NaN → None)"""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s else None


def import_from_excel(delete_existing=True):
    """Excel 파일에서 ConsultingProject로 임포트"""

    if not EXCEL_FILE.exists():
        print(f"  Excel 파일을 찾을 수 없습니다: {EXCEL_FILE}")
        return 0

    print(f"  Excel 파일: {EXCEL_FILE.name}")

    df = pd.read_excel(EXCEL_FILE)
    print(f"  총 {len(df)}개 행 발견")

    if delete_existing:
        existing = ConsultingProject.query.count()
        if existing > 0:
            print(f"  기존 데이터 {existing}개 삭제 중...")
            # FK 참조 테이블 먼저 삭제
            for model in [ProjectLifecycle, Proposal, PerformanceRecord,
                          Contract, TorRfp, Eoi, ConsultingPersonnel]:
                try:
                    model.query.filter(
                        model.consulting_project_id.isnot(None)
                    ).delete()
                except Exception:
                    pass
            BoardPost.query.filter(
                BoardPost.consulting_project_id.isnot(None)
            ).delete()
            ConsultingProject.query.delete()
            db.session.commit()

    imported = 0
    skipped = 0
    fallback_coords = 0

    for idx, row in df.iterrows():
        try:
            title_kr = safe_str(row.get('국문사업명'))
            country = safe_str(row.get('국가별'))

            if not title_kr or not country:
                skipped += 1
                continue

            lat, lng = get_coordinates(row)
            if lat is not None and safe_float(row.get('Y')) is None:
                fallback_coords += 1

            service_types = parse_service_types(row.get('사업형태'))

            # USD 컬럼은 천USD 단위 → 백만USD로 변환
            budget_usd_raw = safe_float(row.get('전체용역비(천USD)'))
            budget_usd = budget_usd_raw / 1000 if budget_usd_raw is not None else None

            krc_budget_usd_raw = safe_float(row.get('용역비(공사)(천USD)'))
            krc_budget_usd = krc_budget_usd_raw / 1000 if krc_budget_usd_raw is not None else None

            project = ConsultingProject(
                number=int(row['번호']) if pd.notna(row.get('번호')) else None,
                contract_year=int(row['년도별']) if pd.notna(row.get('년도별')) else None,
                status=map_status(row.get('진행상황')),
                country=country,
                latitude=lat,
                longitude=lng,
                title_en=safe_str(row.get('영문사업명')),
                title_kr=title_kr,
                project_type=safe_str(row.get('사업형태')),
                type_feasibility=service_types['type_feasibility'],
                type_masterplan=service_types['type_masterplan'],
                type_basic_design=service_types['type_basic_design'],
                type_detailed_design=service_types['type_detailed_design'],
                type_construction=service_types['type_construction'],
                type_pmc=service_types['type_pmc'],
                project_type_etc=service_types['project_type_etc'],
                start_date=parse_date(row.get('착수일')),
                end_date=parse_date(row.get('준공일')),
                budget=safe_float(row.get('전체용역비(백만원)')),
                total_budget=safe_float(row.get('전체사업비(백만USD)')),
                krc_budget=safe_float(row.get('용역비(공사)(백만원)')),
                krc_share_ratio=safe_float(row.get('공사지분율')),
                budget_usd=budget_usd,
                krc_budget_usd=krc_budget_usd,
                client=safe_str(row.get('발주처')),
                funding_source=safe_str(row.get('재원')),
                lead_company=safe_str(row.get('주관')),
                jv1=safe_str(row.get('JV1')),
                jv2=safe_str(row.get('JV2')),
            )

            db.session.add(project)
            imported += 1

        except Exception as e:
            print(f"    행 {idx + 2} 오류: {e}")
            skipped += 1
            continue

    db.session.commit()

    print(f"\n  임포트: {imported}개 | 건너뜀: {skipped}개 | 수도좌표 사용: {fallback_coords}개")
    return imported


def print_statistics():
    """임포트 결과 통계 출력"""
    total = ConsultingProject.query.count()
    print(f"\n{'='*50}")
    print(f"  전체 프로젝트: {total}개")
    print(f"{'='*50}")

    # 상태별
    from sqlalchemy import func
    status_stats = db.session.query(
        ConsultingProject.status, func.count()
    ).group_by(ConsultingProject.status).all()
    print("\n  [상태별]")
    for status, count in status_stats:
        print(f"    {status}: {count}개")

    # 국가별 상위 10개
    country_stats = db.session.query(
        ConsultingProject.country, func.count()
    ).group_by(ConsultingProject.country).order_by(
        func.count().desc()
    ).limit(10).all()
    print("\n  [국가별 상위 10]")
    for country, count in country_stats:
        print(f"    {country}: {count}개")

    # 사업형태별
    type_fields = [
        ('type_feasibility', '타당성조사(F/S)'),
        ('type_masterplan', '마스터플랜(M/P)'),
        ('type_basic_design', '기본설계(B/D)'),
        ('type_detailed_design', '실시설계(D/D)'),
        ('type_construction', '시공감리(C/S)'),
        ('type_pmc', '사업관리(PMC)'),
    ]
    print("\n  [사업형태별]")
    for field, label in type_fields:
        count = ConsultingProject.query.filter(
            getattr(ConsultingProject, field) == True
        ).count()
        print(f"    {label}: {count}개")

    etc_count = ConsultingProject.query.filter(
        ConsultingProject.project_type_etc.isnot(None)
    ).count()
    print(f"    기타: {etc_count}개")

    # 좌표 커버리지
    coords_count = ConsultingProject.query.filter(
        ConsultingProject.latitude.isnot(None),
        ConsultingProject.longitude.isnot(None)
    ).count()
    pct = (coords_count / total * 100) if total > 0 else 0
    print(f"\n  [좌표 커버리지] {coords_count}/{total} ({pct:.1f}%)")

    # 예산 합계
    budget_sum = db.session.query(func.sum(ConsultingProject.budget)).scalar() or 0
    krc_sum = db.session.query(func.sum(ConsultingProject.krc_budget)).scalar() or 0
    print(f"\n  [예산 합계]")
    print(f"    전체 용역비: {budget_sum:,.0f} 백만원")
    print(f"    공사 지분: {krc_sum:,.0f} 백만원")


def main():
    delete_existing = '--no-delete' not in sys.argv

    print("=" * 50)
    print("  해외기술용역 데이터 Import")
    print("=" * 50)

    with app.app_context():
        imported = import_from_excel(delete_existing=delete_existing)

        if imported > 0:
            print_statistics()

    print(f"\n{'='*50}")
    print("  완료")
    print("=" * 50)


if __name__ == '__main__':
    main()
