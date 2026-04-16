import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import SCHEDULE_HOUR, SCHEDULE_MINUTE, DISCORD_CHANNEL_ID

log = logging.getLogger(__name__)


def setup(bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_all,
        CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, timezone='Asia/Seoul'),
        args=[bot],
        id='daily_fetch',
        replace_existing=True,
    )
    scheduler.start()
    log.info(f'스케줄러 시작 — 매일 {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} KST')
    return scheduler


async def run_all(bot, notify_channel=True, trigger='scheduled'):
    from scrapers import worldbank, ungm, adb, koica
    from gbms_client import send_notices, send_run_summary

    log.info('공고 수집 시작...')
    all_notices = []
    sources = []

    for module, name in [
        (worldbank, 'World Bank'),
        (ungm,      'UNGM'),
        (adb,       'ADB'),
        (koica,     'KOICA'),
    ]:
        try:
            items = await module.fetch()
            all_notices.extend(items)
            sources.append({'name': name, 'count': len(items), 'items': items, 'error': None})
            log.info(f'{name} {len(items)}건 수집')
        except Exception as e:
            sources.append({'name': name, 'count': 0, 'items': [], 'error': str(e)})
            log.error(f'{name} 오류: {e}')

    created, skipped = 0, 0
    send_error = None

    if all_notices:
        try:
            result  = await send_notices(all_notices)
            created = result.get('created', 0)
            skipped = result.get('skipped', 0)
            log.info(f'GBMS 전송 완료 — 신규 {created}건, 중복 {skipped}건')
        except Exception as e:
            send_error = str(e)
            log.error(f'GBMS 전송 실패: {e}')
    else:
        log.info('수집된 공고 없음')

    # GBMS에 실행 이력 저장
    try:
        await send_run_summary({
            'trigger': trigger,
            'totalFound': len(all_notices),
            'totalCreated': created,
            'totalSkipped': skipped,
            'sendError': send_error,
            'sources': [
                {'name': s['name'], 'count': s['count'], 'error': s['error']}
                for s in sources
            ],
        })
    except Exception as e:
        log.error(f'실행 이력 전송 실패: {e}')

    # 스케줄 실행 시 채널 알림 (신규 등록된 경우만)
    if notify_channel and created > 0:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            await channel.send(format_summary(sources, created, skipped, send_error))

    return {
        'sources': sources,
        'total_found': len(all_notices),
        'created': created,
        'skipped': skipped,
        'send_error': send_error,
    }


def format_summary(sources, created, skipped, send_error=None, show_samples=True):
    lines = ['📢 **발주공고 수집 결과**']
    total = sum(s['count'] for s in sources)
    lines.append(f'📥 수집: **{total}건**  |  ✅ 신규: **{created}건**  |  ⏭ 중복: {skipped}건')
    if send_error:
        lines.append(f'⚠️ GBMS 전송 실패: {send_error}')
    lines.append('')
    lines.append('**소스별 상세**')

    for s in sources:
        if s['error']:
            lines.append(f'  ❌ **{s["name"]}** — 실패 ({s["error"][:60]})')
            continue
        lines.append(f'  • **{s["name"]}** — {s["count"]}건')
        if show_samples and s['items']:
            for n in s['items'][:3]:
                title = (n.get('title') or '').strip()[:55]
                country = n.get('country') or '-'
                deadline = n.get('deadline') or '-'
                lines.append(f'      - {title}  _(국가: {country} / 마감: {deadline})_')
            if s['count'] > 3:
                lines.append(f'      … 외 {s["count"] - 3}건')

    lines += ['', '🔗 https://krcglobal.vercel.app/pages/notices/bid-notices.html']
    return '\n'.join(lines)[:1900]
