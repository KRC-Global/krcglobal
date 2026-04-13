"""
GBMS - Users Routes
글로벌사업처 해외사업관리시스템 - 사용자관리 API
"""
from flask import Blueprint, request, jsonify
from models import db, User, ActivityLog
from routes.auth import token_required, admin_required

users_bp = Blueprint('users', __name__)


@users_bp.route('', methods=['GET'])
@token_required
def get_users(current_user):
    """Get all users"""
    department = request.args.get('department')
    is_active = request.args.get('is_active', type=bool)
    
    query = User.query
    
    if department:
        query = query.filter(User.department == department)
    
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    
    users = query.order_by(User.name).all()
    
    return jsonify({
        'success': True,
        'data': [u.to_dict() for u in users]
    })


@users_bp.route('/<int:user_id>', methods=['GET'])
@token_required
def get_user(current_user, user_id):
    """Get single user by ID"""
    user = User.query.get_or_404(user_id)
    
    return jsonify({
        'success': True,
        'data': user.to_dict()
    })


@users_bp.route('', methods=['POST'])
@admin_required
def create_user(current_user):
    """Create new user (admin only)"""
    data = request.get_json()
    
    required_fields = ['userId', 'name', 'department', 'password']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'success': False, 'message': f'{field} 필드는 필수입니다.'}), 400
    
    # Check for duplicate user_id
    if User.query.filter_by(user_id=data['userId']).first():
        return jsonify({'success': False, 'message': '이미 존재하는 사번/아이디입니다.'}), 400
    
    user = User(
        user_id=data['userId'],
        name=data['name'],
        department=data['department'],
        role=data.get('role', 'user'),
        permission_scope=data.get('permissionScope', 'readonly'),
        phone=data.get('phone'),
        position=data.get('position'),
        is_active=data.get('isActive', True)
    )
    user.set_password(data['password'])
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '사용자가 등록되었습니다.',
        'data': user.to_dict()
    }), 201


@users_bp.route('/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(current_user, user_id):
    """Update user (admin only)"""
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    if 'name' in data:
        user.name = data['name']
    if 'department' in data:
        user.department = data['department']
    if 'role' in data:
        user.role = data['role']
    if 'permissionScope' in data:
        valid_scopes = ['pending', 'readonly', 'overseas_tech', 'expansion', 'oda', 'methane', 'all']
        if data['permissionScope'] in valid_scopes:
            user.permission_scope = data['permissionScope']
    if 'phone' in data:
        user.phone = data['phone']
    if 'position' in data:
        user.position = data['position']
    if 'isActive' in data:
        user.is_active = data['isActive']
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '사용자 정보가 수정되었습니다.',
        'data': user.to_dict()
    })


@users_bp.route('/<int:user_id>/approve', methods=['PUT'])
@admin_required
def approve_user(current_user, user_id):
    """Approve pending user (admin only)"""
    user = User.query.get_or_404(user_id)
    data = request.get_json() or {}

    # 권한 지정 (기본: readonly)
    new_scope = data.get('permissionScope', 'readonly')
    valid_scopes = ['readonly', 'overseas_tech', 'expansion', 'oda', 'methane', 'all']
    if new_scope not in valid_scopes:
        new_scope = 'readonly'

    user.permission_scope = new_scope
    if new_scope == 'all':
        user.role = 'admin'

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'{user.name}님이 승인되었습니다.',
        'data': user.to_dict()
    })


@users_bp.route('/<int:user_id>/password', methods=['PUT'])
@admin_required
def reset_password(current_user, user_id):
    """Reset user password (admin only)"""
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    if not data.get('newPassword'):
        return jsonify({'success': False, 'message': '새 비밀번호를 입력해주세요.'}), 400
    
    user.set_password(data['newPassword'])
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '비밀번호가 초기화되었습니다.'
    })


@users_bp.route('/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(current_user, user_id):
    """Delete user (admin only)"""
    user = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': '자기 자신은 삭제할 수 없습니다.'}), 400
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '사용자가 삭제되었습니다.'
    })


