"""
GBMS - Banner Management Routes
글로벌사업처 해외사업관리시스템 - 배너 관리
"""
from flask import Blueprint, request, jsonify, send_file, current_app
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from models import db, Banner
from routes.auth import token_required, admin_required

banners_bp = Blueprint('banners', __name__)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@banners_bp.route('', methods=['GET'])
@token_required
def get_active_banners(current_user):
    """활성 배너 목록 조회 (순서대로)"""
    banners = Banner.query.filter_by(is_active=True).order_by(Banner.display_order).all()
    return jsonify({
        'success': True,
        'data': [b.to_dict() for b in banners]
    })


@banners_bp.route('/all', methods=['GET'])
@admin_required
def get_all_banners(current_user):
    """전체 배너 목록 조회 (관리자용, 비활성 포함)"""
    banners = Banner.query.order_by(Banner.display_order).all()
    return jsonify({
        'success': True,
        'data': [b.to_dict() for b in banners]
    })


@banners_bp.route('', methods=['POST'])
@admin_required
def create_banner(current_user):
    """배너 이미지 업로드"""
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': '이미지 파일이 필요합니다.'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다.'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'message': '허용되지 않는 파일 형식입니다. (jpg, jpeg, png, gif, webp)'}), 400

    try:
        # 저장 디렉토리 생성
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'banners')
        os.makedirs(upload_dir, exist_ok=True)

        # 파일명 생성
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        ext = filename.rsplit('.', 1)[1].lower()
        saved_filename = f"{timestamp}_{filename}"

        filepath = os.path.join(upload_dir, saved_filename)
        file.save(filepath)

        # 현재 최대 순서 조회
        max_order = db.session.query(db.func.max(Banner.display_order)).scalar() or 0

        title = request.form.get('title', '')

        banner = Banner(
            title=title,
            image_path=f"uploads/banners/{saved_filename}",
            display_order=max_order + 1,
            is_active=True,
            created_by=current_user.id
        )
        db.session.add(banner)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '배너가 등록되었습니다.',
            'data': banner.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'배너 등록 실패: {str(e)}'}), 500


@banners_bp.route('/<int:banner_id>/order', methods=['PUT'])
@admin_required
def update_banner_order(current_user, banner_id):
    """배너 순서 변경"""
    banner = Banner.query.get(banner_id)
    if not banner:
        return jsonify({'success': False, 'message': '배너를 찾을 수 없습니다.'}), 404

    data = request.get_json()
    if 'displayOrder' in data:
        banner.display_order = data['displayOrder']
        db.session.commit()

    return jsonify({'success': True, 'message': '순서가 변경되었습니다.'})


@banners_bp.route('/reorder', methods=['PUT'])
@admin_required
def reorder_banners(current_user):
    """배너 순서 일괄 변경"""
    data = request.get_json()
    order_list = data.get('orders', [])

    try:
        for item in order_list:
            banner = Banner.query.get(item['id'])
            if banner:
                banner.display_order = item['displayOrder']
        db.session.commit()
        return jsonify({'success': True, 'message': '순서가 변경되었습니다.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'순서 변경 실패: {str(e)}'}), 500


@banners_bp.route('/<int:banner_id>', methods=['DELETE'])
@admin_required
def delete_banner(current_user, banner_id):
    """배너 삭제 (파일도 삭제)"""
    banner = Banner.query.get(banner_id)
    if not banner:
        return jsonify({'success': False, 'message': '배너를 찾을 수 없습니다.'}), 404

    try:
        # 파일 삭제
        filepath = os.path.join(os.path.dirname(current_app.config['UPLOAD_FOLDER']), banner.image_path)
        if not os.path.isabs(filepath):
            filepath = os.path.join(os.path.dirname(__file__), '..', banner.image_path)
        if os.path.exists(filepath):
            os.remove(filepath)

        db.session.delete(banner)
        db.session.commit()

        return jsonify({'success': True, 'message': '배너가 삭제되었습니다.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'배너 삭제 실패: {str(e)}'}), 500


@banners_bp.route('/<int:banner_id>/image', methods=['GET'])
def get_banner_image(banner_id):
    """배너 이미지 파일 서빙"""
    banner = Banner.query.get(banner_id)
    if not banner:
        return jsonify({'success': False, 'message': '배너를 찾을 수 없습니다.'}), 404

    # backend 디렉토리 기준으로 경로 구성
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    filepath = os.path.join(backend_dir, banner.image_path)

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'message': '이미지 파일을 찾을 수 없습니다.'}), 404

    return send_file(filepath)
