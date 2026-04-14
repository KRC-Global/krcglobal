"""
제안서 관리 API
"""
from flask import Blueprint, jsonify, request, current_app
from models import db, Proposal, SystemConfig, ConsultingProject
from routes.auth import token_required
from utils.file_naming import make_overseas_tech_filename, make_overseas_tech_disk_filename
from utils.r2_storage import upload_file, delete_file, check_storage_limit, stream_from_r2
from datetime import datetime
from werkzeug.utils import secure_filename

proposals_bp = Blueprint('proposals', __name__)

ALLOWED_EXTENSIONS = {'pdf', 'zip', 'xlsx', 'xls'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@proposals_bp.route('', methods=['GET'])
@token_required
def get_proposals(current_user):
    """제안서 목록 조회"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # 필터링
        country = request.args.get('country')
        result = request.args.get('result')
        year = request.args.get('year', type=int)
        search = request.args.get('search')

        query = Proposal.query

        if country:
            query = query.filter(Proposal.country == country)
        if result:
            query = query.filter(Proposal.result == result)
        if year:
            query = query.filter(db.extract('year', Proposal.submission_date) == year)
        if search:
            query = query.filter(
                db.or_(
                    Proposal.title.ilike(f'%{search}%'),
                    Proposal.client.ilike(f'%{search}%'),
                    Proposal.country.ilike(f'%{search}%')
                )
            )

        # 정렬 (최신순)
        query = query.order_by(Proposal.submission_date.desc(), Proposal.id.desc())

        # 페이지네이션
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


@proposals_bp.route('/<int:id>', methods=['GET'])
@token_required
def get_proposal(current_user, id):
    """제안서 상세 조회"""
    try:
        proposal = Proposal.query.get_or_404(id)
        return jsonify({
            'success': True,
            'data': proposal.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@proposals_bp.route('', methods=['POST'])
@token_required
def create_proposal(current_user):
    """제안서 등록"""
    try:
        # Form data 처리
        title = request.form.get('title')
        if not title:
            return jsonify({'success': False, 'message': '사업명은 필수입니다.'}), 400

        # consultingProjectId 처리
        consulting_project_id = request.form.get('consultingProjectId', type=int)

        proposal = Proposal(
            title=title,
            country=request.form.get('country'),
            client=request.form.get('client'),
            budget=request.form.get('budget') or None,
            project_period=request.form.get('projectPeriod'),
            result=request.form.get('result', '심사중'),
            description=request.form.get('description'),
            team_members=request.form.get('teamMembers'),
            remarks=request.form.get('remarks'),
            consulting_project_id=consulting_project_id,
            created_by=current_user.id
        )

        # 날짜 처리
        submission_date = request.form.get('submissionDate')
        if submission_date:
            proposal.submission_date = datetime.strptime(submission_date, '%Y-%m-%d').date()

        result_date = request.form.get('resultDate')
        if result_date:
            proposal.result_date = datetime.strptime(result_date, '%Y-%m-%d').date()

        # 파일명 생성용: 프로젝트 및 fallback 연도 결정
        _proj = ConsultingProject.query.get(consulting_project_id) if consulting_project_id else None
        _fallback_year = proposal.submission_date.year if proposal.submission_date else None

        # 기술제안서 파일 처리
        if 'technicalFile' in request.files:
            file = request.files['technicalFile']
            if file and file.filename and allowed_file(file.filename):
                original = secure_filename(file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                file.seek(0, 2); t_size = file.tell(); file.seek(0)
                if not check_storage_limit(t_size):
                    return jsonify({'success': False, 'message': '스토리지 용량이 부족합니다.'}), 400
                unique_filename = make_overseas_tech_disk_filename('기술제안서', ext, _proj, proposal.title, _fallback_year)
                r2_key = f'proposals/{unique_filename}'
                upload_file(file, r2_key, content_type=f'application/{ext}')
                proposal.technical_file_name = make_overseas_tech_filename('기술제안서', ext, _proj, proposal.title, _fallback_year)
                proposal.technical_file_path = r2_key
                proposal.technical_file_size = t_size

        # 가격제안서 파일 처리
        if 'priceFile' in request.files:
            file = request.files['priceFile']
            if file and file.filename and allowed_file(file.filename):
                original = secure_filename(file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                file.seek(0, 2); p_size = file.tell(); file.seek(0)
                if not check_storage_limit(p_size):
                    return jsonify({'success': False, 'message': '스토리지 용량이 부족합니다.'}), 400
                unique_filename = make_overseas_tech_disk_filename('가격제안서', ext, _proj, proposal.title, _fallback_year)
                r2_key = f'proposals/{unique_filename}'
                upload_file(file, r2_key, content_type=f'application/{ext}')
                proposal.price_file_name = make_overseas_tech_filename('가격제안서', ext, _proj, proposal.title, _fallback_year)
                proposal.price_file_path = r2_key
                proposal.price_file_size = p_size

        db.session.add(proposal)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '제안서가 등록되었습니다.',
            'data': proposal.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@proposals_bp.route('/<int:id>', methods=['PUT'])
@token_required
def update_proposal(current_user, id):
    """제안서 수정"""
    try:
        proposal = Proposal.query.get_or_404(id)

        # Form data 처리
        if request.form.get('title'):
            proposal.title = request.form.get('title')
        if request.form.get('country'):
            proposal.country = request.form.get('country')
        if request.form.get('client'):
            proposal.client = request.form.get('client')
        if request.form.get('budget'):
            proposal.budget = request.form.get('budget')
        if request.form.get('projectPeriod'):
            proposal.project_period = request.form.get('projectPeriod')
        if request.form.get('result'):
            proposal.result = request.form.get('result')
        if request.form.get('description'):
            proposal.description = request.form.get('description')
        if request.form.get('teamMembers'):
            proposal.team_members = request.form.get('teamMembers')
        if request.form.get('remarks'):
            proposal.remarks = request.form.get('remarks')

        # consultingProjectId 처리
        consulting_project_id = request.form.get('consultingProjectId', type=int)
        if consulting_project_id is not None:
            proposal.consulting_project_id = consulting_project_id

        # 날짜 처리
        submission_date = request.form.get('submissionDate')
        if submission_date:
            proposal.submission_date = datetime.strptime(submission_date, '%Y-%m-%d').date()

        result_date = request.form.get('resultDate')
        if result_date:
            proposal.result_date = datetime.strptime(result_date, '%Y-%m-%d').date()

        # 파일명 생성용: 프로젝트 및 fallback 연도 결정
        _upd_proj = ConsultingProject.query.get(proposal.consulting_project_id) if proposal.consulting_project_id else None
        _upd_year = proposal.submission_date.year if proposal.submission_date else None

        # 기술제안서 파일 업로드
        if 'technicalFile' in request.files:
            file = request.files['technicalFile']
            if file and file.filename and allowed_file(file.filename):
                # 기존 R2 파일 삭제
                if proposal.technical_file_path:
                    try:
                        delete_file(proposal.technical_file_path)
                    except Exception:
                        pass
                original = secure_filename(file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                file.seek(0, 2); t_size = file.tell(); file.seek(0)
                unique_filename = make_overseas_tech_disk_filename('기술제안서', ext, _upd_proj, proposal.title, _upd_year)
                r2_key = f'proposals/{unique_filename}'
                upload_file(file, r2_key, content_type=f'application/{ext}')
                proposal.technical_file_name = make_overseas_tech_filename('기술제안서', ext, _upd_proj, proposal.title, _upd_year)
                proposal.technical_file_path = r2_key
                proposal.technical_file_size = t_size

        # 가격제안서 파일 업로드
        if 'priceFile' in request.files:
            file = request.files['priceFile']
            if file and file.filename and allowed_file(file.filename):
                # 기존 R2 파일 삭제
                if proposal.price_file_path:
                    try:
                        delete_file(proposal.price_file_path)
                    except Exception:
                        pass
                original = secure_filename(file.filename)
                ext = original.rsplit('.', 1)[1].lower() if '.' in original else 'pdf'
                file.seek(0, 2); p_size = file.tell(); file.seek(0)
                unique_filename = make_overseas_tech_disk_filename('가격제안서', ext, _upd_proj, proposal.title, _upd_year)
                r2_key = f'proposals/{unique_filename}'
                upload_file(file, r2_key, content_type=f'application/{ext}')
                proposal.price_file_name = make_overseas_tech_filename('가격제안서', ext, _upd_proj, proposal.title, _upd_year)
                proposal.price_file_path = r2_key
                proposal.price_file_size = p_size

        db.session.commit()

        return jsonify({
            'success': True,
            'message': '제안서가 수정되었습니다.',
            'data': proposal.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@proposals_bp.route('/<int:id>', methods=['DELETE'])
@token_required
def delete_proposal(current_user, id):
    """제안서 삭제"""
    try:
        proposal = Proposal.query.get_or_404(id)

        # R2 파일 삭제
        if proposal.technical_file_path:
            try:
                delete_file(proposal.technical_file_path)
            except Exception:
                pass
        if proposal.price_file_path:
            try:
                delete_file(proposal.price_file_path)
            except Exception:
                pass

        db.session.delete(proposal)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '제안서가 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@proposals_bp.route('/<int:id>/download', methods=['GET'])
@token_required
def download_file(current_user, id):
    """제안서 파일 다운로드/미리보기"""
    try:
        proposal = Proposal.query.get(id)
        if not proposal:
            return jsonify({'success': False, 'message': '제안서를 찾을 수 없습니다.'}), 404

        file_type = request.args.get('type', 'technical')  # technical 또는 price

        # 가격제안서 비밀번호 검증
        if file_type == 'price':
            stored_password = getattr(proposal, 'price_password', None)
            if stored_password:
                provided_password = request.args.get('password', '')
                if not provided_password or provided_password != stored_password:
                    return jsonify({'success': False, 'message': '비밀번호가 틀렸습니다.', 'requirePassword': True}), 403

        # 파일 타입에 따라 파일 경로 선택
        if file_type == 'price':
            file_relative_path = proposal.price_file_path
            file_prefix = '가격제안서'
        else:
            file_relative_path = proposal.technical_file_path
            file_prefix = '기술제안서'

        if not file_relative_path:
            return jsonify({'success': False, 'message': f'{file_prefix} 파일 경로가 없습니다.'}), 404

        _dl_proj = ConsultingProject.query.get(proposal.consulting_project_id) if proposal.consulting_project_id else None
        _dl_year = proposal.submission_date.year if proposal.submission_date else None
        doc_label = '가격제안서' if file_type == 'price' else '기술제안서'
        file_ext = file_relative_path.rsplit('.', 1)[1] if '.' in file_relative_path else 'pdf'
        download_name = make_overseas_tech_filename(doc_label, file_ext, _dl_proj, proposal.title, _dl_year)

        try:
            return stream_from_r2(file_relative_path, content_type='application/pdf', inline=True, download_name=download_name)
        except Exception as e:
            current_app.logger.error(f'제안서 R2 스트리밍 오류: {str(e)}')
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f'❌ 제안서 다운로드 오류: {error_detail}')
        return jsonify({'success': False, 'message': f'파일 전송 실패: {str(e)}'}), 500


@proposals_bp.route('/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    """제안서 통계"""
    try:
        total = Proposal.query.count()
        selected = Proposal.query.filter(Proposal.result == '선정').count()
        rejected = Proposal.query.filter(Proposal.result == '탈락').count()
        pending = Proposal.query.filter(Proposal.result == '심사중').count()

        # 연도별 통계
        current_year = datetime.now().year
        this_year = Proposal.query.filter(
            db.extract('year', Proposal.submission_date) == current_year
        ).count()

        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'selected': selected,
                'rejected': rejected,
                'pending': pending,
                'thisYear': this_year,
                'successRate': round(selected / total * 100, 1) if total > 0 else 0
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@proposals_bp.route('/countries', methods=['GET'])
@token_required
def get_countries(current_user):
    """제안서 국가 목록"""
    try:
        countries = db.session.query(Proposal.country).distinct().filter(
            Proposal.country.isnot(None)
        ).order_by(Proposal.country).all()

        return jsonify({
            'success': True,
            'data': [c[0] for c in countries if c[0]]
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@proposals_bp.route('/verify-technical-password', methods=['POST'])
@token_required
def verify_technical_password(current_user):
    """기술제안서 비밀번호 검증"""
    try:
        data = request.get_json()
        password = data.get('password')

        if not password:
            return jsonify({'success': False, 'message': '비밀번호를 입력해주세요.'}), 400

        # DB에서 비밀번호 가져오기
        config = SystemConfig.query.filter_by(config_key='technical_proposal_password').first()

        if not config:
            # 설정이 없으면 환경변수에서 기본 비밀번호 가져오기
            import os
            default_pw = os.environ.get('PROPOSAL_PASSWORD', 'changeme')
            config = SystemConfig(
                config_key='technical_proposal_password',
                config_value=default_pw,
                description='기술제안서 열람 비밀번호'
            )
            db.session.add(config)
            db.session.commit()

        # 비밀번호 검증
        if password == config.config_value:
            return jsonify({
                'success': True,
                'message': '비밀번호가 확인되었습니다.'
            })
        else:
            return jsonify({
                'success': False,
                'message': '비밀번호를 확인하세요.'
            }), 400

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
