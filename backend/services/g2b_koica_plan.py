"""나라장터 KOICA 발주계획 수집.

입찰공고(nebid)보다 먼저 공개되는 조달청 발주계획을 씬디스 미러에서 읽어
BidNotice(source=koica_plan) 로 넣는다. 공공데이터포털 OpenAPI 키가 있으면
용역 발주계획 API도 병행한다.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from urllib.parse import quote, urljoin

SOURCE = 'koica_plan'
KOICA_ORG = '한국국제협력단'
SEENTHIS_LIST = 'https://seenthis.kr/bidplan'
SEENTHIS_DETAIL = 'https://seenthis.kr/bidplan/{id}'
KJEBI_DETAIL = 'https://www.kjebi.com/search/smart/order-plan/detail/{plan_no}'

PLAN_NO_RE = re.compile(r'R\d{2}DD\d{8,}')
BOARD_ID_RE = re.compile(r'/bidplan/(\d+)')

_FIELD_PLAN = re.compile(r'발주계획(?:통합)?번호\s*:\s*(R\d{2}DD\d+)')
_FIELD_POSTED = re.compile(r'공개일시\s*:\s*([\d\- :]+)')
_FIELD_TITLE = re.compile(
    r'(?:용\s*역\s*명|사\s*업\s*명|공\s*사\s*명)\s*:\s*(.+?)'
    r'(?=발주기관|공개일시|발주시기|$)',
)
_FIELD_ORG = re.compile(r'발주기관\s*:\s*(.+?)(?=발주시기|용역구분|품\s*명|조달방식|$)')
_FIELD_WHEN = re.compile(r'발주시기\s*:\s*(\d{4}\s*년\s*\d{1,2}\s*월)')
_FIELD_BUDGET = re.compile(
    r'(?:예산액|발주합계금액|구매예정금액(?:\(총액\))?)\s*:\s*([\d,]+)\s*원'
)
_FIELD_METHOD = re.compile(r'계약방법\s*:\s*([^\s\[담당]+)')
_FIELD_PROCURE = re.compile(r'조달방식\s*:\s*([^\s계약담당]+)')
_KIND_RE = re.compile(r'\[(용역|물품|공사|외자)\]')

_COUNTRY_KO = (
    ('방글라데시', 'Bangladesh'),
    ('라오스', 'Laos'),
    ('몽골', 'Mongolia'),
    ('베트남', 'Vietnam'),
    ('캄보디아', 'Cambodia'),
    ('미얀마', 'Myanmar'),
    ('인도네시아', 'Indonesia'),
    ('필리핀', 'Philippines'),
    ('스리랑카', 'Sri Lanka'),
    ('네팔', 'Nepal'),
    ('인도', 'India'),
    ('파키스탄', 'Pakistan'),
    ('우즈베키스탄', 'Uzbekistan'),
    ('키르기스', 'Kyrgyzstan'),
    ('타지키스탄', 'Tajikistan'),
    ('카자흐', 'Kazakhstan'),
    ('몽고', 'Mongolia'),
    ('중국', 'China'),
    ('몽골', 'Mongolia'),
    ('가나', 'Ghana'),
    ('케냐', 'Kenya'),
    ('탄자니아', 'Tanzania'),
    ('에티오피아', 'Ethiopia'),
    ('르완다', 'Rwanda'),
    ('우간다', 'Uganda'),
    ('세네갈', 'Senegal'),
    ('코트디부아르', 'Cote d\'Ivoire'),
    ('나이지리아', 'Nigeria'),
    ('시에라리온', 'Sierra Leone'),
    ('라이베리아', 'Liberia'),
    ('모잠비크', 'Mozambique'),
    ('이집트', 'Egypt'),
    ('모로코', 'Morocco'),
    ('튀니지', 'Tunisia'),
    ('리비아', 'Libya'),
    ('남아공', 'South Africa'),
    ('페루', 'Peru'),
    ('파라과이', 'Paraguay'),
    ('에콰도르', 'Ecuador'),
    ('콜롬비아', 'Colombia'),
    ('볼리비아', 'Bolivia'),
    ('과테말라', 'Guatemala'),
    ('온두라스', 'Honduras'),
    ('니카라과', 'Nicaragua'),
    ('엘살바도르', 'El Salvador'),
    ('도미니카', 'Dominican Republic'),
    ('아이티', 'Haiti'),
    ('자메이카', 'Jamaica'),
    ('피지', 'Fiji'),
    ('솔로몬', 'Solomon Islands'),
    ('동티모르', 'Timor-Leste'),
    ('팔레스타인', 'Palestine'),
    ('요르단', 'Jordan'),
    ('이라크', 'Iraq'),
    ('우크라이나', 'Ukraine'),
    ('몰도바', 'Moldova'),
    ('알바니아', 'Albania'),
    ('세르비아', 'Serbia'),
)

_ORG_MARKERS = ('한국국제협력단', 'KOICA', '코이카')


def is_koica_org(name: str) -> bool:
    blob = name or ''
    return any(m in blob for m in _ORG_MARKERS)


_PLAN_EXTRA_KO = (
    '농식품', '낙농', '미곡', '농가', '농기계', '벼 품종', '쌀 생산',
    '농업생산', '영농', '관개',
)

FRESHNESS_DAYS = 60
# 2026-09-09 테스트 백필(공고 #406–#413) 이후 공개분만 신규 수집·알림.
DEFAULT_MIN_POSTED = '2026-09-10'


def should_store_plan(grade: str, title: str = '', item_kind: str = '') -> bool:
    """농업·농촌(중) 이상, 또는 용역 제목에 농식품·낙농 등이 있으면 저장."""
    from services.krc_fitness import GRADE_HIGH, GRADE_MID
    if grade in (GRADE_HIGH, GRADE_MID):
        return True
    kind = (item_kind or '').strip()
    if kind in ('물품', 'goods', 'Goods'):
        return False
    blob = title or ''
    return any(k in blob for k in _PLAN_EXTRA_KO)


def _parse_posted_date(posted: str):
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', (posted or '').strip())
    if not m:
        return None
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()


def min_posted_cutoff():
    raw = (os.environ.get('KOICA_PLAN_MIN_POSTED') or DEFAULT_MIN_POSTED).strip()
    return _parse_posted_date(raw)


def _is_stale_posted(posted: str, days: int = FRESHNESS_DAYS) -> bool:
    posted_date = _parse_posted_date(posted)
    if posted_date is None:
        return False
    return (datetime.utcnow().date() - posted_date).days > days


def _is_before_min_posted(posted: str) -> bool:
    """백필 기준일 이전 공개분은 신규 수집에서 제외한다."""
    cutoff = min_posted_cutoff()
    posted_date = _parse_posted_date(posted)
    if cutoff is None or posted_date is None:
        return False
    return posted_date < cutoff


def country_from_title(title: str) -> str:
    text = title or ''
    for ko, en in _COUNTRY_KO:
        if ko in text:
            return en
    return ''


def parse_plan_blob(text: str) -> dict:
    """나라장터/씬디스 발주계획 본문에서 핵심 필드를 뽑는다."""
    blob = re.sub(r'\s+', ' ', text or '').strip()
    plan_no = ''
    m = _FIELD_PLAN.search(blob)
    if m:
        plan_no = m.group(1)
    else:
        m = PLAN_NO_RE.search(blob)
        if m:
            plan_no = m.group(0)

    posted = (_FIELD_POSTED.search(blob) or [None, ''])[1].strip()
    title = (_FIELD_TITLE.search(blob) or [None, ''])[1].strip()
    org = (_FIELD_ORG.search(blob) or [None, ''])[1].strip(' .')
    order_month = (_FIELD_WHEN.search(blob) or [None, ''])[1].strip(' .')
    budget = (_FIELD_BUDGET.search(blob) or [None, ''])[1]
    method = (_FIELD_METHOD.search(blob) or [None, ''])[1].strip(' .')
    procure = (_FIELD_PROCURE.search(blob) or [None, ''])[1].strip(' .')
    kind_m = _KIND_RE.search(blob)
    item_kind = kind_m.group(1) if kind_m else ''

    if title:
        title = re.split(r'발주기관|공개일시', title)[0].strip(' .')
    budget_fmt = f'{budget}원' if budget else ''

    return {
        'plan_no': plan_no,
        'posted': posted,
        'title': title,
        'org': org,
        'order_month': order_month,
        'budget': budget_fmt,
        'method': method,
        'procure': procure,
        'item_kind': item_kind,
    }


def parse_seenthis_list(html: str) -> list[dict]:
    """씬디스 발주계획 검색 결과 HTML → 항목 리스트."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return _parse_seenthis_list_regex(html)

    soup = BeautifulSoup(html or '', 'html.parser')
    items = []
    seen = set()
    for a in soup.select('a[href*="/bidplan/"]'):
        href = a.get('href') or ''
        m = BOARD_ID_RE.search(href)
        if not m:
            continue
        board_id = m.group(1)
        if board_id in seen or board_id in ('', '217518'):
            continue
        # 공지/페이지네이션 제외
        if 'page=' in href and '/bidplan/' not in href.split('?')[0]:
            continue
        parent = a.find_parent(['li', 'div', 'article', 'tr']) or a.parent
        block = parent.get_text(' ', strip=True) if parent else a.get_text(' ', strip=True)
        # 제목 링크 다음 형제 스니펫도 합친다
        nxt = parent.find_next_sibling() if parent else None
        if nxt:
            block = f'{block} {nxt.get_text(" ", strip=True)}'
        parsed = parse_plan_blob(block)
        heading = a.get_text(' ', strip=True)
        if not parsed.get('title'):
            parsed['title'] = re.sub(r'^\[(?:용역|물품|공사|외자)\]\s*', '', heading).strip()
        if not parsed.get('item_kind'):
            km = _KIND_RE.search(heading)
            if km:
                parsed['item_kind'] = km.group(1)
        if not parsed.get('plan_no') and not parsed.get('title'):
            continue
        parsed['seenthis_id'] = board_id
        parsed['seenthis_url'] = urljoin(SEENTHIS_LIST + '/', board_id)
        seen.add(board_id)
        items.append(parsed)
    return items


