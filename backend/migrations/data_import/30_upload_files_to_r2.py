"""Stage 5: 첨부파일을 Cloudflare R2로 업로드하고 외부망 DB의 file_path 를 갱신.

재실행 가능 (idempotent):
1) manifests/uploaded_manifest.jsonl 에 이미 기록된 (table, sqlite_id, field) 는 스킵
2) R2 head_object 로 이미 존재하면 업로드 생략 + DB 만 갱신
3) 결정적 키: `{prefix}/migrated_{sqlite_id}_{safe_filename}`

사용법:
    python backend/migrations/data_import/30_upload_files_to_r2.py
      [--dry-run] [--tables a,b] [--skip-quota-check]

산출물:
  - manifests/uploaded_manifest.jsonl
  - reports/failed_uploads.csv
"""
import argparse
import csv
import json
import mimetypes
import os
import re
import sys
from datetime import datetime

from _bootstrap import app, db, MANIFESTS_DIR, REPORTS_DIR, MIGRATION_SRC_DIR  # noqa
from _tables import TABLES, by_name  # noqa
from sqlalchemy import text

UPLOADS_SRC = os.path.join(MIGRATION_SRC_DIR, 'uploads')
MANIFEST_PATH = os.path.join(MANIFESTS_DIR, 'uploaded_manifest.jsonl')
FAILED_PATH = os.path.join(REPORTS_DIR, 'failed_uploads.csv')


def load_id_mapping():
    p = os.path.join(MANIFESTS_DIR, 'id_mapping.json')
    if not os.path.exists(p):
        print(f'ERROR: {p} 없음. 먼저 20_import_to_supabase.py 실행.', file=sys.stderr)
        sys.exit(2)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_manifest_done():
    done = set()
    if not os.path.exists(MANIFEST_PATH):
        return done
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done.add((rec['table'], int(rec['sqlite_id']), rec['field']))
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return done


def append_manifest(record):
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write('\n')


