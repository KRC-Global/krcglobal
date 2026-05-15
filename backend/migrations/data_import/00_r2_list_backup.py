"""Stage 0-b: 외부망 R2 버킷의 현재 객체 listing을 보존한다 (read-only).

사용법:
    python backend/migrations/data_import/00_r2_list_backup.py
      --out backend/migrations/data_import/reports/r2_objects_before.txt

기본 출력 위치는 reports/r2_objects_before.txt. --out 인자로 변경 가능.
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime

from _bootstrap import app, REPORTS_DIR  # noqa


def list_all_objects(client, bucket):
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get('Contents', []):
            yield obj


def prefix_of(key):
    if '/' in key:
        return key.split('/', 1)[0]
    return '(root)'


def format_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.2f} {unit}'
        n /= 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=os.path.join(REPORTS_DIR, 'r2_objects_before.txt'),
                        help='출력 파일 경로')
    args = parser.parse_args()

    with app.app_context():
        from utils.r2_storage import get_r2_client
        client = get_r2_client()
        bucket = app.config['R2_BUCKET_NAME']
        max_bytes = app.config['R2_MAX_STORAGE_BYTES']

        per_prefix_count = defaultdict(int)
        per_prefix_size = defaultdict(int)
        total_count = 0
        total_size = 0

        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(f'# R2 inventory snapshot\n')
            f.write(f'# bucket: {bucket}\n')
            f.write(f'# captured_at: {datetime.utcnow().isoformat()}Z\n')
            f.write(f'# format: <key>\\t<size_bytes>\\t<last_modified>\\t<etag>\n')
            f.write('# --- begin ---\n')

            for obj in list_all_objects(client, bucket):
                key = obj['Key']
                size = obj['Size']
                last_modified = obj['LastModified'].isoformat()
                etag = (obj.get('ETag') or '').strip('"')
                f.write(f'{key}\t{size}\t{last_modified}\t{etag}\n')

                p = prefix_of(key)
                per_prefix_count[p] += 1
                per_prefix_size[p] += size
                total_count += 1
                total_size += size

            f.write('# --- end ---\n')

        print(f'Bucket: {bucket}')
        print(f'Output: {args.out}')
        print(f'Total objects: {total_count}')
        print(f'Total size: {format_size(total_size)}  ({total_size:,} bytes)')
        print(f'Limit:      {format_size(max_bytes)}  ({max_bytes:,} bytes)')
        print(f'Remaining:  {format_size(max_bytes - total_size)}')
        print()
        print('Per-prefix breakdown:')
        for p in sorted(per_prefix_count.keys()):
            print(f'  {p:<24} {per_prefix_count[p]:>6}  {format_size(per_prefix_size[p]):>12}')

        if total_size > max_bytes:
            print()
            print('WARNING: 현재 사용량이 한도를 초과했습니다.', file=sys.stderr)
            return 1
        return 0


if __name__ == '__main__':
    sys.exit(main())
