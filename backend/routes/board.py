"""
기타 게시판 API (해외기술용역/국제협력/해외진출지원)
"""
from flask import Blueprint, jsonify, request
from models import db, BoardPost, ConsultingProject, OdaProject
from routes.auth import token_required
from utils.file_naming import make_overseas_tech_filename, make_overseas_tech_disk_filename
from utils.r2_storage import upload_file, delete_file, check_storage_limit, stream_from_r2
from datetime import datetime
from werkzeug.utils import secure_filename

board_bp = Blueprint('board', __name__)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'hwp', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'zip'}

VALID_BOARD_TYPES = ('overseas_tech', 'oda', 'expansion')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@board_bp.route('', methods=['GET'])
@token_required
def get_posts(current_user):
    """게시글 목록 조회"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search')
        board_type = request.args.get('board_type', 'overseas_tech')
        category = request.args.get('category')

        query = BoardPost.query.filter(BoardPost.board_type == board_type)

        if category:
            query = query.filter(BoardPost.category == category)

        if search:
            query = query.filter(BoardPost.title.ilike(f'%{search}%'))

        query = query.order_by(BoardPost.created_at.desc(), BoardPost.id.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'currentPage': page,
            'perPage': per_page
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('/<int:id>', methods=['GET'])
@token_required
def get_post(current_user, id):
    """게시글 상세 조회"""
    try:
        post = BoardPost.query.get_or_404(id)
        return jsonify({
            'success': True,
            'data': post.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('', methods=['POST'])
@token_required
def create_post(current_user):
    """게시글 등록"""
    try:
        title = request.form.get('title')
        content = request.form.get('content', '')
        board_type = request.form.get('boardType', 'overseas_tech')
        category = request.form.get('category', '').strip() or None
        consulting_project_id = request.form.get('consultingProjectId', type=int)
        oda_project_id = request.form.get('odaProjectId', type=int)

        if not title:
            return jsonify({'success': False, 'message': '제목을 입력해주세요.'}), 400

        if board_type not in VALID_BOARD_TYPES:
            board_type = 'overseas_tech'

        post = BoardPost(
            board_type=board_type,
            category=category,
            title=title,
            content=content,
            consulting_project_id=consulting_project_id if consulting_project_id else None,
            oda_project_id=oda_project_id if oda_project_id else None,
            created_by=current_user.id
        )

        # 파일 처리
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename):
                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)

                if not check_storage_limit(file_size):
                    return jsonify({'success': False, 'message': '저장 공간이 부족합니다.'}), 400

                original = secure_filename(file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'bin'
                _b_proj = ConsultingProject.query.get(consulting_project_id) if consulting_project_id else None
                _b_year = datetime.now().year
                unique_filename = make_overseas_tech_disk_filename('첨부', ext, _b_proj, title, _b_year)

                r2_key = f'board/{unique_filename}'
                upload_file(file, r2_key)

                post.file_name = make_overseas_tech_filename('첨부', ext, _b_proj, title, _b_year)
                post.file_path = r2_key
                post.file_size = file_size
            elif file and file.filename and not allowed_file(file.filename):
                return jsonify({'success': False, 'message': '허용되지 않는 파일 형식입니다.'}), 400

        db.session.add(post)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '게시글이 등록되었습니다.',
            'data': post.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('/<int:id>', methods=['PUT'])
@token_required
def update_post(current_user, id):
    """게시글 수정 (작성자 본인 또는 관리자만 가능)"""
    try:
        post = BoardPost.query.get_or_404(id)

        if post.created_by != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'message': '작성자 본인만 수정할 수 있습니다.'}), 403

        title = request.form.get('title')
        if title:
            post.title = title

        content = request.form.get('content')
        if content is not None:
            post.content = content

        category = request.form.get('category')
        if category is not None:
            post.category = category.strip() or None

        consulting_project_id = request.form.get('consultingProjectId')
        if consulting_project_id is not None:
            post.consulting_project_id = int(consulting_project_id) if consulting_project_id else None

        oda_project_id = request.form.get('odaProjectId')
        if oda_project_id is not None:
            post.oda_project_id = int(oda_project_id) if oda_project_id else None

        # 새 파일 업로드
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename):
                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)

                if not check_storage_limit(file_size):
                    return jsonify({'success': False, 'message': '저장 공간이 부족합니다.'}), 400

                # 기존 R2 파일 삭제
                if post.file_path:
                    old_key = post.file_path if '/' in post.file_path else f'board/{post.file_path}'
                    try:
                        delete_file(old_key)
                    except Exception:
                        pass

                original = secure_filename(file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'bin'
                _upd_proj = ConsultingProject.query.get(post.consulting_project_id) if post.consulting_project_id else None
                _upd_year = post.created_at.year if post.created_at else datetime.now().year
                _upd_title = post.title
                unique_filename = make_overseas_tech_disk_filename('첨부', ext, _upd_proj, _upd_title, _upd_year)

                file.seek(0, 2)
                file_size = file.tell()
                file.seek(0)

                r2_key = f'board/{unique_filename}'
                upload_file(file, r2_key)

                post.file_name = make_overseas_tech_filename('첨부', ext, _upd_proj, _upd_title, _upd_year)
                post.file_path = r2_key
                post.file_size = file_size

        db.session.commit()

        return jsonify({
            'success': True,
            'message': '게시글이 수정되었습니다.',
            'data': post.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('/<int:id>', methods=['DELETE'])
@token_required
def delete_post(current_user, id):
    """게시글 삭제 (작성자 본인 또는 관리자만 가능)"""
    try:
        post = BoardPost.query.get_or_404(id)

        if post.created_by != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'message': '작성자 본인만 삭제할 수 있습니다.'}), 403

        # R2 파일 삭제
        if post.file_path:
            del_key = post.file_path if '/' in post.file_path else f'board/{post.file_path}'
            try:
                delete_file(del_key)
            except Exception:
                pass

        db.session.delete(post)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '게시글이 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('/<int:id>/download', methods=['GET'])
def download_file(id):
    """첨부파일 다운로드"""
    try:
        # 쿼리 파라미터 또는 헤더에서 토큰 가져오기
        token = request.args.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

        from routes.auth import verify_token
        user = verify_token(token)
        if not user:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다.'}), 401

        post = BoardPost.query.get_or_404(id)

        if not post.file_path:
            return jsonify({'success': False, 'message': '첨부파일이 없습니다.'}), 404

        _dl_proj = ConsultingProject.query.get(post.consulting_project_id) if post.consulting_project_id else None
        _dl_year = post.created_at.year if post.created_at else None
        file_ext = '.' + post.file_path.rsplit('.', 1)[-1] if '.' in post.file_path else '.pdf'
        download_name = make_overseas_tech_filename('첨부', file_ext, _dl_proj, post.title, _dl_year)

        # R2 키 결정: 이미 prefix 포함이면 그대로, 아니면 board/ 추가
        r2_key = post.file_path if '/' in post.file_path else f'board/{post.file_path}'
        try:
            return stream_from_r2(r2_key, download_name=download_name)
        except Exception:
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('/projects', methods=['GET'])
@token_required
def get_projects_for_board(current_user):
    """게시글 등록용 프로젝트 목록"""
    try:
        board_type = request.args.get('board_type', 'overseas_tech')

        if board_type == 'oda':
            projects = OdaProject.query.order_by(
                OdaProject.title.asc()
            ).all()
            return jsonify({
                'success': True,
                'data': [{'id': p.id, 'titleKr': p.title, 'country': p.country} for p in projects]
            })
        else:
            # overseas_tech (expansion은 관련사업 없음)
            projects = ConsultingProject.query.order_by(
                ConsultingProject.end_date.desc().nullslast(),
                ConsultingProject.title_kr.asc()
            ).all()
            return jsonify({
                'success': True,
                'data': [{'id': p.id, 'titleKr': p.title_kr, 'country': p.country} for p in projects]
            })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@board_bp.route('/categories', methods=['GET'])
@token_required
def get_categories(current_user):
    """게시판 구분 목록 조회 (기존 입력값)"""
    try:
        board_type = request.args.get('board_type', 'overseas_tech')
        categories = db.session.query(BoardPost.category).filter(
            BoardPost.board_type == board_type,
            BoardPost.category.isnot(None),
            BoardPost.category != ''
        ).distinct().order_by(BoardPost.category).all()

        return jsonify({
            'success': True,
            'data': [c[0] for c in categories]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