def safe_filename(name):
    """파일명에 안전하지 않은 문자 제거. 한글은 보존."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', '_', name).strip('._')
    return name or 'file'


def build_r2_key(prefix, sqlite_id, original_name):
    """결정적 R2 key 생성: {prefix}/migrated_{sqlite_id}_{safe_filename}"""
    fname = safe_filename(os.path.basename(original_name or 'file'))
    return f'{prefix}/migrated_{sqlite_id}_{fname}'


def find_local_file(prefix, original_path, original_name):
    """_migration_src/uploads/{prefix}/ 안에서 파일 위치 찾기.
    DB에 절대경로가 저장된 경우 basename 만 사용.
    """
    candidates = []
    for p in (original_path, original_name):
        if not p:
            continue
        fname = os.path.basename(str(p).replace('\\', '/'))
        if fname and fname not in candidates:
            candidates.append(fname)

    prefix_dir = os.path.join(UPLOADS_SRC, prefix)
    if not os.path.isdir(prefix_dir):
        return None

    for fname in candidates:
        direct = os.path.join(prefix_dir, fname)
        if os.path.isfile(direct):
            return direct

    # 하위 디렉토리(예: proposals/technical/) 탐색
    target_lowers = [c.lower() for c in candidates]
    for root, _, files in os.walk(prefix_dir):
        for f in files:
            if f.lower() in target_lowers:
                return os.path.join(root, f)
    return None


def fetch_record(table_name, supabase_id):
    sql = text(f'SELECT * FROM "{table_name}" WHERE id = :id')
    row = db.session.execute(sql, {'id': supabase_id}).fetchone()
    return row._mapping if row else None


def update_record_file(table_name, supabase_id, file_field, r2_key, file_size, file_name):
    cols = []
    params = {'id': supabase_id, 'p': r2_key, 's': file_size, 'n': file_name}
    if file_field['path_col']:
        cols.append(f'"{file_field["path_col"]}" = :p')
    if file_field['size_col']:
        cols.append(f'"{file_field["size_col"]}" = :s')
    if file_field['name_col']:
        cols.append(f'"{file_field["name_col"]}" = :n')
    if not cols:
        return
    sql = text(f'UPDATE "{table_name}" SET {", ".join(cols)} WHERE id = :id')
    db.session.execute(sql, params)
    db.session.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--tables', default=None)
    parser.add_argument('--skip-quota-check', action='store_true',
                        help='R2 9GB 사전 점검 생략')
    args = parser.parse_args()

    if not os.path.isdir(UPLOADS_SRC):
        print(f'ERROR: 첨부 디렉토리가 없습니다: {UPLOADS_SRC}', file=sys.stderr)
        return 2

    id_mapping = load_id_mapping()
    done = load_manifest_done()

    selected = [t for t in TABLES if t.get('file_fields')]
    if args.tables:
        names = set(args.tables.split(','))
        selected = [t for t in selected if t['name'] in names]

    failed_rows = []
    counters = {'uploaded': 0, 'skip_manifest': 0, 'skip_head': 0,
                'no_file': 0, 'no_mapping': 0, 'error': 0, 'dry': 0}

    with app.app_context():
        from utils.r2_storage import get_r2_client, get_bucket_usage  # noqa
        client = get_r2_client()
        bucket = app.config['R2_BUCKET_NAME']
        max_bytes = app.config['R2_MAX_STORAGE_BYTES']

        # 사전 용량 점검
        if not args.skip_quota_check and not args.dry_run:
            current_usage = get_bucket_usage()
            print(f'R2 현재 사용량: {current_usage:,} / {max_bytes:,} 바이트')
            if current_usage >= max_bytes:
                print('ERROR: 이미 한도 초과', file=sys.stderr)
                return 1

        for entry in selected:
            tname = entry['name']
            mapping_for_table = id_mapping.get(tname, {})
            if not mapping_for_table:
                print(f'[{tname}] id_mapping 비어있음 — 스킵')
                continue

            print(f'\n=== {tname} ===')
            for sl_id_str, sb_id in mapping_for_table.items():
                if not isinstance(sb_id, int):
                    continue  # dry-run placeholder 등
                sl_id = int(sl_id_str)
                rec = fetch_record(tname, sb_id)
                if rec is None:
                    counters['no_mapping'] += 1
                    failed_rows.append([tname, sl_id, sb_id, '', 'no_db_record', ''])
                    continue

                for fld in entry['file_fields']:
                    key_tuple = (tname, sl_id, fld['path_col'])
                    if key_tuple in done:
                        counters['skip_manifest'] += 1
                        continue

                    orig_path = rec.get(fld['path_col'])
                    orig_name = rec.get(fld['name_col']) if fld.get('name_col') else None
                    if not orig_path and not orig_name:
                        continue  # 파일 없는 필드

                    local = find_local_file(fld['prefix'], orig_path, orig_name)
                    if not local:
                        counters['no_file'] += 1
                        failed_rows.append([tname, sl_id, sb_id, fld['path_col'],
                                            'local_file_missing', str(orig_path)])
                        continue

                    size = os.path.getsize(local)
                    r2_key = build_r2_key(fld['prefix'], sl_id,
                                          orig_name or os.path.basename(local))

                    # R2 head_object 확인
                    head_exists = False
                    try:
                        client.head_object(Bucket=bucket, Key=r2_key)
                        head_exists = True
                    except Exception:
                        head_exists = False

                    if args.dry_run:
                        counters['dry'] += 1
                        print(f'  DRY [{fld["path_col"]}] {sl_id} → {r2_key} ({size:,}B)'
                              + (' (head exists)' if head_exists else ''))
                        continue

                    try:
                        if not head_exists:
                            content_type, _ = mimetypes.guess_type(local)
                            with open(local, 'rb') as fp:
                                client.upload_fileobj(
                                    fp, bucket, r2_key,
                                    ExtraArgs={'ContentType': content_type} if content_type else {}
                                )
                            counters['uploaded'] += 1
                        else:
                            counters['skip_head'] += 1

                        update_record_file(tname, sb_id, fld, r2_key, size,
                                           orig_name or os.path.basename(local))
                        append_manifest({
                            'table': tname,
                            'sqlite_id': sl_id,
                            'supabase_id': sb_id,
                            'field': fld['path_col'],
                            'r2_key': r2_key,
                            'size': size,
                            'uploaded_at': datetime.utcnow().isoformat() + 'Z',
                            'already_existed': head_exists,
                        })
                    except Exception as e:
                        counters['error'] += 1
                        failed_rows.append([tname, sl_id, sb_id, fld['path_col'],
                                            'upload_or_update_error', str(e)[:300]])
                        try:
                            db.session.rollback()
                        except Exception:
                            pass

    if failed_rows:
        os.makedirs(os.path.dirname(FAILED_PATH), exist_ok=True)
        with open(FAILED_PATH, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['table', 'sqlite_id', 'supabase_id', 'field', 'reason', 'detail'])
            w.writerows(failed_rows)

    print('\n=== 요약 ===')
    for k, v in counters.items():
        print(f'  {k:<14} {v}')
    print(f'\nmanifest: {MANIFEST_PATH}')
    if failed_rows:
        print(f'failed:   {FAILED_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
