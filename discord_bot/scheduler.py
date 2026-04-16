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


async def run_all(bot):
    from scrapers import worldbank, ungm, adb, koica
    from gbms_client import send_notices

    log.info('공고 수집 시작...')
    all_notices = []
    summary = []

    for module, name in [
        (worldbank, 'World Bank'),
        (ungm,      'UNGM'),
        (adb,       'ADB'),
        (koica,     'KOICA'),
    ]:
        try:
            items = await module.fetch()
            all_notices.extend(items)
            summary.append(f'{name}: {len(items)}건')
            log.info(f'{name} {len(items)}건 수집')
        except Exception as e:
            summary.append(f'{name}: 실패')
            log.error(f'{name} 오류: {e}')

    if not all_notices:
        log.info('수집된 공고 없음')
        return

    # GBMS 전송
    try:
        result  = await send_notices(all_notices)
        created = result.get('created', 0)
        skipped = result.get('skipped', 0)
        log.info(f'GBMS 전송 완료 — 신규 {created}건, 중복 {skipped}건')
    except Exception as e:
        log.error(f'GBMS 전송 실패: {e}')
        created, skipped = 0, 0

    # 디스코드 알림
    if created > 0:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            lines = [
                f'📢 **발주공고 업데이트**',
                f'✅ 신규 등록: **{created}건**  |  ⏭ 중복 건너뜀: {skipped}건',
                '',
                '**수집 현황**',
            ] + [f'  • {s}' for s in summary] + [
                '',
                f'🔗 https://krcglobal.vercel.app/pages/notices/bid-notices.html',
            ]
            await channel.send('\n'.join(lines))
