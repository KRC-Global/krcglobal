import aiohttp
from xml.etree import ElementTree

SEARCH_URL = 'https://www.ungm.org/Public/Notice/Search'
RSS_URL    = 'https://www.ungm.org/Public/Notice/SearchNotices'

KEYWORDS = 'agriculture irrigation rural farming consulting technical assistance'


async def fetch() -> list:
    notices = []

    # ── 1순위: RSS/Atom 피드 (GET, 무인증) ──────────────────────────────────
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                RSS_URL,
                params={
                    'Keywords': KEYWORDS,
                    'NoticeTypes': '3,4',  # RFQ=3, RFP=4
                },
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/xml, text/xml, */*'},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    notices = _parse_xml(content)
                    if notices:
                        print(f'[UNGM] RSS: {len(notices)}건 수집')
                        return notices
    except Exception as e:
        print(f'[UNGM] RSS 시도 실패: {e}')

    # ── 2순위: POST AJAX fallback ─────────────────────────────────────────
    try:
        payload = {
            'Keywords': KEYWORDS,
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
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SEARCH_URL, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    print(f'[UNGM] AJAX 응답 {resp.status}')
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
        print(f'[UNGM] AJAX fallback: {len(notices)}건 수집')
    except Exception as e:
        print(f'[UNGM] AJAX 오류: {e}')

    return notices


def _parse_xml(content: bytes) -> list:
    """RSS/Atom XML 파싱"""
    notices = []
    try:
        root = ElementTree.fromstring(content)
        # Atom 네임스페이스 처리
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        # RSS <item> 형식
        for item in root.findall('.//item'):
            title    = (item.findtext('title') or '').strip()
            link     = (item.findtext('link') or '').strip()
            pub_date = (item.findtext('pubDate') or '')[:10]
            if not title or not link:
                continue
            notices.append({
                'source': 'ungm',
                'title': title,
                'country': '',
                'client': 'UN',
                'sector': 'agriculture',
                'contractValue': '',
                'deadline': pub_date,
                'sourceUrl': link,
            })

        # Atom <entry> 형식
        if not notices:
            for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry'):
                title = (entry.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
                link_el = entry.find('{http://www.w3.org/2005/Atom}link')
                link = (link_el.get('href') if link_el is not None else '') or ''
                updated = (entry.findtext('{http://www.w3.org/2005/Atom}updated') or '')[:10]
                if not title or not link:
                    continue
                notices.append({
                    'source': 'ungm',
                    'title': title,
                    'country': '',
                    'client': 'UN',
                    'sector': 'agriculture',
                    'contractValue': '',
                    'deadline': updated,
                    'sourceUrl': link,
                })
    except Exception as e:
        print(f'[UNGM] XML 파싱 오류: {e}')
    return notices
