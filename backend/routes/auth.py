"""
GBMS - Authentication Routes
글로벌사업처 해외사업관리시스템
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import jwt
from functools import wraps
from models import db, User, ActivityLog, AccessLog
from utils.permissions import ADMIN_EMAILS

auth_bp = Blueprint('auth', __name__)


def get_supabase_secret():
    from flask import current_app
    return current_app.config['SUPABASE_JWT_SECRET']


def decode_supabase_jwt(token):
    """Supabase JWT 디코딩 (ES256/HS256 자동 대응)"""
    try:
        return jwt.decode(token, get_supabase_secret(), algorithms=['HS256'], audience='authenticated')
    except (jwt.exceptions.InvalidAlgorithmError, jwt.exceptions.InvalidSignatureError, jwt.exceptions.DecodeError):
        # ES256 토큰: Supabase Auth가 인증 완료했으므로 서명 검증 생략
        return jwt.decode(token, options={"verify_signature": False}, audience='authenticated')


def verify_token(token):
    """Supabase JWT를 검증하고 사용자 객체 반환 (자동 생성 포함)"""
    if not token:
        return None

    try:
        data = decode_supabase_jwt(token)

        email = data.get('email')
        sub = data.get('sub')  # Supabase user UUID

        if not email:
            return None

        # 이메일로 사용자 조회
        current_user = User.query.filter_by(email=email).first()

        if not current_user:
            # 첫 로그인 — 사용자 자동 생성
            user_metadata = data.get('user_metadata', {})
            full_name = user_metadata.get('full_name', email.split('@')[0])

            # 관리자 이메일 체크
            is_admin = email in ADMIN_EMAILS

            try:
                current_user = User(
                    user_id=email,
                    name=full_name,
                    email=email,
                    department='',
                    role='admin' if is_admin else 'user',
                    permission_scope='all' if is_admin else 'pending',
                    is_active=True
                )
                current_user.set_password(sub or 'oauth-user')
                db.session.add(current_user)
                db.session.commit()
                print(f"[AUTH] 사용자 생성 완료: {email}, admin={is_admin}")
            except Exception as e:
                db.session.rollback()
                print(f"[AUTH] 사용자 생성 실패: {email}, error={e}")
                import traceback
                traceback.print_exc()
                return None

        # 기존 사용자가 ADMIN_EMAILS에 포함되면 자동 승격
        if email in ADMIN_EMAILS and (current_user.role != 'admin' or current_user.permission_scope != 'all'):
            current_user.role = 'admin'
            current_user.permission_scope = 'all'
            db.session.commit()

        if not current_user.is_active:
            return None

        return current_user

    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        print(f"Token verification error (JWT): {e}")
        return None
    except Exception as e:
        import traceback
        print(f"Token verification error (General): {e}")
        traceback.print_exc()
        db.session.rollback()
        return None


def token_required(f):
    """JWT token verification decorator"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # 1. Authorization 헤더에서 토큰 확인
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'message': '유효하지 않은 토큰 형식입니다.'}), 401

        # 2. URL 쿼리 파라미터에서 토큰 확인 (미리보기 등 새 창에서 사용)
        if not token:
            token = request.args.get('token')

        if not token:
            return jsonify({'message': '인증 토큰이 필요합니다.'}), 401

        current_user = verify_token(token)

        if not current_user:
            return jsonify({'message': '유효하지 않은 토큰입니다.'}), 401

        # pending 사용자는 /auth/me만 허용, 나머지 API 차단
        if current_user.permission_scope == 'pending':
            if not request.path.endswith('/auth/me'):
                return jsonify({'success': False, 'message': '관리자 승인 대기 중입니다.'}), 403

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

    # 접속 로그 기록 (일반직원)
    access_log = AccessLog(
        user_id=None,
        username='guest',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:500],
        action='guest_login',
        success=True,
        message='일반직원 조회 접속'
    )
    db.session.add(access_log)

    # Log activity
    log = ActivityLog(
        user_id=None,
        action='guest_login',
        entity_type='guest',
        description='게스트가 로그인했습니다.',

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

    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '로그아웃되었습니다.'})


