"""
메탄감축 프로젝트 API 라우트
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, MethaneProject, MethaneBudgetData
from routes.auth import token_required, admin_required
from sqlalchemy import func, or_

methane_bp = Blueprint('methane', __name__)


@methane_bp.route('', methods=['GET'])
@token_required
def get_methane_projects(current_user):
    """메탄감축 프로젝트 목록 조회 (페이지네이션, 필터링 지원)"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        
        # 필터 파라미터
        year = request.args.get('year')
        country = request.args.get('country')
        status = request.args.get('status')
        search = request.args.get('search')
        
        # 기본 쿼리
        query = MethaneProject.query
        
        # 필터 적용
        if year:
            query = query.filter(MethaneProject.contract_year == int(year))
        
        if country:
            query = query.filter(MethaneProject.country == country)
        
        if status:
            query = query.filter(MethaneProject.status == status)
        
        if search:
            search_pattern = f'%{search}%'
            query = query.filter(or_(
                MethaneProject.title_kr.like(search_pattern),
                MethaneProject.title_en.like(search_pattern),
                MethaneProject.client.like(search_pattern)
            ))
        
        # 정렬: 최신순
        query = query.order_by(MethaneProject.contract_year.desc(), MethaneProject.id.desc())
        
        # 페이지네이션
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in pagination.items],
            'total': pagination.total,
            'currentPage': page,
            'pages': pagination.pages,
            'perPage': per_page
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/<int:project_id>', methods=['GET'])
@token_required
def get_methane_project(current_user, project_id):
    """특정 메탄감축 프로젝트 조회"""
    try:
        project = MethaneProject.query.get_or_404(project_id)
        return jsonify({
            'success': True,
            'data': project.to_dict()
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 404


@methane_bp.route('', methods=['POST'])
@token_required
@admin_required
def create_methane_project():
    """메탄감축 프로젝트 생성"""
    try:
        data = request.get_json()
        
        project = MethaneProject(
            number=data.get('number'),
            contract_year=data.get('contractYear'),
            status=data.get('status', '계획중'),
            country=data['country'],
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            title_en=data.get('titleEn'),
            title_kr=data['titleKr'],
            project_type=data.get('projectType'),
            start_date=data.get('startDate'),
            end_date=data.get('endDate'),
            budget=data.get('budget'),
            client=data.get('client'),
            description=data.get('description'),
            reduction_target=data.get('reductionTarget'),
            reduction_achieved=data.get('reductionAchieved'),
            technology_type=data.get('technologyType'),
            created_by=request.user_id
        )
        
        db.session.add(project)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': project.to_dict(),
            'message': '메탄감축 프로젝트가 생성되었습니다.'
        }), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/<int:project_id>', methods=['PUT'])
@token_required
@admin_required
def update_methane_project(current_user, project_id):
    """메탄감축 프로젝트 수정"""
    try:
        project = MethaneProject.query.get_or_404(project_id)
        data = request.get_json()
        
        # 업데이트
        if 'number' in data:
            project.number = data['number']
        if 'contractYear' in data:
            project.contract_year = data['contractYear']
        if 'status' in data:
            project.status = data['status']
        if 'country' in data:
            project.country = data['country']
        if 'latitude' in data:
            project.latitude = data['latitude']
        if 'longitude' in data:
            project.longitude = data['longitude']
        if 'titleEn' in data:
            project.title_en = data['titleEn']
        if 'titleKr' in data:
            project.title_kr = data['titleKr']
        if 'projectType' in data:
            project.project_type = data['projectType']
        if 'startDate' in data:
            project.start_date = data['startDate']
        if 'endDate' in data:
            project.end_date = data['endDate']
        if 'budget' in data:
            project.budget = data['budget']
        if 'client' in data:
            project.client = data['client']
        if 'description' in data:
            project.description = data['description']
        if 'reductionTarget' in data:
            project.reduction_target = data['reductionTarget']
        if 'reductionAchieved' in data:
            project.reduction_achieved = data['reductionAchieved']
        if 'technologyType' in data:
            project.technology_type = data['technologyType']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': project.to_dict(),
            'message': '메탄감축 프로젝트가 수정되었습니다.'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/<int:project_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_methane_project(current_user, project_id):
    """메탄감축 프로젝트 삭제"""
    try:
        project = MethaneProject.query.get_or_404(project_id)
        
        db.session.delete(project)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '메탄감축 프로젝트가 삭제되었습니다.'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/stats', methods=['GET'])