@users_bp.route('/upload', methods=['POST'])
@admin_required
def upload_users(current_user):
    """Excel 파일을 통한 사용자 일괄 등록"""
    import pandas as pd
    from werkzeug.utils import secure_filename

    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'message': '파일이 전송되지 않았습니다.'
        }), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({
            'success': False,
            'message': '파일이 선택되지 않았습니다.'
        }), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({
            'success': False,
            'message': 'Excel 파일(.xlsx, .xls)만 업로드 가능합니다.'
        }), 400

    try:
        # Excel 파일 읽기 (헤더 행 자동 감지)
        df = pd.read_excel(file, header=0)

        # 첫 번째 행에 필수 컬럼이 없으면 두 번째 행을 헤더로 시도
        if 'username' not in df.columns and 'user_id' not in df.columns:
            file.seek(0)  # 파일 포인터 리셋
            df = pd.read_excel(file, header=1)

        # 그래도 없으면 세 번째 행 시도
        if 'username' not in df.columns and 'user_id' not in df.columns:
            file.seek(0)
            df = pd.read_excel(file, header=2)

        # 필수 컬럼 확인 (username 또는 user_id 허용)
        if 'username' not in df.columns and 'user_id' not in df.columns:
            return jsonify({
                'success': False,
                'message': '필수 컬럼이 없습니다: username (또는 user_id)'
            }), 400

        if 'name' not in df.columns:
            return jsonify({
                'success': False,
                'message': '필수 컬럼이 없습니다: name'
            }), 400

        if 'department' not in df.columns:
            return jsonify({
                'success': False,
                'message': '필수 컬럼이 없습니다: department'
            }), 400

        # username 또는 user_id 컬럼명 결정
        user_id_col = 'username' if 'username' in df.columns else 'user_id'

        imported_count = 0
        skipped_count = 0
        errors = []

        for idx, row in df.iterrows():
            try:
                # #으로 시작하는 행은 주석으로 처리 (건너뛰기)
                first_val = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ''
                if first_val.startswith('#'):
                    continue

                # 필수 필드 검증
                if pd.isna(row.get(user_id_col)) or pd.isna(row.get('name')) or pd.isna(row.get('department')):
                    errors.append(f'행 {idx + 2}: 필수 필드({user_id_col}, name, department) 누락')
                    skipped_count += 1
                    continue

                user_id = str(row[user_id_col]).strip()
                name = str(row['name']).strip()
                department_raw = str(row['department']).strip()

                # 부서명 → 코드 매핑
                department_mapping = {
                    '글로벌사업처': 'gb',
                    '글로벌농업개발부': 'gad',
                    '농식품국제개발협력센터': 'aidc',
                    'gad': 'gad',
                    'gb': 'gb',
                    'aidc': 'aidc'
                }
                department = department_mapping.get(department_raw, department_raw)

                # 중복 체크 - user_id 필드 사용
                existing = User.query.filter_by(user_id=user_id).first()
                if existing:
                    errors.append(f'행 {idx + 2}: 이미 존재하는 사용자 ID - {user_id}')
                    skipped_count += 1
                    continue

                # permission_scope 처리
                permission_scope = 'readonly'  # 기본값
                if pd.notna(row.get('permission_scope')):
                    scope_value = str(row['permission_scope']).strip()
                    # 한글 → 영문 매핑 (대소문자 구분 없이)
                    scope_mapping = {
                        '조회만': 'readonly',
                        'readonly': 'readonly',
                        '해외기술용역': 'overseas_tech',
                        'overseas_tech': 'overseas_tech',
                        '해외진출지원사업': 'expansion',
                        'expansion': 'expansion',
                        '국제협력사업': 'oda',
                        'oda': 'oda',
                        '메탄감축사업': 'methane',
                        'methane': 'methane',
                        '전체': 'all',
                        'all': 'all'
                    }
                    permission_scope = scope_mapping.get(scope_value.lower(), scope_mapping.get(scope_value, 'readonly'))

                # role 처리
                role = 'user'  # 기본값
                if pd.notna(row.get('role')):
                    role_value = str(row['role']).strip().lower()
                    if role_value in ['admin', '관리자']:
                        role = 'admin'
                    elif role_value in ['manager', '매니저']:
                        role = 'manager'
                    else:
                        role = 'user'

                # is_active 처리
                is_active = True  # 기본값
                if pd.notna(row.get('is_active')):
                    active_val = row['is_active']
                    if isinstance(active_val, bool):
                        is_active = active_val
                    elif isinstance(active_val, str):
                        is_active = active_val.lower() in ['true', '1', 'yes', '활성', 'y']
                    else:
                        is_active = bool(active_val)

                # 사용자 생성 - user_id 필드 사용
                user = User(
                    user_id=user_id,
                    name=name,
                    department=department,
                    phone=str(row['phone']).strip() if pd.notna(row.get('phone')) else None,
                    position=str(row['position']).strip() if pd.notna(row.get('position')) else None,
                    role=role,
                    permission_scope=permission_scope,
                    is_active=is_active
                )

                # 기본 비밀번호 설정 (user_id와 동일)
                user.set_password(user_id)

                db.session.add(user)
                imported_count += 1

            except Exception as e:
                errors.append(f'행 {idx + 2}: {str(e)}')
                skipped_count += 1
                continue

        # 데이터베이스에 커밋
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'업로드가 완료되었습니다. (성공: {imported_count}개, 실패: {skipped_count}개)',
            'data': {
                'imported': imported_count,
                'skipped': skipped_count,
                'total': imported_count + skipped_count,
                'errors': errors[:10]  # 최대 10개의 에러만 반환
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        import traceback
        error_detail = traceback.format_exc()
        print(f"Upload error: {error_detail}")
        return jsonify({
            'success': False,
            'message': f'업로드 중 오류가 발생했습니다: {str(e)}'
        }), 500

