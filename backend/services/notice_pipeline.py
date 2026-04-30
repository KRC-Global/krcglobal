"""
발주공고 후처리 파이프라인 — 수집 후 / 작업 완료 후의 큐잉·알림을 캡슐화.

수집 측: notice_collector._do_collect() 가 신규 BidNotice ID 리스트를 만들어
post_collect_hook(new_ids) 를 호출한다.

작업 측: routes/notice_tasks 의 complete/fail 핸들러가
notify_task_done / notify_task_failed 를 호출한다.

알림은 항상 "best-effort" — 실패해도 raise 하지 않는다.
큐잉(commit) 실패만 호출자(엔드포인트)로 propagate.
"""
from __future__ import annotations

import os
from datetime import datetime

from models import db, BidNotice, NoticeTask
from services.notifier import get_notifier


# 신규 공고당 자동으로 enqueue 되는 작업 종류와 우선순위.
# priority 가 작을수록 먼저.
#   translate(0) → infographic(5) → slides(10)
# 번역 완료 후 인포그래픽/슬라이드가 한국어 요약을 활용할 수 있도록 순서를 분리한다.
DEFAULT_TASKS: tuple[tuple[str, int], ...] = (
    ('translate',   0),
    ('infographic', 5),
    # slides 제외 — NotebookLM 파일 export 미지원
)


# ── 큐잉 ──────────────────────────────────────────────────────────────────────
def enqueue_default_tasks(notice_ids: list[int]) -> int:
    """신규 공고 ID 리스트에 대해 DEFAULT_TASKS 를 enqueue.

    UniqueConstraint(notice_id, task_type) 로 중복 enqueue 가 막혀있다.
    재수집/재실행 idempotency 보장을 위해 INSERT 충돌은 조용히 skip 한다.

    Returns: 실제로 추가된 row 수.
    """
    if not notice_ids:
        return 0

    added = 0
    for nid in notice_ids:
        for task_type, priority in DEFAULT_TASKS:
            exists = NoticeTask.query.filter_by(
                notice_id=nid, task_type=task_type
            ).first()
            if exists:
                continue
            db.session.add(NoticeTask(
                notice_id=nid,
                task_type=task_type,
                status='pending',
                priority=priority,
            ))
            added += 1

    if added:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[pipeline] enqueue commit 실패: {e}')
            return 0
    return added


# ── 알림 메시지 빌더 ──────────────────────────────────────────────────────────
def _site_url_for(notice_id: int) -> str | None:
    base = os.environ.get('SITE_BASE_URL', '').rstrip('/')
    if not base:
        return None
    return f'{base}/pages/notices/bid-notices.html?notice_id={notice_id}'


def _format_new_notice(notice: BidNotice, task_ids: dict[str, int]) -> dict:
    """Discord embed 용 dict 4종(title/body/url/fields)."""
    title = (notice.title_ko or notice.title or '제목 미상')[:240]
    head = '[새 발주공고]'
    body_lines = []
    if notice.title and notice.title_ko and notice.title != notice.title_ko:
        body_lines.append(f'원문: {notice.title}')
    if notice.client or notice.country:
        body_lines.append(
            f'발주처/국가: {notice.client or "-"} · {notice.country or "-"}'
        )
    body_lines.append(
        f'마감: {notice.deadline or "-"}   금액: {notice.contract_value or "-"}'
    )
    if notice.source_url:
        body_lines.append(f'원문 링크: {notice.source_url}')
    site_url = _site_url_for(notice.id)
    if site_url:
        body_lines.append(f'시스템: {site_url}')
    if task_ids:
        parts = [f'{t}(#{tid})' for t, tid in task_ids.items()]
        body_lines.append('작업: ' + ' · '.join(parts))

    return {
        'title': f'{head} {title}',
        'body':  '\n'.join(body_lines),
        'url':   site_url or notice.source_url,
        'fields': None,
    }


def notify_new_notices(notice_ids: list[int]) -> int:
    """신규 공고들을 Discord 채널에 발송. 발송 성공 건수를 반환."""
    if not notice_ids:
        return 0

    notifier = get_notifier()
    notices = (BidNotice.query
               .filter(BidNotice.id.in_(notice_ids))
               .all())
    sent = 0
    for n in notices:
        # 해당 공고의 task id 들을 함께 표기 (이미 enqueue 끝난 후 호출됨)
        tasks = (NoticeTask.query
                 .filter_by(notice_id=n.id)
                 .all())
        task_ids = {t.task_type: t.id for t in tasks}
        payload = _format_new_notice(n, task_ids)
        try:
            ok = notifier.send(**payload)
            if ok:
                sent += 1
        except Exception as e:
            print(f'[pipeline] notice #{n.id} 알림 예외: {e}')
    return sent


def notify_task_done(task: NoticeTask, notice: BidNotice) -> bool:
    """작업 완료 시 짧게 한 줄 발송."""
    try:
        notifier = get_notifier()
        title = f'[작업 완료] notice #{notice.id} · {task.task_type} #{task.id}'
        body_parts = [
            f'공고: {(notice.title_ko or notice.title or "")[:200]}',
        ]
        if task.task_type == 'slides' and notice.slides_url:
            body_parts.append(f'슬라이드: {notice.slides_url}')
        if task.task_type == 'translate' and notice.title_ko:
            body_parts.append(f'번역 제목: {notice.title_ko}')
        return notifier.send(
            title=title,
            body='\n'.join(body_parts),
            url=_site_url_for(notice.id) or notice.source_url,
        )
    except Exception as e:
        print(f'[pipeline] notify_task_done 예외: {e}')
        return False


def notify_task_failed(task: NoticeTask, notice: BidNotice, error: str) -> bool:
    try:
        notifier = get_notifier()
        title = f'[작업 실패] notice #{notice.id} · {task.task_type} #{task.id}'
        body = f'시도: {task.attempts}/{task.max_attempts}\n에러: {(error or "")[:300]}'
        return notifier.send(
            title=title,
            body=body,
            url=_site_url_for(notice.id) or notice.source_url,
        )
    except Exception as e:
        print(f'[pipeline] notify_task_failed 예외: {e}')
        return False


# ── 수집 직후 훅 ──────────────────────────────────────────────────────────────
def post_collect_hook(new_notice_ids: list[int]) -> dict:
    """수집 직후 호출. 신규 공고당 task enqueue + Discord 요약 알림 발송.

    실패해도 raise 하지 않는다 (수집 자체는 이미 commit 끝).
    """
    if not new_notice_ids:
        return {'enqueued': 0, 'notified': 0}

    enqueued = 0
    notified = 0
    try:
        enqueued = enqueue_default_tasks(new_notice_ids)
    except Exception as e:
        print(f'[pipeline] enqueue 예외: {e}')

    try:
        notified = notify_new_notices(new_notice_ids)
    except Exception as e:
        print(f'[pipeline] notify 예외: {e}')

    return {'enqueued': enqueued, 'notified': notified}
