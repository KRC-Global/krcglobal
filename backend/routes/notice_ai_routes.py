"""발주공고 LLM 보강 엔드포인트.

services.notice_ai 의 네 기능(요약·추출·적합도·연결)과 주간 다이제스트를
주기 실행으로 묶는다. 한 번에 적은 건수만 처리한다 — 서버리스 실행시간
제한이 있고, 공고 1건당 LLM 호출이 여러 번 일어나기 때문이다.

인증은 수집 엔드포인트와 같다(CRON_SECRET / WORKER_SECRET / admin JWT).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from models import db, BidNotice, KakaoDelivery
from services import notice_ai as ai
from services.claude_client import is_enabled, resolve_model
from services.notice_digest import build_digest

notice_ai_bp = Blueprint('notice_ai', __name__)

DEFAULT_LIMIT = 3
MAX_LIMIT = 10
ALL_STEPS = ('extract', 'fit', 'summary', 'link')

# 적합도를 '바꿀' 때 요구하는 확신도. 기록은 항상 남기고 반영만 가린다.
# 등급을 올리는 쪽(놓친 공고를 건지는 쪽)은 덜 위험하므로 기준이 낮다.
PROMOTE_CONFIDENCE = 0.75
# 내리는 쪽은 게시판에서 공고를 치우는 일이라 더 엄격히 본다. 실측으로
# 산림투자사업(#434)이 0.85 로 제외됐는데, KRC 는 동티모르 산림복원 PMC 를
# 수행한 이력이 있어 과잉 제외였다.
DEMOTE_CONFIDENCE = 0.92
# 아카이브된 공고를 되살릴 때는 더 엄격하게 본다.
RESCUE_CONFIDENCE = 0.85
RESCUE_WINDOW_DAYS = 14


def _auth_ok() -> bool:
    from routes.notice_collector import _check_afdb_ingest_auth
    return _check_afdb_ingest_auth()


def _raw(notice: BidNotice) -> dict:
    return dict(notice.raw_data) if isinstance(notice.raw_data, dict) else {}


def _steps_from_request() -> tuple:
    raw = (request.args.get('steps') or '').strip()
    if not raw:
        return ALL_STEPS
    picked = tuple(s.strip() for s in raw.split(',') if s.strip() in ALL_STEPS)
    return picked or ALL_STEPS


@notice_ai_bp.route('/ai/status', methods=['GET'])
def ai_status():
    """키 설정·선택된 모델 확인 — 운영 점검용."""
    if not _auth_ok():
        return jsonify({'success': False, 'message': '인증 실패'}), 401
    enabled = is_enabled()
    return jsonify({
        'success': True,
        'enabled': enabled,
        'model': resolve_model() if enabled else None,
        'profileChars': len(ai.krc_profile()),
    })


@notice_ai_bp.route('/ai/enrich', methods=['POST', 'GET'])
def ai_enrich():
    """활성 공고를 LLM 으로 보강한다. 한 번에 limit 건.

    쿼리: limit(기본 3), steps(extract,fit,summary,link 중 쉼표 구분)
    """
    if not _auth_ok():
        return jsonify({'success': False, 'message': '인증 실패'}), 401
    if not is_enabled():
        return jsonify({'success': False,
                        'message': 'ANTHROPIC_API_KEY 미설정'}), 503

    try:
        limit = max(1, min(MAX_LIMIT, int(request.args.get('limit', DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    steps = _steps_from_request()

    rows = (BidNotice.query
            .filter(BidNotice.archived_at.is_(None))
            .order_by(BidNotice.id.desc())
            .limit(60)
            .all())

    stats = {'seen': 0, 'extracted': 0, 'judged': 0, 'regraded': 0,
             'summarized': 0, 'linked': 0, 'cards': 0, 'errors': []}
    touched = 0

    for n in rows:
        if touched >= limit:
            break
        raw = _raw(n)
        did = False

        if 'extract' in steps and not raw.get('ai_extract_at'):
            got = ai.extract_fields(n.to_dict())
            if got is not None:
                # 비어 있는 필드만 채운다 — 수집기가 얻은 값을 덮지 않는다.
                if got.get('deadline') and not n.deadline:
                    n.deadline = got['deadline'][:50]
                if got.get('contract_value') and not n.contract_value:
                    n.contract_value = got['contract_value'][:100]
                if got.get('client') and (n.client or '').strip() in (
                        '', 'ADB', 'AfDB', 'World Bank', 'AIIB', 'IsDB'):
                    n.client = got['client'][:200]
                if got.get('eligibility'):
                    raw['eligibility'] = got['eligibility']
                raw['ai_extract'] = got
                stats['extracted'] += 1
            raw['ai_extract_at'] = datetime.utcnow().isoformat() + 'Z'
            did = True

        if 'fit' in steps and not raw.get('krc_fit_llm'):
            verdict = ai.judge_fit(n.to_dict())
            if verdict:
                raw['krc_fit_llm'] = verdict
                stats['judged'] += 1
                # 키워드 판정과 다르고 확신이 높으면 반영한다.
                before = raw.get('krc_fit')
                demote = verdict['grade'] == '하' and before != '하'
                bar = DEMOTE_CONFIDENCE if demote else PROMOTE_CONFIDENCE
                # 이미 카카오로 나간 공고는 자동으로 치우지 않는다. 사람 손에
                # 들어간 건을 게시판에서만 조용히 빼면 둘이 어긋난다.
                if demote and _already_sent(n.id):
                    bar = 2.0   # 반영하지 않고 기록만 남긴다
                    raw['krc_fit_llm_note'] = '발송 완료 건이라 자동 제외하지 않음'
                if (verdict['grade'] != before and verdict['confidence'] >= bar):
                    raw['krc_fit'] = verdict['grade']
                    raw['krc_fit_reason'] = verdict['reason']
                    stats['regraded'] += 1
                    print(f'[ai-enrich] #{n.id} 적합도 {before} → '
                          f'{verdict["grade"]} ({verdict["reason"]}, '
                          f'conf={verdict["confidence"]})')
                    if verdict['grade'] == '하':
                        n.archived_at = datetime.utcnow()
                        n.archive_reason = 'krc_fit_llm'
                        _cancel_pending(n.id, verdict['reason'])
                did = True

        if 'summary' in steps and n.archived_at is None and not raw.get('ai_summary_at'):
            res = ai.translate_and_summarize(n.to_dict())
            if res:
                n.title_ko = res['title_ko']
                n.summary_ko = res['summary_ko']
                raw['ai_summary_at'] = datetime.utcnow().isoformat() + 'Z'
                stats['summarized'] += 1
                if _regenerate_card(n, stats):
                    stats['cards'] += 1
            else:
                raw['ai_summary_at'] = ''   # 다음 주기에 다시 시도
            did = True

        if 'link' in steps and n.archived_at is None and 'related' not in raw:
            cands = [{'id': c.id, 'source': c.source, 'country': c.country,
                      'title': c.title_ko or c.title}
                     for c in rows if c.id != n.id][:40]
            raw['related'] = ai.link_related(n.to_dict(), cands)
            if raw['related']:
                stats['linked'] += 1
            did = True

        if did:
            n.raw_data = raw
            touched += 1
            stats['seen'] += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'저장 실패: {e}'}), 500

    return jsonify({'success': True, 'model': resolve_model(),
                    'steps': list(steps), **stats})


def _already_sent(notice_id: int) -> bool:
    """이 공고가 카카오로 이미 나갔는지."""
    return bool(KakaoDelivery.query
                .filter_by(notice_id=notice_id, status='done')
                .first())


def _cancel_pending(notice_id: int, reason: str) -> None:
    """적합도 하락으로 제외된 공고의 대기 중 카카오 발송을 취소한다."""
    for d in (KakaoDelivery.query
              .filter_by(notice_id=notice_id)
              .filter(KakaoDelivery.status.in_(['pending', 'claimed']))
              .all()):
        d.status = 'skipped'
        d.error = f'LLM 적합도 제외: {reason}'


def _regenerate_card(notice: BidNotice, stats: dict) -> bool:
    """요약이 바뀌었으니 카드를 다시 그린다.

    카카오 큐 등록은 idempotent 해서(같은 notice 의 image 전송이 이미 있으면
    그대로 둔다) 이미 보낸 공고가 다시 나가지 않는다.
    """
    try:
        from services.notice_pipeline import generate_and_queue_notice_infographic
        generate_and_queue_notice_infographic(notice)
        return True
    except Exception as e:
        stats['errors'].append(f'#{notice.id} 카드 재생성: {str(e)[:120]}')
        return False


@notice_ai_bp.route('/ai/rescue', methods=['POST'])
def ai_rescue():
    """키워드로 제외된 최근 공고를 다시 판정해 되살린다.

    키워드 필터가 놓치는 쪽(표현이 달라 제외된 진짜 관개 사업)을 메운다.
    되살리는 판단이라 확신도 기준을 더 높게 둔다.
    """
    if not _auth_ok():
        return jsonify({'success': False, 'message': '인증 실패'}), 401
    if not is_enabled():
        return jsonify({'success': False,
                        'message': 'ANTHROPIC_API_KEY 미설정'}), 503
    try:
        limit = max(1, min(MAX_LIMIT, int(request.args.get('limit', DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    since = datetime.utcnow() - timedelta(days=RESCUE_WINDOW_DAYS)
    rows = (BidNotice.query
            .filter(BidNotice.archived_at.isnot(None))
            .filter(BidNotice.archived_at >= since)
            .filter(BidNotice.archive_reason == 'krc_fit_excluded')
            .order_by(BidNotice.id.desc())
            .limit(40)
            .all())

    checked = rescued = 0
    notes = []
    for n in rows:
        if checked >= limit:
            break
        raw = _raw(n)
        if raw.get('krc_fit_llm_rescue'):
            continue
        verdict = ai.judge_fit(n.to_dict())
        checked += 1
        if not verdict:
            continue
        raw['krc_fit_llm_rescue'] = verdict
        if verdict['grade'] in ('상', '중') and verdict['confidence'] >= RESCUE_CONFIDENCE:
            n.archived_at = None
            n.archive_reason = None
            raw['krc_fit'] = verdict['grade']
            raw['krc_fit_reason'] = verdict['reason']
            rescued += 1
            notes.append(f'#{n.id} {verdict["grade"]} ({verdict["reason"]})')
        n.raw_data = raw

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'저장 실패: {e}'}), 500
    return jsonify({'success': True, 'checked': checked,
                    'rescued': rescued, 'notes': notes})


@notice_ai_bp.route('/ai/digest', methods=['POST', 'GET'])
def ai_digest():
    """주간 다이제스트를 만들어 카카오 큐에 넣는다.

    쿼리: days(기본 7), dry=1 이면 본문만 돌려주고 큐에 넣지 않는다.
    """
    if not _auth_ok():
        return jsonify({'success': False, 'message': '인증 실패'}), 401
    try:
        days = max(1, min(31, int(request.args.get('days', 7))))
    except (TypeError, ValueError):
        days = 7
    dry = (request.args.get('dry') or '').strip() in ('1', 'true', 'yes')

    digest = build_digest(days)
    if not digest:
        return jsonify({'success': True, 'queued': False,
                        'message': f'최근 {days}일 신규 공고가 없어 보내지 않습니다.'})
    if dry:
        return jsonify({'success': True, 'queued': False, **digest})

    if not os.environ.get('KAKAO_RELAY_ENABLED', '').strip().lower() in (
            '1', 'true', 'yes', 'on'):
        # 설정이 꺼져 있으면 본문만 돌려준다(큐에 쌓아 두지 않는다).
        return jsonify({'success': True, 'queued': False,
                        'message': 'KAKAO_RELAY_ENABLED 가 꺼져 있습니다.',
                        **digest})

    delivery = KakaoDelivery(notice_id=None, kind='digest',
                             status='pending', payload=digest['text'])
    db.session.add(delivery)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'큐 등록 실패: {e}'}), 500
    return jsonify({'success': True, 'queued': True,
                    'deliveryId': delivery.id,
                    'period': digest['period'], 'total': digest['total'],
                    'text': digest['text']})
