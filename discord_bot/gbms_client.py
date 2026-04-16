import hmac
import hashlib
import json
import aiohttp
from config import GBMS_WEBHOOK_URL, WEBHOOK_BOT_SECRET


def _sign(body: bytes) -> str:
    return 'sha256=' + hmac.new(
        WEBHOOK_BOT_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()


async def send_notices(notices: list) -> dict:
    if not notices:
        return {'success': True, 'created': 0, 'skipped': 0}

    body = json.dumps({'notices': notices}, ensure_ascii=False).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-Bot-Signature': _sign(body),
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            GBMS_WEBHOOK_URL, data=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            return await resp.json()


async def send_run_summary(summary: dict) -> dict:
    """수집 실행 요약을 GBMS에 기록 (/api/webhook/notices/runs)"""
    url = GBMS_WEBHOOK_URL.rstrip('/') + '/runs'
    body = json.dumps(summary, ensure_ascii=False).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-Bot-Signature': _sign(body),
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, data=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            return await resp.json()
