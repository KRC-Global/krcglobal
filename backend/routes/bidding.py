"""
TOR/RFP·제안서 통합 API
ConsultingProject를 기준으로 TorRfp, Proposal, Eoi를 LEFT JOIN하여 통합 목록 제공
"""
from flask import Blueprint, jsonify, request, current_app
from models import db, ConsultingProject, TorRfp, Proposal, Eoi
from routes.auth import token_required
from utils.file_naming import make_overseas_tech_filename, make_overseas_tech_disk_filename
from utils.r2_storage import upload_file, delete_file, check_storage_limit, stream_from_r2
from sqlalchemy import or_
from werkzeug.utils import secure_filename
from datetime import datetime

bidding_bp = Blueprint('bidding', __name__)


def _row_to_dict(row, source):
    """행 데이터를 딕셔너리로 변환"""
    return {
        'projectId': row.get('project_id'),
        'title': row.get('title'),
        'status': row.get('status'),
        'country': row.get('country'),
        'client': row.get('client'),
        'endDate': row.get('end_date'),
        'torRfpId': row.get('tor_rfp_id'),
        'torFileName': row.get('tor_file_name'),
        'rfpFileName': row.get('rfp_file_name'),
        'proposalId': row.get('proposal_id'),
        'submissionDate': row.get('submission_date'),
        'budget': row.get('budget'),
        'result': row.get('result'),
        'technicalFileName': row.get('technical_file_name'),
        'priceFileName': row.get('price_file_name'),
        'eoiId': row.get('eoi_id'),
        'eoiFileName': row.get('eoi_file_name'),
        'eoiSubmissionDate': row.get('eoi_submission_date'),
        'eoiResult': row.get('eoi_result'),
        'source': source
    }


