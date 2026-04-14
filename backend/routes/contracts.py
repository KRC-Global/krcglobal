"""
GBMS - Contracts Routes
글로벌사업처 해외사업관리시스템 - 해외기술용역 계약서관리 API
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from werkzeug.utils import secure_filename
from models import db, Contract, ConsultingProject, ActivityLog
from routes.auth import token_required, admin_required, permission_required
from utils.file_naming import make_overseas_tech_filename, make_overseas_tech_disk_filename
from utils.r2_storage import upload_file, delete_file, check_storage_limit, stream_from_r2

contracts_bp = Blueprint('contracts', __name__)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'zip'}


def allowed_file(filename):
    """파일 확장자 검증"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@contracts_bp.route('', methods=['GET'])
@token_required
def get_contracts(current_user):
    """모든 프로젝트와 계약서 목록 조회"""
    try:
        # 쿼리 파라미터
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        country = request.args.get('country')
        search = request.args.get('search')

        # ConsultingProject 쿼리 - 준공년도(end_date) 기준 내림차순 정렬
        query = ConsultingProject.query

        if country:
            query = query.filter(ConsultingProject.country == country)

        if search:
            query = query.filter(
                db.or_(
                    ConsultingProject.title_kr.ilike(f'%{search}%'),
                    ConsultingProject.title_en.ilike(f'%{search}%'),
                    ConsultingProject.country.ilike(f'%{search}%')
                )
            )

        # 정렬: 준공년도(end_date) 내림차순 - end_date는 'YY-MM 형식이므로 문자열 비교로 내림차순
        query = query.order_by(
            ConsultingProject.end_date.desc().nullslast(),
            ConsultingProject.title_kr.asc()
        )

        # 페이지네이션
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        # 각 프로젝트별 계약서 정보 포함
        projects_data = []
        for project in pagination.items:
            project_dict = project.to_dict()

            # 프로젝트의 계약서 목록 조회
            contracts = Contract.query.filter_by(
                consulting_project_id=project.id
            ).order_by(Contract.order_number.asc()).all()

            project_dict['contracts'] = [c.to_dict() for c in contracts]
            projects_data.append(project_dict)

        return jsonify({
            'success': True,
            'data': projects_data,
            'total': pagination.total,
            'pages': pagination.pages,
            'currentPage': page,
            'perPage': per_page
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'계약서 목록 조회 실패: {str(e)}'}), 500


@contracts_bp.route('/projects', methods=['GET'])
@token_required
def get_projects_for_selection(current_user):
    """계약서 등록용 프로젝트 목록 조회 (준공년도 내림차순)"""
    try:
        # 준공년도(end_date) 기준 내림차순 정렬
        projects = ConsultingProject.query.order_by(
            ConsultingProject.end_date.desc().nullslast(),
            ConsultingProject.title_kr.asc()
        ).all()

        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in projects]
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'프로젝트 목록 조회 실패: {str(e)}'}), 500