def _parse_seenthis_list_regex(html: str) -> list[dict]:
    items = []
    seen = set()
    for m in re.finditer(
        r'href="([^"]*/bidplan/(\d+)[^"]*)"[^>]*>(.*?)</a>(.{0,800})',
        html or '',
        re.I | re.S,
    ):
        board_id = m.group(2)
        if board_id in seen:
            continue
        heading = re.sub(r'<[^>]+>', ' ', m.group(3))
        snippet = re.sub(r'<[^>]+>', ' ', m.group(4))
        parsed = parse_plan_blob(f'{heading} {snippet}')
        if not parsed.get('title'):
            parsed['title'] = re.sub(r'^\[(?:용역|물품|공사|외자)\]\s*', '', heading).strip()
        parsed['seenthis_id'] = board_id
        parsed['seenthis_url'] = SEENTHIS_DETAIL.format(id=board_id)
        seen.add(board_id)
        items.append(parsed)
    return items


def format_plan_summary(plan: dict, title: str = '') -> str:
    name = title or plan.get('title') or ''
    lines = [
        '[나라장터 발주계획]',
        f'{KOICA_ORG}',
        name,
        f'발주번호 {plan.get("plan_no") or "-"}',
        f'공개 {plan.get("posted") or "-"} · 발주시기 {plan.get("order_month") or "-"}',
    ]
    if plan.get('budget'):
        lines.append(f'예산 {plan["budget"]}')
    extra = ' · '.join(p for p in (plan.get('method'), plan.get('procure'), plan.get('item_kind')) if p)
    if extra:
        lines.append(extra)
    lines.append('※ 입찰공고 전 발주계획입니다.')
    return '\n'.join(lines)


