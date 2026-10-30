#!/usr/bin/env python3
"""AfDB 조달공고 목록 수집 워커 (사내 맥에서 실행).

afdb.org 는 Cloudflare 봇 차단 뒤에 있다. 2026-10 실측:
  - 조달 RSS 없음 (/en/rss-feeds 에 채용·뉴스·민간부문 피드만 있음)
  - 일반 HTTP 요청은 UA·Accept·Accept-Language 를 모두 갖춰도
    403 'Just a moment...' (JS 챌린지) — Vercel 에서는 물론 맥에서도 동일
  - 실제 브라우저(헤드리스 Chrome)로는 정상 열림

그래서 ADB 본문 보강(adb_enrich.py)과 같은 역할 분담을 쓴다:
  이 워커(맥)      Chrome 으로 목록 페이지를 읽어 '원본 행'을 서버로 올림
  서버(Vercel)     필터·적합도·카드 생성·카카오 큐

판정 규칙은 서버에만 둔다. 기준이 바뀔 때 맥을 다시 만지지 않아도 되도록
워커는 거른 결과가 아니라 목록 원본(title/url/posted)을 그대로 보낸다.
파서(_parse_afdb_listing)는 서버 코드에서 import 해 둘이 어긋나지 않게 한다.

사용:
  python3 scripts/afdb_scrape.py --env-file .env --once
  python3 scripts/afdb_scrape.py --env-file .env --once --pages 2
  python3 scripts/afdb_scrape.py --env-file .env            # 주기 실행
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 맥 기본 Chrome 경로. 다른 위치면 AFDB_CHROME_BIN 으로 지정한다.
CHROME_CANDIDATES = (
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
)

# Cloudflare 챌린지를 실제 브라우저로 통과시키려면 평범한 데스크톱 UA 가 필요하다.
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/131.0.0.0 Safari/537.36')


def load_env_file(path: str) -> None:
    """KEY=VALUE 형식의 env 파일을 os.environ 에 반영 (기존 값 우선)."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit(f'env 파일을 찾을 수 없습니다: {p}')
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def find_chrome() -> str:
    explicit = (os.environ.get('AFDB_CHROME_BIN') or '').strip()
    if explicit:
        if not Path(explicit).is_file():
            raise SystemExit(f'AFDB_CHROME_BIN 경로에 파일이 없습니다: {explicit}')
        return explicit
    for cand in CHROME_CANDIDATES:
        if Path(cand).is_file():
            return cand
    raise SystemExit(
        'Chrome 을 찾을 수 없습니다. afdb.org 는 Cloudflare JS 챌린지 때문에 '
        '실제 브라우저가 필요합니다. AFDB_CHROME_BIN 으로 경로를 지정하세요.'
    )


