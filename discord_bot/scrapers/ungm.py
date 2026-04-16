import aiohttp

SEARCH_URL = 'https://www.ungm.org/Public/Notice/Search'


async def fetch() -> list:
    notices = []

    payload = {
        'Keywords': 'agriculture irrigation rural farming',
        'NoticeTypes': [3, 4],
        'PageIndex': 0,
        'PageSize': 30,
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0',
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SEARCH_URL, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)

        for item in data.get('Notices', []):
            title = (item.get('Title') or '').strip()
            nid   = item.get('NoticeId', '')
            if not title or not nid:
                continue

            deadline = (item.get('DeadlineDate') or '')[:10]
            notices.append({
                'source': 'ungm',
                'title': title,
                'country': item.get('Country', ''),
                'client': item.get('AgencyName', ''),
                'sector': 'agriculture',
                'contractValue': '',
                'deadline': deadline,
                'sourceUrl': f'https://www.ungm.org/Public/Notice/{nid}',
            })
    except Exception as e:
        print(f'[UNGM] 오류: {e}')

    return notices
