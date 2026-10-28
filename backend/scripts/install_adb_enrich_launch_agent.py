#!/usr/bin/env python3
"""현재 Mac 사용자용 launchd ADB 본문 보강 서비스를 설치한다.

카카오 릴레이와 달리 상주하지 않는다. ADB 공고는 하루 몇 건 수준이라
30분마다 1회 실행(--once)하고 끝내는 편이 안전하다 — 프로세스가 죽어도
다음 주기에 다시 뜨고, 중복 실행 걱정도 없다.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = 'com.krcglobal.adb-enrich'
DEFAULT_INTERVAL = 1800   # 30분
DEFAULT_LIMIT = 10


def main() -> int:
    parser = argparse.ArgumentParser(description='KRC ADB 본문 보강 launchd 설치')
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--interval', type=int, default=DEFAULT_INTERVAL,
                        help=f'실행 간격(초). 기본 {DEFAULT_INTERVAL}')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT,
                        help=f'1회 처리 건수. 기본 {DEFAULT_LIMIT}')
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
    worker = Path(__file__).with_name('adb_enrich.py').resolve()
    user_home = Path.home()
    launch_dir = user_home / 'Library' / 'LaunchAgents'
    log_dir = user_home / 'Library' / 'Logs'
    launch_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_dir / f'{LABEL}.plist'
    log_path = log_dir / 'krcglobal-adb-enrich.log'

    payload = {
        'Label': LABEL,
        'ProgramArguments': [
            str(python_bin), str(worker),
            '--env-file', str(env_file),
            '--once',
            '--limit', str(args.limit),
        ],
        'EnvironmentVariables': {
            'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
        },
        'RunAtLoad': True,
        'StartInterval': max(300, args.interval),
        'ThrottleInterval': 60,
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
    print(f'실행 주기: {max(300, args.interval)}초 · 1회 {args.limit}건')
    print(f'로그: {log_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