def fetch_dom(chrome: str, url: str, timeout: float) -> str:
    """헤드리스 Chrome 으로 페이지를 열어 JS 실행 후 DOM 을 돌려준다."""
    cmd = [
        chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
        '--no-first-run', '--no-default-browser-check',
        '--disable-extensions', '--disable-background-networking',
        f'--user-agent={USER_AGENT}',
        '--virtual-time-budget=25000',   # JS 챌린지 통과까지 기다린다
        '--dump-dom', url,
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    html = (proc.stdout or b'').decode('utf-8', errors='replace')
    if not html.strip():
        err = (proc.stderr or b'').decode('utf-8', errors='replace')[:200]
        raise RuntimeError(f'DOM 이 비어 있음 (exit {proc.returncode}) {err}')
    # 차단되면 챌린지 페이지가 돌아온다 — 조용한 0건으로 넘기지 않는다.
    low = html.lower()
    if 'just a moment' in low or 'cf-browser-verification' in low:
        raise RuntimeError('Cloudflare 챌린지 페이지가 반환됨 (차단)')
    return html


def scrape(chrome: str, pages: int, timeout: float) -> tuple[list, list]:
    """AfDB 목록 페이지들을 긁어 (행 목록, 실패 목록) 반환."""
    from routes.notice_collector import AFDB_BASE, AFDB_LISTS, _parse_afdb_listing

    rows = []
    errors = []
    seen = set()
    for key, path in AFDB_LISTS:
        for page in range(max(1, pages)):
            url = f'{AFDB_BASE}{path}' + (f'?page={page}' if page else '')
            try:
                html = fetch_dom(chrome, url, timeout)
                found = _parse_afdb_listing(html)
            except Exception as e:
                errors.append(f'{key}[p{page}]: {str(e)[:110]}')
                print(f'  {key} p{page}: 실패 — {str(e)[:110]}', flush=True)
                break
            fresh = 0
            for row in found:
                u = row.get('url') or ''
                if not u or u in seen:
                    continue
                seen.add(u)
                rows.append(row)
                fresh += 1
            print(f'  {key} p{page}: {len(found)}행 (신규 {fresh})', flush=True)
            if not found:
                break
            time.sleep(1.0)   # AfDB 측 부하 배려
    return rows, errors


def push(api_base: str, secret: str, rows: list, timeout: float) -> dict:
    import requests as req

    r = req.post(
        f'{api_base}/api/notices/collect/afdb-rows',
        json={'rows': rows},
        headers={'Authorization': f'Bearer {secret}'},
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code} {r.text[:200]}')
    return r.json() or {}


def enrich(chrome: str, api_base: str, secret: str, limit: int,
           dom_timeout: float, http_timeout: float) -> dict:
    """마감일·금액이 빈 AfDB 공고의 상세 페이지를 Chrome 으로 받아 올린다.

    상세 페이지도 Cloudflare 챌린지가 걸려 있어 requests 로는 403 이다.
    목록 수집과 같은 이유로 이 역할이 맥에 있다. 추출 규칙은 서버 코드
    (_parse_afdb_detail)를 import 해 쓴다 — 규칙이 갈라지지 않도록.
    """
    import requests as req
    from routes.notice_collector import _parse_afdb_detail

    session = req.Session()
    session.headers.update({'Authorization': f'Bearer {secret}'})

    r = session.get(f'{api_base}/api/notices/enrich-pending',
                    params={'source': 'afdb', 'limit': limit},
                    timeout=http_timeout)
    r.raise_for_status()
    pending = (r.json() or {}).get('data') or []
    if not pending:
        return {'pending': 0, 'enriched': 0, 'failed': 0}

    enriched = failed = 0
    for item in pending:
        nid, url = item.get('id'), item.get('sourceUrl') or ''
        if not nid or not url:
            continue
        try:
            details = _parse_afdb_detail(fetch_dom(chrome, url, dom_timeout))
        except Exception as e:
            print(f'  #{nid} 상세 실패: {str(e)[:90]}', flush=True)
            details = {}

        if not details:
            # 실패도 서버에 알려 같은 건을 매 주기 다시 집지 않게 한다.
            details = {'text_excerpt': '', 'enrich_failed': True}
            failed += 1
        else:
            enriched += 1
            got = [k for k in ('deadline', 'contract_value', 'client') if details.get(k)]
            print(f'  #{nid} 보강: {", ".join(got) or "본문만"} '
                  f'({len(details.get("text_excerpt") or "")}자)', flush=True)

        try:
            pr = session.post(f'{api_base}/api/notices/{nid}/enrich',
                              json={'details': details}, timeout=http_timeout)
            if pr.status_code != 200:
                print(f'  #{nid} 전송 실패: HTTP {pr.status_code} {pr.text[:90]}',
                      flush=True)
        except Exception as e:
            print(f'  #{nid} 전송 예외: {str(e)[:90]}', flush=True)

        time.sleep(1.0)   # AfDB 측 부하 배려

    return {'pending': len(pending), 'enriched': enriched, 'failed': failed}


def run_once(api_base: str, secret: str, pages: int, enrich_limit: int,
             dom_timeout: float, http_timeout: float) -> dict:
    chrome = find_chrome()
    rows, errors = scrape(chrome, pages, dom_timeout)
    if not rows:
        # 목록이 통째로 비는 것은 정상이 아니다(SPN 만 853건).
        # 빈 결과를 올려 '워커는 살아있다'만 남기면 차단을 놓친다.
        raise RuntimeError('수집된 행이 0건 — ' + ('; '.join(errors) or '원인 불명'))
    res = push(api_base, secret, rows, http_timeout)
    res['rows'] = len(rows)
    res['scrape_errors'] = errors

    # 목록에는 마감일·금액이 없다 — 상세를 받아 채운다.
    # 수집이 성공했을 때만 돈다(차단 상태면 상세도 막혀 있다).
    if enrich_limit > 0:
        try:
            res['enrich'] = enrich(chrome, api_base, secret, enrich_limit,
                                   dom_timeout, http_timeout)
        except Exception as e:
            print(f'[afdb] 보강 단계 실패: {str(e)[:140]}', flush=True)
            res['enrich'] = {'error': str(e)[:140]}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description='AfDB 조달공고 목록 수집 워커')
    ap.add_argument('--env-file', default=str(BACKEND_DIR / '.env'))
    ap.add_argument('--once', action='store_true', help='1회만 실행')
    ap.add_argument('--pages', type=int, default=1,
                    help='목록당 긁을 페이지 수(1페이지 = 18건). 기본 1')
    ap.add_argument('--enrich-limit', type=int, default=6,
                    help='1회에 상세 보강할 건수. 0 이면 보강 생략. 기본 6')
    ap.add_argument('--interval', type=float, default=1800,
                    help='주기 실행 간격(초)')
    args = ap.parse_args()

    load_env_file(args.env_file)
    api_base = (os.environ.get('KRC_API_BASE_URL') or '').strip().rstrip('/')
    secret = (os.environ.get('WORKER_SECRET') or '').strip()
    if not api_base or not secret:
        raise SystemExit('KRC_API_BASE_URL / WORKER_SECRET 이 필요합니다.')

    dom_timeout = float(os.environ.get('AFDB_DOM_TIMEOUT', '90'))
    http_timeout = float(os.environ.get('AFDB_HTTP_TIMEOUT', '120'))

    while True:
        try:
            res = run_once(api_base, secret, args.pages, args.enrich_limit,
                           dom_timeout, http_timeout)
            print(f'[afdb] 행 {res.get("rows")} / 매칭 {res.get("matched")} '
                  f'/ 신규 {res.get("created")} / 제외 {res.get("skipped")}',
                  flush=True)
            en = res.get('enrich') or {}
            if en:
                print(f'[afdb] 보강 대상 {en.get("pending", 0)} '
                      f'/ 성공 {en.get("enriched", 0)} / 실패 {en.get("failed", 0)}'
                      + (f' / 오류 {en["error"]}' if en.get('error') else ''),
                      flush=True)
            if res.get('scrape_errors'):
                print(f'[afdb] 일부 목록 실패: {res["scrape_errors"]}', flush=True)
        except Exception as e:
            print(f'[afdb] 실행 실패: {str(e)[:200]}', flush=True)
        if args.once:
            return 0
        time.sleep(max(300.0, args.interval))


if __name__ == '__main__':
    raise SystemExit(main())
