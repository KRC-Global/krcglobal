"""
GBMS - Dashboard Routes
글로벌사업처 해외사업관리시스템 - 대시보드 API
"""
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from sqlalchemy import func, case, Integer
from models import db, Project, Budget, Document, Office, ConsultingProject, OdaProject, MethaneProject
from models.expansion import Loan, CompanyCollateral, Company
from routes.auth import token_required

dashboard_bp = Blueprint('dashboard', __name__)

def get_status_counts():
    """Helper to get status counts from both tables"""
    # Consulting Projects
    consulting_active = ConsultingProject.query.filter(ConsultingProject.status == '시행중').count()
    consulting_total = ConsultingProject.query.count()
    consulting_proposing = ConsultingProject.query.filter(
        (ConsultingProject.status == 'EOI제출') | (ConsultingProject.status == '제안서제출')
    ).count()
    consulting_completed = consulting_total - consulting_active - consulting_proposing

    # ODA Projects - contract_year 기반 DB 집계 (전체 로드 제거)
    current_year = datetime.now().year
    oda_total = OdaProject.query.count()
    oda_active = OdaProject.query.filter(
        db.or_(
            OdaProject.contract_year == None,
            OdaProject.contract_year >= current_year - 10
        ),
        OdaProject.status.notin_(['완료', '종료', '준공'])
    ).count()

    oda_planning = OdaProject.query.filter(OdaProject.status.like('%기획%') | OdaProject.status.like('%발굴%')).count()
    oda_completed = oda_total - oda_active - oda_planning

    return {
        'in_progress': consulting_active + oda_active,
        'completed': consulting_completed + oda_completed,
        'planning': oda_planning
    }

