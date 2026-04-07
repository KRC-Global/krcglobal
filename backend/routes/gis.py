"""
GBMS - GIS Routes
글로벌사업처 해외사업관리시스템 - GIS 지도 API
"""
from flask import Blueprint, request, jsonify
from models import db, Project, ConsultingProject, Office, ProjectPersonnel
from routes.auth import token_required

gis_bp = Blueprint('gis', __name__)


@gis_bp.route('/projects', methods=['GET'])
# @token_required  # 임시로 인증 비활성화 (개발용)
def get_gis_projects():
    """Get all projects with GIS data for map display (includes consulting and ODA projects)"""
    # Get query parameters
    project_type = request.args.get('type')
    category = request.args.get('category')  # 'consulting' or 'oda'
    country = request.args.get('country')
    status = request.args.get('status')
    search = request.args.get('search')
    include_consulting = request.args.get('includeConsulting', 'true').lower() == 'true'
    include_oda = request.args.get('includeOda', 'true').lower() == 'true'
    include_offices = request.args.get('includeOffices', 'true').lower() == 'true'

    gis_projects = []

    # Get regular projects (with personnel information)
    # ODA 프로젝트는 OdaProject 테이블에서만 가져오므로 Project 테이블에서는 제외
    include_projects = request.args.get('includeProjects', 'true').lower() == 'true'
    if include_projects:
        projects_query = Project.query.filter(
            Project.latitude.isnot(None),
            Project.longitude.isnot(None),
            Project.latitude != 0,
            Project.longitude != 0,
            ~Project.project_type.in_(['oda_bilateral', 'oda_multilateral'])  # ODA 타입 제외
        )

        if country:
            projects_query = projects_query.filter(Project.country == country)

        if project_type:
            projects_query = projects_query.filter(Project.project_type == project_type)

        if status:
            projects_query = projects_query.filter(Project.status == status)

        if search:
            projects_query = projects_query.filter(
                db.or_(
                    Project.title.ilike(f'%{search}%'),
                    Project.country.ilike(f'%{search}%')
                )
            )

        projects = projects_query.all()
        print(f"GIS API: 프로젝트 {len(projects)}개 발견")

        # Transform projects to GIS format
        for proj in projects:
            try:
                lat = float(proj.latitude) if proj.latitude else None
                lng = float(proj.longitude) if proj.longitude else None
            except (AttributeError, TypeError):
                continue

            if not lat or not lng or lat == 0 or lng == 0:
                continue

            # Get deployed personnel for this project
            deployed_personnel = []
            for person in proj.personnel:
                if person.is_deployed and person.start_date and person.end_date:
                    deployed_personnel.append({
                        'id': person.id,
                        'name': person.name,
                        'role': person.role or '',
                        'startDate': person.start_date.isoformat() if person.start_date else '',
                        'endDate': person.end_date.isoformat() if person.end_date else ''
                    })

            # 프로젝트 타입에 따른 카테고리 분류
            if proj.project_type == 'consulting':
                category = 'Consulting'
            elif proj.project_type in ('oda_bilateral', 'oda_multilateral'):
                category = 'ODA'
            elif proj.project_type == 'k_rice_belt':
                category = 'K-Rice Belt'
            elif proj.project_type == 'investment':
                category = 'Investment'
            else:
                category = 'Other'

            gis_project = {
                '__id': f'PROJECT-{proj.id}',
                'source': 'project',
                'name': proj.country,
                'latitude': lat,
                'longitude': lng,
                'lat': lat,
                'lng': lng,
                'title': proj.title,
                'description': proj.title,
                'category': category,
                'period': f"{proj.start_date or ''}-{proj.end_date or ''}",
                'budget': float(proj.budget_total) if proj.budget_total else 0,
                'continent': '',
                'type': proj.project_type or '',
                'status': proj.status,
                'client': '',
                'startDate': proj.start_date.isoformat() if proj.start_date else '',
                'endDate': proj.end_date.isoformat() if proj.end_date else '',
                'budgetTotal': float(proj.budget_total) if proj.budget_total else 0,
                'dispatchedPersonnel': deployed_personnel
            }
            gis_projects.append(gis_project)

    # Get consulting projects
    if include_consulting:
        from models import ConsultingProject
        consulting_query = ConsultingProject.query.filter(
            ConsultingProject.latitude.isnot(None),
            ConsultingProject.longitude.isnot(None),
            ConsultingProject.latitude != 0,
            ConsultingProject.longitude != 0
        )

        if country:
            consulting_query = consulting_query.filter(ConsultingProject.country == country)

        if status:
            consulting_query = consulting_query.filter(ConsultingProject.status == status)

        if search:
            consulting_query = consulting_query.filter(
                db.or_(
                    ConsultingProject.title_kr.ilike(f'%{search}%'),
                    ConsultingProject.title_en.ilike(f'%{search}%'),
                    ConsultingProject.country.ilike(f'%{search}%')
                )
            )

        consulting_projects = consulting_query.all()
        print(f"GIS API: 해외기술용역 프로젝트 {len(consulting_projects)}개 발견")

        # Transform consulting projects to GIS format
        for cp in consulting_projects:
            try:
                lat = float(cp.latitude) if cp.latitude else None
                lng = float(cp.longitude) if cp.longitude else None
            except (AttributeError, TypeError):
                continue

            if not lat or not lng or lat == 0 or lng == 0:
                continue

            # Get personnel information for this consulting project
            # Note: consulting_projects는 Project 테이블과 연결되어 있지 않으므로
            # project_id로 personnel을 조회할 수 없습니다
            # 대신 consulting_projects 테이블에 직접 연결된 personnel이 있다면 사용

            gis_project = {
                '__id': f'CONSULTING-{cp.id}',
                'source': 'consulting',
                'name': cp.country,
                'latitude': lat,
                'longitude': lng,
                'lat': lat,
                'lng': lng,
                'title': cp.title_kr,
                'titleEn': cp.title_en,
                'description': cp.title_kr,
                'category': 'Consulting',
                'period': f"{cp.start_date or ''}-{cp.end_date or ''}",
                'budget': float(cp.budget) if cp.budget else 0,
                'continent': '',
                'type': cp.project_type or '해외기술용역',
                'status': cp.status,
                'client': cp.client or '',
                'startDate': cp.start_date,
                'endDate': cp.end_date,
                'budgetTotal': float(cp.budget) if cp.budget else 0,
                'contractYear': cp.contract_year,
                'number': cp.number,
                'dispatchedPersonnel': []  # 파견자 정보 (추후 추가)
            }
            gis_projects.append(gis_project)
    
    # Get ODA projects
    if include_oda:
        from models import OdaProject
        oda_query = OdaProject.query.filter(
            OdaProject.latitude.isnot(None),
            OdaProject.longitude.isnot(None),
            OdaProject.latitude != 0,
            OdaProject.longitude != 0
        )

        if country:
            oda_query = oda_query.filter(OdaProject.country == country)

        if search:
            oda_query = oda_query.filter(
                db.or_(
                    OdaProject.title.ilike(f'%{search}%'),
                    OdaProject.country.ilike(f'%{search}%')
                )
            )

        oda_projects = oda_query.all()
        print(f"GIS API: ODA 프로젝트 {len(oda_projects)}개 발견")

        # Transform ODA projects to GIS format
        for oda in oda_projects:
            try:
                lat = float(oda.latitude) if oda.latitude else None
                lng = float(oda.longitude) if oda.longitude else None
            except (AttributeError, TypeError):
                continue

            if not lat or not lng or lat == 0 or lng == 0:
                continue

            gis_project = {
                '__id': f'ODA-{oda.id}',
                'source': 'oda',
                'name': oda.country,
                'latitude': lat,
                'longitude': lng,
                'lat': lat,
                'lng': lng,
                'title': oda.title,
                'description': oda.title,
                'category': 'ODA',
                'period': oda.period or '',
                'budget': float(oda.budget) if oda.budget else 0,
                'continent': oda.continent or '',
                'type': oda.project_type or '양자무상',
                'status': oda.status or '진행중',
                'client': '',
                'startDate': '',
                'endDate': '',
                'budgetTotal': float(oda.budget) if oda.budget else 0,
                'number': oda.number
            }
            gis_projects.append(gis_project)

    # Get Offices (해외사무소)
    if include_offices:
        office_query = Office.query.filter(
            Office.latitude.isnot(None),
            Office.longitude.isnot(None),
            Office.latitude != 0,
            Office.longitude != 0
        )

        if country:
            office_query = office_query.filter(Office.country == country)

        if search:
            office_query = office_query.filter(
                db.or_(
                    Office.name.ilike(f'%{search}%'),
                    Office.country.ilike(f'%{search}%'),
                    Office.city.ilike(f'%{search}%')
                )
            )

        offices = office_query.all()
        print(f"GIS API: 해외사무소 {len(offices)}개 발견")

        # Transform offices to GIS format
        for office in offices:
            try:
                lat = float(office.latitude) if office.latitude else None
                lng = float(office.longitude) if office.longitude else None
            except (AttributeError, TypeError):
                continue

            if not lat or not lng or lat == 0 or lng == 0:
                continue

            # Format dispatched personnel for office
            dispatched_personnel = []
            if office.contact_person:
                dispatched_personnel.append({
                    'id': f'office-{office.id}',
                    'name': office.contact_person,
                    'role': '사무소장',
                    'startDate': office.dispatch_start_date.isoformat() if office.dispatch_start_date else '',
                    'endDate': office.dispatch_end_date.isoformat() if office.dispatch_end_date else ''
                })

            gis_office = {
                '__id': f'OFFICE-{office.id}',
                'source': 'office',
                'name': office.country,
                'latitude': lat,
                'longitude': lng,
                'lat': lat,
                'lng': lng,
                'title': office.name,
                'description': f"{office.name} ({office.city or office.country})",
                'category': 'Office',
                'period': '',
                'budget': 0,
                'continent': '',
                'type': office.office_type or '해외사무소',
                'officeType': office.office_type or '해외사무소',
                'status': office.status or '파견중',
                'client': '',
                'address': office.address or '',
                'city': office.city or '',
                'contactPerson': office.contact_person or '',
                'contactEmail': office.contact_email or '',
                'contactPhone': office.contact_phone or '',
                'establishedDate': office.established_date.strftime('%Y-%m-%d') if office.established_date else '',
                'dispatchedPersonnel': dispatched_personnel
            }
            gis_projects.append(gis_office)

    print(f"GIS API: 총 {len(gis_projects)}개의 프로젝트를 반환합니다.")
    print(f"  - Projects: {len([p for p in gis_projects if p.get('source') == 'project'])}개")
    print(f"  - Consulting: {len([p for p in gis_projects if p.get('source') == 'consulting'])}개")
    print(f"  - ODA: {len([p for p in gis_projects if p.get('source') == 'oda'])}개")
    print(f"  - Office: {len([p for p in gis_projects if p['category'] == 'Office'])}개")
    print(f"  - 파견자 정보 포함: {len([p for p in gis_projects if p.get('dispatchedPersonnel') and len(p.get('dispatchedPersonnel')) > 0])}개")

    return jsonify({
        'success': True,
        'data': gis_projects,
        'count': len(gis_projects)
    })


