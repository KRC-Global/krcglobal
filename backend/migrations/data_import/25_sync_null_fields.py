"""Stage 4.5: SKIPped 외부망 행의 NULL 필드를 내부망 export 값으로 보강.

배경:
- 20_import_to_supabase.py 의 SKIP 정책은 외부망에 이미 존재하는 사업/제안서/계약 등은
  보존하기 위해 INSERT 를 건너뛴다.
- 하지만 내부망에서 그 행에 (a) PDS 보조 필드를 새로 채웠거나, (b) 첨부 PDF 를
  새로 업로드했다면 외부망에 자동 반영되지 않는다.
- 이 스크립트는 그런 신규 입력을 외부망의 NULL 필드에만 안전하게 채워 넣는다
  (외부망의 기존 값은 덮어쓰지 않음).

처리 컬럼:
- PDS: consulting_projects.pds_* (8개)
- 첨부 파일: file_path / file_size / file_name 류 (3종 세트)
  - proposals: file_*, technical_file_*, price_file_*, price_password
  - contracts: file_*
  - performance_records: file_*
  - tor_rfp: tor_file_*, rfp_file_*
  - eois: eoi_file_*
  - oda_reports: file_*
  - oda_notes: file_*
  - board_posts: file_*

사용법:
    python backend/migrations/data_import/25_sync_null_fields.py
      [--dry-run] [--tables a,b] [--only={pds,files,all}]

산출물:
  - reports/sync_null_report.csv  (table, sqlite_id, supabase_id, column, action, detail)
"""
import argparse
import csv
import json
import os
import sys

from _bootstrap import app, db, EXPORTS_DIR, MANIFESTS_DIR, REPORTS_DIR  # noqa
from _tables import TABLES, by_name  # noqa
from sqlalchemy import text


# ── 보강 대상 컬럼 정의 ────────────────────────────────────
PDS_COLUMNS = [
    'pds_location_within_country',
    'pds_client_address',
    'pds_total_staff_months',
    'pds_associated_staff_months',
    'pds_senior_staff',
    'pds_narrative_description_en',
    'pds_services_description_en',
    'pds_extracted_at',
]

# 테이블별 "파일 트리플(path/size/name)" 그룹.
FILE_TRIPLES = {
    'proposals': [
        ('file_path', 'file_size', 'file_name'),
        ('technical_file_path', 'technical_file_size', 'technical_file_name'),
        ('price_file_path', 'price_file_size', 'price_file_name'),
    ],
    'contracts': [
        ('file_path', 'file_size', 'file_name'),
    ],
    'performance_records': [
        ('file_path', 'file_size', 'file_name'),
    ],
    'tor_rfp': [
        ('tor_file_path', 'tor_file_size', 'tor_file_name'),
        ('rfp_file_path', 'rfp_file_size', 'rfp_file_name'),
    ],
    'eois': [
        ('eoi_file_path', 'eoi_file_size', 'eoi_file_name'),
    ],
    'oda_reports': [
        ('file_path', 'file_size', 'file_name'),
    ],
    'oda_notes': [
        ('file_path', 'file_size', 'file_name'),
    ],
    'board_posts': [
        ('file_path', 'file_size', 'file_name'),
    ],
}

# 단독 추가 컬럼 (트리플 아닌 단일 컬럼) — proposals.price_password 등
EXTRA_SOLO_COLUMNS = {
    'proposals': ['price_password'],
}


