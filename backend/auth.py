"""
GBMS - Authentication Routes
글로벌사업처 해외사업관리시스템
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import jwt
import re
from functools import wraps
from models import db, User, ActivityLog, AccessLog

auth_bp = Blueprint('auth', __name__)


def validate_password_strength(password):
    """
    국정원 권고 비밀번호 정책 검증
    - 최소 10자 이상
    - 대문자 1개 이상
    - 소문자 1개 이상
    - 숫자 1개 이상
    - 특수문자 1개 이상
    """
    if len(password) < 10:
        return False, '비밀번호는 10자 이상이어야 합니다.'

    if not re.search(r'[A-Z]', password):
        return False, '대문자를 1개 이상 포함해야 합니다.'

    if not re.search(r'[a-z]', password):
        return False, '소문자를 1개 이상 포함해야 합니다.'

    if not re.search(r'\d', password):
        return False, '숫자를 1개 이상 포함해야 합니다.'

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, '특수문자(!@#$%^&*(),.?":{}|<>)를 1개 이상 포함해야 합니다.'

    return True, ''


def get_secret_key():
    from flask import current_app
    return current_app.config['JWT_SECRET_KEY']


def verify_token(token):
    """토큰을 검증하고 사용자 객체 반환"""
    if not token:
        return None

    try:
        data = jwt.decode(token, get_secret_key(), algorithms=['HS256'])

        # Check if guest user
        if data.get('user_id') == 'guest':
            # Create a guest user object
            class GuestUser:
                id = 'guest'
                user_id = 'guest'
                name = '일반직원'
                role = 'guest'
                department = '조회 전용'
                is_active = True

                def to_dict(self):
                    return {
                        'id': self.id,
                        'userId': self.user_id,
                        'name': self.name,
                        'role': self.role,
                        'department': self.department,
                        'isActive': self.is_active
                    }

            return GuestUser()
        else:
            current_user = User.query.get(data['user_id'])

            if not current_user:
                return None

            if not current_user.is_active:
                return None

            return current_user

    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def token_required(f):
    """JWT token verification decorator"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'message': '유효하지 않은 토큰 형식입니다.'}), 401

        if not token:
            return jsonify({'message': '인증 토큰이 필요합니다.'}), 401

        current_user = verify_token(token)

        if not current_user:
            return jsonify({'message': '유효하지 않은 토큰입니다.'}), 401

        return f(current_user, *args, **kwargs)

    return decorated


def admin_required(f):
    """Admin role verification decorator"""
    @wraps(f)
    @token_required
    def decorated(current_user, *args, **kwargs):
        if current_user.role != 'admin':
            return jsonify({'message': '관리자 권한이 필요합니다.'}), 403
        return f(current_user, *args, **kwargs)

    return decorated


def permission_required(required_scope):
    """Permission scope verification decorator"""
    def decorator(f):
        @wraps(f)
        @token_required
        def decorated(current_user, *args, **kwargs):
            # 관리자는 모든 권한
            if current_user.role == 'admin':
                return f(current_user, *args, **kwargs)

            # permission_scope 확인
            user_scope = getattr(current_user, 'permission_scope', 'readonly')

            # all 권한은 모든 접근 가능
            if user_scope == 'all':
                return f(current_user, *args, **kwargs)

            # 요청된 scope와 사용자 scope가 일치하는지 확인
            if user_scope != required_scope:
                return jsonify({
                    'success': False,
                    'message': '이 메뉴에 대한 접근 권한이 없습니다.'
                }), 403

            return f(current_user, *args, **kwargs)

        return decorated
    return decorator