@gis_bp.route('/stats', methods=['GET'])
# @token_required  # 임시로 인증 비활성화 (개발용)
def get_gis_stats():
    """Get GIS statistics for map (consulting_projects and oda_projects only)"""
    # Count consulting projects
    consulting_projects_count = ConsultingProject.query.filter(
        ConsultingProject.latitude.isnot(None),
        ConsultingProject.longitude.isnot(None),
        ConsultingProject.latitude != 0,
        ConsultingProject.longitude != 0
    ).count()
    
    # Count ODA projects
    from models import OdaProject
    oda_count = OdaProject.query.filter(
        OdaProject.latitude.isnot(None),
        OdaProject.longitude.isnot(None),
        OdaProject.latitude != 0,
        OdaProject.longitude != 0
    ).count()

    # Count by country from consulting projects
    consulting_country_stats = db.session.query(
        ConsultingProject.country,
        db.func.count(ConsultingProject.id)
    ).filter(
        ConsultingProject.latitude.isnot(None),
        ConsultingProject.longitude.isnot(None),
        ConsultingProject.latitude != 0,
        ConsultingProject.longitude != 0
    ).group_by(ConsultingProject.country).all()
    
    # Count by country from ODA projects
    oda_country_stats = db.session.query(
        OdaProject.country,
        db.func.count(OdaProject.id)
    ).filter(
        OdaProject.latitude.isnot(None),
        OdaProject.longitude.isnot(None),
        OdaProject.latitude != 0,
        OdaProject.longitude != 0
    ).group_by(OdaProject.country).all()

    # Merge country statistics
    country_dict = {}
    for country, count in consulting_country_stats:
        country_dict[country] = country_dict.get(country, 0) + count
    for country, count in oda_country_stats:
        country_dict[country] = country_dict.get(country, 0) + count

    return jsonify({
        'success': True,
        'data': {
            'consulting': consulting_projects_count,
            'oda': oda_count,
            'total': consulting_projects_count + oda_count,
            'consultingProjects': consulting_projects_count,
            'byCountry': country_dict
        }
    })


@gis_bp.route('/projects/<int:project_id>/location', methods=['PUT'])
# @token_required  # 임시로 인증 비활성화 (개발용)
def update_project_location(project_id):
    """Update project location coordinates"""
    project = Project.query.get_or_404(project_id)
    data = request.get_json()
    
    if 'latitude' in data:
        project.latitude = data['latitude']
    if 'longitude' in data:
        project.longitude = data['longitude']
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '위치 정보가 업데이트되었습니다.',
        'data': {
            'latitude': float(project.latitude) if project.latitude else None,
            'longitude': float(project.longitude) if project.longitude else None
        }
    })


