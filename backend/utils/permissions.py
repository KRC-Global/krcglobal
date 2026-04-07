"""
GBMS - Permission Utilities
역할 기반 권한 관리 유틸리티
"""
from functools import wraps
from flask import jsonify


# 권한 범위 정의
PERMISSION_SCOPES = {
    'all': '전체',
    'overseas_tech': '해외기술용역',
    'expansion': '해외진출지원사업',
    'oda': '국제협력사업',
    'readonly': '조회만'
}


def permission_required(required_scope):
    """
    특정 권한이 필요한 API 엔드포인트에 사용하는 데코레이터
    
    Usage:
        @permission_required('overseas_tech')
        def update_project(current_user, project_id):
            ...
    
    Note: token_required 데코레이터와 함께 사용해야 함
    """
    def decorator(f):
        @wraps(f)
        def decorated(current_user, *args, **kwargs):
            # admin 역할이면 모든 권한 허용
            if current_user.role == 'admin':
                return f(current_user, *args, **kwargs)
            
            # permission_scope가 'all'이면 모든 권한 허용
            user_scope = getattr(current_user, 'permission_scope', 'readonly')
            if user_scope == 'all':
                return f(current_user, *args, **kwargs)
            
            # 요청된 권한과 사용자 권한 비교
            if user_scope == required_scope:
                return f(current_user, *args, **kwargs)
            
            # 권한 없음
            return jsonify({
                'success': False,
                'message': '이 작업에 대한 권한이 없습니다.',
                'requiredScope': required_scope,
                'userScope': user_scope
            }), 403
        
        return decorated
    return decorator


def check_permission(current_user, required_scope):
    """
    사용자가 특정 권한을 가지고 있는지 확인하는 함수
    
    Args:
        current_user: User 객체
        required_scope: 필요한 권한 범위 ('overseas_tech', 'expansion', 'oda', 'all')
    
    Returns:
        bool: 권한 여부
    """
    # admin 역할이면 모든 권한 허용
    if current_user.role == 'admin':
        return True
    
    # permission_scope가 'all'이면 모든 권한 허용
    user_scope = getattr(current_user, 'permission_scope', 'readonly')
    if user_scope == 'all':
        return True
    
    # 요청된 권한과 사용자 권한 비교
    return user_scope == required_scope