def load_id_mapping():
    p = os.path.join(MANIFESTS_DIR, 'id_mapping.json')
    if not os.path.exists(p):
        print(f'ERROR: {p} 없음. 먼저 20_import_to_supabase.py 실행.', file=sys.stderr)
        sys.exit(2)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_jsonl(table_name):
    p = os.path.join(EXPORTS_DIR, f'{table_name}.jsonl')
    if not os.path.exists(p):
        return None
    rows = []
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def column_exists(table_name, col_name):
    sql = text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t AND column_name=:c
    """)
    return db.session.execute(sql, {'t': table_name, 'c': col_name}).fetchone() is not None


def get_external_row(table_name, sb_id):
    sql = text(f'SELECT * FROM "{table_name}" WHERE id = :id')
    r = db.session.execute(sql, {'id': sb_id}).fetchone()
    return dict(r._mapping) if r else None


def is_empty(v):
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == '':
        return True
    return False


def apply_updates(table_name, sb_id, updates, dry_run):
    if not updates:
        return
    sets = []
    params = {'id': sb_id}
    for i, (col, val) in enumerate(updates.items()):
        sets.append(f'"{col}" = :v{i}')
        params[f'v{i}'] = val
    sql = text(f'UPDATE "{table_name}" SET {", ".join(sets)} WHERE id = :id')
    if not dry_run:
        db.session.execute(sql, params)
        db.session.commit()


def determine_target_columns(table_name, only_mode):
    """이 테이블에서 보강 시도할 컬럼 집합."""
    cols = []
    if only_mode in ('pds', 'all') and table_name == 'consulting_projects':
        cols.extend(PDS_COLUMNS)
    if only_mode in ('files', 'all'):
        for triple in FILE_TRIPLES.get(table_name, []):
            cols.extend(triple)
        cols.extend(EXTRA_SOLO_COLUMNS.get(table_name, []))
    # 외부망에 실제로 존재하는 컬럼만 남기기
    return [c for c in cols if column_exists(table_name, c)]


def process_table(entry, id_mapping, only_mode, dry_run, writer):
    name = entry['name']
    target_cols = determine_target_columns(name, only_mode)
    if not target_cols:
        return 0, 0
    records = load_jsonl(name)
    if not records:
        return 0, 0
    mapping_for_table = id_mapping.get(name, {})

    updated_rows = 0
    updated_cells = 0

    # File triples: path/size/name 은 묶어서 갱신해야 일관성 유지
    triples = FILE_TRIPLES.get(name, []) if only_mode in ('files', 'all') else []
    triple_path_cols = {t[0] for t in triples}

    for rec in records:
        sl_id = rec.get('id')
        sb_id = mapping_for_table.get(str(sl_id))
        if not isinstance(sb_id, int):
            continue

        ext_row = get_external_row(name, sb_id)
        if ext_row is None:
            continue

        updates = {}

        # 단일 컬럼들 (PDS + EXTRA_SOLO)
        single_cols = [c for c in target_cols if c not in triple_path_cols and not any(
            c == t[1] or c == t[2] for t in triples)]
        for col in single_cols:
            ext_val = ext_row.get(col)
            new_val = rec.get(col)
            if is_empty(ext_val) and not is_empty(new_val):
                updates[col] = new_val
                writer.writerow([name, sl_id, sb_id, col, 'BACKFILL', repr(new_val)[:80]])

        # 파일 트리플 — path 가 비어있으면 size/name 까지 한 묶음으로 채움
        for path_c, size_c, name_c in triples:
            ext_path = ext_row.get(path_c)
            int_path = rec.get(path_c)
            if is_empty(ext_path) and not is_empty(int_path):
                updates[path_c] = int_path
                int_size = rec.get(size_c)
                int_name = rec.get(name_c)
                if not is_empty(int_size):
                    updates[size_c] = int_size
                if not is_empty(int_name):
                    updates[name_c] = int_name
                writer.writerow([name, sl_id, sb_id, path_c, 'BACKFILL_FILE',
                                 int_name or int_path])

        if updates:
            apply_updates(name, sb_id, updates, dry_run)
            updated_rows += 1
            updated_cells += len(updates)

    return updated_rows, updated_cells


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--tables', default=None,
                        help='쉼표 구분 — 일부만')
    parser.add_argument('--only', choices=['pds', 'files', 'all'], default='all',
                        help='pds=PDS 보조필드만, files=첨부 path/size/name 만, all=둘 다')
    parser.add_argument('--report', default=os.path.join(REPORTS_DIR, 'sync_null_report.csv'))
    args = parser.parse_args()

    id_mapping = load_id_mapping()
    selected = TABLES
    if args.tables:
        names = set(args.tables.split(','))
        selected = [t for t in TABLES if t['name'] in names]

    with app.app_context(), open(args.report, 'w', encoding='utf-8', newline='') as cf:
        # expansion 모델 로드
        try:
            from models import expansion  # noqa
        except ImportError:
            pass

        writer = csv.writer(cf)
        writer.writerow(['table', 'sqlite_id', 'supabase_id', 'column', 'action', 'detail'])

        totals = []
        for entry in selected:
            rows, cells = process_table(entry, id_mapping, args.only, args.dry_run, writer)
            totals.append((entry['name'], rows, cells))
            if rows or cells:
                print(f'  {entry["name"]:<25} rows={rows}  cells={cells}')

    print()
    grand_rows = sum(r for _, r, _ in totals)
    grand_cells = sum(c for _, _, c in totals)
    print(f'총 갱신 대상: {grand_rows} 행 / {grand_cells} 셀')
    print(f'report: {args.report}')
    if args.dry_run:
        print('** DRY RUN — DB 변경 없음 **')
    return 0


if __name__ == '__main__':
    sys.exit(main())
