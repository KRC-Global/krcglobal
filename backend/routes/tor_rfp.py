"""
TOR/RFP 관리 API
해외기술용역 과업설명서(TOR) 및 제안요청서(RFP) 관리
"""
from flask import Blueprint, jsonify, request, current_app, send_file
from models import db, TorRfp, ConsultingProject
from routes.auth import token_required
from utils.file_naming import make_overseas_tech_filename, make_overseas_tech_disk_filename
from datetime import datetime
import os
from werkzeug.utils import secure_filename

tor_rfp_bp = Blueprint('tor_rfp', __name__)


def resolve_file_path(stored_path, subfolder='tor_rfp'):
    """크로스 플랫폼 파일 경로 해석.
    DB에 Windows 절대 경로가 저장되어 있어도 로컬 uploads/ 하위에서 파일을 찾는다."""
    if not stored_path:
        return None
    if os.path.exists(stored_path):
        return stored_path
    filename = stored_path.replace('\\', '/').split('/')[-1]
    upload_folder = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'uploads', subfolder
    )
    local_path = os.path.join(upload_folder, filename)
    if os.path.exists(local_path):
        return local_path
    return None

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'hwp', 'zip'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def check_tor_rfp_permission(user):
    """TOR/RFP 수정 권한 확인: admin 또는 krcgisul만 가능"""
    return user.role == 'admin' or user.user_id == 'krcgisul'