@contracts_bp.route('/upload', methods=['POST'])
@permission_required('overseas_tech')
def upload_contract(current_user):
    """계약서 업로드 (해외기술용역 권한 필요)"""
    try:
        # 파라미터 검증
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다.'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': '허용되지 않는 파일 형식입니다. (PDF, DOC, DOCX, ZIP만 허용)'}), 400

        consulting_project_id = request.form.get('consultingProjectId', type=int)
        document_type = request.form.get('documentType', 'contract')  # 'contract' 또는 'final_report'
        if document_type == 'final_report':
            # 최종보고서: reportLang으로 언어 구분 (1=국문, 2=영문)
            report_lang = request.form.get('reportLang', 'kr')
            order_number = 1 if report_lang == 'kr' else 2
        else:
            order_number = request.form.get('orderNumber', 1, type=int)
        description = request.form.get('description', '')

        if not consulting_project_id:
            return jsonify({'success': False, 'message': '프로젝트를 선택해주세요.'}), 400

        # 프로젝트 존재 확인
        project = ConsultingProject.query.get(consulting_project_id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        # 기존 문서 확인
        if document_type == 'final_report':
            # 최종보고서는 프로젝트당 언어별 1개 (국문/영문)
            existing_contract = Contract.query.filter_by(
                consulting_project_id=consulting_project_id,
                document_type='final_report',
                order_number=order_number
            ).first()
        else:
            # 계약서는 프로젝트 + 차수별로 구분
            existing_contract = Contract.query.filter_by(
                consulting_project_id=consulting_project_id,
                document_type='contract',
                order_number=order_number
            ).first()

        # 파일 크기 확인 및 R2 용량 체크
        filename = secure_filename(file.filename)
        file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'pdf'

        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        if not check_storage_limit(file_size):
            return jsonify({'success': False, 'message': '스토리지 용량이 부족합니다. (최대 9GB)'}), 400

        # 파일명 생성 (문서 유형에 따라 다르게)
        if document_type == 'final_report':
            lang_text = '국문' if order_number == 1 else '영문'
            doc_label = f'최종보고서_{lang_text}'
        else:
            doc_label = f'{order_number}차계약서'
        new_filename = make_overseas_tech_disk_filename(doc_label, file_ext, project)
        r2_key = f'contracts/{new_filename}'

        # 기존 R2 파일 삭제 (업데이트인 경우)
        if existing_contract and existing_contract.file_path:
            try:
                delete_file(existing_contract.file_path)
            except Exception:
                pass

        upload_file(file, r2_key, content_type=f'application/{file_ext}')
        standard_name = make_overseas_tech_filename(doc_label, file_ext, project)

        if existing_contract:
            # 기존 문서 업데이트
            existing_contract.file_name = standard_name
            existing_contract.file_path = r2_key
            existing_contract.file_size = file_size
            existing_contract.file_type = file_ext
            existing_contract.description = description
            existing_contract.upload_date = datetime.utcnow()
            existing_contract.updated_at = datetime.utcnow()

            if document_type == 'final_report':
                lang_text = '국문' if order_number == 1 else '영문'
                message = f'최종보고서({lang_text})가 업데이트되었습니다.'
            else:
                message = f'{order_number}차 계약서가 업데이트되었습니다.'
            contract = existing_contract
        else:
            # 새 문서 생성 (파일명만 저장 - 플랫폼 독립적)
            contract = Contract(
                consulting_project_id=consulting_project_id,
                document_type=document_type,
                order_number=order_number,
                file_name=standard_name,
                file_path=r2_key,
                file_size=file_size,
                file_type=file_ext,
                description=description,
                created_by=current_user.id
            )
            db.session.add(contract)

            if document_type == 'final_report':
                lang_text = '국문' if order_number == 1 else '영문'
                message = f'최종보고서({lang_text})가 등록되었습니다.'
            else:
                message = f'{order_number}차 계약서가 등록되었습니다.'

        # 활동 로그
        if document_type == 'final_report':
            lang_text = '국문' if order_number == 1 else '영문'
            log_desc = f'최종보고서({lang_text}) 업로드: {project.title_kr}'
        else:
            log_desc = f'계약서 업로드: {project.title_kr} - {order_number}차'

        log = ActivityLog(
            user_id=current_user.id,
            action='upload' if not existing_contract else 'update',
            entity_type='contract',
            entity_id=contract.id if existing_contract else None,
            description=log_desc,
            ip_address=request.remote_addr
        )
        db.session.add(log)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': message,
            'data': contract.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'업로드 실패: {str(e)}'}), 500


@contracts_bp.route('/<int:contract_id>', methods=['DELETE'])
@permission_required('overseas_tech')
def delete_contract(current_user, contract_id):
    """계약서 삭제 (해외기술용역 권한 필요)"""
    try:
        contract = Contract.query.get_or_404(contract_id)

        # R2 파일 삭제
        if contract.file_path:
            try:
                delete_file(contract.file_path)
            except Exception as e:
                print(f"R2 파일 삭제 실패: {str(e)}")

        # 활동 로그
        log = ActivityLog(
            user_id=current_user.id,
            action='delete',
            entity_type='contract',
            entity_id=contract.id,
            description=f'계약서 삭제: {contract.order_number}차',
            ip_address=request.remote_addr
        )
        db.session.add(log)

        db.session.delete(contract)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '계약서가 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'삭제 실패: {str(e)}'}), 500


