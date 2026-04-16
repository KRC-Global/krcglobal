import aiohttp
from bs4 import BeautifulSoup

LIST_URL = 'https://www.koica.go.kr/koica_kr/bid/selectBidList.do'


async def fetch() -> list:
    notices = []

    headers = {'User-Agent': 'Mozilla/5.0'}

    for kw in ['농업', '농촌', '관개', '식량']:
        try:
            params = {'pageIndex': 1, 'searchWrd': kw}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    LIST_URL, params=params, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text()

            soup = BeautifulSoup(html, 'lxml')
            rows = soup.select('table tbody tr')

            for row in rows:
                title_el = row.select_one('td a')
                if not title_el:
                    continue

                title    = title_el.get_text(strip=True)
                href     = title_el.get('href', '')
                url      = 'https://www.koica.go.kr' + href if href.startswith('/') else href
                cols     = row.select('td')
                deadline = cols[-1].get_text(strip=True) if cols else ''

                if not title:
                    continue

                notices.append({
                    'source': 'koica',
                    'title': title,
                    'country': '',
                    'client': 'KOICA',
                    'sector': 'agriculture',
                    'contractValue': '',
                    'deadline': deadline,
                    'sourceUrl': url,
                })
        except Exception as e:
            print(f'[KOICA] {kw} 오류: {e}')

    # 중복 제거
    seen = set()
    result = []
    for n in notices:
        if n['sourceUrl'] not in seen:
            seen.add(n['sourceUrl'])
            result.append(n)
    return result
