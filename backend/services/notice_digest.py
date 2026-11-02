"""주간 발주공고 다이제스트.

카드는 한 건씩 날아가므로 한 주를 통으로 보기 어렵다. 금요일에 한 장으로
묶어 "이번 주 무엇이 올라왔고, 무엇부터 봐야 하는지"를 알려 준다.

Claude 가 쓰되, 숫자와 사업명은 DB 에서 그대로 넘긴 것만 쓰게 한다.
모델이 건수를 세거나 사업을 지어내면 다이제스트의 쓸모가 사라진다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models import BidNotice
from services.claude_client import ClaudeUnavailable, complete, is_enabled
from services.notice_ai import krc_profile

KST = timezone(timedelta(hours=9))

_SYSTEM = """너는 한국농어촌공사(KRC) 글로벌사업처의 주간 공고 브리핑 담당이다.

{profile}

아래 '이번 주 공고 목록'만 근거로 카카오톡에 보낼 브리핑을 쓴다.

형식(이대로):

[KRC 해외발주공고] {period}

이번 주 {total}건

주목
· <사업명 한 줄 — 왜 볼 만한지>
· <최대 3건까지>

마감 임박
· <사업명 — D-n>
(없으면 이 절 전체를 생략)

한 줄 총평: <한 문장>

규칙:
- **목록에 없는 사업·숫자·날짜를 쓰지 않는다.** 건수는 주어진 값을 그대로 쓴다.
- '주목'은 KRC 본업(관개·농업용수·배수·경지정리)에 가까운 순으로 고른다.
- 사업명은 길면 줄이되 국가명은 남긴다.
- 이모지·굵은 글씨·마크다운 기호를 쓰지 않는다. 카카오톡 평문이다.
- 전체 900자를 넘기지 않는다."""


def _days_left(deadline: str) -> int | None:
    for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d'):
        try:
            d = datetime.strptime((deadline or '').strip()[:10], fmt).date()
        except ValueError:
            continue
        return (d - datetime.now(KST).date()).days
    return None


def collect_week(days: int = 7) -> dict:
    """이번 주 활성 공고를 모은다. LLM 없이도 쓸 수 있는 순수 집계."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (BidNotice.query
            .filter(BidNotice.archived_at.is_(None))
            .filter(BidNotice.created_at >= since)
            .order_by(BidNotice.created_at.desc())
            .all())
    items = []
    for n in rows:
        raw = n.raw_data if isinstance(n.raw_data, dict) else {}
        items.append({
            'id': n.id,
            'source': n.source,
            'country': n.country or '',
            'title': n.title_ko or n.title or '',
            'grade': raw.get('krc_fit') or '',
            'deadline': n.deadline or '',
            'days_left': _days_left(n.deadline or ''),
        })
    closing = [i for i in items
               if i['days_left'] is not None and 0 <= i['days_left'] <= 14]
    closing.sort(key=lambda i: i['days_left'])
    return {'items': items, 'closing': closing, 'total': len(items), 'days': days}


def _period_label(days: int) -> str:
    end = datetime.now(KST).date()
    start = end - timedelta(days=days - 1)
    return f'{start.strftime("%m.%d")}~{end.strftime("%m.%d")}'


def build_digest(days: int = 7) -> dict | None:
    """주간 브리핑 텍스트. 공고가 없으면 None(보내지 않는다)."""
    data = collect_week(days)
    if not data['total']:
        return None

    lines = []
    for i in data['items']:
        dl = (f' / D-{i["days_left"]}' if i['days_left'] is not None
              and i['days_left'] >= 0 else '')
        lines.append(
            f'- [{i["source"]}] [{i["grade"] or "?"}] {i["country"]} '
            f'{i["title"][:110]}{dl}'
        )
    closing_lines = [
        f'- {i["country"]} {i["title"][:80]} / D-{i["days_left"]}'
        for i in data['closing'][:5]
    ]

    period = _period_label(days)
    body = (
        f'이번 주 신규 공고 {data["total"]}건\n\n'
        + '\n'.join(lines)
        + ('\n\n[마감 임박 14일 이내]\n' + '\n'.join(closing_lines)
           if closing_lines else '')
    )

    text = None
    if is_enabled():
        try:
            text = complete(
                _SYSTEM.format(profile=krc_profile(), period=period,
                               total=data['total']),
                body,
                max_tokens=1200,
            ).strip()
        except ClaudeUnavailable as e:
            print(f'[digest] 작성 실패, 기본 형식 사용: {str(e)[:120]}')

    if not text:
        text = _plain_digest(period, data)
    return {'text': text[:1500], 'period': period, **data}


def _plain_digest(period: str, data: dict) -> str:
    """Claude 가 없을 때 쓰는 기본 형식 — 다이제스트가 아예 빠지지 않게."""
    out = [f'[KRC 해외발주공고] {period}', '', f'이번 주 {data["total"]}건', '']
    core = [i for i in data['items'] if i['grade'] == '상'][:3]
    if core:
        out.append('주목')
        for i in core:
            out.append(f'· {i["country"]} {i["title"][:60]}')
        out.append('')
    if data['closing']:
        out.append('마감 임박')
        for i in data['closing'][:3]:
            out.append(f'· {i["country"]} {i["title"][:50]} — D-{i["days_left"]}')
    return '\n'.join(out).strip()