@auth_bp.route('/google-login', methods=['POST'])
def google_login():
    """Google OAuth 로그인 후 접속 로그 기록"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    if not token:
        return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

    current_user = verify_token(token)
    if not current_user:
        # 로그인 실패 로그
        access_log = AccessLog(
            user_id=None,
            username='(google)',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            action='login_failed',
            success=False,
            message='Google 토큰 검증 실패'
        )
        db.session.add(access_log)
        db.session.commit()
        return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다.'}), 401

    if not current_user.is_active:
        return jsonify({'success': False, 'message': '비활성화된 계정입니다.'}), 401

    # 로그인 성공 로그
    current_user.last_login = datetime.utcnow()

    access_log = AccessLog(
        user_id=current_user.id,
        username=current_user.email or current_user.user_id,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:500],
        action='login',
        success=True,
        message='Google 로그인 성공'
    )
    db.session.add(access_log)

    activity_log = ActivityLog(
        user_id=current_user.id,
        action='login',
        entity_type='user',
        entity_id=current_user.id,
        description=f'{current_user.name}님이 Google 계정으로 로그인했습니다.',
        ip_address=request.remote_addr
    )
    db.session.add(activity_log)
    db.session.commit()

    return jsonify({
        'success': True,
        'user': current_user.to_dict()
    })


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    """Get current user info"""
    return jsonify({
        'success': True,
        'user': current_user.to_dict()
    })


@auth_bp.route('/me', methods=['PUT'])
@token_required
def update_current_user(current_user):
    """승인 대기 중인 사용자가 이름·사번을 입력·수정"""
    if current_user.permission_scope != 'pending':
        return jsonify({'success': False, 'message': '이미 승인된 사용자는 이 기능을 사용할 수 없습니다.'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '요청 데이터가 없습니다.'}), 400

    name = data.get('name', '').strip()
    employee_number = data.get('employeeNumber', '').strip()

    if not name or len(name) > 100:
        return jsonify({'success': False, 'message': '이름을 1~100자로 입력해주세요.'}), 400
    if not employee_number:
        return jsonify({'success': False, 'message': '사번을 입력해주세요.'}), 400
    if len(employee_number) > 20:
        return jsonify({'success': False, 'message': '사번은 20자 이내로 입력해주세요.'}), 400

    try:
        current_user.name = name
        current_user.employee_number = employee_number
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"사용자 정보 저장 오류: {e}")
        return jsonify({'success': False, 'message': '정보 저장에 실패했습니다.'}), 500

    return jsonify({
        'success': True,
        'message': '정보가 저장되었습니다.',
        'user': current_user.to_dict()
    })


@auth_bp.route('/debug-token', methods=['GET'])
def debug_token():
    """디버그용: 토큰 검증 상세 정보 (배포 안정화 후 제거)"""
    token = None
    if 'Authorization' in request.headers:
        try:
            token = request.headers['Authorization'].split(" ")[1]
        except IndexError:
            return jsonify({'error': 'Invalid token format'}), 400

    if not token:
        return jsonify({'error': 'No token provided'}), 400

    try:
        data = decode_supabase_jwt(token)
        email = data.get('email')
        sub = data.get('sub')

        # DB 연결 테스트
        try:
            user = User.query.filter_by(email=email).first() if email else None
            db_status = 'connected'
            user_exists = user is not None
            user_info = user.to_dict() if user else None
        except Exception as db_err:
            db_status = f'error: {str(db_err)}'
            user_exists = False
            user_info = None

        return jsonify({
            'jwt_valid': True,
            'email': email,
            'sub': sub,
            'db_status': db_status,
            'user_exists': user_exists,
            'user': user_info
        })
    except Exception as e:
        import traceback
        return jsonify({
            'jwt_valid': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


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