@dashboard_bp.route('/overview', methods=['GET'])
@token_required
def get_overview(current_user):
    """Get dashboard overview statistics with detailed categorization"""

    # 1. Consulting Projects (기술용역)
    consulting_total = ConsultingProject.query.count()
    # 제안중: EOI제출, 제안서제출
    consulting_proposing = ConsultingProject.query.filter(
        (ConsultingProject.status == 'EOI제출') | (ConsultingProject.status == '제안서제출')
    ).count()
    # 진행: 시행중 (금년도 사업)
    consulting_active = ConsultingProject.query.filter(ConsultingProject.status == '시행중').count()
    # 종료: 전체에서 제안중과 진행을 제외한 나머지
    consulting_completed = consulting_total - consulting_proposing - consulting_active
    # 전체용역비: 준공과 시행중인 사업만 합산
    consulting_budget = db.session.query(func.sum(ConsultingProject.budget)).filter(
        (ConsultingProject.status == '준공') | (ConsultingProject.status == '시행중')
    ).scalar() or 0

    # 2. ODA Projects (국제협력사업)
    oda_total = OdaProject.query.count()

    # 진행: contract_year 기반 DB 집계 (전체 로드 제거)
    current_year = datetime.now().year
    oda_active = OdaProject.query.filter(
        db.or_(
            OdaProject.contract_year == None,
            OdaProject.contract_year >= current_year - 10
        ),
        OdaProject.status.notin_(['완료', '종료', '준공'])
    ).count()

    oda_planning = OdaProject.query.filter(OdaProject.status.like('%기획%') | OdaProject.status.like('%발굴%')).count()
    # 종료: 전체에서 진행과 기획을 제외한 나머지
    oda_completed = oda_total - oda_active - oda_planning
    oda_budget = db.session.query(func.sum(OdaProject.budget)).scalar() or 0

    # 3. Unique Countries and Continents
    consulting_countries = db.session.query(ConsultingProject.country).distinct().all()
    oda_countries = db.session.query(OdaProject.country).distinct().all()
    methane_countries = db.session.query(MethaneProject.country).distinct().all()

    unique_countries = set([c[0] for c in consulting_countries if c[0]] +
                          [c[0] for c in oda_countries if c[0]] +
                          [c[0] for c in methane_countries if c[0]])

    # 대륙별 국가 매핑
    continent_mapping = {
        '아시아': ['캄보디아', '베트남', '필리핀', '인도네시아', '라오스', '미얀마', '태국', '말레이시아',
                   '네팔', '스리랑카', '방글라데시', '파키스탄', '인도', '몽골', '우즈베키스탄',
                   '카자흐스탄', '키르기스스탄', '타지키스탄', '투르크메니스탄'],
        '아프리카': ['탄자니아', '케냐', '우간다', '에티오피아', '르완다', '가나', '세네갈', '모잠비크',
                    '코트디부아르', '나이지리아', '카메룬', '잠비아', '감비아', '기니'],
        '중남미': ['과테말라', '페루', '에콰도르', '볼리비아', '파라과이', '콜롬비아', '도미니카공화국'],
        '중동': ['요르단', '이라크', '팔레스타인', '이집트'],
        '오세아니아': ['키리바시', '피지', '통가', '사모아', '파푸아뉴기니', '바누아투']
    }

    # 실제 데이터에 있는 대륙만 카운트
    unique_continents = set()
    for country in unique_countries:
        for continent, countries in continent_mapping.items():
            if country in countries:
                unique_continents.add(continent)
                break

    # 기술용역사업 (consulting + methane) 대륙 및 국가 수
    consulting_countries_set = set([c[0] for c in consulting_countries if c[0]] +
                                   [c[0] for c in methane_countries if c[0]])
    consulting_continents_set = set()
    for country in consulting_countries_set:
        for continent, countries in continent_mapping.items():
            if country in countries:
                consulting_continents_set.add(continent)
                break

    # ODA 사업 대륙 및 국가 수
    oda_countries_set = set([c[0] for c in oda_countries if c[0]])
    oda_continents_set = set()
    for country in oda_countries_set:
        for continent, countries in continent_mapping.items():
            if country in countries:
                oda_continents_set.add(continent)
                break

    # 4. Offices (전체 해외사무소 등 개수, status와 무관)
    offices_total = Office.query.count()

    # 유형별 해외사무소 개수
    offices_by_type = db.session.query(
        Office.office_type,
        func.count(Office.id)
    ).group_by(Office.office_type).all()

    offices_detail = {
        'total': offices_total,
        'byType': {office_type: count for office_type, count in offices_by_type if office_type}
    }

    # 5. Companies (해외진출지원사업 - 기업관리)
    companies = Company.query.count()

    # 6. Total Budget
    total_budget = float(consulting_budget) + float(oda_budget)
    total_budget_won = total_budget * 1_000_000
    consulting_budget_won = float(consulting_budget) * 1_000_000
    oda_budget_won = float(oda_budget) * 1_000_000

    # 7. Projects by Type
    oda_types = db.session.query(
        OdaProject.project_type,
        func.count(OdaProject.id)
    ).group_by(OdaProject.project_type).all()

    by_type = {
        'overseas_tech': consulting_total
    }

    for o_type, count in oda_types:
        if not o_type: continue
        key = 'oda_other'
        if '양자' in o_type: key = 'oda_bilateral'
        elif '다자' in o_type: key = 'oda_multilateral'
        elif 'K-라이스벨트' in o_type or '라이스' in o_type: key = 'k_rice_belt'
        elif '투자' in o_type: key = 'overseas_investment'

        if key in by_type:
            by_type[key] += count
        else:
            by_type[key] = count

    return jsonify({
        'success': True,
        'data': {
            'projects': {
                'total': consulting_total + oda_total,
                'inProgress': consulting_active + oda_active,
                'completed': consulting_completed + oda_completed,
                'planning': oda_planning,
                'consulting': {
                    'total': consulting_total,
                    'proposing': consulting_proposing,
                    'active': consulting_active,
                    'completed': consulting_completed,
                    'budget': consulting_budget_won,
                    'continents': len(consulting_continents_set),
                    'countries': len(consulting_countries_set)
                },
                'oda': {
                    'total': oda_total,
                    'active': oda_active,
                    'completed': oda_completed,
                    'planning': oda_planning,
                    'budget': oda_budget_won,
                    'continents': len(oda_continents_set),
                    'countries': len(oda_countries_set)
                }
            },
            'countries': len(unique_countries),
            'continents': len(unique_continents),
            'companies': companies,
            'offices': offices_detail,
            'budget': {
                'total': total_budget_won,
                'consulting': consulting_budget_won,
                'oda': oda_budget_won,
                'planned': total_budget_won,
                'executed': total_budget_won * 0.7,
                'executionRate': 70.0
            },
            'byType': by_type
        }
    })

