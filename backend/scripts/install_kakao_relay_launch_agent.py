#!/usr/bin/env python3
"""현재 Mac 사용자용 launchd 카카오 릴레이 서비스를 설치한다."""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


LABEL = 'com.krcglobal.kakao-relay'


def main() -> int:
    parser = argparse.ArgumentParser(description='KRC 카카오 릴레이 launchd 설치')
    parser.add_argument('--env-file', type=Path, required=True)
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
    relay_script = Path(__file__).with_name('kakao_relay.py').resolve()
    kmsg_bin = shutil.which('kmsg') or '/opt/homebrew/bin/kmsg'
    user_home = Path.home()
    launch_dir = user_home / 'Library' / 'LaunchAgents'
    log_dir = user_home / 'Library' / 'Logs'
    launch_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_dir / f'{LABEL}.plist'

    payload = {
        'Label': LABEL,
        'ProgramArguments': [
            str(python_bin), str(relay_script), '--env-file', str(env_file),
        ],
        'EnvironmentVariables': {
            'PATH': f'{Path(kmsg_bin).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
        },
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 15,
        'ProcessType': 'Interactive',
        'StandardOutPath': str(log_dir / 'krcglobal-kakao-relay.log'),
        'StandardErrorPath': str(log_dir / 'krcglobal-kakao-relay.log'),
    }
    temp_path = plist_path.with_suffix('.tmp')
    with temp_path.open('wb') as output:
        plistlib.dump(payload, output, sort_keys=True)
    temp_path.replace(plist_path)

    domain = f'gui/{os.getuid()}'
    subprocess.run(
        ['launchctl', 'bootout', domain, str(plist_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(['launchctl', 'bootstrap', domain, str(plist_path)], check=True)
    print(f'설치 완료: {plist_path}')
    print(f'로그: {log_dir / "krcglobal-kakao-relay.log"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
