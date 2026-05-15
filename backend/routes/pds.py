"""
GBMS - PDS(Project Data Sheet) API 라우트
해외기술용역 사업별 PDS 조회/편집/자동추출/DOCX 다운로드
"""
from flask import Blueprint, jsonify, request, current_app, send_file
from routes.auth import token_required, permission_required
from models import db, ConsultingProject
from datetime import datetime
import re

pds_bp = Blueprint('pds', __name__)


@pds_bp.route('/<int:id>/pds', methods=['GET'])
@token_required
def get_pds_data(current_user, id):
    """PDS JSON 데이터 조회 (미리보기용)"""
    try:
        project = ConsultingProject.query.get(id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        from utils.pds_generator import build_pds_dict, _format_date_pds, _calc_duration_months, _format_usd, _format_currency, _build_consortium_names

        # 8행 2열 셀 데이터
        pds_rows = build_pds_dict(project)

        # 프론트에서 편집 폼에 필요한 raw 데이터도 함께 전달
        data = {
            'id': project.id,
            'titleKr': project.title_kr,
            'titleEn': project.title_en,
            'country': project.country,
            'client': project.client,
            'startDate': project.start_date,
            'endDate': project.end_date,
            'budget': float(project.budget) if project.budget else None,
            'budgetUsd': float(project.budget_usd) if project.budget_usd else None,
            'krcBudget': float(project.krc_budget) if project.krc_budget else None,
            'krcBudgetUsd': float(project.krc_budget_usd) if project.krc_budget_usd else None,
            'krcShareRatio': float(project.krc_share_ratio) if project.krc_share_ratio else None,
            'leadCompany': project.lead_company,
            'descriptionEn': project.description_en,
            'description': project.description,
            # PDS 전용 필드
            'pdsLocationWithinCountry': project.pds_location_within_country,
            'pdsClientAddress': project.pds_client_address,
            'pdsTotalStaffMonths': project.pds_total_staff_months,
            'pdsAssociatedStaffMonths': project.pds_associated_staff_months,
            'pdsSeniorStaff': project.pds_senior_staff,
            'pdsNarrativeDescriptionEn': project.pds_narrative_description_en,
            'pdsServicesDescriptionEn': project.pds_services_description_en,
            'pdsExtractedAt': project.pds_extracted_at.isoformat() if project.pds_extracted_at else None,
            # 8행 2열 표 렌더링용
            'rows': [{'left': left, 'right': right} for left, right in pds_rows],
        }

        return jsonify({'success': True, 'data': data})

    except Exception as e:
        current_app.logger.error(f'PDS 데이터 조회 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@pds_bp.route('/<int:id>/pds', methods=['PUT'])
@permission_required('overseas_tech')
def update_pds_data(current_user, id):
    """PDS 보조 필드 수정"""
    try:
        project = ConsultingProject.query.get(id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '요청 데이터가 없습니다.'}), 400

        # PDS 전용 필드만 업데이트
        pds_fields = {
            'pdsLocationWithinCountry': 'pds_location_within_country',
            'pdsClientAddress': 'pds_client_address',
            'pdsTotalStaffMonths': 'pds_total_staff_months',
            'pdsAssociatedStaffMonths': 'pds_associated_staff_months',
            'pdsSeniorStaff': 'pds_senior_staff',
            'pdsNarrativeDescriptionEn': 'pds_narrative_description_en',
            'pdsServicesDescriptionEn': 'pds_services_description_en',
        }

        updated = []
        for camel_key, db_field in pds_fields.items():
            if camel_key in data:
                value = data[camel_key]
                # 빈 문자열은 None으로 저장
                if isinstance(value, str) and not value.strip():
                    value = None
                setattr(project, db_field, value)
                updated.append(camel_key)

        if updated:
            project.updated_at = datetime.utcnow()
            db.session.commit()

        return jsonify({
            'success': True,
            'message': f'{len(updated)}개 항목이 저장되었습니다.',
            'updatedFields': updated,
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'PDS 데이터 수정 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@pds_bp.route('/<int:id>/pds/extract', methods=['POST'])
@permission_required('overseas_tech')
def extract_pds_data(current_user, id):
    """첨부문서 자동 추출"""
    try:
        project = ConsultingProject.query.get(id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        from utils.pds_extractor import extract_pds_data as do_extract
        result = do_extract(id)

        updated_count = len(result.get('updatedFields', []))
        skipped_count = len(result.get('skippedFiles', []))
        message = f'{updated_count}개 항목이 자동 추출되었습니다.'
        if skipped_count:
            message += f' ({skipped_count}개 파일 건너뜀)'

        return jsonify({
            'success': True,
            'message': message,
            'data': result,
        })

    except Exception as e:
        current_app.logger.error(f'PDS 자동 추출 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500


@pds_bp.route('/<int:id>/pds/download', methods=['GET'])
@token_required
def download_pds_docx(current_user, id):
    """PDS DOCX 파일 다운로드"""
    try:
        project = ConsultingProject.query.get(id)
        if not project:
            return jsonify({'success': False, 'message': '프로젝트를 찾을 수 없습니다.'}), 404

        from utils.pds_generator import generate_pds_docx

        buffer = generate_pds_docx(project)

        # 파일명 생성 (한글 사업명 우선)
        name = project.title_kr or project.title_en or 'PDS'
        # 파일명에서 위험 문자 제거
        safe_name = re.sub(r'[<>:"/\\|?*]', '', name)
        download_name = f'{safe_name}_PDS.docx'

        return send_file(
            buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=download_name,
        )

    except Exception as e:
        current_app.logger.error(f'PDS 다운로드 오류: {str(e)}')
        return jsonify({'success': False, 'message': str(e)}), 500
