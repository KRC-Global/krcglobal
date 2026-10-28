#!/usr/bin/env python3
"""ADB 공고 본문 보강 워커 (사내 맥에서 실행).

ADB 는 데이터센터 IP 를 차단한다. Vercel 에서 공고 PDF 를 받으면 HTTP 403 이
돌아와 마감일·금액·본문을 채울 수 없다. 반면 사내 맥에서는 정상 접근된다.

그래서 역할을 나눈다:
  서버(Vercel)  수집·필터·카드 생성·카카오 큐
  이 워커(맥)    ADB 링크를 열어 PDF 본문을 추출해 서버로 올림

동작:
  1. GET  /api/notices/enrich-pending?source=adb   보강 필요한 공고 목록
  2. 각 source_url 을 열어 PDF 텍스트·마감일·금액·국가 추출
  3. POST /api/notices/<id>/enrich                 결과 전송
  서버는 비어 있는 필드만 채우고, 본문이 생기면 재번역을 큐에 넣는다.

추출 로직은 수집기의 _fetch_adb_detail 을 그대로 쓴다. 규칙이 한 곳에만
있어야 서버와 워커가 어긋나지 않는다.

사용:
  python3 scripts/adb_enrich.py --env-file .env --once
  python3 scripts/adb_enrich.py --env-file .env          # 주기 실행
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


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


def run_once(api_base: str, secret: str, limit: int, timeout: float) -> dict:
    import requests as req
    from routes.notice_collector import _fetch_adb_detail

    session = req.Session()
    session.headers.update({'Authorization': f'Bearer {secret}'})

    r = session.get(f'{api_base}/api/notices/enrich-pending',
                    params={'source': 'adb', 'limit': limit}, timeout=timeout)
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
            details = _fetch_adb_detail(url)
        except Exception as e:
            print(f'  #{nid} 추출 예외: {str(e)[:80]}')
            details = {}

        if not details:
            # 추출 실패도 서버에 알려 같은 건을 매번 다시 집지 않게 한다.
            details = {'text_excerpt': '', 'enrich_failed': True}
            failed += 1
        else:
            enriched += 1
            got = [k for k in ('deadline', 'contract_value', 'country') if details.get(k)]
            print(f'  #{nid} 보강: {", ".join(got) or "본문만"} '
                  f'({len(details.get("text_excerpt") or "")}자)')

        try:
            pr = session.post(f'{api_base}/api/notices/{nid}/enrich',
                              json={'details': details}, timeout=timeout)
            if pr.status_code != 200:
                print(f'  #{nid} 전송 실패: HTTP {pr.status_code} {pr.text[:90]}')
        except Exception as e:
            print(f'  #{nid} 전송 예외: {str(e)[:80]}')

        time.sleep(1.0)  # ADB 측 부하 배려

    return {'pending': len(pending), 'enriched': enriched, 'failed': failed}


def main() -> int:
    ap = argparse.ArgumentParser(description='ADB 공고 본문 보강 워커')
    ap.add_argument('--env-file', default=str(BACKEND_DIR / '.env'))
    ap.add_argument('--once', action='store_true', help='1회만 실행')
    ap.add_argument('--limit', type=int, default=10, help='한 번에 처리할 건수')
    ap.add_argument('--interval', type=float, default=1800, help='주기 실행 간격(초)')
    args = ap.parse_args()

    load_env_file(args.env_file)
    api_base = (os.environ.get('KRC_API_BASE_URL') or '').strip().rstrip('/')
    secret = (os.environ.get('WORKER_SECRET') or '').strip()
    if not api_base or not secret:
        raise SystemExit('KRC_API_BASE_URL / WORKER_SECRET 이 필요합니다.')

    timeout = float(os.environ.get('ADB_ENRICH_HTTP_TIMEOUT', '60'))
    while True:
        try:
            res = run_once(api_base, secret, args.limit, timeout)
            print(f'[adb-enrich] 대상 {res["pending"]} / 보강 {res["enriched"]} '
                  f'/ 실패 {res["failed"]}', flush=True)
        except Exception as e:
            print(f'[adb-enrich] 실행 실패: {str(e)[:140]}', flush=True)
        if args.once:
            return 0
        time.sleep(max(60.0, args.interval))


if __name__ == '__main__':
    raise SystemExit(main())
