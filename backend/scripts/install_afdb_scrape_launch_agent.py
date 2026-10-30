#!/usr/bin/env python3
"""현재 Mac 사용자용 launchd AfDB 공고 수집 서비스를 설치한다.

ADB 본문 보강(install_adb_enrich_launch_agent.py)과 같은 방식이다.
상주하지 않고 주기마다 1회 실행(--once)하고 끝낸다 — 프로세스가 죽어도
다음 주기에 다시 뜨고, 중복 실행 걱정이 없다.

AfDB 는 하루 수십 건이 올라오지만 KRC 적합 건은 많지 않고, 헤드리스
Chrome 을 4회 띄우므로 ADB 보강(10분)보다 여유 있게 30분 주기로 돈다.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = 'com.krcglobal.afdb-scrape'
DEFAULT_INTERVAL = 1800   # 30분 — Chrome 4회 실행이라 ADB 보강보다 길게 둔다
DEFAULT_PAGES = 1         # 목록당 1페이지(18건). 과거분까지 긁을 땐 늘린다


def main() -> int:
    parser = argparse.ArgumentParser(description='KRC AfDB 공고 수집 launchd 설치')
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                        help=f'실행 간격(초). 기본 {DEFAULT_INTERVAL}')
    parser.add_argument('--pages', type=int, default=DEFAULT_PAGES,
                        help=f'목록당 긁을 페이지 수. 기본 {DEFAULT_PAGES}')
    args = parser.parse_args()

    if sys.platform != 'darwin':
        parser.error('macOS에서만 설치할 수 있습니다.')
    env_file = args.env_file.expanduser().resolve()
    if not env_file.is_file():
        parser.error(f'설정 파일을 찾을 수 없습니다: {env_file}')
    try:
        env_file.chmod(0o600)
    except OSError:
        pass

    python_bin = Path(sys.executable).resolve()
    worker = Path(__file__).with_name('afdb_scrape.py').resolve()
    user_home = Path.home()
    launch_dir = user_home / 'Library' / 'LaunchAgents'
    log_dir = user_home / 'Library' / 'Logs'
    launch_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_dir / f'{LABEL}.plist'
    log_path = log_dir / 'krcglobal-afdb-scrape.log'

    payload = {
        'Label': LABEL,
        'ProgramArguments': [
            str(python_bin), str(worker),
            '--env-file', str(env_file),
            '--once',
            '--pages', str(args.pages),
        ],
        'EnvironmentVariables': {
            'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
        },
        'RunAtLoad': True,
        'StartInterval': max(600, args.interval),
        'ThrottleInterval': 120,
        'StandardOutPath': str(log_path),
        'StandardErrorPath': str(log_path),
    }
    temp_path = plist_path.with_suffix('.tmp')
    with temp_path.open('wb') as output:
        plistlib.dump(payload, output, sort_keys=True)
    temp_path.replace(plist_path)

    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', domain, str(plist_path)],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', domain, str(plist_path)], check=True)
    print(f'설치 완료: {plist_path}')
    print(f'실행 주기: {max(600, args.interval)}초 · 목록당 {args.pages}페이지')
    print(f'로그: {log_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