def consulting_active_planning_count():
    return ConsultingProject.query.filter(ConsultingProject.status != '준공').count()

def oda_active_planning_count():
    # contract_year 기반 DB 집계 (전체 로드 제거)
    current_year = datetime.now().year
    return OdaProject.query.filter(
        db.or_(
            OdaProject.contract_year == None,
            OdaProject.contract_year >= current_year - 10
        ),
        OdaProject.status.notin_(['완료', '종료', '준공'])
    ).count()


@dashboard_bp.route('/recent-projects', methods=['GET'])
@token_required
def get_recent_projects(current_user):
    """Get recent projects for dashboard combined from both tables"""
    limit = request.args.get('limit', 5, type=int)
    
    # Fetch recent Consulting
    recent_consulting = ConsultingProject.query.order_by(
        ConsultingProject.created_at.desc()
    ).limit(limit).all()
    
    # Fetch recent ODA
    recent_oda = OdaProject.query.order_by(
        OdaProject.created_at.desc()
    ).limit(limit).all()
    
    combined = []
    
    for p in recent_consulting:
        combined.append({
            'title': p.title_kr,
            'project_type': 'overseas_tech',
            'country': p.country,
            'department': '글로벌사업부',
            'start_date': p.start_date or '-',
            'end_date': p.end_date or '-',
            'status': 'in_progress' if p.status == '진행중' else 'completed',
            'updated_at': p.updated_at or p.created_at
        })
        
    for p in recent_oda:
        # Map ODA type
        p_type = 'oda_bilateral' # default
        if p.project_type:
            if '다자' in p.project_type: p_type = 'oda_multilateral'
            elif '라이스' in p.project_type: p_type = 'k_rice_belt'
            elif '투자' in p.project_type: p_type = 'overseas_investment'
            
        status = 'in_progress'
        if p.status and ('종료' in p.status or '완료' in p.status):
            status = 'completed'
        elif p.status and ('기획' in p.status):
            status = 'planning'
            
        combined.append({
            'title': p.title,
            'project_type': p_type,
            'country': p.country,
            'department': '농식품국제개발협력센터',
            'start_date': p.period.split('-')[0] if p.period and '-' in p.period else '-',
            'end_date': p.period.split('-')[1] if p.period and '-' in p.period else '-',
            'status': status,
            'updated_at': p.updated_at or p.created_at
        })
    
    # Sort by updated_at desc
    combined.sort(key=lambda x: x['updated_at'], reverse=True)
    
    return jsonify({
        'success': True,
        'data': combined[:limit]
    })


@dashboard_bp.route('/department-budgets', methods=['GET'])
@token_required
def get_department_budgets(current_user):
    """Get budget by department (Inferred from project types)"""

    # Consulting -> Global Business (준공과 시행중인 사업만)
    consulting_budget = db.session.query(func.sum(ConsultingProject.budget)).filter(
        (ConsultingProject.status == '준공') | (ConsultingProject.status == '시행중') | (ConsultingProject.status == '진행중')
    ).scalar() or 0
    consulting_budget_won = float(consulting_budget) * 1_000_000
    
    # ODA -> AIDC
    oda_budget = db.session.query(func.sum(OdaProject.budget)).scalar() or 0
    oda_budget_won = float(oda_budget) * 1_000_000
    
    data = [
        {
            'department': 'gb',
            'departmentName': '글로벌사업부',
            'planned': consulting_budget_won,
            'executed': consulting_budget_won * 0.8, # Mock execution
            'rate': 80.0
        },
        {
            'department': 'aidc',
            'departmentName': '농식품국제개발협력센터',
            'planned': oda_budget_won,
            'executed': oda_budget_won * 0.6, # Mock execution
            'rate': 60.0
        }
    ]
    
    return jsonify({
        'success': True,
        'data': data
    })


