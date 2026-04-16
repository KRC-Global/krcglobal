import aiohttp
from datetime import datetime

BASE = 'https://search.worldbank.org/api/v2/procurement'

KEYWORDS = ['agriculture', 'irrigation', 'rural', 'farming', 'crop', 'food security']


async def fetch() -> list:
    notices = []
    seen = set()

    for kw in KEYWORDS:
        params = {
            'format': 'json',
            'rows': 20,
            'os': 0,
            'qterm': kw,
            'sort': 'score',
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    BASE, params=params,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

            for item in data.get('procurement', {}).get('rows', []):
                title = (item.get('project_name') or '').strip()
                url   = (item.get('url') or '').strip()
                if not title or not url or url in seen:
                    continue
                seen.add(url)

                notices.append({
                    'source': 'worldbank',
                    'title': title,
                    'country': item.get('country_name', ''),
                    'client': 'World Bank',
                    'sector': item.get('major_sector_name', ''),
                    'contractValue': '',
                    'deadline': _fmt(item.get('submission_date', '')),
                    'sourceUrl': url,
                })
        except Exception as e:
            print(f'[WorldBank] {kw} 오류: {e}')

    return notices


def _fmt(raw: str) -> str:
    if not raw:
        return ''
    try:
        return datetime.strptime(raw[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except Exception:
        return raw[:10]