@contracts_bp.route('/<int:id>/download', methods=['GET'])
@token_required
def download_contract_file(current_user, id):
    """계약서/최종보고서 파일 다운로드 (Bearer 토큰 방식)"""
    try:
        contract = Contract.query.get_or_404(id)

        if not contract.file_path:
            return jsonify({'success': False, 'message': '파일이 없습니다.'}), 404

        project = ConsultingProject.query.get(contract.consulting_project_id)
        if contract.document_type == 'final_report':
            lang_text = '국문' if contract.order_number == 1 else '영문'
            doc_label = f'최종보고서_{lang_text}'
        else:
            doc_label = f'{contract.order_number}차계약서' if contract.order_number else '계약서'

        file_ext = contract.file_type if contract.file_type else 'pdf'
        download_name = make_overseas_tech_filename(doc_label, file_ext, project)

        try:
            return stream_from_r2(contract.file_path, download_name=download_name)
        except Exception:
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': f'다운로드 실패: {str(e)}'}), 500


@contracts_bp.route('/download/<int:contract_id>', methods=['GET'])
def download_contract(contract_id):
    """계약서 다운로드"""
    try:
        # 쿼리 파라미터 또는 헤더에서 토큰 가져오기
        token = request.args.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')

        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

        # 토큰 검증
        from routes.auth import verify_token
        user = verify_token(token)
        if not user:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다.'}), 401

        contract = Contract.query.get_or_404(contract_id)

        if not contract.file_path:
            return jsonify({'success': False, 'message': '파일 경로가 없습니다.'}), 404

        project = ConsultingProject.query.get(contract.consulting_project_id)
        if contract.document_type == 'final_report':
            lang_text = '국문' if contract.order_number == 1 else '영문'
            doc_label = f'최종보고서_{lang_text}'
        else:
            doc_label = f'{contract.order_number}차계약서' if contract.order_number else '계약서'

        file_ext = contract.file_type if contract.file_type else 'pdf'
        download_name = make_overseas_tech_filename(doc_label, file_ext, project)

        try:
            return stream_from_r2(contract.file_path, download_name=download_name)
        except Exception:
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': f'다운로드 실패: {str(e)}'}), 500


@contracts_bp.route('/preview/<int:contract_id>', methods=['GET'])
def preview_contract(contract_id):
    """계약서 미리보기"""
    try:
        # 쿼리 파라미터 또는 헤더에서 토큰 가져오기
        token = request.args.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')

        if not token:
            return '<html><body><h1>인증 오류</h1><p>인증 토큰이 필요합니다.</p></body></html>', 401

        # 토큰 검증
        from routes.auth import verify_token
        user = verify_token(token)
        if not user:
            return '<html><body><h1>인증 오류</h1><p>유효하지 않은 토큰입니다.</p></body></html>', 401

        contract = Contract.query.get(contract_id)
        if not contract:
            return '<html><body><h1>오류</h1><p>계약서를 찾을 수 없습니다.</p></body></html>', 404

        if not contract.file_path:
            return '<html><body><h1>오류</h1><p>파일 경로가 없습니다.</p></body></html>', 404

        mimetype = 'application/pdf' if contract.file_type == 'pdf' else f'application/{contract.file_type}'
        try:
            return stream_from_r2(contract.file_path, content_type=mimetype, inline=True)
        except Exception:
            return '<html><body><h1>오류</h1><p>파일을 찾을 수 없습니다.</p></body></html>', 404

    except Exception as e:
        return f'<html><body><h1>오류</h1><p>미리보기 실패: {str(e)}</p></body></html>', 500


@contracts_bp.route('/countries', methods=['GET'])
@token_required
def get_countries(current_user):
    """계약서가 있는 프로젝트 국가 목록 조회"""
    try:
        countries = db.session.query(ConsultingProject.country).distinct().order_by(ConsultingProject.country).all()
        country_list = [c[0] for c in countries if c[0]]

        return jsonify({
            'success': True,
            'data': country_list
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'국가 목록 조회 실패: {str(e)}'}), 500


@contracts_bp.route('/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    """계약서 통계"""
    try:
        total_contracts = Contract.query.count()
        
        # 올해 등록된 계약서
        current_year = datetime.now().year
        this_year_contracts = Contract.query.filter(
            db.extract('year', Contract.created_at) == current_year
        ).count()

        # 계약서가 있는 프로젝트 수
        projects_with_contracts = db.session.query(Contract.consulting_project_id).distinct().count()

        # 전체 프로젝트 수
        total_projects = ConsultingProject.query.count()

        return jsonify({
            'success': True,
            'data': {
                'totalContracts': total_contracts,
                'thisYearContracts': this_year_contracts,
                'projectsWithContracts': projects_with_contracts,
                'totalProjects': total_projects
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'통계 조회 실패: {str(e)}'}), 500
