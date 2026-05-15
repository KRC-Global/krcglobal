"""(롤백 전용) Stage 5 의 R2 업로드와 DB file_path 변경을 되돌린다.

uploaded_manifest.jsonl 에 기록된 모든 r2_key 를 R2에서 삭제하고,
대응 Supabase 레코드의 file_path/file_size 컬럼을 NULL 로 되돌린다.

DB 레코드 자체는 삭제하지 않는다 (Stage 4 INSERT 롤백은 pg_restore 로).

사용법:
    python backend/migrations/data_import/99_rollback_r2.py
      [--confirm]   # 실제 실행
      [--dry-run]   # 시뮬레이션 (기본)
"""
import argparse
import json
import os
import sys
from datetime import datetime

from _bootstrap import app, db, MANIFESTS_DIR, REPORTS_DIR  # noqa
from sqlalchemy import text

MANIFEST_PATH = os.path.join(MANIFESTS_DIR, 'uploaded_manifest.jsonl')
DONE_LOG = os.path.join(REPORTS_DIR, f'rollback_r2_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.log')


def load_manifest():
    if not os.path.exists(MANIFEST_PATH):
        print(f'ERROR: {MANIFEST_PATH} 없음. 롤백할 항목이 없습니다.', file=sys.stderr)
        sys.exit(2)
    out = []
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', action='store_true',
                        help='실제 R2 객체 삭제 및 DB 컬럼 NULL 처리')
    parser.add_argument('--dry-run', action='store_true', default=True)
    parser.add_argument('--only-new', action='store_true',
                        help='already_existed=False 인 항목만 삭제 (안전)')
    args = parser.parse_args()

    if args.confirm:
        args.dry_run = False

    manifest = load_manifest()
    print(f'manifest 항목 수: {len(manifest)}')
    if args.only_new:
        manifest = [m for m in manifest if not m.get('already_existed', False)]
        print(f'--only-new 적용 후: {len(manifest)} 항목')

    if args.dry_run:
        print('** DRY RUN — 실제 변경 없음. --confirm 으로 실행하세요. **')
    else:
        print('** 실제 롤백 실행. R2 객체 삭제와 DB UPDATE 가 수행됩니다. **')

    deleted = 0
    db_updated = 0
    errors = 0

    with app.app_context(), open(DONE_LOG, 'w', encoding='utf-8') as logf:
        from utils.r2_storage import get_r2_client
        client = get_r2_client()
        bucket = app.config['R2_BUCKET_NAME']

        for rec in manifest:
            r2_key = rec.get('r2_key')
            table = rec.get('table')
            sb_id = rec.get('supabase_id')
            field = rec.get('field')

            try:
                if not args.dry_run:
                    client.delete_object(Bucket=bucket, Key=r2_key)
                deleted += 1
                logf.write(f'R2 DELETE\t{r2_key}\n')
            except Exception as e:
                errors += 1
                logf.write(f'R2 ERROR\t{r2_key}\t{e}\n')
                continue

            try:
                if not args.dry_run and table and sb_id and field:
                    # path / name / size 컬럼명을 추론 (field 가 path_col 임을 가정)
                    name_col = None
                    size_col = None
                    if field.endswith('_path'):
                        base = field[:-len('_path')]
                        name_col = f'{base}_name'
                        size_col = f'{base}_size'
                    elif field == 'file_path':
                        name_col = 'file_name'
                        size_col = 'file_size'

                    set_cols = [f'"{field}" = NULL']
                    if name_col:
                        set_cols.append(f'"{name_col}" = NULL')
                    if size_col:
                        set_cols.append(f'"{size_col}" = NULL')
                    sql = text(
                        f'UPDATE "{table}" SET {", ".join(set_cols)} WHERE id = :id'
                    )
                    db.session.execute(sql, {'id': sb_id})
                    db.session.commit()
                db_updated += 1
                logf.write(f'DB UPDATE\t{table}#{sb_id}\t{field}=NULL\n')
            except Exception as e:
                errors += 1
                logf.write(f'DB ERROR\t{table}#{sb_id}\t{e}\n')

    print(f'\n=== 결과 ===')
    print(f'  deleted     {deleted}')
    print(f'  db_updated  {db_updated}')
    print(f'  errors      {errors}')
    print(f'  log:        {DONE_LOG}')
    if not args.dry_run:
        print('\n manifest 파일을 폐기/백업하시려면 수동으로 처리하세요:')
        print(f'  {MANIFEST_PATH}')
    return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
