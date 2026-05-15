"""Stage 4: 외부망 Supabase로 skip-conflict INSERT.

테이블별 conflict_key로 SELECT → 존재 시 SKIP + id_mapping 기록,
부재 시 INSERT + 신규 id 기록.

사용법:
    python backend/migrations/data_import/20_import_to_supabase.py
      [--dry-run] [--limit N] [--tables a,b,c] [--null-conflict skip|insert]

산출물:
  - manifests/id_mapping.json
  - reports/conflicts_report.csv
  - reports/insert_report.csv
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

from _bootstrap import app, db, EXPORTS_DIR, MANIFESTS_DIR, REPORTS_DIR  # noqa
from _tables import TABLES, by_name  # noqa
from sqlalchemy import text


def load_user_map():
    p = os.path.join(MANIFESTS_DIR, 'user_map.json')
    if not os.path.exists(p):
        print(f'ERROR: {p} 없음. 먼저 15_build_user_map.py 실행.', file=sys.stderr)
        sys.exit(2)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_id_mapping():
    p = os.path.join(MANIFESTS_DIR, 'id_mapping.json')
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_id_mapping(mapping):
    p = os.path.join(MANIFESTS_DIR, 'id_mapping.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def get_table(name):
    return db.metadata.tables.get(name)


def coerce_for_column(col, value):
    """Python 값을 SQLAlchemy 컬럼 타입에 맞게 변환."""
    if value is None or value == '':
        return None if value is None else ('' if str(col.type).upper().startswith(('VARCHAR', 'TEXT', 'STRING')) else None)

    import sqlalchemy.types as t
    coltype = col.type

    if isinstance(coltype, t.Boolean):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 't', 'yes')
        return bool(value)

    if isinstance(coltype, (t.Numeric, t.Float)):
        try:
            return Decimal(str(value)) if not isinstance(value, Decimal) else value
        except InvalidOperation:
            return None

    if isinstance(coltype, t.Integer):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if isinstance(coltype, (t.DateTime, t.Date)):
        if isinstance(value, str):
            # ISO 8601 → datetime
            try:
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                # 'YYYY-MM-DD' 만이거나 비표준
                for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                return None
        return value

    return value


def remap_fk(record, entry, user_map_full, id_mapping):
    """parent_fks 기준으로 record 의 FK 컬럼을 외부망 id로 치환.
    반환: (remapped_record_or_None, drop_reason)
    None 이면 부모 매핑 실패로 행을 건너뜀.
    """
    parent_fks = entry.get('parent_fks', {})
    new = dict(record)
    fallback = user_map_full.get('fallback_user_id')
    user_map = user_map_full.get('map', {})

    for fk_col, parent_table in parent_fks.items():
        if fk_col not in new:
            continue
        sl_val = new[fk_col]
        if sl_val is None:
            continue
        if parent_table == 'users':
            mapped = user_map.get(str(sl_val))
            if mapped is None:
                mapped = fallback  # int or None
            new[fk_col] = mapped
        else:
            tbl_map = id_mapping.get(parent_table, {})
            mapped = tbl_map.get(str(sl_val))
            if mapped is None:
                return None, f'부모 {parent_table}#{sl_val} 매핑 없음'
            new[fk_col] = mapped
    return new, None


def build_where(table, conflict_key, record):
    """conflict_key 컬럼들로 (where_sql, params) 생성. NULL은 IS NULL 처리."""
    pieces = []
    params = {}
    for i, col_name in enumerate(conflict_key):
        col = table.columns.get(col_name)
        if col is None:
            # 외부망에 없는 컬럼 → SKIP 불가, conflict 검사도 의미 없음
            return None, None
        val = record.get(col_name)
        if val is None:
            pieces.append(f'"{col_name}" IS NULL')
        else:
            pkey = f'p{i}'
            pieces.append(f'"{col_name}" = :{pkey}')
            params[pkey] = coerce_for_column(col, val)
    where_sql = ' AND '.join(pieces) if pieces else '1=1'
    return where_sql, params


def find_conflict(table, conflict_key, record):
    where_sql, params = build_where(table, conflict_key, record)
    if where_sql is None:
        return None
    sql = text(f'SELECT id FROM "{table.name}" WHERE {where_sql} LIMIT 1')
    row = db.session.execute(sql, params).fetchone()
    return row.id if row else None


def do_insert(table, record):
    # id 컬럼 제외, 모델에 있는 컬럼만 사용
    insert_data = {}
    for col_name, val in record.items():
        col = table.columns.get(col_name)
        if col is None:
            continue
        if col.primary_key:
            continue
        coerced = coerce_for_column(col, val)
        if coerced is None and col.default is None and not col.nullable:
            # NOT NULL 인데 NULL — 컬럼 default가 있다면 server-side 적용
            # 우선 생략하여 server default 가 동작하도록 한다
            continue
        insert_data[col_name] = coerced

    cols = list(insert_data.keys())
    if not cols:
        return None
    quoted_cols = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(f':{c}' for c in cols)
    sql = text(f'INSERT INTO "{table.name}" ({quoted_cols}) VALUES ({placeholders}) RETURNING id')
    result = db.session.execute(sql, insert_data)
    new_id = result.scalar()
    return new_id


def load_jsonl(table_name):
    p = os.path.join(EXPORTS_DIR, f'{table_name}.jsonl')
    if not os.path.exists(p):
        return None
    out = []
    with open(p, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def process_table(entry, user_map, id_mapping, dry_run, limit, null_conflict,
                  conflicts_writer, insert_writer):
    name = entry['name']
    table = get_table(name)
    if table is None:
        print(f'[{name}] 외부망 모델 없음 — 스킵')
        return 0, 0, 0
    records = load_jsonl(name)
    if records is None:
        print(f'[{name}] export 파일 없음 — 스킵')
        return 0, 0, 0

    inserted = 0
    skipped = 0
    dropped = 0

    if limit:
        records = records[:limit]

    mapping_for_table = id_mapping.setdefault(name, {})

    for rec in records:
        sl_id = rec.get('id')
        remapped, drop_reason = remap_fk(rec, entry, user_map, id_mapping)
        if remapped is None:
            dropped += 1
            conflicts_writer.writerow([name, sl_id, '', 'DROP', drop_reason])
            continue

        # conflict 검사
        conflict_key = entry['conflict_key']
        has_null_in_key = any(remapped.get(k) is None for k in conflict_key)
        if has_null_in_key and null_conflict == 'skip':
            # NULL 포함 키는 충돌 검사 불가 → skip 정책 적용 시 INSERT 안 함
            dropped += 1
            conflicts_writer.writerow([name, sl_id, '', 'SKIP_NULL_KEY',
                                       f'conflict_key contains NULL: {conflict_key}'])
            continue

        existing = find_conflict(table, conflict_key, remapped)
        if existing is not None:
            skipped += 1
            mapping_for_table[str(sl_id)] = existing
            conflicts_writer.writerow([name, sl_id, existing, 'SKIP_EXISTS',
                                       ' / '.join(str(remapped.get(k) or '') for k in conflict_key)])
            continue

        if dry_run:
            inserted += 1
            mapping_for_table[str(sl_id)] = f'<dry-{sl_id}>'
            insert_writer.writerow([name, sl_id, 'DRY_RUN', ''])
            continue

        try:
            new_id = do_insert(table, remapped)
            db.session.commit()
            inserted += 1
            mapping_for_table[str(sl_id)] = new_id
            insert_writer.writerow([name, sl_id, new_id, ''])
        except Exception as e:
            db.session.rollback()
            dropped += 1
            conflicts_writer.writerow([name, sl_id, '', 'INSERT_ERROR', str(e)[:300]])

    # 테이블 단위 저장
    save_id_mapping(id_mapping)
    return inserted, skipped, dropped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='실제 INSERT 없이 시뮬레이션')
    parser.add_argument('--limit', type=int, default=None, help='테이블당 최대 N행')
    parser.add_argument('--tables', default=None, help='쉼표 구분 — 일부만')
    parser.add_argument('--null-conflict', choices=['skip', 'insert'], default='skip',
                        help='conflict_key에 NULL이 포함된 행 처리 방식')
    args = parser.parse_args()

    user_map = load_user_map()
    id_mapping = load_id_mapping()

    selected = TABLES
    if args.tables:
        names = set(args.tables.split(','))
        selected = [t for t in TABLES if t['name'] in names]

    conflicts_path = os.path.join(REPORTS_DIR, 'conflicts_report.csv')
    insert_path = os.path.join(REPORTS_DIR, 'insert_report.csv')

    with app.app_context(), \
            open(conflicts_path, 'w', encoding='utf-8', newline='') as cf, \
            open(insert_path, 'w', encoding='utf-8', newline='') as ifd:

        # expansion 모델 로드 트리거
        try:
            from models import expansion  # noqa
        except ImportError:
            pass

        conflicts_writer = csv.writer(cf)
        conflicts_writer.writerow(['table', 'sqlite_id', 'existing_id_or_blank', 'reason_code', 'detail'])

        insert_writer = csv.writer(ifd)
        insert_writer.writerow(['table', 'sqlite_id', 'supabase_id', 'note'])

        totals = []
        for entry in selected:
            print(f'\n=== {entry["name"]} ===')
            ins, skp, drp = process_table(entry, user_map, id_mapping,
                                          args.dry_run, args.limit, args.null_conflict,
                                          conflicts_writer, insert_writer)
            totals.append((entry['name'], ins, skp, drp))
            print(f'  inserted={ins}  skipped={skp}  dropped={drp}')

    print('\n=== 요약 ===')
    print(f'{"table":<25} {"insert":>7} {"skip":>7} {"drop":>7}')
    for name, ins, skp, drp in totals:
        print(f'{name:<25} {ins:>7} {skp:>7} {drp:>7}')
    print(f'\nconflicts_report: {conflicts_path}')
    print(f'insert_report:    {insert_path}')
    print(f'id_mapping:       {os.path.join(MANIFESTS_DIR, "id_mapping.json")}')
    if args.dry_run:
        print('\n** DRY RUN — DB에 변경 없음 **')
    return 0


if __name__ == '__main__':
    sys.exit(main())