@auth_bp.route('/login', methods=['POST'])
def login():
    """User login"""
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'message': '요청 데이터가 없습니다.'}), 400
    
    user_id = data.get('userId')
    password = data.get('password')
    
    if not user_id or not password:
        return jsonify({'success': False, 'message': '아이디와 비밀번호를 입력해주세요.'}), 400
    
    user = User.query.filter_by(user_id=user_id).first()

    # 로그인 실패 시 접속 로그 기록
    if not user or not user.check_password(password):
        access_log = AccessLog(
            user_id=user.id if user else None,
            username=user_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            action='login_failed',
            success=False,
            message='아이디 또는 비밀번호 불일치'
        )
        db.session.add(access_log)
        db.session.commit()
        return jsonify({'success': False, 'message': '아이디 또는 비밀번호가 올바르지 않습니다.'}), 401

    if not user.is_active:
        access_log = AccessLog(
            user_id=user.id,
            username=user_id,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            action='login_failed',
            success=False,
            message='비활성화된 계정'
        )
        db.session.add(access_log)
        db.session.commit()
        return jsonify({'success': False, 'message': '비활성화된 계정입니다. 관리자에게 문의하세요.'}), 401
    
    # Generate JWT token
    from flask import current_app
    token_expires = current_app.config['JWT_ACCESS_TOKEN_EXPIRES']
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + token_expires
    }, get_secret_key(), algorithm='HS256')
    
    # Update last login
    user.last_login = datetime.utcnow()

    # 접속 로그 기록 (성공)
    access_log = AccessLog(
        user_id=user.id,
        username=user_id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:500],
        action='login',
        success=True,
        message='로그인 성공'
    )
    db.session.add(access_log)

    # Log activity
    log = ActivityLog(
        user_id=user.id,
        action='login',
        entity_type='user',
        entity_id=user.id,
        description=f'{user.name}님이 로그인했습니다.',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'token': token,
        'user': user.to_dict()
    })


@auth_bp.route('/guest-login', methods=['POST'])
def guest_login():
    """Guest login (read-only access)"""
    # Generate guest token
    from flask import current_app
    token_expires = current_app.config['JWT_ACCESS_TOKEN_EXPIRES']

    token = jwt.encode({
        'user_id': 'guest',
        'role': 'guest',
        'exp': datetime.utcnow() + token_expires
    }, get_secret_key(), algorithm='HS256')

    # Log activity
    log = ActivityLog(
        user_id=None,
        action='guest_login',
        entity_type='guest',
        description='게스트가 로그인했습니다.',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': 'guest',
            'userId': 'guest',
            'name': '일반직원',
            'role': 'guest',
            'department': '조회 전용',
            'isActive': True
        }
    })


@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    """User logout"""
    # Log activity
    log = ActivityLog(
        user_id=current_user.id if hasattr(current_user, 'id') else None,
        action='logout',
        entity_type='user',
        entity_id=current_user.id if hasattr(current_user, 'id') else None,
        description=f'{current_user.name if hasattr(current_user, "name") else "게스트"}님이 로그아웃했습니다.',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '로그아웃되었습니다.'})


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    """Get current user info"""
    return jsonify({
        'success': True,
        'user': current_user.to_dict()
    })


@auth_bp.route('/change-password', methods=['POST'])
@token_required
def change_password(current_user):
    """Change password"""
    data = request.get_json()
    
    current_password = data.get('currentPassword')
    new_password = data.get('newPassword')
    
    if not current_password or not new_password:
        return jsonify({'success': False, 'message': '현재 비밀번호와 새 비밀번호를 입력해주세요.'}), 400
    
    if not current_user.check_password(current_password):
        return jsonify({'success': False, 'message': '현재 비밀번호가 올바르지 않습니다.'}), 400

    # 강화된 비밀번호 정책 검증
    is_valid, error_message = validate_password_strength(new_password)
    if not is_valid:
        return jsonify({'success': False, 'message': error_message}), 400

    current_user.set_password(new_password)

    # 비밀번호 변경 로그
    log = ActivityLog(
        user_id=current_user.id,
        action='password_change',
        entity_type='user',
        entity_id=current_user.id,
        description=f'{current_user.name}님이 비밀번호를 변경했습니다.',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '비밀번호가 변경되었습니다.'})


@auth_bp.route('/access-logs', methods=['GET'])
@admin_required
def get_access_logs(current_user):
    """접속 로그 조회 (관리자 전용)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('perPage', 50, type=int)
    username = request.args.get('username', '')
    action = request.args.get('action', '')

    query = AccessLog.query

    # 필터 적용
    if username:
        query = query.filter(AccessLog.username.ilike(f'%{username}%'))
    if action:
        query = query.filter(AccessLog.action == action)

    # 최신 순으로 정렬
    query = query.order_by(AccessLog.created_at.desc())

    # 페이지네이션
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'success': True,
        'data': [log.to_dict() for log in pagination.items],
        'total': pagination.total,
        'currentPage': page,
        'pages': pagination.pages,
        'perPage': per_page
    })