def to_notice_item(plan: dict) -> dict | None:
    title = (plan.get('title') or '').strip()
    plan_no = (plan.get('plan_no') or '').strip()
    if not title or not is_koica_org(plan.get('org') or title):
        # 검색 결과 페이지는 KOICA 질의이므로 org 가 잘려도 제목+검색 맥락으로 통과
        if not title:
            return None
        if plan.get('org') and not is_koica_org(plan.get('org')):
            return None
        if not plan.get('org') and not is_koica_org(title) and not plan_no:
            return None
    if not plan_no and not plan.get('seenthis_id'):
        return None

    item_kind = plan.get('item_kind') or ''
    combined = f"{title} {item_kind}"
    sector = 'consulting' if '용역' in item_kind or 'PMC' in title.upper() else 'agriculture'
    source_url = plan.get('seenthis_url') or ''
    if not source_url and plan.get('seenthis_id'):
        source_url = SEENTHIS_DETAIL.format(id=plan['seenthis_id'])
    if not source_url and plan_no:
        source_url = f'https://www.kjebi.com/search/smart/order-plan/detail/{plan_no}'
    if not source_url:
        return None

    tag = '발주계획'
    decorated = title if f'[{tag}]' in title else f'{title} [{tag}]'
    if item_kind and f'[{item_kind}]' not in decorated:
        decorated = f'{decorated} [{item_kind}]'

    return {
        'source': SOURCE,
        'title': decorated,
        'country': country_from_title(title),
        'client': KOICA_ORG,
        'sector': sector,
        'contract_value': plan.get('budget') or '',
        'deadline': '',
        'source_url': source_url,
        'raw_data': {
            'channel': 'g2b_order_plan',
            'plan_no': plan_no,
            'posted': plan.get('posted') or '',
            'order_month': plan.get('order_month') or '',
            'item_kind': item_kind,
            'method': plan.get('method') or '',
            'procure': plan.get('procure') or '',
            'org': plan.get('org') or KOICA_ORG,
            'seenthis_id': plan.get('seenthis_id') or '',
            'title': title,
        },
    }


