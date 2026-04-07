"""
GBMS - Projects Routes
글로벌사업처 해외사업관리시스템 - 사업관리 API
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Project, ProjectPhase, ProjectPersonnel, ActivityLog
from routes.auth import token_required

projects_bp = Blueprint('projects', __name__)


@projects_bp.route('', methods=['GET'])
@token_required
def get_projects(current_user):
    """Get all projects with filters"""
    # Get query parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    project_type = request.args.get('type')
    department = request.args.get('department')
    status = request.args.get('status')
    country = request.args.get('country')
    year = request.args.get('year', type=int)
    search = request.args.get('search')
    include_personnel = request.args.get('include_personnel', 'false').lower() == 'true'

    # Build query
    query = Project.query

    if project_type:
        query = query.filter(Project.project_type == project_type)

    if department:
        query = query.filter(Project.department == department)

    if status:
        query = query.filter(Project.status == status)

    if country:
        query = query.filter(Project.country == country)

    if year:
        query = query.filter(db.extract('year', Project.start_date) == year)

    if search:
        query = query.filter(
            db.or_(
                Project.title.ilike(f'%{search}%'),
                Project.code.ilike(f'%{search}%'),
                Project.country.ilike(f'%{search}%')
            )
        )

    # Order by updated_at descending
    query = query.order_by(Project.updated_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Build response data
    project_data = []
    for p in pagination.items:
        data = p.to_dict()
        if include_personnel:
            data['personnel'] = [person.to_dict() for person in p.personnel]
        project_data.append(data)

    return jsonify({
        'success': True,
        'data': project_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'currentPage': page
    })


@projects_bp.route('/<int:project_id>', methods=['GET'])
@token_required
def get_project(current_user, project_id):
    """Get single project by ID"""
    project = Project.query.get_or_404(project_id)
    
    data = project.to_dict(include_details=True)
    
    # Include phases
    data['phases'] = [p.to_dict() for p in project.phases.order_by(ProjectPhase.order)]
    
    # Include personnel
    data['personnel'] = [p.to_dict() for p in project.personnel]
    
    return jsonify({
        'success': True,
        'data': data
    })


@projects_bp.route('', methods=['POST'])
@token_required
def create_project(current_user):
    """Create new project"""
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'message': '요청 데이터가 없습니다.'}), 400
    
    required_fields = ['code', 'title', 'projectType', 'country', 'department']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'success': False, 'message': f'{field} 필드는 필수입니다.'}), 400
    
    # Check for duplicate code
    if Project.query.filter_by(code=data['code']).first():
        return jsonify({'success': False, 'message': '이미 존재하는 사업코드입니다.'}), 400
    
    project = Project(
        code=data['code'],
        title=data['title'],
        title_en=data.get('titleEn'),
        project_type=data['projectType'],
        country=data['country'],
        country_code=data.get('countryCode'),
        region=data.get('region'),
        department=data['department'],
        manager_id=data.get('managerId'),
        description=data.get('description'),
        objectives=data.get('objectives'),
        scope=data.get('scope'),
        start_date=datetime.strptime(data['startDate'], '%Y-%m-%d').date() if data.get('startDate') else None,
        end_date=datetime.strptime(data['endDate'], '%Y-%m-%d').date() if data.get('endDate') else None,
        duration_months=data.get('durationMonths'),
        budget_total=data.get('budgetTotal', 0),
        budget_krw=data.get('budgetKrw', 0),
        budget_foreign=data.get('budgetForeign', 0),
        currency=data.get('currency', 'KRW'),
        status=data.get('status', 'planning'),
        client=data.get('client'),
        partner=data.get('partner'),
        funding_source=data.get('fundingSource'),
        created_by=current_user.id
    )
    
    db.session.add(project)
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='create',
        entity_type='project',
        entity_id=project.id,
        description=f'사업 "{project.title}" 생성',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '사업이 등록되었습니다.',
        'data': project.to_dict()
    }), 201


@projects_bp.route('/<int:project_id>', methods=['PUT'])
@token_required
def update_project(current_user, project_id):
    """Update project"""
    project = Project.query.get_or_404(project_id)
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'message': '요청 데이터가 없습니다.'}), 400
    
    # Update fields
    if 'title' in data:
        project.title = data['title']
    if 'titleEn' in data:
        project.title_en = data['titleEn']
    if 'projectType' in data:
        project.project_type = data['projectType']
    if 'country' in data:
        project.country = data['country']
    if 'countryCode' in data:
        project.country_code = data['countryCode']
    if 'region' in data:
        project.region = data['region']
    if 'department' in data:
        project.department = data['department']
    if 'managerId' in data:
        project.manager_id = data['managerId']
    if 'description' in data:
        project.description = data['description']
    if 'objectives' in data:
        project.objectives = data['objectives']
    if 'scope' in data:
        project.scope = data['scope']
    if 'startDate' in data:
        project.start_date = datetime.strptime(data['startDate'], '%Y-%m-%d').date() if data['startDate'] else None
    if 'endDate' in data:
        project.end_date = datetime.strptime(data['endDate'], '%Y-%m-%d').date() if data['endDate'] else None
    if 'durationMonths' in data:
        project.duration_months = data['durationMonths']
    if 'budgetTotal' in data:
        project.budget_total = data['budgetTotal']
    if 'budgetKrw' in data:
        project.budget_krw = data['budgetKrw']
    if 'budgetForeign' in data:
        project.budget_foreign = data['budgetForeign']
    if 'currency' in data:
        project.currency = data['currency']
    if 'status' in data:
        project.status = data['status']
    if 'progress' in data:
        project.progress = data['progress']
    if 'client' in data:
        project.client = data['client']
    if 'partner' in data:
        project.partner = data['partner']
    if 'fundingSource' in data:
        project.funding_source = data['fundingSource']
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='update',
        entity_type='project',
        entity_id=project.id,
        description=f'사업 "{project.title}" 수정',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '사업이 수정되었습니다.',
        'data': project.to_dict()
    })


@projects_bp.route('/<int:project_id>', methods=['DELETE'])
@token_required
def delete_project(current_user, project_id):
    """Delete project"""
    project = Project.query.get_or_404(project_id)
    
    # Only admin can delete
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': '삭제 권한이 없습니다.'}), 403
    
    project_title = project.title
    
    # Log activity before deletion
    log = ActivityLog(
        user_id=current_user.id,
        action='delete',
        entity_type='project',
        entity_id=project.id,
        description=f'사업 "{project_title}" 삭제',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.delete(project)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '사업이 삭제되었습니다.'
    })


@projects_bp.route('/stats', methods=['GET'])
@token_required
def get_project_stats(current_user):
    """Get project statistics"""
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Total projects count by status
    total = Project.query.count()
    in_progress = Project.query.filter(Project.status == 'in_progress').count()
    completed = Project.query.filter(Project.status == 'completed').count()
    planning = Project.query.filter(Project.status == 'planning').count()
    
    # Projects by type
    by_type = db.session.query(
        Project.project_type,
        db.func.count(Project.id)
    ).group_by(Project.project_type).all()
    
    # Projects by department
    by_department = db.session.query(
        Project.department,
        db.func.count(Project.id)
    ).group_by(Project.department).all()
    
    # Projects by country
    by_country = db.session.query(
        Project.country,
        db.func.count(Project.id)
    ).group_by(Project.country).order_by(db.func.count(Project.id).desc()).limit(10).all()
    
    # Total budget
    total_budget = db.session.query(db.func.sum(Project.budget_total)).scalar() or 0
    
    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'inProgress': in_progress,
            'completed': completed,
            'planning': planning,
            'byType': {t[0]: t[1] for t in by_type},
            'byDepartment': {d[0]: d[1] for d in by_department},
            'byCountry': {c[0]: c[1] for c in by_country},
            'totalBudget': float(total_budget)
        }
    })


@projects_bp.route('/<int:project_id>/phases', methods=['POST'])
@token_required
def add_project_phase(current_user, project_id):
    """Add phase to project"""
    project = Project.query.get_or_404(project_id)
    data = request.get_json()
    
    phase = ProjectPhase(
        project_id=project.id,
        name=data.get('name'),
        description=data.get('description'),
        order=data.get('order', 0),
        start_date=datetime.strptime(data['startDate'], '%Y-%m-%d').date() if data.get('startDate') else None,
        end_date=datetime.strptime(data['endDate'], '%Y-%m-%d').date() if data.get('endDate') else None,
        status=data.get('status', 'pending')
    )
    
    db.session.add(phase)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '단계가 추가되었습니다.',
        'data': phase.to_dict()
    }), 201


@projects_bp.route('/<int:project_id>/personnel', methods=['POST'])
@token_required
def add_project_personnel(current_user, project_id):
    """Add personnel to project"""
    project = Project.query.get_or_404(project_id)
    data = request.get_json()

    personnel = ProjectPersonnel(
        project_id=project.id,
        name=data.get('name'),
        role=data.get('role'),
        position=data.get('position'),
        affiliation=data.get('affiliation'),
        start_date=datetime.strptime(data['startDate'], '%Y-%m-%d').date() if data.get('startDate') else None,
        end_date=datetime.strptime(data['endDate'], '%Y-%m-%d').date() if data.get('endDate') else None,
        is_deployed=data.get('isDeployed', False),
        contact_email=data.get('contactEmail'),
        contact_phone=data.get('contactPhone')
    )

    db.session.add(personnel)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '인력이 추가되었습니다.',
        'data': personnel.to_dict()
    }), 201


@projects_bp.route('/personnel/<int:personnel_id>', methods=['PUT'])
@token_required
def update_personnel(current_user, personnel_id):
    """Update personnel information"""
    personnel = ProjectPersonnel.query.get_or_404(personnel_id)
    data = request.get_json()

    if 'name' in data:
        personnel.name = data['name']
    if 'role' in data:
        personnel.role = data['role']
    if 'startDate' in data:
        personnel.start_date = datetime.strptime(data['startDate'], '%Y-%m-%d').date() if data['startDate'] else None
    if 'endDate' in data:
        personnel.end_date = datetime.strptime(data['endDate'], '%Y-%m-%d').date() if data['endDate'] else None
    if 'isDeployed' in data:
        personnel.is_deployed = data['isDeployed']

    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='update',
        entity_type='personnel',
        entity_id=personnel.id,
        description=f'파견정보 수정: {personnel.name}',
        ip_address=request.remote_addr
    )
    db.session.add(log)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': '파견정보가 수정되었습니다.',
        'data': personnel.to_dict()
    })