@token_required
def get_methane_stats(current_user):
    """메탄감축 프로젝트 통계"""
    try:
        # request에서 필터 가져오기
        filters = request.args.to_dict()
        
        query = MethaneProject.query
        
        # 필터 적용
        if filters.get('year'):
            query = query.filter(MethaneProject.contract_year == int(filters['year']))
        if filters.get('country'):
            query = query.filter(MethaneProject.country == filters['country'])
        if filters.get('status'):
            query = query.filter(MethaneProject.status == filters['status'])
        
        # 통계 계산
        total = query.count()
        
        # 상태별 통계
        by_status = {}
        status_counts = db.session.query(
            MethaneProject.status,
            func.count(MethaneProject.id)
        ).group_by(MethaneProject.status).all()
        
        for status, count in status_counts:
            by_status[status or '미정'] = count
        
        # 총 사업비
        total_budget = db.session.query(
            func.sum(MethaneProject.budget)
        ).scalar() or 0
        
        # 총 감축량
        total_reduction = db.session.query(
            func.sum(MethaneProject.reduction_achieved)
        ).scalar() or 0
        
        # 좌표 등록률
        with_coords = query.filter(
            MethaneProject.latitude.isnot(None),
            MethaneProject.longitude.isnot(None)
        ).count()
        coordinate_rate = round((with_coords / total * 100) if total > 0 else 0, 1)
        
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'byStatus': by_status,
                'totalBudget': float(total_budget),
                'totalReduction': float(total_reduction),
                'coordinateRate': coordinate_rate
            }
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/countries', methods=['GET'])
@token_required
def get_methane_countries(current_user):
    """메탄감축 프로젝트 국가 목록 (프로젝트 수 포함)"""
    try:
        countries = db.session.query(
            MethaneProject.country,
            func.count(MethaneProject.id).label('count')
        ).group_by(MethaneProject.country).order_by(MethaneProject.country).all()

        return jsonify({
            'success': True,
            'data': [{'country': c[0], 'count': c[1]} for c in countries if c[0]]
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/clients', methods=['GET'])
@token_required
def get_methane_clients(current_user):
    """메탄감축 프로젝트 클라이언트 목록"""
    try:
        clients = db.session.query(
            MethaneProject.client
        ).distinct().order_by(MethaneProject.client).all()

        return jsonify({
            'success': True,
            'data': [c[0] for c in clients if c[0]]
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/current-year-projects', methods=['GET'])
@token_required
def get_current_year_projects(current_user):
    """금년도 추진사업 목록 - 연도별 예산 데이터 포함

    2026년에 진행중인 사업만 표시:
    - 시작일이 2026년 이전 또는 2026년
    - 종료일이 2026년 이후 또는 NULL (진행중)
    - 상태가 "진행중" 또는 "시행중"
    """
    try:
        current_year = datetime.now().year
        next_year = current_year + 1

        # 모든 시행중/진행중 프로젝트 가져오기
        all_projects = MethaneProject.query.filter(
            or_(
                MethaneProject.status == '진행중',
                MethaneProject.status == '시행중'
            )
        ).all()

        # 2026년에 진행중인 프로젝트만 필터링
        in_progress_projects = []
        for project in all_projects:
            # 시작일 확인 (2026년 이전 또는 2026년에 시작)
            start_ok = True
            if project.start_date:
                start_year = project.start_date.year if hasattr(project.start_date, 'year') else None
                if start_year and start_year > current_year:
                    # 2027년 이후 시작하는 사업은 제외
                    start_ok = False

            # 종료일 확인 (2026년 이후 종료 또는 종료일 없음)
            end_ok = True
            if project.end_date:
                end_year = project.end_date.year if hasattr(project.end_date, 'year') else None
                if end_year and end_year < current_year:
                    # 2025년 이전에 끝난 사업은 제외
                    end_ok = False

            # 둘 다 만족하는 경우만 포함
            if start_ok and end_ok:
                in_progress_projects.append(project)

        if not in_progress_projects:
            return jsonify({
                'success': True,
                'currentYear': current_year,
                'nextYear': next_year,
                'yearColumns': [],
                'projects': [],
                'totals': {}
            })

        # 연도 범위 계산
        all_years = set()
        for project in in_progress_projects:
            start_year = project.start_date.year if project.start_date else (project.contract_year or current_year)
            end_year = project.end_date.year if project.end_date else current_year

            for y in range(start_year, current_year + 1):
                all_years.add(y)

        year_columns = sorted(list(all_years))

        # 프로젝트별 연도별 예산 데이터 구성
        project_data_list = []
        totals_by_year = {}

        for project in in_progress_projects:
            # 연도별 예산 데이터 조회
            budget_records = MethaneBudgetData.query.filter_by(
                methane_project_id=project.id
            ).all()

            budgets_by_year = {record.year: record.budget_amount for record in budget_records}
            total_budget_sum = sum(budgets_by_year.values())

            # 전체 예산과 비교하여 미래 예산 계산
            project_budget = float(project.budget * 1000) if project.budget else 0  # 백만원 → 천원
            future_budget = max(0, project_budget - total_budget_sum)

            project_data = {
                'id': project.id,
                'titleKr': project.title_kr,
                'country': project.country,
                'budget': project_budget / 1000,  # 천원 → 백만원
                'budgetInThousands': project_budget,
                'budgets': budgets_by_year,  # 연도별 예산 (천원)
                'futureBudget': future_budget
            }

            project_data_list.append(project_data)

            # 연도별 합계 계산
            for year, budget in budgets_by_year.items():
                totals_by_year[year] = totals_by_year.get(year, 0) + budget

        # 전체 예산 합계
        total_budget = sum(p['budgetInThousands'] for p in project_data_list)
        total_future = sum(p['futureBudget'] for p in project_data_list)

        return jsonify({
            'success': True,
            'currentYear': current_year,
            'nextYear': next_year,
            'yearColumns': year_columns,
            'projects': project_data_list,
            'totals': {
                'totalBudget': total_budget,
                'byYear': totals_by_year,
                'future': total_future
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/budget-data', methods=['POST'])
@token_required
@admin_required
def save_budget_data():
    """연도별 예산 데이터 저장"""
    try:
        data = request.get_json()
        methane_project_id = data.get('methaneProjectId')
        year = data.get('year')
        budget_amount = data.get('budgetAmount', 0)

        if not methane_project_id or not year:
            return jsonify({
                'success': False,
                'message': '프로젝트 ID와 연도는 필수입니다.'
            }), 400

        # 기존 데이터 확인
        existing = MethaneBudgetData.query.filter_by(
            methane_project_id=methane_project_id,
            year=year
        ).first()

        if existing:
            existing.budget_amount = budget_amount
            existing.updated_at = datetime.utcnow()
            existing.updated_by = request.user_id
        else:
            new_record = MethaneBudgetData(
                methane_project_id=methane_project_id,
                year=year,
                budget_amount=budget_amount,
                created_by=request.user_id
            )
            db.session.add(new_record)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': '예산 데이터가 저장되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/budget-data/<int:project_id>', methods=['GET'])
@token_required
def get_budget_data(current_user, project_id):
    """특정 프로젝트의 연도별 예산 데이터 조회"""
    try:
        budget_records = MethaneBudgetData.query.filter_by(
            methane_project_id=project_id
        ).all()

        return jsonify({
            'success': True,
            'data': [record.to_dict() for record in budget_records]
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/bulk-update', methods=['POST'])
@token_required
@admin_required
def bulk_update_methane_projects():
    """메탄감축 프로젝트 일괄 업데이트 (용역비 등)"""
    try:
        data = request.get_json()
        updates = data.get('updates', [])

        if not updates:
            return jsonify({
                'success': False,
                'message': '업데이트할 데이터가 없습니다.'
            }), 400

        success_count = 0
        fail_count = 0
        errors = []

        for update in updates:
            try:
                project_id = update.get('id')
                budget = update.get('budget')

                if not project_id:
                    fail_count += 1
                    errors.append({'id': project_id, 'error': 'ID가 없습니다.'})
                    continue

                project = MethaneProject.query.get(project_id)
                if not project:
                    fail_count += 1
                    errors.append({'id': project_id, 'error': '프로젝트를 찾을 수 없습니다.'})
                    continue

                # budget 업데이트
                if budget is not None:
                    project.budget = budget

                success_count += 1

            except Exception as e:
                fail_count += 1
                errors.append({'id': update.get('id'), 'error': str(e)})

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{success_count}개 업데이트 성공, {fail_count}개 실패',
            'successCount': success_count,
            'failCount': fail_count,
            'errors': errors
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@methane_bp.route('/export', methods=['GET'])
@token_required
def export_methane_projects(current_user):
    """메탄감축 프로젝트 엑셀 내보내기"""
    try:
        # TODO: 엑셀 내보내기 구현
        return jsonify({
            'success': False,
            'message': '엑셀 내보내기 기능은 준비 중입니다.'
        }), 501

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