def _browser_headers() -> dict:
    return {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
    }


def _fetch_seenthis_pages(max_pages: int = 3) -> list[dict]:
    import requests as req

    q = quote(KOICA_ORG)
    results = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = f'{SEENTHIS_LIST}?sfl=wr_content&stx={q}&page={page}'
        r = req.get(url, headers=_browser_headers(), timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f'seenthis HTTP {r.status_code} page {page}')
        page_items = parse_seenthis_list(r.text)
        fresh = 0
        for it in page_items:
            key = it.get('plan_no') or it.get('seenthis_id')
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(it)
            fresh += 1
        if fresh == 0:
            break
    return results


def _enrich_detail(plan: dict) -> dict:
    """예산 등이 비었으면 씬디스 상세를 한 번 더 읽는다."""
    if plan.get('budget') and plan.get('method'):
        return plan
    board_id = plan.get('seenthis_id')
    if not board_id:
        return plan
    try:
        import requests as req
        r = req.get(
            SEENTHIS_DETAIL.format(id=board_id),
            headers=_browser_headers(),
            timeout=15,
        )
        if r.status_code != 200:
            return plan
        extra = parse_plan_blob(r.text)
        for k, v in extra.items():
            if v and not plan.get(k):
                plan[k] = v
    except Exception as e:
        print(f'[koica-plan] 상세 보강 실패 {board_id}: {e}')
    return plan


