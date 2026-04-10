"""
GBMS - ODA Reports Routes
글로벌사업처 해외사업관리시스템 - ODA 보고서관리 API
"""
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
import os
from models import db, OdaReport, OdaProject, OdaNote, ActivityLog
from routes.auth import token_required, admin_required, permission_required
from utils.file_naming import make_oda_report_filename, make_oda_report_disk_filename

oda_reports_bp = Blueprint('oda_reports', __name__)

# 업로드 디렉토리 설정
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'oda_reports')
NOTE_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads', 'oda_notes')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'hwp', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'zip'}

# 업로드 폴더 생성 (Vercel 등 읽기 전용 파일시스템에서는 무시)
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(NOTE_UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass

def allowed_file(filename):
    """파일 확장자 검증"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@oda_reports_bp.route('', methods=['GET'])
@token_required
def get_all_reports_by_project(current_user):
    """모든 ODA 프로젝트와 보고서 목록 조회"""
    try:
        # 쿼리 파라미터
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        country = request.args.get('country')
        search = request.args.get('search')
        status = request.args.get('status')

        # ODA 프로젝트 쿼리
        query = OdaProject.query

        if country:
            query = query.filter(OdaProject.country == country)

        if status:
            query = query.filter(OdaProject.status == status)

        if search:
            query = query.filter(
                db.or_(
                    OdaProject.title.ilike(f'%{search}%'),
                    OdaProject.country.ilike(f'%{search}%')
                )
            )

        # 정렬: 준공년도(끝 연도) 내림차순, 같으면 사업명 가나다순
        # period 형식: '22-'25 → 끝 2자리 추출하여 정렬
        query = query.order_by(
            db.func.substr(OdaProject.period, -2).desc().nullslast(),
            OdaProject.title.asc()
        )

        # 페이지네이션
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        # 각 프로젝트별 보고서 정보 포함
        projects_data = []
        for project in pagination.items:
            project_dict = project.to_dict()

            # 각 보고서 타입별 조회 (다중 파일 지원 - 배열 반환)
            reports = {}
            report_types = ['pcp', 'implementation_plan', 'fs', 'rod', 'proposal', 'pmc', 'performance', 'post_evaluation']
            for report_type in report_types:
                type_reports = OdaReport.query.filter_by(
                    oda_project_id=project.id,
                    report_type=report_type
                ).order_by(OdaReport.created_at.asc()).all()
                reports[report_type] = [r.to_dict() for r in type_reports]

            project_dict['reports'] = reports

            # 비고(note) 데이터 포함
            note = OdaNote.query.filter_by(oda_project_id=project.id).first()
            project_dict['note'] = note.to_dict() if note else None

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
        return jsonify({'success': False, 'message': f'보고서 목록 조회 실패: {str(e)}'}), 500


@oda_reports_bp.route('/project/<int:project_id>', methods=['GET'])
@token_required
def get_project_reports(current_user, project_id):
    """특정 프로젝트의 모든 보고서 조회"""
    try:
        project = OdaProject.query.get_or_404(project_id)

        reports = OdaReport.query.filter_by(oda_project_id=project_id).all()

        return jsonify({
            'success': True,
            'data': {
                'project': project.to_dict(),
                'reports': [report.to_dict() for report in reports]
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'보고서 조회 실패: {str(e)}'}), 500


@oda_reports_bp.route('/upload', methods=['POST'])
@permission_required('oda')
def upload_report(current_user):
    """보고서 업로드 (ODA 권한 필요)"""
    try:
        # 파라미터 검증
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다.'}), 400

        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': '허용되지 않는 파일 형식입니다.'}), 400

        oda_project_id = request.form.get('odaProjectId', type=int)
        report_type = request.form.get('reportType')
        description = request.form.get('description', '')

        if not oda_project_id or not report_type:
            return jsonify({'success': False, 'message': '필수 파라미터가 누락되었습니다.'}), 400

        # 프로젝트 존재 확인
        project = OdaProject.query.get(oda_project_id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        # 파일 저장 - 원본 파일명에서 확장자 추출
        original_filename = file.filename
        file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''

        # 표준 파일명 생성
        download_name = make_oda_report_filename(report_type, file_ext, project)
        disk_name = make_oda_report_disk_filename(report_type, file_ext, project)
        file_path = os.path.join(UPLOAD_FOLDER, disk_name)

        file.save(file_path)
        file_size = os.path.getsize(file_path)

        # 항상 새 레코드 생성 (다중 파일 지원)
        report = OdaReport(
            oda_project_id=oda_project_id,
            report_type=report_type,
            file_name=download_name,
            file_path=disk_name,
            file_size=file_size,
            file_type=file_ext,
            description=description,
            created_by=current_user.id
        )
        db.session.add(report)
        message = '보고서가 등록되었습니다.'

        # 활동 로그
        log = ActivityLog(
            user_id=current_user.id,
            action='upload',
            entity_type='oda_report',
            entity_id=None,
            description=f'ODA 보고서 업로드: {project.title} - {report_type}',
            ip_address=request.remote_addr
        )
        db.session.add(log)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': message,
            'data': report.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'업로드 실패: {str(e)}'}), 500


@oda_reports_bp.route('/<int:report_id>', methods=['DELETE'])
@permission_required('oda')
def delete_report(current_user, report_id):
    """보고서 삭제 (ODA 권한 필요)"""
    try:
        report = OdaReport.query.get_or_404(report_id)

        # 파일 삭제
        if report.file_path:
            file_path = os.path.join(UPLOAD_FOLDER, report.file_path)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"파일 삭제 실패: {str(e)}")

        # 활동 로그
        log = ActivityLog(
            user_id=current_user.id,
            action='delete',
            entity_type='oda_report',
            entity_id=report.id,
            description=f'ODA 보고서 삭제: {report.report_type}',
            ip_address=request.remote_addr
        )
        db.session.add(log)

        db.session.delete(report)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '보고서가 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'삭제 실패: {str(e)}'}), 500


@oda_reports_bp.route('/download/<int:report_id>', methods=['GET'])
def download_report(report_id):
    """보고서 다운로드"""
    try:
        # 쿼리 파라미터 또는 헤더에서 토큰 가져오기
        token = request.args.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')

        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

        # 토큰 검증 (간단한 방식 - 실제로는 JWT 검증 필요)
        from routes.auth import verify_token
        user = verify_token(token)
        if not user:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다.'}), 401

        report = OdaReport.query.get_or_404(report_id)

        if not report.file_path:
            return jsonify({'success': False, 'message': '파일 경로가 없습니다.'}), 404

        # 파일 경로 생성 (파일명만 저장되어 있으므로 UPLOAD_FOLDER와 결합)
        file_path = os.path.join(UPLOAD_FOLDER, report.file_path)

        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

        # 프로젝트 정보 가져오기
        from models import OdaProject
        project = OdaProject.query.get(report.oda_project_id)

        # 표준 다운로드 파일명 생성
        file_ext = report.file_type if report.file_type else 'pdf'
        download_name = make_oda_report_filename(report.report_type, file_ext, project)

        return send_file(
            file_path,
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        return jsonify({'success': False, 'message': f'다운로드 실패: {str(e)}'}), 500


@oda_reports_bp.route('/preview/<int:report_id>', methods=['GET'])
def preview_report(report_id):
    """보고서 미리보기"""
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

        report = OdaReport.query.get(report_id)
        if not report:
            return '<html><body><h1>오류</h1><p>보고서를 찾을 수 없습니다.</p></body></html>', 404

        if not report.file_path:
            return '<html><body><h1>오류</h1><p>파일 경로가 없습니다.</p></body></html>', 404

        # 파일 경로 생성 (파일명만 저장되어 있으므로 UPLOAD_FOLDER와 결합)
        file_path = os.path.join(UPLOAD_FOLDER, report.file_path)

        if not os.path.exists(file_path):
            return f'<html><body><h1>오류</h1><p>파일을 찾을 수 없습니다: {report.file_path}</p></body></html>', 404

        # PDF 등은 브라우저에서 직접 표시 (다운로드 아님)
        # 파일 확장자 기반 mimetype 결정 (DB file_type이 비어있을 수 있으므로 파일명에서도 추출)
        ext = report.file_type or ''
        if not ext and report.file_path:
            ext = report.file_path.rsplit('.', 1)[1].lower() if '.' in report.file_path else ''
        mimetype_map = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'ppt': 'application/vnd.ms-powerpoint',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'hwp': 'application/x-hwp',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'txt': 'text/plain',
        }
        mimetype = mimetype_map.get(ext, 'application/octet-stream')
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=False  # 미리보기 모드
        )

    except Exception as e:
        return f'<html><body><h1>오류</h1><p>미리보기 실패: {str(e)}</p></body></html>', 500


@oda_reports_bp.route('/countries', methods=['GET'])
@token_required
def get_countries(current_user):
    """보고서가 있는 국가 목록 조회"""
    try:
        countries = db.session.query(OdaProject.country).distinct().order_by(OdaProject.country).all()
        country_list = [c[0] for c in countries if c[0]]

        return jsonify({
            'success': True,
            'data': country_list
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'국가 목록 조회 실패: {str(e)}'}), 500


# ==================== 비고(Note) API ====================

@oda_reports_bp.route('/note/<int:project_id>', methods=['GET'])
@token_required
def get_note(current_user, project_id):
    """프로젝트 비고 조회"""
    try:
        note = OdaNote.query.filter_by(oda_project_id=project_id).first()
        return jsonify({
            'success': True,
            'data': note.to_dict() if note else None
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'비고 조회 실패: {str(e)}'}), 500


@oda_reports_bp.route('/note', methods=['POST'])
@permission_required('oda')
def save_note(current_user):
    """비고 저장 (메모 + 파일)"""
    try:
        oda_project_id = request.form.get('odaProjectId', type=int)
        memo = request.form.get('memo', '').strip()

        if not oda_project_id:
            return jsonify({'success': False, 'message': '프로젝트 ID가 필요합니다.'}), 400

        # 메모 길이 검증
        if len(memo) > 500:
            return jsonify({'success': False, 'message': '메모는 500자를 초과할 수 없습니다.'}), 400

        # 프로젝트 존재 확인
        project = OdaProject.query.get(oda_project_id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        # 기존 비고 확인
        note = OdaNote.query.filter_by(oda_project_id=oda_project_id).first()

        # 파일 처리
        file = request.files.get('file')
        new_file_name = None
        new_file_path = None
        new_file_size = None
        new_file_type = None

        if file and file.filename:
            if not allowed_file(file.filename):
                return jsonify({'success': False, 'message': '허용되지 않는 파일 형식입니다.'}), 400

            original_filename = file.filename
            file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
            new_file_name = secure_filename(original_filename) or f'note.{file_ext}'
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            saved_filename = f"{timestamp}_note_{oda_project_id}.{file_ext}"
            file_full_path = os.path.join(NOTE_UPLOAD_FOLDER, saved_filename)

            # 기존 파일 삭제
            if note and note.file_path:
                old_path = os.path.join(NOTE_UPLOAD_FOLDER, note.file_path)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except:
                        pass

            file.save(file_full_path)
            new_file_name = original_filename
            new_file_path = saved_filename
            new_file_size = os.path.getsize(file_full_path)
            new_file_type = file_ext

        if note:
            # 업데이트
            note.memo = memo
            if new_file_path:
                note.file_name = new_file_name
                note.file_path = new_file_path
                note.file_size = new_file_size
                note.file_type = new_file_type
            note.updated_at = datetime.utcnow()
            message = '비고가 수정되었습니다.'
        else:
            # 새로 생성
            note = OdaNote(
                oda_project_id=oda_project_id,
                memo=memo,
                file_name=new_file_name,
                file_path=new_file_path,
                file_size=new_file_size,
                file_type=new_file_type,
                created_by=current_user.id
            )
            db.session.add(note)
            message = '비고가 등록되었습니다.'

        db.session.commit()

        return jsonify({
            'success': True,
            'message': message,
            'data': note.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'비고 저장 실패: {str(e)}'}), 500


@oda_reports_bp.route('/note/<int:note_id>', methods=['DELETE'])
@permission_required('oda')
def delete_note(current_user, note_id):
    """비고 삭제"""
    try:
        note = OdaNote.query.get_or_404(note_id)

        # 파일 삭제
        if note.file_path:
            file_path = os.path.join(NOTE_UPLOAD_FOLDER, note.file_path)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass

        db.session.delete(note)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '비고가 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'비고 삭제 실패: {str(e)}'}), 500


@oda_reports_bp.route('/note/delete-file/<int:note_id>', methods=['POST'])
@permission_required('oda')
def delete_note_file(current_user, note_id):
    """비고 첨부파일만 삭제"""
    try:
        note = OdaNote.query.get_or_404(note_id)

        if note.file_path:
            file_path = os.path.join(NOTE_UPLOAD_FOLDER, note.file_path)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass

        note.file_name = None
        note.file_path = None
        note.file_size = None
        note.file_type = None
        note.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            'success': True,
            'message': '첨부파일이 삭제되었습니다.',
            'data': note.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'파일 삭제 실패: {str(e)}'}), 500


@oda_reports_bp.route('/note/download/<int:note_id>', methods=['GET'])
def download_note_file(note_id):
    """비고 첨부파일 다운로드"""
    try:
        token = request.args.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'success': False, 'message': '인증 토큰이 필요합니다.'}), 401

        from routes.auth import verify_token
        user = verify_token(token)
        if not user:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다.'}), 401

        note = OdaNote.query.get_or_404(note_id)

        if not note.file_path:
            return jsonify({'success': False, 'message': '첨부파일이 없습니다.'}), 404

        file_path = os.path.join(NOTE_UPLOAD_FOLDER, note.file_path)
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

        download_name = note.file_name or f'note.{note.file_type or "dat"}'

        return send_file(
            file_path,
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        return jsonify({'success': False, 'message': f'다운로드 실패: {str(e)}'}), 500