@bidding_bp.route('', methods=['GET'])
@token_required
def get_bidding_list(current_user):
    """통합 입찰 목록 조회"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '')
        country = request.args.get('country', '')
        result_filter = request.args.get('result', '')
        year = request.args.get('year', type=int)

        all_rows = []

        # 1) ConsultingProject 기준 LEFT JOIN
        project_query = db.session.query(
            ConsultingProject, TorRfp, Proposal, Eoi
        ).outerjoin(
            TorRfp, ConsultingProject.id == TorRfp.consulting_project_id
        ).outerjoin(
            Proposal, ConsultingProject.id == Proposal.consulting_project_id
        ).outerjoin(
            Eoi, ConsultingProject.id == Eoi.consulting_project_id
        )

        for cp, tr, pr, eoi in project_query.all():
            row = {
                'project_id': cp.id,
                'title': cp.title_kr,
                'status': cp.status,
                'country': cp.country,
                'client': cp.client,
                'end_date': cp.end_date if cp.end_date else None,
                'tor_rfp_id': tr.id if tr else None,
                'tor_file_name': tr.tor_file_name if tr else None,
                'rfp_file_name': tr.rfp_file_name if tr else None,
                'proposal_id': pr.id if pr else None,
                'submission_date': pr.submission_date.isoformat() if pr and pr.submission_date else None,
                'budget': float(pr.budget) if pr and pr.budget else None,
                'result': pr.result if pr else None,
                'technical_file_name': pr.technical_file_name if pr else None,
                'price_file_name': pr.price_file_name if pr else None,
                'eoi_id': eoi.id if eoi else None,
                'eoi_file_name': eoi.eoi_file_name if eoi else None,
                'eoi_submission_date': eoi.submission_date.isoformat() if eoi and eoi.submission_date else None,
                'eoi_result': eoi.result if eoi else None,
            }
            all_rows.append(_row_to_dict(row, 'project'))

        # 2) 독립 TOR/RFP (consulting_project_id IS NULL)
        standalone_tors = TorRfp.query.filter(TorRfp.consulting_project_id.is_(None)).all()
        for tr in standalone_tors:
            row = {
                'project_id': None,
                'title': tr.title,
                'country': tr.country,
                'client': None,
                'end_date': None,
                'tor_rfp_id': tr.id,
                'tor_file_name': tr.tor_file_name,
                'rfp_file_name': tr.rfp_file_name,
                'proposal_id': None,
                'submission_date': None,
                'budget': None,
                'result': None,
                'technical_file_name': None,
                'price_file_name': None,
                'eoi_id': None,
                'eoi_file_name': None,
                'eoi_submission_date': None,
                'eoi_result': None,
            }
            all_rows.append(_row_to_dict(row, 'tor_rfp'))

        # 3) 독립 제안서 (consulting_project_id IS NULL)
        standalone_proposals = Proposal.query.filter(Proposal.consulting_project_id.is_(None)).all()
        for pr in standalone_proposals:
            row = {
                'project_id': None,
                'title': pr.title,
                'country': pr.country,
                'client': pr.client,
                'end_date': None,
                'tor_rfp_id': None,
                'tor_file_name': None,
                'rfp_file_name': None,
                'proposal_id': pr.id,
                'submission_date': pr.submission_date.isoformat() if pr.submission_date else None,
                'budget': float(pr.budget) if pr.budget else None,
                'result': pr.result,
                'technical_file_name': pr.technical_file_name,
                'price_file_name': pr.price_file_name,
                'eoi_id': None,
                'eoi_file_name': None,
                'eoi_submission_date': None,
                'eoi_result': None,
            }
            all_rows.append(_row_to_dict(row, 'proposal'))

        # 4) 독립 EOI (consulting_project_id IS NULL)
        standalone_eois = Eoi.query.filter(Eoi.consulting_project_id.is_(None)).all()
        for eoi in standalone_eois:
            row = {
                'project_id': None,
                'title': eoi.title,
                'country': eoi.country,
                'client': eoi.client,
                'end_date': None,
                'tor_rfp_id': None,
                'tor_file_name': None,
                'rfp_file_name': None,
                'proposal_id': None,
                'submission_date': None,
                'budget': None,
                'result': None,
                'technical_file_name': None,
                'price_file_name': None,
                'eoi_id': eoi.id,
                'eoi_file_name': eoi.eoi_file_name,
                'eoi_submission_date': eoi.submission_date.isoformat() if eoi.submission_date else None,
                'eoi_result': eoi.result,
            }
            all_rows.append(_row_to_dict(row, 'eoi'))

        # 필터 적용
        if search:
            s = search.lower()
            all_rows = [r for r in all_rows if
                        (r['title'] and s in r['title'].lower()) or
                        (r['country'] and s in r['country'].lower()) or
                        (r['client'] and s in r['client'].lower())]
        if country:
            all_rows = [r for r in all_rows if r['country'] == country]
        if result_filter:
            all_rows = [r for r in all_rows if r['result'] == result_filter]
        if year:
            all_rows = [r for r in all_rows if
                        r['submissionDate'] and r['submissionDate'][:4] == str(year)]

        # 정렬: end_date 내림차순 (null 마지막), submission_date 내림차순, title
        def sort_key(r):
            ed = r.get('endDate') or ''
            sd = r.get('submissionDate') or ''
            t = r.get('title') or ''
            return (0 if ed else 1, ed, 0 if sd else 1, sd, t)

        all_rows.sort(key=sort_key, reverse=False)
        # 역정렬: ed desc, sd desc이므로 두 번째 정렬
        all_rows.sort(key=lambda r: (
            0 if r.get('endDate') else 1,
            r.get('endDate') or '',
            0 if r.get('submissionDate') else 1,
            r.get('submissionDate') or '',
        ), reverse=True)

        total = len(all_rows)

        # 페이지네이션
        start = (page - 1) * per_page
        items = all_rows[start:start + per_page]

        pages = (total + per_page - 1) // per_page if total > 0 else 1

        return jsonify({
            'success': True,
            'data': items,
            'total': total,
            'pages': pages,
            'currentPage': page,
            'perPage': per_page
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/stats', methods=['GET'])
@token_required
def get_bidding_stats(current_user):
    """통합 통계"""
    try:
        total_projects = ConsultingProject.query.count()
        tor_count = TorRfp.query.filter(TorRfp.tor_file_name.isnot(None)).count()
        rfp_count = TorRfp.query.filter(TorRfp.rfp_file_name.isnot(None)).count()

        total_proposals = Proposal.query.count()
        selected = Proposal.query.filter(Proposal.result == '선정').count()
        rejected = Proposal.query.filter(Proposal.result == '탈락').count()
        pending = Proposal.query.filter(Proposal.result == '심사중').count()
        success_rate = round(selected / total_proposals * 100, 1) if total_proposals > 0 else 0

        # EOI 통계
        eoi_count = Eoi.query.count()

        return jsonify({
            'success': True,
            'data': {
                'totalProjects': total_projects,
                'torCount': tor_count,
                'rfpCount': rfp_count,
                'totalProposals': total_proposals,
                'selected': selected,
                'rejected': rejected,
                'pending': pending,
                'successRate': success_rate,
                'eoiCount': eoi_count
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/countries', methods=['GET'])
@token_required
def get_countries(current_user):
    """국가 목록 (ConsultingProject + Proposal + Eoi 통합)"""
    try:
        project_countries = db.session.query(ConsultingProject.country).distinct().filter(
            ConsultingProject.country.isnot(None)
        )
        proposal_countries = db.session.query(Proposal.country).distinct().filter(
            Proposal.country.isnot(None)
        )
        eoi_countries = db.session.query(Eoi.country).distinct().filter(
            Eoi.country.isnot(None)
        )

        all_countries = set()
        for (c,) in project_countries:
            if c:
                all_countries.add(c)
        for (c,) in proposal_countries:
            if c:
                all_countries.add(c)
        for (c,) in eoi_countries:
            if c:
                all_countries.add(c)

        return jsonify({
            'success': True,
            'data': sorted(list(all_countries))
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ EOI API ============

@bidding_bp.route('/eoi', methods=['POST'])
@token_required
def create_eoi(current_user):
    """EOI 등록"""
    try:
        # 파일 처리
        eoi_file = request.files.get('eoiFile')

        # 폼 데이터
        consulting_project_id = request.form.get('consultingProjectId')
        if consulting_project_id:
            consulting_project_id = int(consulting_project_id) if consulting_project_id != 'null' else None
        else:
            consulting_project_id = None

        title = request.form.get('title')
        country = request.form.get('country')
        client = request.form.get('client')
        submission_date_str = request.form.get('submissionDate')
        result = request.form.get('result')
        remarks = request.form.get('remarks')

        # 제출일 파싱
        submission_date = None
        if submission_date_str:
            submission_date = datetime.strptime(submission_date_str, '%Y-%m-%d').date()

        # EOI 생성
        eoi = Eoi(
            consulting_project_id=consulting_project_id,
            title=title,
            country=country,
            client=client,
            submission_date=submission_date,
            result=result,
            remarks=remarks,
            created_by=current_user.id
        )

        # R2 파일 업로드
        if eoi_file:
            original = secure_filename(eoi_file.filename)
            ext = original.rsplit('.', 1)[-1].lower() if '.' in original else 'pdf'
            eoi_file.seek(0, 2); eoi_size = eoi_file.tell(); eoi_file.seek(0)
            if not check_storage_limit(eoi_size):
                return jsonify({'success': False, 'message': '스토리지 용량이 부족합니다.'}), 400
            _eoi_proj = ConsultingProject.query.get(consulting_project_id) if consulting_project_id else None
            _eoi_year = submission_date.year if submission_date else None
            saved_name = make_overseas_tech_disk_filename('EOI', ext, _eoi_proj, title, _eoi_year)
            r2_key = f'eoi/{saved_name}'
            upload_file(eoi_file, r2_key, content_type=f'application/{ext}')
            eoi.eoi_file_name = make_overseas_tech_filename('EOI', ext, _eoi_proj, title, _eoi_year)
            eoi.eoi_file_path = r2_key
            eoi.eoi_file_size = eoi_size
            eoi.eoi_file_type = ext

        db.session.add(eoi)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'EOI가 등록되었습니다.',
            'data': eoi.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/eoi/<int:eoi_id>', methods=['GET'])
@token_required
def get_eoi(current_user, eoi_id):
    """EOI 상세 조회"""
    try:
        eoi = Eoi.query.get(eoi_id)
        if not eoi:
            return jsonify({'success': False, 'message': 'EOI를 찾을 수 없습니다.'}), 404

        return jsonify({
            'success': True,
            'data': eoi.to_dict()
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/eoi/<int:eoi_id>', methods=['PUT'])
@token_required
def update_eoi(current_user, eoi_id):
    """EOI 수정"""
    try:
        eoi = Eoi.query.get(eoi_id)
        if not eoi:
            return jsonify({'success': False, 'message': 'EOI를 찾을 수 없습니다.'}), 404

        # 파일 처리
        eoi_file = request.files.get('eoiFile')

        # 폼 데이터
        consulting_project_id = request.form.get('consultingProjectId')
        if consulting_project_id:
            eoi.consulting_project_id = int(consulting_project_id) if consulting_project_id != 'null' else None
        else:
            eoi.consulting_project_id = None

        eoi.title = request.form.get('title')
        eoi.country = request.form.get('country')
        eoi.client = request.form.get('client')

        submission_date_str = request.form.get('submissionDate')
        if submission_date_str:
            eoi.submission_date = datetime.strptime(submission_date_str, '%Y-%m-%d').date()
        else:
            eoi.submission_date = None

        eoi.result = request.form.get('result')
        eoi.remarks = request.form.get('remarks')
        eoi.updated_by = current_user.id

        # 새 파일이 있으면 R2에 교체
        if eoi_file:
            if eoi.eoi_file_path:
                try:
                    delete_file(eoi.eoi_file_path)
                except Exception:
                    pass
            original = secure_filename(eoi_file.filename)
            ext = original.rsplit('.', 1)[-1].lower() if '.' in original else 'pdf'
            eoi_file.seek(0, 2); eoi_size = eoi_file.tell(); eoi_file.seek(0)
            _upd_proj = ConsultingProject.query.get(eoi.consulting_project_id) if eoi.consulting_project_id else None
            _upd_year = eoi.submission_date.year if eoi.submission_date else None
            saved_name = make_overseas_tech_disk_filename('EOI', ext, _upd_proj, eoi.title, _upd_year)
            r2_key = f'eoi/{saved_name}'
            upload_file(eoi_file, r2_key, content_type=f'application/{ext}')
            eoi.eoi_file_name = make_overseas_tech_filename('EOI', ext, _upd_proj, eoi.title, _upd_year)
            eoi.eoi_file_path = r2_key
            eoi.eoi_file_size = eoi_size
            eoi.eoi_file_type = ext

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'EOI가 수정되었습니다.',
            'data': eoi.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/eoi/<int:eoi_id>', methods=['DELETE'])
@token_required
def delete_eoi(current_user, eoi_id):
    """EOI 삭제"""
    try:
        eoi = Eoi.query.get(eoi_id)
        if not eoi:
            return jsonify({'success': False, 'message': 'EOI를 찾을 수 없습니다.'}), 404

        # R2 파일 삭제
        if eoi.eoi_file_path:
            try:
                delete_file(eoi.eoi_file_path)
            except Exception:
                pass

        db.session.delete(eoi)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'EOI가 삭제되었습니다.'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/eoi/<int:eoi_id>/preview', methods=['GET'])
@token_required
def preview_eoi(current_user, eoi_id):
    """EOI 파일 미리보기"""
    try:
        eoi = Eoi.query.get(eoi_id)
        if not eoi:
            return jsonify({'success': False, 'message': 'EOI를 찾을 수 없습니다.'}), 404

        if not eoi.eoi_file_path:
            return jsonify({'success': False, 'message': '파일이 존재하지 않습니다.'}), 404
        try:
            return stream_from_r2(eoi.eoi_file_path, content_type='application/pdf', inline=True)
        except Exception:
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@bidding_bp.route('/eoi/<int:eoi_id>/download', methods=['GET'])
@token_required
def download_eoi(current_user, eoi_id):
    """EOI 파일 다운로드"""
    try:
        eoi = Eoi.query.get(eoi_id)
        if not eoi:
            return jsonify({'success': False, 'message': 'EOI를 찾을 수 없습니다.'}), 404

        if not eoi.eoi_file_path:
            return jsonify({'success': False, 'message': '파일이 존재하지 않습니다.'}), 404
        _dl_proj = ConsultingProject.query.get(eoi.consulting_project_id) if eoi.consulting_project_id else None
        _dl_year = eoi.submission_date.year if eoi.submission_date else None
        ext = '.' + eoi.eoi_file_type if eoi.eoi_file_type else '.pdf'
        download_name = make_overseas_tech_filename('EOI', ext, _dl_proj, eoi.title, _dl_year)
        try:
            return stream_from_r2(eoi.eoi_file_path, download_name=download_name)
        except Exception:
            return jsonify({'success': False, 'message': '파일을 찾을 수 없습니다.'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
