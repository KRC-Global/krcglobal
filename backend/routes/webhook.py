"""
GBMS - Webhook Routes
디스코드 봇 → 발주공고 수신 및 조회 API
"""
import hmac
import hashlib
import os
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from models import db, BidNotice
from routes.auth import token_required, admin_required

webhook_bp = Blueprint('webhook', __name__)

VALID_STATUSES = {'new', 'reviewed', 'applied', 'closed'}
VALID_SOURCES = {
    'worldbank', 'adb', 'aiib', 'afdb', 'ifad', 'ida',
    'koica', 'edcf', 'ungm', 'devex', 'other'
}


def verify_bot_signature(body: bytes, signature: str) -> bool:
    """HMAC-SHA256 서명 검증"""
    secret = os.environ.get('WEBHOOK_BOT_SECRET', '')
    if not secret:
        # 비밀키 미설정 시 개발 환경에서만 통과 (production에서는 반드시 설정)
        return current_app.config.get('DEBUG', False)
    expected = 'sha256=' + hmac.new(
        secret.encode('utf-8'), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── 봇 → GBMS 공고 전송 ─────────────────────────────────────────────────────

@webhook_bp.route('/notices', methods=['POST'])
def receive_notices():
    """
    디스코드 봇이 수집한 발주공고를 일괄 전송

    Headers:
        X-Bot-Signature: sha256=<HMAC-SHA256(body, WEBHOOK_BOT_SECRET)>
    Body (JSON):
        { "notices": [ { source, title, country, client, sector,
                          contractValue, deadline, sourceUrl, ...} ] }
    Response:
        { "success": true, "created": 3, "skipped": 1 }
    """
    body = request.get_data()
    signature = request.headers.get('X-Bot-Signature', '')

    if not verify_bot_signature(body, signature):
        return jsonify({'success': False, 'message': '서명 불일치 — 인증 실패'}), 401

    data = request.get_json(silent=True)
    if not data or 'notices' not in data:
        return jsonify({'success': False, 'message': "notices 배열이 필요합니다."}), 400

    notices = data['notices']
    if not isinstance(notices, list):
        return jsonify({'success': False, 'message': "notices는 배열이어야 합니다."}), 400

    created = 0
    skipped = 0

    for item in notices:
        source_url = (item.get('sourceUrl') or item.get('source_url') or '').strip()
        title = (item.get('title') or '').strip()

        if not source_url or not title:
            skipped += 1
            continue

        # 중복 확인 — source_url unique
        if BidNotice.query.filter_by(source_url=source_url).first():
            skipped += 1
            continue

        source = (item.get('source') or 'other').lower().strip()
        if source not in VALID_SOURCES:
            source = 'other'

        notice = BidNotice(
            source=source,
            title=title,
            country=(item.get('country') or '').strip() or None,
            client=(item.get('client') or '').strip() or None,
            sector=(item.get('sector') or '').strip() or None,
            contract_value=(item.get('contractValue') or item.get('contract_value') or '').strip() or None,
            deadline=(item.get('deadline') or '').strip() or None,
            source_url=source_url,
            status='new',
            raw_data=item,
        )
        db.session.add(notice)
        created += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'저장 실패: {str(e)}'}), 500

    return jsonify({'success': True, 'created': created, 'skipped': skipped})


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
