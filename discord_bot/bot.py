import discord
from discord.ext import commands
import aiohttp
import logging
import scheduler as sched
from config import DISCORD_TOKEN, DISCORD_CHANNEL_ID

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

SOURCE_MAP = {
    'worldbank': 'WB', 'adb': 'ADB', 'aiib': 'AIIB', 'afdb': 'AfDB',
    'ifad': 'IFAD', 'ida': 'IDA', 'koica': 'KOICA', 'edcf': 'EDCF',
    'ungm': 'UNGM', 'devex': 'DevEx', 'other': '기타',
}
STATUS_MAP = {
    'new': '미확인', 'reviewed': '검토중', 'applied': '응찰완료', 'closed': '마감'
}
GBMS_BASE = 'https://krcglobal.vercel.app/api/webhook'


@bot.event
async def on_ready():
    print(f'✅ 봇 로그인: {bot.user}')
    sched.setup(bot)
    await bot.tree.sync()
    print('슬래시 커맨드 동기화 완료')


# ── /공고수집 ────────────────────────────────────────────────────────────────
@bot.tree.command(name='공고수집', description='지금 즉시 발주공고를 수집해 GBMS에 등록합니다')
async def fetch_now(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    result = await sched.run_all(bot, notify_channel=False, trigger='manual')
    msg = sched.format_summary(
        result['sources'],
        result['created'],
        result['skipped'],
        result.get('send_error'),
    )
    await interaction.followup.send(msg)


# ── /공고검색 ────────────────────────────────────────────────────────────────
@bot.tree.command(name='공고검색', description='키워드로 GBMS 발주공고를 검색합니다')
async def search_notice(interaction: discord.Interaction, keyword: str):
    await interaction.response.defer(thinking=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'{GBMS_BASE}/notices',
                params={'search': keyword, 'perPage': 5},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
    except Exception as e:
        await interaction.followup.send(f'❌ 검색 실패: {e}')
        return

    items = data.get('data', [])
    total = data.get('total', 0)

    if not items:
        await interaction.followup.send(f'`{keyword}` 검색 결과가 없습니다.')
        return

    lines = [f"🔍 **'{keyword}' 검색결과** — 총 {total}건 중 최대 5건\n"]
    for n in items:
        src      = SOURCE_MAP.get(n.get('source', ''), n.get('source', '').upper())
        status   = STATUS_MAP.get(n.get('status', ''), n.get('status', ''))
        title    = n.get('title', '')[:60]
        country  = n.get('country', '-')
        deadline = n.get('deadline', '-')
        url      = n.get('sourceUrl', '')

        lines.append(f"**[{src}]** {title}")
        lines.append(f"  국가: {country}  |  마감: {deadline}  |  상태: {status}")
        if url:
            lines.append(f"  🔗 {url}")
        lines.append('')

    await interaction.followup.send('\n'.join(lines)[:1900])


# ── /공고현황 ────────────────────────────────────────────────────────────────
@bot.tree.command(name='공고현황', description='미확인(new) 공고 수와 최신 공고를 보여줍니다')
async def notice_status(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'{GBMS_BASE}/notices/summary',
                params={'limit': 5},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
    except Exception as e:
        await interaction.followup.send(f'❌ 조회 실패: {e}')
        return

    count = data.get('newCount', 0)
    items = data.get('data', [])

    lines = [f'📋 **미확인 발주공고: {count}건**\n']

    if items:
        lines.append('**최신 공고**')
        for n in items:
            src      = SOURCE_MAP.get(n.get('source', ''), n.get('source', '').upper())
            title    = n.get('title', '')[:55]
            deadline = n.get('deadline', '-')
            lines.append(f'  • [{src}] {title} (마감: {deadline})')

    lines += ['', f'🔗 https://krcglobal.vercel.app/pages/notices/bid-notices.html']
    await interaction.followup.send('\n'.join(lines))


bot.run(DISCORD_TOKEN)