@tor_rfp_bp.route('', methods=['GET'])
@token_required
def get_tor_rfp_list(current_user):
    """TOR/RFP 목록 조회 - 등록된 항목만 표시"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '')

        # TOR/RFP 조회 (ConsultingProject와 LEFT JOIN - 독립 항목 포함)
        query = db.session.query(TorRfp, ConsultingProject).outerjoin(
            ConsultingProject, TorRfp.consulting_project_id == ConsultingProject.id
        )

        # 검색 필터
        if search:
            query = query.filter(
                db.or_(
                    ConsultingProject.title_kr.ilike(f'%{search}%'),
                    ConsultingProject.country.ilike(f'%{search}%'),
                    TorRfp.title.ilike(f'%{search}%'),
                    TorRfp.country.ilike(f'%{search}%')
                )
            )

        # 정렬 (준공일 기준 최신순 - end_date 내림차순)
        query = query.order_by(ConsultingProject.end_date.desc().nullslast(), TorRfp.id.desc())

        # 페이지네이션
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        data = []
        for tor_rfp, project in pagination.items:
            data.append({
                'id': tor_rfp.id,
                'consultingProjectId': project.id if project else None,
                'projectTitle': project.title_kr if project else tor_rfp.title,
                'projectCountry': project.country if project else tor_rfp.country,
                'projectEndDate': project.end_date if project else None,
                'torFileName': tor_rfp.tor_file_name,
                'torFileSize': tor_rfp.tor_file_size,
                'rfpFileName': tor_rfp.rfp_file_name,
                'rfpFileSize': tor_rfp.rfp_file_size,
                'createdAt': tor_rfp.created_at.isoformat() if tor_rfp.created_at else None,
                'updatedAt': tor_rfp.updated_at.isoformat() if tor_rfp.updated_at else None
            })

        return jsonify({
            'success': True,
            'data': data,
            'total': pagination.total,
            'pages': pagination.pages,
            'currentPage': page,
            'perPage': per_page
        })

    except Exception as e:
        current_app.logger.error(f'TOR/RFP 목록 조회 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/projects', methods=['GET'])
@token_required
def get_available_projects(current_user):
    """TOR/RFP 등록 가능한 프로젝트 목록 (검색용)"""
    try:
        search = request.args.get('search', '')

        query = ConsultingProject.query

        if search:
            query = query.filter(
                db.or_(
                    ConsultingProject.title_kr.ilike(f'%{search}%'),
                    ConsultingProject.country.ilike(f'%{search}%')
                )
            )

        query = query.order_by(ConsultingProject.title_kr.asc())
        projects = query.all()  # 전체 프로젝트 로드 (limit 제거)

        return jsonify({
            'success': True,
            'data': [{
                'id': p.id,
                'title': p.title_kr,
                'country': p.country,
                'status': p.status
            } for p in projects]
        })

    except Exception as e:
        current_app.logger.error(f'프로젝트 목록 조회 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:project_id>', methods=['GET'])
@token_required
def get_tor_rfp(current_user, project_id):
    """특정 프로젝트의 TOR/RFP 조회"""
    try:
        tor_rfp = TorRfp.query.filter_by(consulting_project_id=project_id).first()

        if not tor_rfp:
            return jsonify({
                'success': True,
                'data': None,
                'message': '등록된 TOR/RFP가 없습니다.'
            })

        return jsonify({
            'success': True,
            'data': tor_rfp.to_dict()
        })

    except Exception as e:
        current_app.logger.error(f'TOR/RFP 조회 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('', methods=['POST'])
@token_required
def create_or_update_tor_rfp(current_user):
    """TOR/RFP 등록 또는 수정"""
    try:
        # 권한 확인
        if not check_tor_rfp_permission(current_user):
            return jsonify({'success': False, 'message': '권한이 없습니다. (admin 또는 krcgisul만 가능)'}), 403

        project_id = request.form.get('projectId', type=int)
        direct_title = request.form.get('title', '').strip()
        direct_country = request.form.get('country', '').strip()

        if not project_id and not direct_title:
            return jsonify({'success': False, 'message': '프로젝트를 선택하거나 사업명을 입력해주세요.'}), 400

        project = None
        if project_id:
            # 프로젝트 확인
            project = ConsultingProject.query.get(project_id)
            if not project:
                return jsonify({'success': False, 'message': '해당 프로젝트를 찾을 수 없습니다.'}), 404

        # 기존 TOR/RFP 확인
        if project_id:
            tor_rfp = TorRfp.query.filter_by(consulting_project_id=project_id).first()
        else:
            tor_rfp = None
        is_new = tor_rfp is None

        if is_new:
            tor_rfp = TorRfp(
                consulting_project_id=project_id,
                title=direct_title if not project_id else None,
                country=direct_country if not project_id else None,
                created_by=current_user.id
            )

        # 업로드 디렉토리 생성
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'tor_rfp')
        os.makedirs(upload_dir, exist_ok=True)

        # TOR 파일 처리
        if 'torFile' in request.files:
            tor_file = request.files['torFile']
            if tor_file and tor_file.filename and allowed_file(tor_file.filename):
                # 기존 파일 삭제
                if tor_rfp.tor_file_path and os.path.exists(tor_rfp.tor_file_path):
                    os.remove(tor_rfp.tor_file_path)

                original = secure_filename(tor_file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                unique_filename = make_overseas_tech_disk_filename('TOR', ext, project, direct_title)
                file_path = os.path.join(upload_dir, unique_filename)
                tor_file.save(file_path)

                tor_rfp.tor_file_name = make_overseas_tech_filename('TOR', ext, project, direct_title)
                tor_rfp.tor_file_path = file_path
                tor_rfp.tor_file_size = os.path.getsize(file_path)
                tor_rfp.tor_file_type = ext

        # RFP 파일 처리
        if 'rfpFile' in request.files:
            rfp_file = request.files['rfpFile']
            if rfp_file and rfp_file.filename and allowed_file(rfp_file.filename):
                # 기존 파일 삭제
                if tor_rfp.rfp_file_path and os.path.exists(tor_rfp.rfp_file_path):
                    os.remove(tor_rfp.rfp_file_path)

                original = secure_filename(rfp_file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                unique_filename = make_overseas_tech_disk_filename('RFP', ext, project, direct_title)
                file_path = os.path.join(upload_dir, unique_filename)
                rfp_file.save(file_path)

                tor_rfp.rfp_file_name = make_overseas_tech_filename('RFP', ext, project, direct_title)
                tor_rfp.rfp_file_path = file_path
                tor_rfp.rfp_file_size = os.path.getsize(file_path)
                tor_rfp.rfp_file_type = ext

        tor_rfp.updated_by = current_user.id
        tor_rfp.updated_at = datetime.utcnow()

        if is_new:
            db.session.add(tor_rfp)

        db.session.commit()

        # 관계 로드를 위해 객체 새로고침
        db.session.refresh(tor_rfp)

        return jsonify({
            'success': True,
            'message': 'TOR/RFP가 저장되었습니다.',
            'data': tor_rfp.to_dict()
        }), 201 if is_new else 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'TOR/RFP 저장 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/detail/<int:id>', methods=['GET'])
@token_required
def get_tor_rfp_by_id(current_user, id):
    """TOR/RFP ID로 조회"""
    try:
        tor_rfp = TorRfp.query.get_or_404(id)
        return jsonify({
            'success': True,
            'data': tor_rfp.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f'TOR/RFP 조회 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>', methods=['PUT'])
@token_required
def update_tor_rfp(current_user, id):
    """TOR/RFP 수정 (ID 기반)"""
    try:
        if not check_tor_rfp_permission(current_user):
            return jsonify({'success': False, 'message': '권한이 없습니다. (admin 또는 krcgisul만 가능)'}), 403

        tor_rfp = TorRfp.query.get_or_404(id)

        # 프로젝트 또는 직접 입력 정보 업데이트
        project_id = request.form.get('projectId', type=int)
        direct_title = request.form.get('title', '').strip()
        direct_country = request.form.get('country', '').strip()
        project = None

        if project_id:
            project = ConsultingProject.query.get(project_id)
            if not project:
                return jsonify({'success': False, 'message': '해당 프로젝트를 찾을 수 없습니다.'}), 404
            tor_rfp.consulting_project_id = project_id
            tor_rfp.title = None
            tor_rfp.country = None
        elif direct_title:
            tor_rfp.consulting_project_id = None
            tor_rfp.title = direct_title
            tor_rfp.country = direct_country
        else:
            # 변경 없음 - 기존 프로젝트 정보로 파일명 생성
            if tor_rfp.consulting_project_id:
                project = ConsultingProject.query.get(tor_rfp.consulting_project_id)
            direct_title = tor_rfp.title or ''

        # 업로드 디렉토리 생성
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'tor_rfp')
        os.makedirs(upload_dir, exist_ok=True)

        # TOR 파일 처리
        if 'torFile' in request.files:
            tor_file = request.files['torFile']
            if tor_file and tor_file.filename and allowed_file(tor_file.filename):
                # 기존 파일 삭제
                if tor_rfp.tor_file_path and os.path.exists(tor_rfp.tor_file_path):
                    os.remove(tor_rfp.tor_file_path)

                original = secure_filename(tor_file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                unique_filename = make_overseas_tech_disk_filename('TOR', ext, project, direct_title)
                file_path = os.path.join(upload_dir, unique_filename)
                tor_file.save(file_path)

                tor_rfp.tor_file_name = make_overseas_tech_filename('TOR', ext, project, direct_title)
                tor_rfp.tor_file_path = file_path
                tor_rfp.tor_file_size = os.path.getsize(file_path)
                tor_rfp.tor_file_type = ext

        # RFP 파일 처리
        if 'rfpFile' in request.files:
            rfp_file = request.files['rfpFile']
            if rfp_file and rfp_file.filename and allowed_file(rfp_file.filename):
                # 기존 파일 삭제
                if tor_rfp.rfp_file_path and os.path.exists(tor_rfp.rfp_file_path):
                    os.remove(tor_rfp.rfp_file_path)

                original = secure_filename(rfp_file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                unique_filename = make_overseas_tech_disk_filename('RFP', ext, project, direct_title)
                file_path = os.path.join(upload_dir, unique_filename)
                rfp_file.save(file_path)

                tor_rfp.rfp_file_name = make_overseas_tech_filename('RFP', ext, project, direct_title)
                tor_rfp.rfp_file_path = file_path
                tor_rfp.rfp_file_size = os.path.getsize(file_path)
                tor_rfp.rfp_file_type = ext

        tor_rfp.updated_by = current_user.id
        tor_rfp.updated_at = datetime.utcnow()

        db.session.commit()
        db.session.refresh(tor_rfp)

        return jsonify({
            'success': True,
            'message': 'TOR/RFP가 수정되었습니다.',
            'data': tor_rfp.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'TOR/RFP 수정 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>/tor', methods=['DELETE'])
@token_required
def delete_tor(current_user, id):
    """TOR 파일 삭제"""
    try:
        if not check_tor_rfp_permission(current_user):
            return jsonify({'success': False, 'message': '권한이 없습니다.'}), 403

        tor_rfp = TorRfp.query.get_or_404(id)

        resolved = resolve_file_path(tor_rfp.tor_file_path)
        if resolved:
            os.remove(resolved)

        tor_rfp.tor_file_name = None
        tor_rfp.tor_file_path = None
        tor_rfp.tor_file_size = None
        tor_rfp.tor_file_type = None
        tor_rfp.updated_by = current_user.id
        tor_rfp.updated_at = datetime.utcnow()

        # TOR과 RFP 모두 없으면 레코드 삭제
        if not tor_rfp.rfp_file_name:
            db.session.delete(tor_rfp)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'TOR 파일이 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'TOR 삭제 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>/rfp', methods=['DELETE'])
@token_required
def delete_rfp(current_user, id):
    """RFP 파일 삭제"""
    try:
        if not check_tor_rfp_permission(current_user):
            return jsonify({'success': False, 'message': '권한이 없습니다.'}), 403

        tor_rfp = TorRfp.query.get_or_404(id)

        resolved = resolve_file_path(tor_rfp.rfp_file_path)
        if resolved:
            os.remove(resolved)

        tor_rfp.rfp_file_name = None
        tor_rfp.rfp_file_path = None
        tor_rfp.rfp_file_size = None
        tor_rfp.rfp_file_type = None
        tor_rfp.updated_by = current_user.id
        tor_rfp.updated_at = datetime.utcnow()

        # TOR과 RFP 모두 없으면 레코드 삭제
        if not tor_rfp.tor_file_name:
            db.session.delete(tor_rfp)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'RFP 파일이 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'RFP 삭제 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>/tor/download', methods=['GET'])
@token_required
def download_tor(current_user, id):
    """TOR 파일 다운로드"""
    try:
        tor_rfp = TorRfp.query.get_or_404(id)

        resolved = resolve_file_path(tor_rfp.tor_file_path)
        if not resolved:
            return jsonify({'success': False, 'message': 'TOR 파일을 찾을 수 없습니다.'}), 404

        project = ConsultingProject.query.get(tor_rfp.consulting_project_id) if tor_rfp.consulting_project_id else None
        ext = '.' + tor_rfp.tor_file_type if tor_rfp.tor_file_type else '.pdf'
        download_name = make_overseas_tech_filename('TOR', ext, project, tor_rfp.title)
        return send_file(
            resolved,
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        current_app.logger.error(f'TOR 다운로드 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>/rfp/download', methods=['GET'])
@token_required
def download_rfp(current_user, id):
    """RFP 파일 다운로드"""
    try:
        tor_rfp = TorRfp.query.get_or_404(id)

        resolved = resolve_file_path(tor_rfp.rfp_file_path)
        if not resolved:
            return jsonify({'success': False, 'message': 'RFP 파일을 찾을 수 없습니다.'}), 404

        project = ConsultingProject.query.get(tor_rfp.consulting_project_id) if tor_rfp.consulting_project_id else None
        ext = '.' + tor_rfp.rfp_file_type if tor_rfp.rfp_file_type else '.pdf'
        download_name = make_overseas_tech_filename('RFP', ext, project, tor_rfp.title)
        return send_file(
            resolved,
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        current_app.logger.error(f'RFP 다운로드 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>/tor/preview', methods=['GET'])
def preview_tor(id):
    """TOR 파일 미리보기 (새창에서 inline 표시)"""
    try:
        # URL 파라미터로 토큰 받기 (새창 열기용)
        token = request.args.get('token')
        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

        tor_rfp = TorRfp.query.get_or_404(id)

        resolved = resolve_file_path(tor_rfp.tor_file_path)
        if not resolved:
            return jsonify({'success': False, 'message': 'TOR 파일을 찾을 수 없습니다.'}), 404

        project = ConsultingProject.query.get(tor_rfp.consulting_project_id) if tor_rfp.consulting_project_id else None
        ext = '.' + tor_rfp.tor_file_type if tor_rfp.tor_file_type else '.pdf'
        download_name = make_overseas_tech_filename('TOR', ext, project, tor_rfp.title)
        return send_file(
            resolved,
            as_attachment=False,
            download_name=download_name
        )

    except Exception as e:
        current_app.logger.error(f'TOR 미리보기 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/<int:id>/rfp/preview', methods=['GET'])
def preview_rfp(id):
    """RFP 파일 미리보기 (새창에서 inline 표시)"""
    try:
        # URL 파라미터로 토큰 받기 (새창 열기용)
        token = request.args.get('token')
        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

        tor_rfp = TorRfp.query.get_or_404(id)

        resolved = resolve_file_path(tor_rfp.rfp_file_path)
        if not resolved:
            return jsonify({'success': False, 'message': 'RFP 파일을 찾을 수 없습니다.'}), 404

        project = ConsultingProject.query.get(tor_rfp.consulting_project_id) if tor_rfp.consulting_project_id else None
        ext = '.' + tor_rfp.rfp_file_type if tor_rfp.rfp_file_type else '.pdf'
        download_name = make_overseas_tech_filename('RFP', ext, project, tor_rfp.title)
        return send_file(
            resolved,
            as_attachment=False,
            download_name=download_name
        )

    except Exception as e:
        current_app.logger.error(f'RFP 미리보기 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@tor_rfp_bp.route('/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    """TOR/RFP 통계 조회"""
    try:
        total_projects = ConsultingProject.query.count()
        total_tor_rfp = TorRfp.query.count()
        tor_count = TorRfp.query.filter(TorRfp.tor_file_name.isnot(None)).count()
        rfp_count = TorRfp.query.filter(TorRfp.rfp_file_name.isnot(None)).count()

        return jsonify({
            'success': True,
            'data': {
                'totalProjects': total_projects,
                'totalTorRfp': total_tor_rfp,
                'torCount': tor_count,
                'rfpCount': rfp_count
            }
        })

    except Exception as e:
        current_app.logger.error(f'TOR/RFP 통계 조회 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500
