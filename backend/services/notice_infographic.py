"""발주공고 보고용 16:9 인포그래픽 슬라이드.

기본 경로는 결정론적 렌더(`style='slide'`)다. Chrome 이 있으면 HTML 을 캡처하고,
Vercel 같은 서버리스 환경에서는 Pillow 로 같은 정보 구조를 직접 그린다. 실제
폰트를 사용하므로 한글·숫자·URL 이 틀어지지 않아 사람이 QA 하지 않는 자동
파이프라인에 적합하다. `style='imagegen'` 은 Codex `$imagegen` 으로 같은 구성의
포스터를 그리지만 작은 텍스트의 정확도가 보장되지 않는다.

디자인: Danuri 워크북 팔레트(따뜻한 미색 종이 · 검정 잉크 · 베이지 패널 ·
갈색 룰 · 붉은 인장) 위에 Obsidian 의 콜아웃/태그/인용과 진행 순서도를 얹는다.
폰트는 Pretendard(assets/fonts/notice).
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from html import escape, unescape
from pathlib import Path
from string import Template
from urllib.parse import urlparse

SLIDE_W = 1920
SLIDE_H = 1080

# Danuri 워크북 팔레트
PALETTE = {
    'W': SLIDE_W,
    'H': SLIDE_H,
    'PAPER': '#F7F3EA',   # 미색 종이
    'PANEL': '#EDE5D5',   # 베이지 패널
    'RULE': '#8B6F47',    # 갈색 룰
    'INK': '#1A1A1A',     # 검정 잉크
    'MUTED': '#6E6355',
    'SEAL': '#B0392E',    # 붉은 인장
    'BLUE': '#3E6B8A',    # 콜아웃 info
    'AMBER': '#A9762B',   # 콜아웃 warn
    'GREEN': '#4C7A5A',   # 콜아웃 tip
}

REPO_ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = REPO_ROOT / 'assets' / 'fonts' / 'notice'
FONT_FILES = ('Pretendard-Regular.ttf', 'Pretendard-Bold.ttf')
CHROME_BIN = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

SOURCE_LABELS = {
    'worldbank': 'World Bank',
    'ungm': 'UNGM',
    'adb': 'ADB',
    'afdb': 'AfDB',
    'aiib': 'AIIB',
    'isdb': 'IsDB',
    'ifad': 'IFAD',
    'koica': 'KOICA',
    'koica_plan': 'KOICA 발주계획',
    'edcf': 'EDCF',
}

# 발주처(수집 소스)별 테마. 상단 바·발주처명·룰에 써서 한눈에 구분한다.
SOURCE_THEMES = {
    'worldbank': {'ACCENT': '#1B4F9C', 'ACCENT_SOFT': '#D6E2F5'},
    'adb':       {'ACCENT': '#0F7B73', 'ACCENT_SOFT': '#D4EBE7'},
    'afdb':      {'ACCENT': '#D9761F', 'ACCENT_SOFT': '#F6E3CC'},
    'aiib':      {'ACCENT': '#2C3E8C', 'ACCENT_SOFT': '#D9DEF0'},
    'isdb':      {'ACCENT': '#0A6B4A', 'ACCENT_SOFT': '#D3EBDF'},
    'ifad':      {'ACCENT': '#C45C26', 'ACCENT_SOFT': '#F3E0D4'},
    'koica':     {'ACCENT': '#C41E3A', 'ACCENT_SOFT': '#F5D6DC'},
    'koica_plan': {'ACCENT': '#C41E3A', 'ACCENT_SOFT': '#F5D6DC'},
    'edcf':      {'ACCENT': '#0A3166', 'ACCENT_SOFT': '#D3DCEB'},
    'ungm':      {'ACCENT': '#0B8DC7', 'ACCENT_SOFT': '#D2EEF8'},
}
DEFAULT_THEME = {'ACCENT': '#8B6F47', 'ACCENT_SOFT': '#E9DFCD'}


def _source_theme(source_key: str) -> dict:
    return SOURCE_THEMES.get((source_key or '').strip().lower(), DEFAULT_THEME)

SECTOR_LABELS = {
    'agriculture': '농업',
    'irrigation': '관개·수리',
    'water': '수자원',
    'rural': '농촌개발',
    'environment': '환경',
    'energy': '에너지',
    'infrastructure': '인프라',
}

# ── 공고 유형 판별 ───────────────────────────────────────────────────────────
# 영문 제목의 대괄호 태그가 국문보다 표기가 일정해(국문은 '관심표명 요청' /
# '관심표명요청' / '관심 표명 요청' 등 변형이 많다) 영문을 1순위로 본다.
# 순서 주의: 'Invitation for Prequalification' 이 'Invitation for Bids' 보다 먼저.
NOTICE_KINDS: tuple[tuple[str, str, str, str], ...] = (
    ('pq', '사전적격심사',
     r'prequalification',
     r'사전\s*적격\s*심사'),
    ('eoi', '관심표명',
     r'expressions?\s+of\s+interest|\bEOI\b|\bREOI\b',
     r'관심\s*표명'),
    ('itb', '입찰',
     r'invitation\s+(for|to)\s+bid',
     r'입찰\s*(초청|공고)'),
    ('plan', '조달예고',
     r'(general|specific)\s+procurement\s+notice|procurement\s+plan|\bGPN\b|\bSPN\b',
     r'조달\s*(계획|공고)|일반\s*조달|특정\s*조달'),
)

# 유형별 진행 순서도. {posted}/{due} 는 렌더 시 치환한다.
FLOWS: dict[str, list[tuple[str, str, str]]] = {
    'eoi': [
        ('send', '공고 게시', '{posted}'),
        ('clock', '관심표명(EOI) 제출', '{due}'),
        ('search', '숏리스트 선정', '발주처 심사'),
        ('sign', 'RFP 제출·계약', '선정 업체 대상'),
    ],
    'itb': [
        ('send', '입찰 공고', '{posted}'),
        ('clock', '입찰서 제출', '{due}'),
        ('search', '개찰·평가', '발주처'),
        ('sign', '낙찰·계약 체결', '—'),
    ],
    'pq': [
        ('send', '공고 게시', '{posted}'),
        ('clock', 'PQ 서류 제출', '{due}'),
        ('search', '적격 심사', '발주처'),
        ('sign', '본입찰 초청', '적격 업체 대상'),
    ],
    'plan': [
        ('send', '조달 예고 게시', '{posted}'),
        ('clock', '세부 공고 대기', '{due}'),
        ('search', '입찰·EOI 공고', '추후 공지'),
        ('sign', '참여 검토', 'KRC 내부'),
    ],
    'generic': [
        ('send', '공고 게시', '{posted}'),
        ('clock', '서류 제출', '{due}'),
        ('search', '발주처 심사', '공고 후 개별 통보'),
        ('sign', '계약 체결', '—'),
    ],
}

# 발주번호 패턴 — 공고 원문에서 최선 노력으로 추출한다.
NOTICE_NO_RE = re.compile(
    r'(?:AMI|RFP|RFQ|RFB|IFB|ITB|REOI|ICB|NCB)\s*N?[°ºo]?\s*[:.]?\s*'
    r'([A-Z0-9][A-Z0-9/\-]{6,40})'
)

# ── 인라인 SVG 아이콘 (외부 의존 없음 — 폐쇄망 동작 보장) ────────────────────
ICONS = '''
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/>
  <path d="M3 12h18M12 3c2.6 2.6 2.6 15 0 18M12 3c-2.6 2.6-2.6 15 0 18"/></symbol>
<symbol id="i-bank" viewBox="0 0 24 24"><path d="M3 9.5 12 4l9 5.5"/>
  <path d="M5 10v8M9.6 10v8M14.4 10v8M19 10v8M3 20h18"/></symbol>
<symbol id="i-sprout" viewBox="0 0 24 24"><path d="M12 21v-8"/>
  <path d="M12 13C12 9 9 6.5 5 6.5c0 4 2.8 6.5 7 6.5Z"/>
  <path d="M12.6 13c0-3.2 2.4-5.2 5.6-5.2 0 3.2-2.4 5.2-5.6 5.2Z"/></symbol>
<symbol id="i-calendar" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/>
  <path d="M3 10h18M8 3v4M16 3v4"/></symbol>
<symbol id="i-coin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/>
  <path d="M12 7v10M9.5 9.6c0-1.2 1.1-1.9 2.5-1.9s2.5.7 2.5 1.9-1.1 1.7-2.5 1.9-2.5.8-2.5 2 1.1 1.9 2.5 1.9 2.5-.7 2.5-1.9"/></symbol>
<symbol id="i-hash" viewBox="0 0 24 24"><path d="M9 3 7 21M17 3l-2 18M4 8.5h16M3 15.5h16"/></symbol>
<symbol id="i-link" viewBox="0 0 24 24"><path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 1 0-5.7-5.7L11.9 6.4"/>
  <path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.8 2.8a4 4 0 1 0 5.7 5.7l1.4-1.4"/></symbol>
<symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/>
  <path d="M12 11v5.5M12 7.6v.9"/></symbol>
<symbol id="i-alert" viewBox="0 0 24 24"><path d="M12 3.8 21 19.5H3L12 3.8Z"/>
  <path d="M12 10v4.2M12 16.8v.9"/></symbol>
<symbol id="i-bulb" viewBox="0 0 24 24"><path d="M9.2 17h5.6M10 20.5h4"/>
  <path d="M12 3.5a5.6 5.6 0 0 0-3.3 10.1c.5.4.8 1 .8 1.6h5c0-.6.3-1.2.8-1.6A5.6 5.6 0 0 0 12 3.5Z"/></symbol>
<symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/>
  <path d="M12 7v5.4l3.4 2"/></symbol>
<symbol id="i-send" viewBox="0 0 24 24"><path d="M21 3 10.5 13.5"/>
  <path d="M21 3l-6.8 18-3.7-7.5L3 9.8 21 3Z"/></symbol>
<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></symbol>
<symbol id="i-sign" viewBox="0 0 24 24"><path d="M4 20.5h16"/>
  <path d="M5 16.5 15.6 5.9a2.2 2.2 0 0 1 3.1 3.1L8.1 19.6l-4 .9.9-4Z"/></symbol>
</defs></svg>
'''

CSS = Template('''
@font-face { font-family:"Pretendard"; src:url("./Pretendard-Regular.ttf") format("truetype"); font-weight:400; }
@font-face { font-family:"Pretendard"; src:url("./Pretendard-Bold.ttf") format("truetype"); font-weight:700; }
* { box-sizing:border-box; margin:0; padding:0; }
html,body { width:${W}px; height:${H}px; overflow:hidden; }
body {
  background:$PAPER; color:$INK; font-family:"Pretendard",sans-serif;
  padding:0 64px 34px; display:flex; flex-direction:column;
  background-image:
    repeating-linear-gradient(0deg, rgba(139,111,71,.035) 0 1px, transparent 1px 4px),
    repeating-linear-gradient(90deg, rgba(139,111,71,.022) 0 1px, transparent 1px 6px);
}
svg.ic { width:1em; height:1em; fill:none; stroke:currentColor; stroke-width:1.8;
         stroke-linecap:round; stroke-linejoin:round; flex:0 0 auto; }

/* ── 헤더 ── */
.head-bar { height:14px; background:$ACCENT; margin:0 -64px 16px; }
.head { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; }
.issuer-block { min-width:0; }
.issuer { font-weight:700; font-size:32px; letter-spacing:.04em; color:$ACCENT; line-height:1.15; }
.client { margin-top:4px; font-size:18px; color:$MUTED; }
.head .label { margin-top:6px; font-weight:700; font-size:16px; letter-spacing:.28em; color:$MUTED; }
.tags { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.tag {
  font-size:17px; font-weight:700; color:$ACCENT;
  background:$ACCENT_SOFT; border:1px solid $ACCENT;
  border-radius:999px; padding:5px 15px 6px;
}
.rule { height:3px; background:$ACCENT; margin-top:12px; }
.rule.thin { height:1px; background:$RULE; opacity:.45; }

/* ── 본문 2단 ── */
.body { flex:1 1 auto; display:flex; gap:36px; padding-top:18px; min-height:0; overflow:hidden; }
.left { flex:1 1 0; min-width:0; display:flex; flex-direction:column; overflow:hidden; }
.right { width:560px; flex:0 0 560px; display:flex; flex-direction:column; gap:12px; }

h1 { font-size:46px; font-weight:700; line-height:1.28; letter-spacing:-.02em; word-break:keep-all; }
.subtitle { margin-top:12px; font-size:18px; line-height:1.4; color:$MUTED; word-break:break-word; }

/* ── Obsidian 콜아웃 ── */
.callout {
  margin-top:12px; border-radius:8px; padding:12px 18px 13px 16px;
  border:1px solid rgba(139,111,71,.3); border-left-width:6px; border-left-style:solid;
  flex:1 1 0; min-height:0;
}
.callout .ct {
  display:flex; align-items:center; gap:9px;
  font-size:19px; font-weight:700; letter-spacing:.02em; margin-bottom:8px;
}
.callout .ct svg.ic { font-size:21px; stroke-width:2; }
.callout p { font-size:20px; line-height:1.58; word-break:keep-all; margin-top:5px; }
.callout p:first-of-type { margin-top:0; }
.callout p::before { content:"\\2022"; color:$RULE; font-weight:700; margin-right:8px; }
.c-info { background:rgba(62,107,138,.10); border-left-color:$BLUE; }
.c-info .ct { color:$BLUE; }
.c-warn { background:rgba(169,118,43,.12); border-left-color:$AMBER; }
.c-warn .ct { color:$AMBER; }
.c-tip  { background:rgba(76,122,90,.11); border-left-color:$GREEN; }
.c-tip  .ct { color:$GREEN; }

/* ── D-day 배지 ── */
.dday {
  display:flex; align-items:center; gap:14px;
  background:$PANEL; border:1px solid $RULE; border-left:6px solid $SEAL;
  border-radius:8px; padding:10px 16px;
}
.dday svg.ic { font-size:36px; color:$SEAL; stroke-width:1.6; }
.dday .n { font-size:36px; font-weight:700; line-height:1; color:$SEAL; letter-spacing:-.01em; }
.dday .s { font-size:17px; color:$MUTED; margin-top:5px; }

/* 달력 일러스트: 스프링 바인딩 + 빨간 월 머리 + 큰 일자 */
.cal {
  width:56px; flex:0 0 56px; background:#fff; border:1.5px solid $SEAL;
  border-radius:9px; overflow:hidden; text-align:center; line-height:1;
}
.cal .rings {
  display:flex; justify-content:space-evenly; background:$SEAL; height:8px;
}
.cal .rings span {
  width:8px; height:8px; margin-top:3px; background:$PAPER;
  border:1.5px solid $SEAL; border-radius:50%;
}
.cal .cm {
  background:$SEAL; color:#fff; font-size:12px; font-weight:700;
  letter-spacing:.06em; padding:1px 0 6px;
}
.cal .cd { font-size:24px; font-weight:700; color:$INK; padding:6px 0 1px; }
.cal .cy { font-size:11px; color:$MUTED; padding:0 0 7px; }
.cal.cal-sm { width:42px; flex-basis:42px; border-radius:7px; }
.cal.cal-sm .rings { height:6px; }
.cal.cal-sm .rings span { width:6px; height:6px; margin-top:2px; }
.cal.cal-sm .cm { font-size:10px; padding:0 0 4px; }
.cal.cal-sm .cd { font-size:18px; padding:4px 0 0; }
.cal.cal-sm .cy { font-size:9px; padding:0 0 5px; }

/* ── 아이콘 팩트 카드 ── */
.cards { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.card {
  background:$PANEL; border:1px solid rgba(139,111,71,.55); border-radius:8px;
  padding:10px 14px 11px; display:flex; gap:10px; align-items:center; min-height:78px;
}
.card.has-cal { min-height:90px; }
.card svg.ic { font-size:24px; color:$RULE; }
.card .k { font-size:15px; font-weight:700; color:$RULE; letter-spacing:.08em; }
.card .v { font-size:22px; font-weight:700; line-height:1.22; margin-top:4px; word-break:keep-all; }
.card .v.sm { font-size:18px; line-height:1.28; }
.card .v.nowrap { white-space:nowrap; }

.urlbox {
  background:$PANEL; border:1px solid rgba(139,111,71,.55); border-radius:8px;
  padding:10px 14px; display:flex; gap:10px; align-items:center;
}
.urlbox svg.ic { font-size:20px; color:$RULE; }
.urlbox .u { font-size:16px; line-height:1.4; word-break:keep-all; }

/* 원문 발췌가 없는 공고는 콜아웃이 남는 세로 공간을 나눠 갖는다. */
body.noquote .body { flex:1; }
body.noquote .callout { flex:1; display:flex; flex-direction:column; justify-content:center; }
body.noquote .lower { flex:0 0 128px; }

/* ── 하단: 원문 발췌 + 순서도 | QR. 높이를 고정해 발췌가 잘리거나 QR과 겹치지 않게. */
.lower {
  display:flex; gap:16px; align-items:stretch;
  margin-top:12px; flex:0 0 258px; min-height:0;
}
.lower-main { flex:1; min-width:0; display:flex; flex-direction:column; gap:10px; min-height:0; }

/* ── 원문 발췌: 제목/본문 세로 배치, 4줄 말줄임 ── */
.quote {
  flex:1 1 auto; min-height:0; max-height:148px;
  display:flex; flex-direction:column; gap:6px;
  border-left:6px solid rgba(139,111,71,.55);
  background:rgba(139,111,71,.07); border-radius:0 8px 8px 0;
  padding:10px 16px 12px 16px; overflow:hidden;
}
.quote .qh {
  flex:0 0 auto; display:flex; align-items:center; gap:8px;
  font-size:15px; font-weight:700; color:$RULE; letter-spacing:.14em;
}
.quote .qt {
  margin:0; font-size:17px; line-height:1.5; color:$INK;
  overflow:hidden; overflow-wrap:anywhere; word-break:break-word;
  display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:4;
}

/* ── 진행 순서도 ── */
.flow { display:flex; align-items:stretch; margin:0; flex:0 0 auto; }
.step {
  flex:1; min-width:0; background:$PANEL; border:1px solid rgba(139,111,71,.55);
  border-radius:8px; padding:10px 12px; display:flex; gap:10px; align-items:center;
}
.step svg.ic { font-size:22px; color:$RULE; flex:0 0 auto; }
.step .t { font-size:18px; font-weight:700; line-height:1.2; }
.step .d { font-size:15px; color:$MUTED; margin-top:4px; }
.step .d.date { display:flex; align-items:center; gap:8px; margin-top:5px; }
.step .d.date span { font-size:14px; color:$MUTED; }
.step.done { opacity:.62; }
.step.done svg.ic { color:$GREEN; }
.step.now { background:rgba(176,57,46,.10); border-color:$SEAL; border-width:2px; }
.step.now svg.ic { color:$SEAL; }
.step.now .t { color:$SEAL; }
.arrow { flex:0 0 36px; display:flex; align-items:center; justify-content:center;
         font-size:22px; color:$RULE; opacity:.75; }
.seal {
  flex:0 0 88px; width:88px; height:88px; margin-left:12px; border-radius:50%;
  border:3px solid $SEAL; color:$SEAL; display:flex; align-items:center;
  justify-content:center; font-size:30px; font-weight:700; transform:rotate(-8deg); opacity:.9;
  align-self:center;
}
.qrbox {
  flex:0 0 196px; width:196px; align-self:stretch; background:#fff;
  border:1px solid rgba(139,111,71,.55); border-radius:8px;
  padding:10px 10px 8px; display:flex; flex-direction:column;
  align-items:center; justify-content:center;
}
.qrbox img { width:176px; height:176px; display:block; image-rendering:pixelated; }
.qrbox .ql {
  margin-top:6px; font-size:15px; font-weight:700; color:$RULE; letter-spacing:.06em;
}
.foot { display:flex; justify-content:space-between; font-size:16px; color:$MUTED; padding-top:8px; }
''')

PAGE = Template('''<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><style>$css</style></head>
<body class="$bodycls">
$icons
  <div class="head-bar"></div>
  <div class="head">
    <div class="issuer-block">
      <div class="issuer">$issuer</div>
      $client_line
      <div class="label">발주공고 보고</div>
    </div>
    <div class="tags">$tags</div>
  </div>
  <div class="rule"></div>

  <div class="body">
    <div class="left">
      <h1>$title</h1>
      $subtitle
      $callouts
    </div>
    <div class="right">
      $dday
      <div class="cards">$cards</div>
      $urlbox
    </div>
  </div>

  <div class="lower">
    <div class="lower-main">
      $quote
      <div class="flow">$flow</div>
    </div>
    $qrbox
  </div>

  <div class="rule thin" style="margin-top:10px"></div>
  <div class="foot"><span>한국농어촌공사 · 글로벌사업</span><span>$footer</span></div>
</body></html>
''')


# ── 데이터 정규화 ────────────────────────────────────────────────────────────
def _text(value, fallback: str = '—') -> str:
    out = ' '.join(str(value or '').split())
    return out or fallback


def _parse_ymd(value: str | None) -> tuple[int, int, int] | None:
    match = re.search(r'(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})', value or '')
    if not match:
        return None
    try:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    except ValueError:
        return None


def _days_left(deadline: str) -> int | None:
    """마감일까지 남은 일수. 파싱 불가하면 None."""
    parts = _parse_ymd(deadline)
    if not parts:
        return None
    try:
        target = date(*parts)
    except ValueError:
        return None
    return (target - date.today()).days


def _format_date_ko(value: str | None) -> str:
    parts = _parse_ymd(value)
    if not parts:
        return ''
    year, month, day = parts
    return f'{year}년 {month}월 {day}일'


def _short_date_ko(value: str | None) -> str:
    parts = _parse_ymd(value)
    if not parts:
        return ''
    _, month, day = parts
    return f'{month}월 {day}일'


def _calendar_html(value: str | None, *, size: str = 'md') -> str:
    """월/일/년이 보이는 달력 카드. 파싱 실패 시 빈 문자열."""
    parts = _parse_ymd(value)
    if not parts:
        return ''
    year, month, day = parts
    cls = 'cal cal-sm' if size == 'sm' else 'cal'
    return (
        f'<div class="{cls}" aria-hidden="true">'
        f'<div class="rings"><span></span><span></span></div>'
        f'<div class="cm">{month}월</div>'
        f'<div class="cd">{day}</div>'
        f'<div class="cy">{year}</div></div>'
    )


def _summary_lines(notice: dict) -> list[str]:
    raw = (
        notice.get('summaryKo') or notice.get('summary_ko')
        or notice.get('textExcerptKo') or notice.get('text_excerpt_ko') or ''
    )
    out = []
    for line in str(raw).splitlines():
        line = ' '.join(line.split())
        # ①② / 1. 같은 머리 번호는 콜아웃 불릿으로 대체하므로 떼어낸다.
        line = re.sub(r'^[①-⑳\d]+[.)]?\s*', '', line)
        if line:
            out.append(line)
    return out


def _fallback_summary_lines(data: dict) -> list[str]:
    """번역 워커가 summary_ko 를 넣기 전에도 카드가 비지 않게 기본 요약을 만든다."""
    issuer = data.get('issuer') or data.get('source') or '발주처'
    country = data.get('country') or ''
    if country in ('—',):
        country = ''
    kind = data.get('kind_label') or '발주공고'
    sector = data.get('sector') or ''
    client = data.get('client_line') or ''
    deadline = data.get('deadline') or '—'
    value = data.get('value') or '공고 미표기'
    where = f'{country} ' if country else ''
    lines = [
        f'{issuer}가 {where}{kind}를 공고했습니다.',
    ]
    if client:
        lines.append(f'현지 발주기관은 {client}입니다.')
    facts = []
    if sector and sector != '—':
        facts.append(f'분야 {sector}')
    if value and value not in ('—', '공고 미표기'):
        facts.append(f'계약규모 {value}')
    if facts:
        lines.append(' · '.join(facts) + '입니다.')
    if deadline != '—':
        lines.append(f'마감일은 {deadline}입니다. 원문은 우측 하단 QR로 확인합니다.')
    else:
        lines.append('마감일이 공고에 없습니다. 원문은 우측 하단 QR로 확인합니다.')
    lines.append('KRC 농업·관개·수자원 적합 여부는 제목과 원문으로 검토하세요.')
    return lines


def _details(notice: dict) -> dict:
    details = notice.get('details') or {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            return {}
    return details if isinstance(details, dict) else {}


def _plain_text(raw) -> str:
    """HTML/엔티티/개행이 섞인 원문을 한 줄 평문으로 만든다."""
    text = unescape(str(raw or ''))
    text = re.sub(r'(?is)<script[^>]*>.*?</script>', ' ', text)
    text = re.sub(r'(?is)<style[^>]*>.*?</style>', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = text.replace('\xa0', ' ').replace('\u200b', '')
    return re.sub(r'\s+', ' ', text).strip()


def _clip_excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ('다. ', '요. ', '. ', '。', '! ', '? '):
        idx = cut.rfind(sep)
        if idx >= int(limit * 0.45):
            return cut[: idx + len(sep)].rstrip() + '…'
    idx = max(cut.rfind(' '), cut.rfind('·'))
    if idx >= int(limit * 0.55):
        return cut[:idx].rstrip() + '…'
    return cut.rstrip() + '…'


def _excerpt(notice: dict, limit: int = 260) -> str:
    """공고 원문 발췌. 한국어가 있으면 우선하고, HTML 찌꺼기는 제거한다."""
    details = _details(notice)
    korean = (
        notice.get('textExcerptKo'), notice.get('text_excerpt_ko'),
        details.get('text_excerpt_ko'), details.get('textExcerptKo'),
    )
    english = (
        details.get('text_excerpt'), details.get('textExcerpt'),
        notice.get('textExcerpt'), notice.get('text_excerpt'),
    )
    for raw in korean:
        text = _plain_text(raw)
        if text:
            return _clip_excerpt(text, limit)
    for raw in english:
        text = _plain_text(raw)
        if text:
            return _clip_excerpt(text, limit)
    return ''


def _notice_no(notice: dict) -> str:
    """공고 원문에서 발주번호를 최선 노력으로 뽑고, 없으면 내부 ID 로 대체."""
    details = _details(notice)
    text = unescape(str(details.get('text_excerpt') or details.get('textExcerpt') or ''))
    match = NOTICE_NO_RE.search(text)
    if match:
        return match.group(1).strip(' /-')
    return f'#{notice.get("id")}' if notice.get('id') else '—'


def _notice_kind(notice: dict) -> tuple[str, str]:
    """제목에서 공고 유형을 판별해 (kind, 라벨) 을 돌려준다."""
    title_en = str(notice.get('title') or '')
    title_ko = str(notice.get('titleKo') or notice.get('title_ko') or '')
    for kind, label, pat_en, pat_ko in NOTICE_KINDS:
        if re.search(pat_en, title_en, re.I) or re.search(pat_ko, title_ko):
            return kind, label
    return 'generic', '발주공고'


def _client_line_text(issuer: str, client: str) -> str:
    """상단에 이미 큰 글씨로 쓴 발주처명과 겹치면 생략한다."""
    client = (client or '').strip()
    issuer = (issuer or '').strip()
    if not client or client in ('—',):
        return ''
    if issuer and (client.lower() == issuer.lower() or issuer.lower() in client.lower()
                   or client.lower() in issuer.lower()):
        return ''
    return client


def normalize_notice(notice: dict) -> dict:
    kind, kind_label = _notice_kind(notice)
    source = (notice.get('source') or '').strip().lower()
    sector = (notice.get('sector') or '').strip().lower()
    deadline = _text(notice.get('deadline'), '')
    issuer = SOURCE_LABELS.get(source, source.upper() or 'NOTICE')
    theme = _source_theme(source)
    client = _text(notice.get('client'))
    data = {
        'kind': kind,
        'kind_label': kind_label,
        'source_key': source,
        'source': issuer,
        'issuer': issuer,
        'accent': theme['ACCENT'],
        'accent_soft': theme['ACCENT_SOFT'],
        'title': _text(notice.get('titleKo') or notice.get('title_ko') or notice.get('title')),
        'title_en': _text(notice.get('title'), ''),
        'country': _text(notice.get('country')),
        'client': client,
        'client_line': _client_line_text(issuer, client),
        'sector': SECTOR_LABELS.get(sector, sector or '—'),
        'deadline': deadline or '—',
        'deadline_ko': _format_date_ko(deadline),
        'deadline_short': _short_date_ko(deadline),
        'created_ko': _format_date_ko(
            _text(notice.get('createdAt') or notice.get('created_at'), '')[:10]
        ),
        'created_short': _short_date_ko(
            _text(notice.get('createdAt') or notice.get('created_at'), '')[:10]
        ),
        'days_left': _days_left(deadline),
        'value': _text(notice.get('contractValue') or notice.get('contract_value'), '공고 미표기'),
        'url': _text(notice.get('sourceUrl') or notice.get('source_url'), ''),
        'created': _text(notice.get('createdAt') or notice.get('created_at'), '')[:10],
        'notice_no': _notice_no(notice),
        'summary': _summary_lines(notice),
        'excerpt': _excerpt(notice),
    }
    if not data['summary']:
        data['summary'] = _fallback_summary_lines(data)
    return data


# ── HTML 조각 ────────────────────────────────────────────────────────────────
def _icon(name: str) -> str:
    return f'<svg class="ic"><use href="#i-{name}"/></svg>'


def _tags(data: dict) -> str:
    # 'Micronesia, Federated States of' 같은 긴 정식 국명은 태그에서 앞부분만 쓴다.
    country = data['country'].split(',')[0].split('(')[0].strip()
    raw = [data['kind_label'], country, data['sector']]
    if data['days_left'] is not None and data['days_left'] >= 0:
        raw.append('마감임박' if data['days_left'] <= 14 else '진행중')
    seen, out = set(), []
    for tag in raw:
        tag = tag.replace(' ', '_')
        if tag in ('—', '') or tag in seen:
            continue
        seen.add(tag)
        out.append(f'<span class="tag">#{escape(tag)}</span>')
    return ''.join(out)


def _callouts(data: dict) -> str:
    """요약 문장을 개요 / 확인 필요 / KRC 검토 세 콜아웃으로 재배치."""
    groups = _callout_groups(data)
    out = []
    for kind, icon, title, body in groups:
        paras = ''.join(f'<p>{escape(line)}</p>' for line in body)
        out.append(
            f'<div class="callout c-{kind}">'
            f'<div class="ct">{_icon(icon)}{escape(title)}</div>'
            f'{paras}</div>'
        )
    return ''.join(out)


def _callout_groups(data: dict) -> list[tuple[str, str, str, list[str]]]:
    """HTML/Pillow 렌더러가 함께 쓰는 콜아웃 데이터."""
    lines = data['summary']
    if not lines:
        groups = [('info', 'info', '개요', ['요약이 아직 생성되지 않았습니다.'])]
    else:
        groups = [
            ('info', 'info', '개요', lines[0:2]),
            ('warn', 'alert', '확인 필요', lines[2:4]),
            ('tip', 'bulb', 'KRC 검토', lines[4:]),
        ]
    return [group for group in groups if group[3]]


def _dday(data: dict) -> str:
    left = data['days_left']
    cal = _calendar_html(data.get('deadline') or '')
    mark = cal or _icon('calendar')
    if left is None:
        big, sub = '마감 미상', '공고에 마감일이 없습니다'
    elif left > 0:
        big, sub = f'D-{left}', '제출 마감까지'
    elif left == 0:
        big, sub = 'D-DAY', '오늘 마감'
    else:
        big, sub = '마감', '접수 종료'
    return (
        f'<div class="dday">{mark}'
        f'<div><div class="n">{escape(big)}</div>'
        f'<div class="s">{escape(sub)}</div></div></div>'
    )


def _cards(data: dict) -> str:
    collected = data.get('created_short') or data.get('created_ko') or data.get('created') or '—'
    collected_cal = _calendar_html(data.get('created') or '')
    items = (
        ('globe', '국가', data['country'], '', ''),
        ('bank', '발주처', data['client'], '', ''),
        ('sprout', '분야', data['sector'], '', ''),
        ('coin', '계약규모', data['value'], ' sm', ''),
        ('hash', '공고번호', data['notice_no'], ' sm', ''),
        ('calendar', '수집일', collected, ' nowrap', collected_cal),
    )
    out = []
    for icon, label, value, extra, widget in items:
        mark = widget or _icon(icon)
        cls = 'card has-cal' if widget else 'card'
        out.append(
            f'<div class="{cls}">{mark}<div>'
            f'<div class="k">{escape(label)}</div>'
            f'<div class="v{extra}">{escape(value)}</div>'
            f'</div></div>'
        )
    return ''.join(out)


def _urlbox(data: dict) -> str:
    if not data['url']:
        return ''
    return (
        f'<div class="urlbox">{_icon("link")}'
        f'<span class="u">우측 하단 QR을 스캔하면 원문 공고가 열립니다</span></div>'
    )


def _qr_target_url(value: str | None) -> str:
    """QR에 넣을 http(s) 원문 URL. 스킴이 없거나 javascript 등은 거부한다."""
    url = (value or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return ''
    return url


def _qr_png_bytes(url: str, pixel_size: int = 176) -> bytes | None:
    """원문 URL을 담은 PNG QR. 외부 API 없이 segno로 직접 생성한다."""
    target = _qr_target_url(url)
    if not target:
        return None
    try:
        import segno
    except ImportError as exc:
        raise RuntimeError('segno 가 없어 공고 QR을 생성할 수 없습니다.') from exc
    qr = segno.make(target, error='m')
    modules = qr.symbol_size(scale=1, border=1)[0]
    scale = max(2, int(pixel_size / max(modules, 1)))
    buf = io.BytesIO()
    qr.save(buf, kind='png', scale=scale, border=1, dark='#1A1A1A', light='#FFFFFF')
    return buf.getvalue()


def _qrbox(data: dict) -> str:
    png = _qr_png_bytes(data.get('url') or '')
    if not png:
        return '<div class="seal">공고</div>'
    b64 = base64.b64encode(png).decode('ascii')
    return (
        '<div class="qrbox">'
        f'<img src="data:image/png;base64,{b64}" width="176" height="176" alt="발주공고 QR">'
        '<div class="ql">발주공고보기</div></div>'
    )


def _quote(data: dict) -> str:
    if not data['excerpt']:
        return ''
    return (
        f'<div class="quote">'
        f'<div class="qh">{_icon("info")}원문 발췌</div>'
        f'<p class="qt">{escape(data["excerpt"])}</p></div>'
    )


def _flow_detail(template: str, data: dict) -> str:
    """순서도 날짜는 달력 카드로, 그 외 설명은 짧은 캡션으로 둔다."""
    if '{posted}' in template:
        cal = _calendar_html(data.get('created') or '', size='sm')
        caption = '게시' if cal else (data.get('created_short') or data.get('created') or '—')
        if cal:
            return (
                f'<div class="d date">{cal}<span>{escape(caption)}</span></div>'
            )
        return f'<div class="d">{escape(caption)}</div>'
    if '{due}' in template:
        if data.get('deadline') in ('', '—', None):
            return '<div class="d">시기 미정</div>'
        cal = _calendar_html(data.get('deadline') or '', size='sm')
        caption = '마감' if cal else (data.get('deadline_short') or data['deadline'])
        if cal:
            return (
                f'<div class="d date">{cal}<span>{escape(caption)}</span></div>'
            )
        return f'<div class="d">{escape(caption)}</div>'
    return f'<div class="d">{escape(template)}</div>'


def _flow(data: dict) -> str:
    left = data['days_left']
    open_now = left is None or left >= 0
    icons, titles, subs = zip(*FLOWS[data['kind']])
    # 마감 전이면 제출 단계가 현재, 마감 후면 심사 단계가 현재.
    states = ['done', 'now' if open_now else 'done', '' if open_now else 'now', '']

    out = []
    for i, (icon, title, sub, state) in enumerate(zip(icons, titles, subs, states)):
        if i:
            out.append('<div class="arrow">&rarr;</div>')
        out.append(
            f'<div class="step {state}">{_icon(icon)}<div>'
            f'<div class="t">{escape(title)}</div>'
            f'{_flow_detail(sub, data)}</div></div>'
        )
    return ''.join(out)


def build_slide_html(notice: dict) -> str:
    data = normalize_notice(notice)
    subtitle = f'<p class="subtitle">{escape(data["title_en"])}</p>' if data['title_en'] else ''
    footer = f'출처 · {data["source"]}'
    if data.get('created_short') or data['created']:
        footer += f'   |   수집일 {data.get("created_short") or data["created"]}'
    client_line = ''
    if data['client_line']:
        client_line = f'<div class="client">발주처  {escape(data["client_line"])}</div>'
    return PAGE.substitute(
        bodycls='' if data['excerpt'] else 'noquote',
        css=CSS.substitute({**PALETTE, **_source_theme(data['source_key'])}),
        icons=ICONS,
        issuer=escape(data['issuer']),
        client_line=client_line,
        tags=_tags(data),
        title=escape(data['title']),
        subtitle=subtitle,
        callouts=_callouts(data),
        dday=_dday(data),
        cards=_cards(data),
        urlbox=_urlbox(data),
        quote=_quote(data),
        flow=_flow(data),
        qrbox=_qrbox(data),
        footer=escape(footer),
    )


# ── 렌더 ─────────────────────────────────────────────────────────────────────
def _chrome_bin() -> str:
    env_bin = os.environ.get('CHROME_BIN', '').strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin
    if Path(CHROME_BIN).is_file():
        return CHROME_BIN
    found = shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chrome')
    if not found:
        raise RuntimeError('Chrome/Chromium 이 없어 인포그래픽을 렌더할 수 없습니다.')
    return found


def _render_slide_png_chrome(notice: dict, out_path: Path) -> Path:
    """Chrome 헤드리스로 16:9 슬라이드를 찍는다."""
    if not FONT_DIR.is_dir():
        raise RuntimeError(f'폰트 폴더가 없습니다: {FONT_DIR}')
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='krc-notice-slide-') as tmp:
        work = Path(tmp)
        for name in FONT_FILES:
            src = FONT_DIR / name
            if not src.is_file():
                raise RuntimeError(f'필수 폰트 없음: {src}')
            shutil.copy2(src, work / name)

        html_path = work / 'slide.html'
        html_path.write_text(build_slide_html(notice), encoding='utf-8')
        screenshot = work / 'slide.png'
        result = subprocess.run(
            [
                _chrome_bin(),
                '--headless=new',
                '--disable-gpu',
                '--hide-scrollbars',
                '--allow-file-access-from-files',
                '--force-device-scale-factor=1',
                f'--window-size={SLIDE_W},{SLIDE_H}',
                f'--screenshot={screenshot}',
                html_path.as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if not screenshot.is_file():
            err = (result.stderr or result.stdout or '').strip()[:500]
            raise RuntimeError(f'Chrome 스크린샷 실패: {err or result.returncode}')
        shutil.copy2(screenshot, out_path)
    return out_path


def _pil_font(size: int, *, bold: bool = False):
    try:
        from PIL import ImageFont
    except ImportError as exc:  # pragma: no cover - 배포 의존성 누락 안내
        raise RuntimeError('Pillow 가 없어 휴대형 슬라이드 렌더를 할 수 없습니다.') from exc
    name = 'Pretendard-Bold.ttf' if bold else 'Pretendard-Regular.ttf'
    path = FONT_DIR / name
    if not path.is_file():
        raise RuntimeError(f'필수 폰트 없음: {path}')
    return ImageFont.truetype(str(path), size=size)


def _pil_text_width(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), str(text), font=font)
    return max(0, box[2] - box[0])


def _pil_ellipsize(draw, text: str, font, max_width: int) -> str:
    text = str(text)
    if _pil_text_width(draw, text, font) <= max_width:
        return text
    suffix = '…'
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _pil_text_width(draw, text[:mid].rstrip() + suffix, font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + suffix


def _pil_wrap(draw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    """공백 단위 우선으로 감싸고 긴 URL/국명은 글자 단위로도 나눈다."""
    words = str(text or '').split()
    if not words:
        return []
    lines: list[str] = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if _pil_text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
            if len(lines) >= max_lines:
                break
        while word and _pil_text_width(draw, word, font) > max_width:
            cut = 1
            while cut < len(word) and _pil_text_width(draw, word[:cut + 1], font) <= max_width:
                cut += 1
            lines.append(word[:cut])
            word = word[cut:]
            if len(lines) >= max_lines:
                break
        if len(lines) >= max_lines:
            break
        current = word
    if current and len(lines) < max_lines:
        lines.append(current)
    source = ' '.join(words)
    visible = ''.join(lines).replace(' ', '')
    if len(visible) < len(source.replace(' ', '')) and lines:
        lines[-1] = _pil_ellipsize(draw, lines[-1] + '…', font, max_width)
    return lines[:max_lines]


def _pil_draw_lines(draw, xy: tuple[int, int], lines: list[str], font, fill: str,
                    *, spacing: int) -> int:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += spacing
    return y


def _pil_icon(draw, name: str, box: tuple[int, int, int, int], color: str,
              *, width: int = 3) -> None:
    """Pillow 폴백용 단순 선 아이콘. 외부 아이콘/이모지 폰트가 필요 없다."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    w, h = x2 - x1, y2 - y1
    pad = max(2, min(w, h) // 8)
    if name in ('info', 'clock', 'coin', 'globe'):
        draw.ellipse((x1 + pad, y1 + pad, x2 - pad, y2 - pad), outline=color, width=width)
    if name == 'info':
        draw.line((cx, cy - 1, cx, y2 - pad * 2), fill=color, width=width)
        draw.ellipse((cx - 1, y1 + pad * 2, cx + 1, y1 + pad * 2 + 2), fill=color)
    elif name == 'clock':
        draw.line((cx, cy, cx, y1 + pad * 2), fill=color, width=width)
        draw.line((cx, cy, x2 - pad * 2, cy + pad), fill=color, width=width)
    elif name == 'coin':
        draw.text((cx - 6, cy - 13), '$', font=_pil_font(19, bold=True), fill=color)
    elif name == 'globe':
        draw.line((x1 + pad, cy, x2 - pad, cy), fill=color, width=max(1, width - 1))
        draw.arc((cx - w // 6, y1 + pad, cx + w // 6, y2 - pad), 90, 270, fill=color, width=width)
        draw.arc((cx - w // 6, y1 + pad, cx + w // 6, y2 - pad), 270, 90, fill=color, width=width)
    elif name == 'alert':
        draw.polygon(((cx, y1 + pad), (x2 - pad, y2 - pad), (x1 + pad, y2 - pad)),
                     outline=color)
        draw.line((cx, cy - 3, cx, cy + 5), fill=color, width=width)
    elif name == 'bulb':
        draw.ellipse((x1 + pad, y1 + pad, x2 - pad, y2 - pad * 2), outline=color, width=width)
        draw.line((cx - 5, y2 - pad, cx + 5, y2 - pad), fill=color, width=width)
    elif name == 'bank':
        draw.polygon(((cx, y1 + pad), (x2 - pad, cy - 2), (x1 + pad, cy - 2)), outline=color)
        for col in (x1 + pad * 2, cx, x2 - pad * 2):
            draw.line((col, cy, col, y2 - pad), fill=color, width=max(1, width - 1))
        draw.line((x1 + pad, y2 - pad, x2 - pad, y2 - pad), fill=color, width=width)
    elif name == 'sprout':
        draw.line((cx, y2 - pad, cx, cy), fill=color, width=width)
        draw.arc((x1 + pad, y1 + pad, cx + 1, cy + 5), 180, 360, fill=color, width=width)
        draw.arc((cx - 1, y1 + pad * 2, x2 - pad, cy + 7), 180, 360, fill=color, width=width)
    elif name == 'calendar':
        draw.rounded_rectangle((x1 + pad, y1 + pad * 2, x2 - pad, y2 - pad), radius=3,
                               outline=color, width=width)
        draw.line((x1 + pad, cy - 3, x2 - pad, cy - 3), fill=color, width=width)
    elif name == 'hash':
        draw.text((x1 + 3, y1 - 3), '#', font=_pil_font(max(18, h - 4), bold=True), fill=color)
    elif name == 'link':
        draw.arc((x1 + pad, cy - 5, cx + 6, y2 - pad), 40, 300, fill=color, width=width)
        draw.arc((cx - 6, y1 + pad, x2 - pad, cy + 5), 220, 120, fill=color, width=width)
    elif name == 'send':
        draw.polygon(((x1 + pad, cy), (x2 - pad, y1 + pad), (cx + 3, y2 - pad)), outline=color)
        draw.line((x1 + pad, cy, cx + 2, cy + 2), fill=color, width=width)
    elif name == 'search':
        draw.ellipse((x1 + pad, y1 + pad, cx + 6, cy + 6), outline=color, width=width)
        draw.line((cx + 4, cy + 4, x2 - pad, y2 - pad), fill=color, width=width)
    elif name == 'sign':
        draw.line((x1 + pad, y2 - pad, x2 - pad, y1 + pad), fill=color, width=width + 1)
        draw.line((x1 + pad, y2 - pad, cx - 2, y2 - pad - 2), fill=color, width=width)


def _pil_dday(data: dict) -> tuple[str, str]:
    left = data['days_left']
    if left is None:
        return '마감 미상', '공고에 마감일이 없습니다'
    if left > 0:
        return f'D-{left}', '제출 마감까지'
    if left == 0:
        return 'D-DAY', '오늘 마감'
    return '마감', '접수 종료'


def _pil_calendar(draw, xy: tuple[int, int], parts: tuple[int, int, int],
                  *, size: str = 'md', color: str | None = None) -> tuple[int, int]:
    """스프링 바인딩이 있는 달력 카드. (width, height) 를 반환한다."""
    x, y = xy
    color = color or PALETTE['SEAL']
    if size == 'sm':
        w, h, header, day_size, month_size, year_size = 42, 54, 20, 18, 10, 9
    else:
        w, h, header, day_size, month_size, year_size = 54, 66, 24, 24, 12, 11
    year, month, day = parts
    draw.rounded_rectangle((x, y, x + w, y + h), radius=7, fill='#FFFFFF',
                           outline=color, width=2)
    draw.rectangle((x + 2, y + 2, x + w - 2, y + header), fill=color)
    ring_y = y + 2
    for rx in (x + int(w * 0.30), x + int(w * 0.70)):
        draw.ellipse((rx - 4, ring_y, rx + 4, ring_y + 8), fill=PALETTE['PAPER'],
                     outline=color, width=2)
    month_font = _pil_font(month_size, bold=True)
    month_s = f'{month}월'
    mw = _pil_text_width(draw, month_s, month_font)
    draw.text((x + (w - mw) // 2, y + (6 if size == 'md' else 4)), month_s,
              font=month_font, fill='#FFFFFF')
    day_font = _pil_font(day_size, bold=True)
    day_s = str(day)
    dw = _pil_text_width(draw, day_s, day_font)
    draw.text((x + (w - dw) // 2, y + header + (2 if size == 'sm' else 4)),
              day_s, font=day_font, fill=PALETTE['INK'])
    year_font = _pil_font(year_size)
    year_s = str(year)
    yw = _pil_text_width(draw, year_s, year_font)
    draw.text((x + (w - yw) // 2, y + h - (16 if size == 'md' else 13)),
              year_s, font=year_font, fill=PALETTE['MUTED'])
    return w, h


def _render_slide_png_pillow(notice: dict, out_path: Path) -> Path:
    """Chrome 이 없는 서버리스 환경에서 동작하는 결정론적 PNG 렌더러."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - 배포 의존성 누락 안내
        raise RuntimeError('Pillow 가 없어 휴대형 슬라이드 렌더를 할 수 없습니다.') from exc
    if not FONT_DIR.is_dir():
        raise RuntimeError(f'폰트 폴더가 없습니다: {FONT_DIR}')

    data = normalize_notice(notice)
    image = Image.new('RGB', (SLIDE_W, SLIDE_H), PALETTE['PAPER'])
    draw = ImageDraw.Draw(image)
    # 미세한 워크북 종이 결. PNG 압축 시에도 단색보다 밋밋하지 않게 보인다.
    for y in range(0, SLIDE_H, 5):
        draw.line((0, y, SLIDE_W, y), fill='#F1EBDD', width=1)
    for x in range(2, SLIDE_W, 13):
        draw.point((x, (x * 47) % SLIDE_H), fill='#E8DFCF')

    regular16 = _pil_font(16)
    regular17 = _pil_font(17)
    regular18 = _pil_font(18)
    regular19 = _pil_font(19)
    bold16 = _pil_font(16, bold=True)
    bold17 = _pil_font(17, bold=True)
    bold19 = _pil_font(19, bold=True)
    bold20 = _pil_font(20, bold=True)
    bold22 = _pil_font(22, bold=True)
    bold24 = _pil_font(24, bold=True)
    bold38 = _pil_font(38, bold=True)

    margin = 64
    accent = data.get('accent') or PALETTE['RULE']
    accent_soft = data.get('accent_soft') or '#E9DFCD'
    draw.rectangle((0, 0, SLIDE_W, 14), fill=accent)
    draw.text((margin, 28), data['issuer'], font=bold38, fill=accent)
    header_bottom = 70
    if data.get('client_line'):
        draw.text((margin, 70), f'발주처  {data["client_line"]}', font=regular18, fill=PALETTE['MUTED'])
        header_bottom = 96
    draw.text((margin, header_bottom), '발 주 공 고  보 고', font=bold16, fill=PALETTE['MUTED'])
    country = data['country'].split(',')[0].split('(')[0].strip()
    tags = [data['kind_label'], country, data['sector']]
    if data['days_left'] is not None and data['days_left'] >= 0:
        tags.append('마감임박' if data['days_left'] <= 14 else '진행중')
    tag_x = SLIDE_W - margin
    seen: set[str] = set()
    for raw in reversed(tags):
        tag = raw.replace(' ', '_')
        if not tag or tag == '—' or tag in seen:
            continue
        seen.add(tag)
        label = f'#{tag}'
        tag_w = _pil_text_width(draw, label, bold16) + 28
        tag_x -= tag_w
        if tag_x < 640:
            break
        draw.rounded_rectangle((tag_x, 30, tag_x + tag_w - 8, 63), radius=16,
                               fill=accent_soft, outline=accent, width=1)
        draw.text((tag_x + 12, 36), label, font=bold16, fill=accent)
        tag_x -= 7
    rule_y = header_bottom + 28
    draw.rectangle((margin, rule_y, SLIDE_W - margin, rule_y + 3), fill=accent)

    left_x, left_w = margin, 1210
    right_x, right_w = 1314, 542
    title_size = 46
    while title_size > 34:
        title_font = _pil_font(title_size, bold=True)
        title_lines = _pil_wrap(draw, data['title'], title_font, left_w, 2)
        if len(title_lines) <= 2 and all(_pil_text_width(draw, line, title_font) <= left_w for line in title_lines):
            break
        title_size -= 2
    title_y = rule_y + 22
    title_lines = _pil_wrap(draw, data['title'], title_font, left_w, 2)
    title_end = _pil_draw_lines(draw, (left_x, title_y), title_lines, title_font,
                                PALETTE['INK'], spacing=title_size + 12)
    if data['title_en'] and data['title_en'] != data['title']:
        english = _pil_wrap(draw, data['title_en'], regular18, left_w, 2)
        title_end = _pil_draw_lines(draw, (left_x, title_end + 3), english, regular18,
                                    PALETTE['MUTED'], spacing=25)

    group_colors = {
        'info': (PALETTE['BLUE'], '#E7ECEE'),
        'warn': (PALETTE['AMBER'], '#EEE5D3'),
        'tip': (PALETTE['GREEN'], '#E4E9DF'),
    }
    groups = _callout_groups(data)
    has_qr = bool(_qr_target_url(data.get('url') or ''))
    qr_panel_w, qr_img, qr_gap = 196, 168, 16
    footer_rule_y = 1018
    lower_h = 252
    lower_top = footer_rule_y - 12 - lower_h
    callout_limit = lower_top - 10
    callout_y = max(250, title_end + 12)
    available = max(180, callout_limit - callout_y)
    gap = 10
    box_h = max(84, (available - gap * (len(groups) - 1)) // max(1, len(groups)))
    for kind, icon, label, body in groups:
        color, fill = group_colors[kind]
        bottom = min(callout_limit, callout_y + box_h)
        draw.rounded_rectangle((left_x, callout_y, left_x + left_w, bottom), radius=8,
                               fill=fill, outline='#CBBDA6', width=1)
        draw.rectangle((left_x, callout_y, left_x + 6, bottom), fill=color)
        _pil_icon(draw, icon, (left_x + 18, callout_y + 13, left_x + 42, callout_y + 37),
                  color, width=2)
        draw.text((left_x + 50, callout_y + 13), label, font=bold19, fill=color)
        text_y = callout_y + 45
        max_body_lines = max(1, (bottom - text_y - 8) // 27)
        body_lines: list[str] = []
        for line in body:
            wrapped = _pil_wrap(draw, f'• {line}', regular19, left_w - 44,
                                max_body_lines - len(body_lines))
            body_lines.extend(wrapped)
            if len(body_lines) >= max_body_lines:
                break
        _pil_draw_lines(draw, (left_x + 22, text_y), body_lines, regular19,
                        PALETTE['INK'], spacing=27)
        callout_y = bottom + gap

    # 오른쪽 D-day(달력)와 2x3 팩트 카드.
    dday_y, dday_h = 118, 90
    draw.rounded_rectangle((right_x, dday_y, right_x + right_w, dday_y + dday_h), radius=8,
                           fill=PALETTE['PANEL'], outline=PALETTE['RULE'], width=1)
    draw.rectangle((right_x, dday_y, right_x + 6, dday_y + dday_h), fill=PALETTE['SEAL'])
    deadline_parts = _parse_ymd(data.get('deadline') or '')
    if deadline_parts:
        cal_w, _ = _pil_calendar(draw, (right_x + 18, dday_y + 12), deadline_parts)
        text_x = right_x + 18 + cal_w + 14
    else:
        _pil_icon(draw, 'calendar', (right_x + 22, dday_y + 24, right_x + 62, dday_y + 64),
                  PALETTE['SEAL'], width=3)
        text_x = right_x + 78
    big, sub = _pil_dday(data)
    draw.text((text_x, dday_y + 14), big, font=bold38, fill=PALETTE['SEAL'])
    draw.text((text_x, dday_y + 56), sub, font=regular17, fill=PALETTE['MUTED'])

    collected_parts = _parse_ymd(data.get('created') or '')
    collected_value = data.get('created_short') or data.get('created') or '—'
    facts = (
        ('globe', '국가', data['country'], None),
        ('bank', '발주처', data['client'], None),
        ('sprout', '분야', data['sector'], None),
        ('coin', '계약규모', data['value'], None),
        ('hash', '공고번호', data['notice_no'], None),
        ('calendar', '수집일', collected_value, collected_parts),
    )
    card_gap = 10
    card_w = (right_w - card_gap) // 2
    card_h = 96
    card_start = dday_y + dday_h + 12
    for index, (icon, label, value, date_parts) in enumerate(facts):
        col, row = index % 2, index // 2
        x = right_x + col * (card_w + card_gap)
        y = card_start + row * (card_h + card_gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=8,
                               fill=PALETTE['PANEL'], outline='#B8A17E', width=1)
        if date_parts:
            cal_w, _ = _pil_calendar(draw, (x + 10, y + 14), date_parts)
            text_x = x + 10 + cal_w + 10
        else:
            _pil_icon(draw, icon, (x + 14, y + 16, x + 42, y + 44), PALETTE['RULE'], width=2)
            text_x = x + 52
        draw.text((text_x, y + 14), label, font=bold16, fill=PALETTE['RULE'])
        value_width = x + card_w - text_x - 10
        if label == '공고번호':
            value_font = bold16
            draw.text((text_x, y + 44),
                      _pil_ellipsize(draw, str(value), value_font, value_width),
                      font=value_font, fill=PALETTE['INK'])
        else:
            value_font = bold22 if len(str(value)) <= 16 else bold17
            value_lines = _pil_wrap(draw, value, value_font, value_width, 2)
            _pil_draw_lines(draw, (text_x, y + 42), value_lines, value_font,
                            PALETTE['INK'], spacing=24)

    if data['url']:
        url_y = card_start + 3 * (card_h + card_gap)
        draw.rounded_rectangle((right_x, url_y, right_x + right_w, url_y + 64), radius=8,
                               fill=PALETTE['PANEL'], outline='#B8A17E', width=1)
        _pil_icon(draw, 'link', (right_x + 16, url_y + 18, right_x + 42, url_y + 44),
                  PALETTE['RULE'], width=2)
        url_lines = _pil_wrap(draw, '우측 하단 QR을 스캔하면 원문 공고가 열립니다',
                              regular16, right_w - 68, 2)
        _pil_draw_lines(draw, (right_x + 52, url_y + 14), url_lines, regular16,
                        PALETTE['MUTED'], spacing=22)

    quote_h = 138 if data['excerpt'] else 0
    flow_h = 104
    quote_y = lower_top
    flow_y = lower_top + quote_h + (10 if data['excerpt'] else 0)
    arrow_w, seal_w, seal_gap = 36, 88, 12
    reserved = (qr_panel_w + qr_gap) if has_qr else (seal_w + seal_gap)
    quote_right = SLIDE_W - margin - reserved
    if data['excerpt']:
        draw.rounded_rectangle((margin, quote_y, quote_right, quote_y + quote_h), radius=8,
                               fill='#F0EADD')
        draw.rectangle((margin, quote_y, margin + 6, quote_y + quote_h), fill='#B8A17E')
        _pil_icon(draw, 'info', (margin + 16, quote_y + 12, margin + 38, quote_y + 34),
                  PALETTE['RULE'], width=2)
        draw.text((margin + 44, quote_y + 12), '원문 발췌', font=bold16, fill=PALETTE['RULE'])
        quote_lines = _pil_wrap(draw, data['excerpt'], regular17, quote_right - margin - 36, 4)
        _pil_draw_lines(draw, (margin + 18, quote_y + 40), quote_lines, regular17,
                        PALETTE['INK'], spacing=24)

    flow_total = SLIDE_W - margin * 2 - reserved
    step_w = (flow_total - arrow_w * 3) // 4
    left = data['days_left']
    open_now = left is None or left >= 0
    states = ['done', 'now' if open_now else 'done', '' if open_now else 'now', '']
    posted_parts = _parse_ymd(data.get('created') or '')
    due_parts = _parse_ymd(data.get('deadline') or '')
    flow_x = margin
    for index, ((icon, title, sub_text), state) in enumerate(zip(FLOWS[data['kind']], states)):
        border = PALETTE['SEAL'] if state == 'now' else '#B8A17E'
        fill = '#EEDDD7' if state == 'now' else PALETTE['PANEL']
        draw.rounded_rectangle((flow_x, flow_y, flow_x + step_w, flow_y + flow_h), radius=8,
                               fill=fill, outline=border, width=2 if state == 'now' else 1)
        icon_color = PALETTE['SEAL'] if state == 'now' else (
            PALETTE['GREEN'] if state == 'done' else PALETTE['RULE'])
        _pil_icon(draw, icon, (flow_x + 12, flow_y + 36, flow_x + 38, flow_y + 62),
                  icon_color, width=2)
        title_color = PALETTE['SEAL'] if state == 'now' else PALETTE['INK']
        draw.text((flow_x + 46, flow_y + 12), title, font=bold17, fill=title_color)
        date_parts = posted_parts if '{posted}' in sub_text else (
            due_parts if '{due}' in sub_text else None)
        if '{posted}' in sub_text:
            caption = '게시' if posted_parts else (data.get('created_short') or data.get('created') or '—')
        elif '{due}' in sub_text:
            if data.get('deadline') in ('', '—', None):
                caption = '시기 미정'
                date_parts = None
            else:
                caption = '마감' if due_parts else (data.get('deadline_short') or data['deadline'])
        else:
            caption = sub_text
        if date_parts:
            cal_w, _ = _pil_calendar(
                draw, (flow_x + 46, flow_y + 42), date_parts, size='sm')
            draw.text((flow_x + 46 + cal_w + 8, flow_y + 58), caption,
                      font=regular16, fill=PALETTE['MUTED'])
        else:
            caption = _pil_ellipsize(draw, caption, regular16, step_w - 58)
            draw.text((flow_x + 46, flow_y + 58), caption, font=regular16, fill=PALETTE['MUTED'])
        flow_x += step_w
        if index < 3:
            draw.text((flow_x + 6, flow_y + 32), '→', font=bold24, fill=PALETTE['RULE'])
            flow_x += arrow_w
    qr_png = _qr_png_bytes(data.get('url') or '', pixel_size=qr_img) if has_qr else None
    if qr_png:
        from PIL import Image as PilImage
        qr_x = SLIDE_W - margin - qr_panel_w
        qr_h = 214
        qr_y = lower_top + lower_h - qr_h
        draw.rounded_rectangle((qr_x, qr_y, qr_x + qr_panel_w, qr_y + qr_h), radius=8,
                               fill='#FFFFFF', outline='#B8A17E', width=1)
        qr_image = PilImage.open(io.BytesIO(qr_png)).convert('RGB')
        qr_image = qr_image.resize((qr_img, qr_img), PilImage.Resampling.NEAREST)
        image.paste(qr_image, (qr_x + 14, qr_y + 12))
        label = '발주공고보기'
        label_w = _pil_text_width(draw, label, bold16)
        draw.text((qr_x + (qr_panel_w - label_w) // 2, qr_y + 184), label,
                  font=bold16, fill=PALETTE['RULE'])
    else:
        seal_x = SLIDE_W - margin - seal_w
        draw.ellipse((seal_x, flow_y + 8, seal_x + seal_w, flow_y + 96),
                     outline=PALETTE['SEAL'], width=3)
        draw.text((seal_x + 18, flow_y + 33), '공고', font=bold24, fill=PALETTE['SEAL'])

    rule_right = SLIDE_W - margin - (qr_panel_w + qr_gap if qr_png else 0)
    draw.line((margin, footer_rule_y, max(margin + 200, rule_right), footer_rule_y),
              fill='#B8A17E', width=1)
    draw.text((margin, 1030), '한국농어촌공사 · 글로벌사업', font=regular17, fill=PALETTE['MUTED'])
    footer = f'출처 · {data["source"]}'
    if data.get('created_short') or data['created']:
        footer += f'   |   수집일 {data.get("created_short") or data["created"]}'
    footer_w = _pil_text_width(draw, footer, regular17)
    footer_x = (SLIDE_W - margin - qr_panel_w - qr_gap - footer_w) if qr_png else (
        SLIDE_W - margin - footer_w)
    if footer_x > margin + 280:
        draw.text((footer_x, 1030), footer, font=regular17, fill=PALETTE['MUTED'])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format='PNG', optimize=True)
    return out_path


def render_slide_png(notice: dict, out_path: Path) -> Path:
    """16:9 슬라이드 렌더.

    NOTICE_SLIDE_RENDERER=chrome|pillow 로 강제할 수 있다. 기본 auto 는 Chrome 을
    우선하고, 실행 파일이 없거나 캡처가 실패하면 Pillow 로 즉시 폴백한다.
    """
    renderer = os.environ.get('NOTICE_SLIDE_RENDERER', 'auto').strip().lower() or 'auto'
    if renderer not in ('auto', 'chrome', 'pillow'):
        raise ValueError(f'지원하지 않는 NOTICE_SLIDE_RENDERER: {renderer}')
    if renderer == 'pillow':
        return _render_slide_png_pillow(notice, out_path)
    if renderer == 'chrome':
        return _render_slide_png_chrome(notice, out_path)
    try:
        return _render_slide_png_chrome(notice, out_path)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return _render_slide_png_pillow(notice, out_path)


# ── Codex $imagegen 경로 (선택) ──────────────────────────────────────────────
def _codex_bin() -> str:
    env_bin = os.environ.get('CODEX_CLI', '').strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin
    found = shutil.which('codex') or os.path.expanduser('~/.npm-global/bin/codex')
    if found and Path(found).is_file():
        return found
    raise RuntimeError('codex CLI 를 찾을 수 없습니다.')


def build_imagegen_prompt(notice: dict) -> str:
    """`$imagegen` 으로 같은 구성의 16:9 보고 슬라이드를 그리게 하는 프롬프트."""
    data = normalize_notice(notice)
    lines = [
        '발주공고 보고',
        f'출처: {data["source"]}',
        data['title'],
    ]
    if data['title_en']:
        lines.append(data['title_en'])
    lines.append('요약')
    lines.extend(data['summary'][:5])
    for label, value in (
        ('국가', data['country']),
        ('발주처', data['client']),
        ('분야', data['sector']),
        ('마감', data['deadline']),
        ('계약규모', data['value']),
        ('공고번호', data['notice_no']),
    ):
        lines.extend([label, value])
    if data['url']:
        lines.extend(['원문', re.sub(r'^https?://(www\.)?', '', data['url'])])
    for _, title, sub in FLOWS[data['kind']]:
        lines.append(title)
    lines.append('한국농어촌공사 · 글로벌사업')

    quoted = '\n'.join(f'- "{line}"' for line in lines if line and line != '—')
    return f'''Use the $imagegen skill now. Call the built-in image_gen tool once.
Do not ask questions. Do not write Python, HTML, SVG, or screenshot a webpage.
Draw the entire slide as one finished raster image, including every Korean character.

Use case: productivity-visual
Asset type: complete full 16:9 landscape briefing slide image, {SLIDE_W}x{SLIDE_H}

This is an internal reporting slide, not an advertisement. It must read as a calm,
dense, well-organized one-page briefing document projected in a meeting.

Style: Danuri workbook look. Warm off-white paper {PALETTE['PAPER']} with faint fiber
texture, black ink {PALETTE['INK']} typography, muted brown {PALETTE['RULE']} rules,
beige {PALETTE['PANEL']} panels and table blocks, one small round red
{PALETTE['SEAL']} ink seal near the lower right. Adult professional tone: clear,
calm, practical, not promotional. No photographs, no gradients, no drop shadows.

Layout, 16:9 landscape, margins about 64 px:
- Top band: a small letterspaced label at far left, the source line and short tag
  pills at far right, then a muted brown rule across the full width.
- Left column (about 62%): a large bold Hangul headline over two lines, one small
  gray line of the English original title, then three stacked callout blocks in the
  Obsidian style - each with a colored left bar, a small icon, a bold title, and
  short bullet lines. Use a muted blue bar for the first, muted amber for the
  second, muted olive green for the third.
- Right column (about 38%): a bold red deadline badge with a clock icon at the top,
  then a two-by-three grid of small beige fact cards, each with a thin line icon, a
  small brown label and a bold black value, then a small box holding the source URL.
- Below both columns: a full-width quoted excerpt block with a brown left bar and
  small gray text.
- Bottom band: a four-step horizontal process flow of rounded beige boxes joined by
  right arrows. The second step is the current one and is outlined in red. The round
  red seal sits at the far right of this band.
- Footer: a thin brown rule then one small footer line at far left.

Typography: bold Korean gothic for the headline, regular Korean gothic elsewhere.
Body text must be readable when projected. At most three competing text sizes.

Color palette: warm off-white paper, beige panels, muted brown rules, black ink,
one red seal, and muted blue / amber / olive only for the three callout bars.

Text (verbatim), render each string exactly once with correct Hangul:
{quoted}

Constraints: correct Korean spelling; no missing, broken or extra jamo; no Latin
lookalike Hangul; do not translate the Hangul into English; no invented labels or
extra slogans; no watermark; no logos; no browser or UI chrome; no lorem text; no
unreadable type; no photorealistic imagery.
Avoid: bright white cards, glossy effects, marketing hero layout, large empty areas.
'''


def generate_full_poster(notice: dict, dest: Path, timeout: int = 480) -> Path:
    """Codex `$imagegen` 한 장으로 한글 포함 전체 슬라이드를 그린다."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='krc-imagegen-'))
    prompt = build_imagegen_prompt(notice) + f'''

After the image is generated, copy the file to exactly:
{dest}

Then print one line:
SAVED {dest}
'''
    result = subprocess.run(
        [
            _codex_bin(), 'exec',
            '--skip-git-repo-check',
            '--dangerously-bypass-approvals-and-sandbox',
            '-C', str(work),
            prompt,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or '').strip()[:800]
        raise RuntimeError(f'codex $imagegen 실패: {err or result.returncode}')
    if dest.is_file() and dest.stat().st_size >= 1000:
        return dest
    found = sorted(
        list(work.rglob('*.png')) + list(work.rglob('*.jpg')),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if found and found[0].stat().st_size >= 1000:
        shutil.copy2(found[0], dest)
        return dest
    raise RuntimeError(f'codex $imagegen 이 이미지를 저장하지 않았습니다: {dest}')


# ── 공개 엔트리 ──────────────────────────────────────────────────────────────
def generate_notice_infographic(
    notice: dict,
    out_path: Path,
    *,
    style: str = 'slide',
) -> dict:
    """발주공고 인포그래픽을 생성한다.

    style='slide'    HTML + Chrome 결정론적 렌더 (기본). 텍스트 정확도 보장.
    style='imagegen' Codex $imagegen 한 장. 손맛은 좋지만 작은 글자가 틀어질 수 있어
                     사람이 QA 하는 경우에만 쓴다.
    """
    if style not in ('slide', 'imagegen'):
        raise ValueError(f'지원하지 않는 style: {style}')

    out_path = Path(out_path)
    if style == 'imagegen':
        generate_full_poster(notice, out_path)
    else:
        render_slide_png(notice, out_path)
    return {
        'path': str(out_path),
        'width': SLIDE_W,
        'height': SLIDE_H,
        'style': style,
        'imagegen': style == 'imagegen',
        'kind': normalize_notice(notice)['kind'],
    }
