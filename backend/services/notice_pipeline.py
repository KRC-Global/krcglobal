"""
발주공고 후처리 파이프라인 — 수집 후 / 작업 완료 후의 렌더·큐잉·알림을 캡슐화.

수집 측: notice_collector._do_collect() 가 신규 BidNotice ID 리스트를 만들어
post_collect_hook(new_ids) 를 호출한다.

작업 측: 번역 complete 에 한국어 요약(summary_ko)이 있어야 인포그래픽을
생성·R2 저장하고 카카오 이미지 큐에 넣는다. 요약이 비면 완료를 거절해
워커가 요약을 채워 재시도한다.

알림은 항상 "best-effort" — 실패해도 raise 하지 않는다.
번역 이후 렌더/R2 저장 실패는 번역 완료를 rollback 해 재시도 가능하게 한다.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from flask import current_app

from models import db, BidNotice, NoticeTask, KakaoDelivery
from services.notifier import get_notifier


# 신규 공고당 외부 워커에 enqueue 되는 작업.
# 인포그래픽은 번역 완료 API 안에서 서버가 결정론적으로 생성하므로 별도 외부
# 작업을 만들지 않는다. 이 순서 보장으로 번역 전 영문 카드가 발송되는 경쟁도 막는다.
DEFAULT_TASKS: tuple[tuple[str, int], ...] = (
    ('translate',   0),
    # slides 제외 — NotebookLM 파일 export 미지원
)


def notice_summary_ready(notice: BidNotice | None) -> bool:
    """카톡 발송·인포그래픽 렌더에 쓸 한국어 요약이 있는지."""
    return bool(notice and (notice.summary_ko or '').strip())


def enqueue_kakao_image_delivery(notice_id: int) -> KakaoDelivery | None:
    """인포그래픽 완료 공고의 첫 카카오 전송 단계(image)를 idempotent하게 등록.

    호출자가 가진 트랜잭션에 포함되도록 commit 하지 않는다. 운영에서
    KAKAO_RELAY_ENABLED가 꺼져 있으면 아무 작업도 만들지 않는다.
    한국어 요약이 없으면 큐에 넣지 않는다 — 빈 요약 카드가 테스트방에 나가지 않게.
    """
    if not current_app.config.get('KAKAO_RELAY_ENABLED', False):
        return None

    notice = BidNotice.query.get(notice_id)
    if not notice_summary_ready(notice):
        return None

    existing = KakaoDelivery.query.filter_by(
        notice_id=notice_id,
        kind='image',
    ).first()
    if existing:
        return existing

    delivery = KakaoDelivery(
        notice_id=notice_id,
        kind='image',
        status='pending',
    )
    db.session.add(delivery)
    return delivery


def generate_and_queue_notice_infographic(notice: BidNotice) -> dict:
    """번역된 공고를 렌더해 R2에 저장하고 카카오 이미지 큐를 등록한다.

    DB commit 은 하지 않는다. 호출자는 번역 필드·인포그래픽 경로·카카오 큐를
    한 트랜잭션으로 commit 한다. R2 키가 공고 ID 기준으로 고정되어 재시도해도
    같은 객체를 덮어쓰므로 중복 파일이 생기지 않는다.
    """
    if not notice or not notice.id:
        raise RuntimeError('인포그래픽을 생성할 공고 ID가 없습니다.')
    if notice.archived_at is not None:
        raise RuntimeError(f'아카이브된 공고 #{notice.id}는 인포그래픽을 생성하지 않습니다.')
    if not notice_summary_ready(notice):
        raise RuntimeError(
            f'공고 #{notice.id} 한국어 요약이 없어 인포그래픽을 만들지 않습니다. '
            '번역 워커가 summaryKo를 채운 뒤 다시 완료 보고해야 합니다.'
        )

    from services.notice_infographic import generate_notice_infographic
    from utils.r2_storage import upload_file

    object_key = f'infographics/notice_{notice.id}.png'
    with tempfile.TemporaryDirectory(prefix=f'krc-notice-{notice.id}-') as temp_dir:
        output = Path(temp_dir) / f'notice_{notice.id}.png'
        generated = generate_notice_infographic(notice.to_dict(), output, style='slide')
        if not output.is_file() or output.stat().st_size < 1000:
            raise RuntimeError(f'공고 #{notice.id} 인포그래픽 파일이 생성되지 않았습니다.')
        with output.open('rb') as image:
            upload_file(image, object_key, content_type='image/png')
        size = output.stat().st_size

    notice.infographic_path = object_key
    notice.infographic_url = f'/api/notices/{notice.id}/infographic'
    delivery = enqueue_kakao_image_delivery(notice.id)
    # 배포 전 이미 만들어진 외부 infographic 작업이 뒤늦게 완료되어 새 슬라이드를
    # 덮어쓰지 않게 같은 트랜잭션에서 서버 처리 완료로 닫는다.
    legacy_task = NoticeTask.query.filter_by(
        notice_id=notice.id,
        task_type='infographic',
    ).first()
    if legacy_task and legacy_task.status != 'done':
        legacy_task.status = 'done'
        legacy_task.worker_id = 'server-renderer'
        legacy_task.completed_at = datetime.utcnow()
        legacy_task.error = None
        legacy_task.result = {
            'mode': 'server',
            'r2_key': object_key,
            'infographic_url': notice.infographic_url,
            'superseded_external_task': True,
        }
    return {
        'r2_key': object_key,
        'infographic_url': notice.infographic_url,
        'width': generated.get('width'),
        'height': generated.get('height'),
        'style': generated.get('style', 'slide'),
        'kind': generated.get('kind'),
        'size': size,
        'kakao_queued': delivery is not None,
        'legacy_task_closed': legacy_task.id if legacy_task else None,
    }


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


def requeue_translation(notice_ids: list[int]) -> int:
    """재활성화된 공고의 번역을 다시 돌린다 — 최신 문서 기준으로 카드를 갱신.

    AIIB 처럼 한 사업의 공고가 단계별로 다른 문서로 올라오는 소스
    (GPN → REOI → SPN → Addendum)에서는 레코드가 재활성화돼도
    title_ko/summary_ko 가 옛 단계 기준으로 남아, 마감일·공고종류가
    실제 문서와 어긋난 카드가 그대로 쓰인다.

    done/failed 상태의 translate 작업을 pending 으로 되돌리면 워커가 다시
    번역하고, 완료 처리에서 인포그래픽 재생성 + 카카오 큐 등록까지 이어진다
    (generate_and_queue_notice_infographic). 즉 재활성화 건도 신규 공고와
    같은 경로로 발송된다.

    기존 번역문은 지우지 않는다 — 워커가 덮어쓸 때까지 카드가 비지 않게.

    Returns: 다시 큐에 넣은 작업 수.
    """
    if not notice_ids:
        return 0

    requeued = 0
    for nid in notice_ids:
        task = NoticeTask.query.filter_by(
            notice_id=nid, task_type='translate'
        ).first()
        if task is None:
            db.session.add(NoticeTask(
                notice_id=nid,
                task_type='translate',
                status='pending',
                priority=0,
            ))
            requeued += 1
            continue
        # 이미 대기/처리 중이면 건드리지 않는다 (워커 claim 과 경쟁 방지)
        if task.status in ('pending', 'claimed'):
            continue
        task.status = 'pending'
        task.worker_id = None
        task.claimed_at = None
        task.completed_at = None
        task.error = None
        task.attempts = 0
        requeued += 1

    if requeued:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f'[pipeline] 재번역 큐 commit 실패: {e}')
            return 0
    return requeued


# ── 알림 메시지 빌더 ──────────────────────────────────────────────────────────
def _site_url_for(notice_id: int) -> str | None:
    base = os.environ.get('SITE_BASE_URL', '').rstrip('/')
    if not base:
        return None
    return f'{base}/pages/notices/bid-notices.html?notice_id={notice_id}'


def _format_new_notice(notice: BidNotice, task_ids: dict[str, int]) -> dict:
    """Discord embed 용 dict 4종(title/body/url/fields)."""
    title = (notice.title_ko or notice.title or '제목 미상')[:240]
    is_plan = notice.source == 'koica_plan'
    head = '[KOICA 발주계획]' if is_plan else '[새 발주공고]'
    body_lines = []
    if notice.title and notice.title_ko and notice.title != notice.title_ko:
        body_lines.append(f'원문: {notice.title}')
    if notice.client or notice.country:
        body_lines.append(
            f'발주처/국가: {notice.client or "-"} · {notice.country or "-"}'
        )
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    if is_plan:
        if raw.get('plan_no'):
            body_lines.append(f'발주번호: {raw.get("plan_no")}')
        body_lines.append(
            f'공개: {raw.get("posted") or "-"}   '
            f'발주시기: {raw.get("order_month") or "-"}'
        )
        body_lines.append(f'예산: {notice.contract_value or "-"}')
        body_lines.append('※ 입찰공고가 아니라 나라장터 발주계획입니다.')
    else:
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