@dashboard_bp.route('/country-stats', methods=['GET'])
@token_required
def get_country_stats(current_user):
    """Get project statistics by country combined"""

    # Dictionary to aggregate: country -> {count, budget}
    stats = {}

    # Consulting
    c_results = db.session.query(
        ConsultingProject.country,
        func.count(ConsultingProject.id),
        func.sum(ConsultingProject.budget)
    ).group_by(ConsultingProject.country).all()

    for country, count, budget in c_results:
        if not country: continue
        if country not in stats: stats[country] = {'count': 0, 'budget': 0}
        stats[country]['count'] += count
        stats[country]['budget'] += float(budget or 0)

    # ODA
    o_results = db.session.query(
        OdaProject.country,
        func.count(OdaProject.id),
        func.sum(OdaProject.budget)
    ).group_by(OdaProject.country).all()

    for country, count, budget in o_results:
        if not country: continue
        if country not in stats: stats[country] = {'count': 0, 'budget': 0}
        stats[country]['count'] += count
        stats[country]['budget'] += float(budget or 0)

    # Convert to list and sort
    result_list = []
    for country, data in stats.items():
        result_list.append({
            'country': country,
            'projectCount': data['count'],
            'totalBudget': data['budget'] * 1_000_000 # Convert to Won
        })

    result_list.sort(key=lambda x: x['projectCount'], reverse=True)

    return jsonify({
        'success': True,
        'data': result_list
    })


@dashboard_bp.route('/continent-stats', methods=['GET'])
@token_required
def get_continent_stats(current_user):
    """Get project statistics by continent"""

    # 대륙별 국가 매핑
    continent_mapping = {
        '아시아': ['캄보디아', '베트남', '필리핀', '인도네시아', '라오스', '미얀마', '태국', '말레이시아',
                   '네팔', '스리랑카', '방글라데시', '파키스탄', '인도', '몽골', '우즈베키스탄',
                   '카자흐스탄', '키르기스스탄', '타지키스탄', '투르크메니스탄'],
        '아프리카': ['탄자니아', '케냐', '우간다', '에티오피아', '르완다', '가나', '세네갈', '모잠비크',
                    '코트디부아르', '나이지리아', '카메룬', '잠비아'],
        '중남미': ['과테말라', '페루', '에콰도르', '볼리비아', '파라과이', '콜롬비아', '도미니카공화국'],
        '중동': ['요르단', '이라크', '팔레스타인', '이집트'],
        '유럽/CIS': ['우크라이나', '아제르바이잔', '조지아'],
        '오세아니아': ['파푸아뉴기니', '피지', '솔로몬제도']
    }

    # 국가별 대륙 역매핑
    country_to_continent = {}
    for continent, countries in continent_mapping.items():
        for country in countries:
            country_to_continent[country] = continent

    # 대륙별 집계 초기화
    continent_stats = {}
    for continent in continent_mapping.keys():
        continent_stats[continent] = {
            'name': continent,
            'projectCount': 0,
            'budget': 0,
            'countries': []
        }

    # Consulting 프로젝트 집계
    c_results = db.session.query(
        ConsultingProject.country,
        func.count(ConsultingProject.id),
        func.sum(ConsultingProject.budget)
    ).group_by(ConsultingProject.country).all()

    for country, count, budget in c_results:
        if not country: continue
        continent = country_to_continent.get(country, '기타')
        if continent not in continent_stats:
            continent_stats[continent] = {
                'name': continent,
                'projectCount': 0,
                'budget': 0,
                'countries': []
            }
        continent_stats[continent]['projectCount'] += count
        continent_stats[continent]['budget'] += float(budget or 0)
        if country not in continent_stats[continent]['countries']:
            continent_stats[continent]['countries'].append(country)

    # ODA 프로젝트 집계
    o_results = db.session.query(
        OdaProject.country,
        func.count(OdaProject.id),
        func.sum(OdaProject.budget)
    ).group_by(OdaProject.country).all()

    for country, count, budget in o_results:
        if not country: continue
        continent = country_to_continent.get(country, '기타')
        if continent not in continent_stats:
            continent_stats[continent] = {
                'name': continent,
                'projectCount': 0,
                'budget': 0,
                'countries': []
            }
        continent_stats[continent]['projectCount'] += count
        continent_stats[continent]['budget'] += float(budget or 0)
        if country not in continent_stats[continent]['countries']:
            continent_stats[continent]['countries'].append(country)

    # 결과 리스트로 변환
    result_list = []
    for continent, data in continent_stats.items():
        if data['projectCount'] > 0:
            result_list.append({
                'continent': continent,
                'projectCount': data['projectCount'],
                'totalBudget': data['budget'] * 1_000_000,
                'countries': sorted(data['countries'])
            })

    # 프로젝트 수로 정렬
    result_list.sort(key=lambda x: x['projectCount'], reverse=True)

    return jsonify({
        'success': True,
        'data': result_list
    })


