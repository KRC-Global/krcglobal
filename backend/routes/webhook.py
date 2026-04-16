"""
GBMS - 발주공고 조회/이력 Routes
(수집 엔드포인트는 routes/notice_collector.py 참조)
"""
from flask import Blueprint, request, jsonify
from models import db, BidNotice, ScrapingRun
from routes.auth import token_required, admin_required

webhook_bp = Blueprint('webhook', __name__)

VALID_STATUSES = {'new', 'reviewed', 'applied', 'closed'}


# ── GBMS 사용자 → 공고 조회 ──────────────────────────────────────────────────

@webhook_bp.route('/notices', methods=['GET'])
@token_required
def list_notices(current_user):
    """발주공고 목록 조회 (필터 + 페이지네이션)"""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('perPage', 20, type=int), 100)
    source = request.args.get('source', '')
    country = request.args.get('country', '')
    status = request.args.get('status', '')
    search = request.args.get('search', '')

    query = BidNotice.query

    if source:
        query = query.filter(BidNotice.source == source)
    if country:
        query = query.filter(BidNotice.country.ilike(f'%{country}%'))
    if status:
        query = query.filter(BidNotice.status == status)
    if search:
        query = query.filter(BidNotice.title.ilike(f'%{search}%'))

    query = query.order_by(BidNotice.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'success': True,
        'data': [n.to_dict() for n in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'currentPage': page,
        'perPage': per_page,
    })


@webhook_bp.route('/notices/summary', methods=['GET'])
@token_required
def notices_summary(current_user):
    """대시보드용 — new 상태 공고 최신 N건 + 총 new 건수"""
    limit = min(request.args.get('limit', 5, type=int), 20)

    new_count = BidNotice.query.filter_by(status='new').count()
    recent = (BidNotice.query
              .filter_by(status='new')
              .order_by(BidNotice.created_at.desc())
              .limit(limit)
              .all())

    return jsonify({
        'success': True,
        'newCount': new_count,
        'data': [n.to_dict() for n in recent],
    })


# ── 상태 변경 ────────────────────────────────────────────────────────────────

@webhook_bp.route('/notices/<int:notice_id>', methods=['PATCH'])
@token_required
def update_notice_status(current_user, notice_id):
    """공고 상태 변경 (reviewed / applied / closed / new)"""
    notice = BidNotice.query.get(notice_id)
    if not notice:
        return jsonify({'success': False, 'message': '공고를 찾을 수 없습니다.'}), 404

    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()

    if new_status not in VALID_STATUSES:
        return jsonify({'success': False, 'message': f'유효하지 않은 상태입니다. ({", ".join(VALID_STATUSES)})'}), 400

    notice.status = new_status
    db.session.commit()

    return jsonify({'success': True, 'data': notice.to_dict()})


# ── 수집 실행 이력 ───────────────────────────────────────────────────────────

@webhook_bp.route('/notices/runs', methods=['GET'])
@token_required
def list_scraping_runs(current_user):
    """발주공고 수집 실행 이력 (최근순)"""
    limit = min(request.args.get('limit', 20, type=int), 100)
    runs = (ScrapingRun.query
            .order_by(ScrapingRun.run_at.desc())
            .limit(limit)
            .all())
    return jsonify({
        'success': True,
        'data': [r.to_dict() for r in runs],
    })


@webhook_bp.route('/notices/runs/latest', methods=['GET'])
@token_required
def latest_scraping_run(current_user):
    """최근 실행 1건 — 상단 카드용"""
    run = ScrapingRun.query.order_by(ScrapingRun.run_at.desc()).first()
    return jsonify({
        'success': True,
        'data': run.to_dict() if run else None,
    })


# ── 삭제 (관리자 전용) ───────────────────────────────────────────────────────

@webhook_bp.route('/notices/<int:notice_id>', methods=['DELETE'])
@admin_required
def delete_notice(current_user, notice_id):
    """발주공고 삭제 (관리자 전용)"""
    notice = BidNotice.query.get(notice_id)
    if not notice:
        return jsonify({'success': False, 'message': '공고를 찾을 수 없습니다.'}), 404

    db.session.delete(notice)
    db.session.commit()

    return jsonify({'success': True, 'message': '삭제되었습니다.'})
