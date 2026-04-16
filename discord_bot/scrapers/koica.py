import aiohttp
from bs4 import BeautifulSoup

LIST_URL = 'https://www.koica.go.kr/koica_kr/bid/selectBidList.do'

# 농업 키워드
AGRI_KEYWORDS = ['농업', '농촌', '관개', '식량', '작물', '수산', '산림', '농지', '용수']

# 해외기술용역 키워드
TECH_KEYWORDS = ['기술용역', '컨설팅', '자문', '기술협력', '용역', '타당성',
                 '기술지원', '기술조사', '사업관리', 'PMC', 'PMO', '조사연구']

ALL_KEYWORDS = AGRI_KEYWORDS + TECH_KEYWORDS


async def fetch() -> list:
    notices = []
    headers = {'User-Agent': 'Mozilla/5.0'}

    for kw in ALL_KEYWORDS:
        try:
            params = {'pageIndex': 1, 'searchWrd': kw}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    LIST_URL, params=params, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text()

            soup = BeautifulSoup(html, 'lxml')

            # 1차 셀렉터: 표준 table tbody tr
            rows = soup.select('table tbody tr')

            # fallback: 게시판 목록 형태
            if not rows:
                rows = soup.select('.board-list tr, .list-type tr, .bbs-list tr')

            for row in rows:
                title_el = row.select_one('td a, td .title a')
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not title:
                    continue

                href = title_el.get('href', '')
                url  = 'https://www.koica.go.kr' + href if href.startswith('/') else href

                cols     = row.select('td')
                deadline = cols[-1].get_text(strip=True) if cols else ''

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

    # 중복 제거 (URL 기준)
    seen = set()
    result = []
    for n in notices:
        if n['sourceUrl'] not in seen:
            seen.add(n['sourceUrl'])
            result.append(n)

    print(f'[KOICA] 총 {len(result)}건 수집 (키워드 {len(ALL_KEYWORDS)}개)')
    return result