@dashboard_bp.route('/office-list', methods=['GET'])
@token_required
def get_office_list(current_user):
    """Get list of overseas offices"""

    offices = Office.query.all()

    office_list = []
    for office in offices:
        office_list.append({
            'id': office.id,
            'name': office.name,
            'country': office.country,
            'city': office.city,
            'region': office.region,
            'office_type': office.office_type,
            'contact_person': office.contact_person,
            'contact_email': office.contact_email,
            'established_date': office.established_date.isoformat() if office.established_date else None
        })

    # 지역별로 정렬
    office_list.sort(key=lambda x: (x['region'], x['country']))

    return jsonify({
        'success': True,
        'data': office_list
    })


@dashboard_bp.route('/current-year-projects', methods=['GET'])
@token_required
def get_current_year_projects(current_user):
    """Get current year (2026) projects by type for dashboard tables"""
    from flask import request

    current_year = 2026
    per_page = 20  # 페이지당 항목 수

    # 페이지 번호 파라미터 (기본값 1)
    consulting_page = request.args.get('consulting_page', 1, type=int)
    oda_page = request.args.get('oda_page', 1, type=int)
    loan_page = request.args.get('loan_page', 1, type=int)

    # 1. 해외기술용역사업 (ConsultingProject) - 시행중이고 2026년 이상 종료 예정인 사업
    # 모든 시행중 프로젝트를 가져온 후 Python에서 날짜 필터링 (다양한 날짜 형식 처리)
    consulting_projects_all = ConsultingProject.query.filter(
        ConsultingProject.status == '시행중'
    ).order_by(ConsultingProject.start_date.desc()).all()

    consulting_all_filtered = []
    import re
    import math

    for p in consulting_projects_all:
        # end_date에서 종료년도 추출 (다양한 형식 처리)
        end_year = None
        if p.end_date:
            end_date_str = str(p.end_date)
            # 먼저 4자리 연도 시도 (예: 2026-04-30)
            year_match = re.search(r'(\d{4})', end_date_str)
            if year_match:
                end_year = int(year_match.group(1))
            else:
                # 2자리 연도 처리 (예: '26-04 → 2026)
                year_match2 = re.search(r"'?(\d{2})(?:[-./]|$)", end_date_str)
                if year_match2:
                    end_year = 2000 + int(year_match2.group(1))

        # 2026년 이후 종료 예정인 사업만 포함
        if not end_year or end_year < current_year:
            continue

        # 날짜에서 연.월 추출 (예: "2024-03-01" → "'24.03", "'26-04" → "'26.04")
        def extract_ym(date_str):
            if not date_str:
                return None
            s = str(date_str)
            # 4자리 연도 형식 처리
            m = re.search(r'(\d{4})[\-\./](\d{1,2})', s)
            if m:
                return f"'{m.group(1)[2:]}.{m.group(2).zfill(2)}"
            m2 = re.search(r'(\d{4})', s)
            if m2:
                return f"'{m2.group(1)[2:]}"
            # 2자리 연도 형식 처리 (예: '26-04)
            m3 = re.search(r"'?(\d{2})[-./](\d{1,2})", s)
            if m3:
                return f"'{m3.group(1)}.{m3.group(2).zfill(2)}"
            m4 = re.search(r"'?(\d{2})$", s)
            if m4:
                return f"'{m4.group(1)}"
            return None

        start_ym = extract_ym(p.start_date)
        end_ym = extract_ym(p.end_date)
        period = f"{start_ym}~{end_ym}" if start_ym and end_ym else (start_ym or end_ym or '-')

        # 컨소시엄 구성 (대표사 + JV파트너)
        consortium_parts = []
        if p.lead_company:
            ratio_str = f"({int(p.lead_company_ratio * 100)}%)" if p.lead_company_ratio else ''
            consortium_parts.append(f"{p.lead_company}{ratio_str}")
        for jv_idx in range(1, 6):
            jv_name = getattr(p, f'jv{jv_idx}', None)
            jv_ratio = getattr(p, f'jv{jv_idx}_ratio', None)
            if jv_name:
                ratio_str = f"({int(jv_ratio * 100)}%)" if jv_ratio else ''
                consortium_parts.append(f"{jv_name}{ratio_str}")
        consortium = ', '.join(consortium_parts) if consortium_parts else '-'

        consulting_all_filtered.append({
            'projectName': p.title_kr or '-',
            'country': p.country or '-',
            'totalBudget': float(p.budget or 0) if p.budget else 0,
            'krcBudget': float(p.krc_budget or 0) if p.krc_budget else 0,
            'krcShareRatio': float(p.krc_share_ratio * 100) if p.krc_share_ratio else None,
            'period': period,
            'consortium': consortium,
            'client': p.client or '-',
            'fundingSource': p.funding_source or '-',
            'isMethane': False,
            '_startDate': str(p.start_date or ''),
            '_endDate': str(p.end_date or '')
        })

    # 3. 메탄감축사업 → 컨설팅 목록 뒤(9번~)에 배치
    methane_projects_all = MethaneProject.query.filter(
        MethaneProject.status == '진행중'
    ).order_by(MethaneProject.created_at.desc()).all()

    methane_items = []
    for p in methane_projects_all:
        # 사업명: 국가명 메탄감축사업
        project_name = f"{p.country} 메탄감축사업" if p.country else '메탄감축사업'

        # 메탄 사업기간 (연.월 형식)
        def extract_ym_m(date_val):
            if not date_val:
                return None
            s = str(date_val)
            m = re.search(r'(\d{4})[\-\./](\d{1,2})', s)
            if m:
                return f"'{m.group(1)[2:]}.{m.group(2).zfill(2)}"
            m2 = re.search(r'(\d{4})', s)
            if m2:
                return f"'{m2.group(1)[2:]}"
            return None

        m_start_ym = extract_ym_m(p.start_date)
        m_end_ym = extract_ym_m(p.end_date)
        if m_start_ym and m_end_ym:
            period = f"{m_start_ym}~{m_end_ym}"
        elif p.period:
            period = p.period
        else:
            period = '-'

        # 정렬용 원본 날짜
        m_start = str(p.start_date or '') if p.start_date else (p.period or '')
        m_end = str(p.end_date or '') if p.end_date else ''

        methane_items.append({
            'projectName': project_name,
            'country': p.country or '-',
            'totalBudget': float(p.budget or 0) if p.budget else 0,
            'krcBudget': 0,
            'krcShareRatio': None,
            'period': period,
            'consortium': '-',
            'client': p.client or '-',
            'fundingSource': '-',
            'isMethane': True,
            '_startDate': m_start,
            '_endDate': m_end
        })

    # 컨설팅(1~N) + 메탄(N+1~) 순서로 통합 (사업명+국가 기준 중복 제거)
    seen = set()
    combined_all = []
    for item in consulting_all_filtered + methane_items:
        key = (item['projectName'], item['country'])
        if key not in seen:
            seen.add(key)
            combined_all.append(item)

    # 착수일 빠른 순 정렬 (1차), 준공일 빠른 순 (2차)
    def sort_key(item):
        def extract_date(s):
            """날짜 문자열에서 정렬용 값 추출 (빠른 순)"""
            if not s:
                return '9999'
            m = re.search(r'(\d{4})', s)
            return m.group(1) if m else '9999'
        return (item['isMethane'], extract_date(item['_startDate']), extract_date(item['_endDate']))

    combined_all.sort(key=sort_key)

    # 정렬용 내부 필드 제거
    for item in combined_all:
        item.pop('_startDate', None)
        item.pop('_endDate', None)

    # 페이지네이션 적용
    consulting_total = len(combined_all)
    consulting_pages = math.ceil(consulting_total / per_page)
    consulting_start = (consulting_page - 1) * per_page
    consulting_end = consulting_start + per_page
    consulting_list = combined_all[consulting_start:consulting_end]

    # 2. 국제협력사업 (OdaProject) - 진행중이고 2026년 이후 종료 예정인 사업
    oda_projects_all = OdaProject.query.filter(
        OdaProject.status == '진행중'
    ).order_by(OdaProject.created_at.desc()).all()

    # period에서 종료년도 확인하여 2026년 이후인 것만 필터링
    oda_all_filtered = []
    for p in oda_projects_all:
        # period에서 종료년도 추출하여 2026년 이후인지 확인
        if not p.period:
            continue

        original_period = str(p.period)

        # Unicode 곡선 따옴표를 ASCII 직선 따옴표로 변환
        original_period = original_period.replace(chr(8216), "'").replace(chr(8217), "'")
        original_period = original_period.replace(chr(8220), '"').replace(chr(8221), '"')

        # 종료년도 추출
        end_year = None
        if '-' in original_period:
            parts = original_period.replace("'", "").split('-')
            if len(parts) >= 2:
                end_year_str = parts[1].strip()
                # 2자리 연도를 4자리로 변환: "25" -> 2025
                if len(end_year_str) == 2:
                    end_year = 2000 + int(end_year_str)
                elif len(end_year_str) == 4:
                    end_year = int(end_year_str)

        # 2026년 이후 종료 예정인 사업만 포함
        if not end_year or end_year < current_year:
            continue

        # period 포맷팅
        period = '-'
        if original_period.startswith("''"):
            period = "'" + original_period[2:]
        elif original_period.startswith("'") and "-'" in original_period:
            period = original_period
        elif '-' in original_period and "'" not in original_period:
            parts = original_period.split('-')
            start_year = parts[0].strip()
            completion_year = parts[1].strip() if len(parts) > 1 else ''
            if len(start_year) == 4:
                start_year = start_year[2:]
            if len(completion_year) == 4:
                completion_year = completion_year[2:]
            if start_year and completion_year:
                period = f"'{start_year}-'{completion_year}"
        else:
            period = original_period

        oda_all_filtered.append({
            'projectName': p.title or '-',
            'country': p.country or '-',
            'currentYearBudget': float(p.budget or 0) if p.budget else 0,
            'period': period
        })

    # 페이지네이션 적용
    oda_total = len(oda_all_filtered)
    oda_pages = math.ceil(oda_total / per_page)
    oda_start = (oda_page - 1) * per_page
    oda_end = oda_start + per_page
    oda_list = oda_all_filtered[oda_start:oda_end]

    # 4. 해외진출지원사업 - 기업별 담보현황
    collateral_all = CompanyCollateral.query.order_by(CompanyCollateral.company_name).all()

    loan_all_filtered = []
    for c in collateral_all:
        loan_all_filtered.append({
            'companyName': c.company_name or '-',
            'loanAmount': c.loan_amount or 0,  # 천원 단위
            'balance': c.balance or 0  # 천원 단위
        })

    # 페이지네이션 적용
    loan_total = len(loan_all_filtered)
    loan_pages = math.ceil(loan_total / per_page)
    loan_start = (loan_page - 1) * per_page
    loan_end = loan_start + per_page
    loan_list = loan_all_filtered[loan_start:loan_end]

    return jsonify({
        'success': True,
        'data': {
            'consulting': {
                'items': consulting_list,
                'total': consulting_total,
                'currentPage': consulting_page,
                'totalPages': consulting_pages
            },
            'oda': {
                'items': oda_list,
                'total': oda_total,
                'currentPage': oda_page,
                'totalPages': oda_pages
            },
            'loan': {
                'items': loan_list,
                'total': loan_total,
                'currentPage': loan_page,
                'totalPages': loan_pages
            }
        }
    })