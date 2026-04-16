import aiohttp
from bs4 import BeautifulSoup

SEARCH_URL = 'https://www.adb.org/projects/tenders/procurement'


async def fetch() -> list:
    notices = []

    params = {
        'terms': 'agriculture irrigation rural',
        'procurement_type': 'consulting',
    }
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                SEARCH_URL, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

        soup = BeautifulSoup(html, 'lxml')
        rows = soup.select('table.procurement-table tbody tr, .views-row')

        for row in rows:
            title_el = row.select_one('td.views-field-title a, .field-content a')
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            href  = title_el.get('href', '')
            url   = 'https://www.adb.org' + href if href.startswith('/') else href

            country_el  = row.select_one('td.views-field-field-country')
            deadline_el = row.select_one('td.views-field-field-closing-date')

            notices.append({
                'source': 'adb',
                'title': title,
                'country': country_el.get_text(strip=True) if country_el else '',
                'client': 'ADB',
                'sector': 'agriculture',
                'contractValue': '',
                'deadline': deadline_el.get_text(strip=True) if deadline_el else '',
                'sourceUrl': url,
            })
    except Exception as e:
        print(f'[ADB] 오류: {e}')

    return notices
