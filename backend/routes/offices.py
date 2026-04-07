"""
GBMS - Offices Routes
글로벌사업처 해외사업관리시스템 - 해외사무소관리 API
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Office, ActivityLog
from routes.auth import token_required

offices_bp = Blueprint('offices', __name__)


@offices_bp.route('', methods=['GET'])
@token_required
def get_offices(current_user):
    """Get all offices"""
    status = request.args.get('status')
    office_type = request.args.get('type')
    region = request.args.get('region')
    
    query = Office.query
    
    if status:
        query = query.filter(Office.status == status)
    
    if office_type:
        query = query.filter(Office.office_type == office_type)
    
    if region:
        query = query.filter(Office.region == region)
    
    offices = query.order_by(Office.name).all()
    
    return jsonify({
        'success': True,
        'data': [o.to_dict() for o in offices]
    })


@offices_bp.route('/<int:office_id>', methods=['GET'])
@token_required
def get_office(current_user, office_id):
    """Get single office by ID"""
    office = Office.query.get_or_404(office_id)
    
    return jsonify({
        'success': True,
        'data': office.to_dict()
    })


@offices_bp.route('', methods=['POST'])
@token_required
def create_office(current_user):
    """Create new office"""
    data = request.get_json()
    
    if not data.get('name') or not data.get('country'):
        return jsonify({'success': False, 'message': '사무소명과 국가는 필수입니다.'}), 400
    
    office = Office(
        name=data['name'],
        country=data['country'],
        country_code=data.get('countryCode'),
        region=data.get('region'),
        city=data.get('city'),
        address=data.get('address'),
        office_type=data.get('officeType', 'regular'),
        status=data.get('status', 'active'),
        contact_person=data.get('contactPerson'),
        contact_email=data.get('contactEmail'),
        contact_phone=data.get('contactPhone'),
        established_date=datetime.strptime(data['establishedDate'], '%Y-%m-%d').date() if data.get('establishedDate') else None,
        annual_budget=data.get('annualBudget'),
        dispatch_start_date=datetime.strptime(data['dispatchStartDate'], '%Y-%m-%d').date() if data.get('dispatchStartDate') else None,
        dispatch_end_date=datetime.strptime(data['dispatchEndDate'], '%Y-%m-%d').date() if data.get('dispatchEndDate') else None,
        latitude=data.get('latitude'),
        longitude=data.get('longitude')
    )
    
    db.session.add(office)
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='create',
        entity_type='office',
        entity_id=office.id,
        description=f'해외사무소 등록: {office.name}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '해외사무소가 등록되었습니다.',
        'data': office.to_dict()
    }), 201


@offices_bp.route('/<int:office_id>', methods=['PUT'])
@token_required
def update_office(current_user, office_id):
    """Update office"""
    office = Office.query.get_or_404(office_id)
    data = request.get_json()

    if 'name' in data:
        office.name = data['name']
    if 'country' in data:
        office.country = data['country']
    if 'countryCode' in data:
        office.country_code = data['countryCode']
    if 'region' in data:
        office.region = data['region']
    if 'city' in data:
        office.city = data['city']
    if 'address' in data:
        office.address = data['address']
    if 'officeType' in data:
        office.office_type = data['officeType']
    if 'status' in data:
        office.status = data['status']
    if 'contactPerson' in data:
        office.contact_person = data['contactPerson']
    if 'contactEmail' in data:
        office.contact_email = data['contactEmail']
    if 'contactPhone' in data:
        office.contact_phone = data['contactPhone']
    if 'establishedDate' in data:
        office.established_date = datetime.strptime(data['establishedDate'], '%Y-%m-%d').date() if data['establishedDate'] else None
    if 'annualBudget' in data:
        office.annual_budget = data['annualBudget']
    if 'dispatchStartDate' in data:
        office.dispatch_start_date = datetime.strptime(data['dispatchStartDate'], '%Y-%m-%d').date() if data['dispatchStartDate'] else None
    if 'dispatchEndDate' in data:
        office.dispatch_end_date = datetime.strptime(data['dispatchEndDate'], '%Y-%m-%d').date() if data['dispatchEndDate'] else None
    if 'latitude' in data:
        office.latitude = data['latitude']
    if 'longitude' in data:
        office.longitude = data['longitude']

    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='update',
        entity_type='office',
        entity_id=office.id,
        description=f'해외사무소 수정: {office.name}',
        ip_address=request.remote_addr
    )
    db.session.add(log)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': '해외사무소 정보가 수정되었습니다.',
        'data': office.to_dict()
    })


@offices_bp.route('/<int:office_id>', methods=['DELETE'])
@token_required
def delete_office(current_user, office_id):
    """Delete office"""
    office = Office.query.get_or_404(office_id)
    
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': '삭제 권한이 없습니다.'}), 403
    
    db.session.delete(office)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '해외사무소가 삭제되었습니다.'
    })