def _collect_via_openapi() -> list[dict]:
    """조달청 발주계획현황 OpenAPI — 키가 있을 때만."""
    key = (
        os.environ.get('DATA_GO_KR_API_KEY')
        or os.environ.get('KOICA_API_KEY')
        or ''
    ).strip()
    if not key:
        return []
    try:
        import requests as req
    except ImportError:
        return []

    now = datetime.utcnow()
    start = now.replace(day=1)
    # 최근 2개월 등록분
    if start.month == 1:
        bgn = datetime(start.year - 1, 11, 1)
    elif start.month == 2:
        bgn = datetime(start.year - 1, 12, 1)
    else:
        bgn = datetime(start.year, start.month - 2, 1)
    params = {
        'serviceKey': key,
        'pageNo': 1,
        'numOfRows': 100,
        'inqryDiv': 1,
        'type': 'json',
        'inqryBgnDt': bgn.strftime('%Y%m%d0000'),
        'inqryEndDt': now.strftime('%Y%m%d2359'),
        'ntceInsttNm': KOICA_ORG,
    }
    url = (
        'https://apis.data.go.kr/1230000/ao/OrderPlanSttusService'
        '/getOrderPlanSttusListServcPPSSrch'
    )
    try:
        r = req.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f'[koica-plan] OpenAPI 요청 실패: {e}')
        return []

    body = (data.get('response') or {}).get('body') or {}
    items = ((body.get('items') or {}).get('item')) if isinstance(body, dict) else None
    if items is None:
        # 일부 게이트웨이는 바로 items
        items = data.get('items') or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []

    out = []
    for row in items:
        if not isinstance(row, dict):
            continue
        org = (
            row.get('ntceInsttNm')
            or row.get('orderInsttNm')
            or row.get('dminsttNm')
            or ''
        )
        title = (
            row.get('bsnsNm')
            or row.get('svcNm')
            or row.get('orderPlanNm')
            or row.get('bidNtceNm')
            or ''
        ).strip()
        plan_no = (
            row.get('orderPlanUntyNo')
            or row.get('untyOrderPlanNo')
            or row.get('ntceNo')
            or ''
        ).strip()
        if not title or not is_koica_org(org + title):
            continue
        budget = row.get('bsnsBdgtAmt') or row.get('bdgtAmt') or row.get('allocAmt') or ''
        if isinstance(budget, (int, float)):
            budget = f'{int(budget):,}원'
        elif budget and '원' not in str(budget):
            digits = re.sub(r'[^\d]', '', str(budget))
            budget = f'{int(digits):,}원' if digits else ''
        posted = (
            row.get('ntceDt')
            or row.get('rgstDt')
            or row.get('orderPlanNtceDt')
            or ''
        )
        out.append({
            'plan_no': plan_no,
            'posted': str(posted)[:19],
            'title': title,
            'org': org or KOICA_ORG,
            'order_month': str(row.get('orderDt') or row.get('orderMnth') or ''),
            'budget': budget,
            'method': row.get('cntrctMthdNm') or '',
            'procure': row.get('prcmntMthdNm') or '',
            'item_kind': '용역',
            'seenthis_id': '',
            'seenthis_url': (
                f'https://www.kjebi.com/search/smart/order-plan/detail/{plan_no}'
                if plan_no else ''
            ),
        })
    print(f'[koica-plan] OpenAPI {len(out)}건')
    return out


def collect_koica_g2b_plans(*, max_pages: int = 3, enrich_limit: int = 15) -> list[dict]:
    """KOICA 나라장터 발주계획 → 수집기 아이템 리스트.

    씬디스를 기본으로 하고, OpenAPI 키면 용역 계획을 보강한다.
    실패는 호출자에게 올려 이번 소스 전체를 에러로 보호하게 한다.
    """
    errors = []
    plans = []
    try:
        plans = _fetch_seenthis_pages(max_pages=max_pages)
    except Exception as e:
        errors.append(f'seenthis: {e}')
        print(f'[koica-plan] seenthis 실패: {e}')

    try:
        api_plans = _collect_via_openapi()
        have = {p.get('plan_no') for p in plans if p.get('plan_no')}
        for p in api_plans:
            if p.get('plan_no') and p['plan_no'] not in have:
                plans.append(p)
                have.add(p['plan_no'])
    except Exception as e:
        print(f'[koica-plan] OpenAPI 예외: {e}')

    if not plans and errors:
        raise RuntimeError('KOICA 나라장터 발주계획 수집 실패: ' + ' | '.join(errors))

    from services.krc_fitness import classify_krc_fit

    items = []
    seen_urls = set()
    enrich_left = enrich_limit
    for plan in plans:
        org = (plan.get('org') or '').strip()
        title = (plan.get('title') or '').strip()
        if org.startswith('한국국') or is_koica_org(org) or is_koica_org(title):
            plan['org'] = KOICA_ORG
        else:
            continue
        if _is_stale_posted(plan.get('posted') or ''):
            continue
        if _is_before_min_posted(plan.get('posted') or ''):
            continue
        grade, _ = classify_krc_fit(
            f"{title} {plan.get('org') or ''}",
            item_kind=plan.get('item_kind') or '',
        )
        if not should_store_plan(grade, title=title, item_kind=plan.get('item_kind') or ''):
            continue
        if enrich_left > 0:
            plan = _enrich_detail(plan)
            enrich_left -= 1
        item = to_notice_item(plan)
        if not item:
            continue
        url = item['source_url']
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(item)

    print(f'[koica-plan] {len(items)} KOICA 발주계획 (raw {len(plans)})')
    return items
