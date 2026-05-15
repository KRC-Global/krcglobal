"""Stage 2: 내부망 SQLite → JSONL 추출 (read-only).

외부망 모델 컬럼(화이트리스트) 과 SQLite 컬럼의 교집합만 추출.
SQLite에만 있고 외부망 모델에 없는 컬럼(예: consulting_projects의 pds_*)은 자동 제외.

사용법:
    python backend/migrations/data_import/10_export_sqlite.py \
      --sqlite _migration_src/gbms.db

산출물: exports/<table>.jsonl + exports/users.jsonl + reports/export_summary.md
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, date
from decimal import Decimal

from _bootstrap import app, db, EXPORTS_DIR, REPORTS_DIR, MIGRATION_SRC_DIR  # noqa
from _tables import TABLES  # noqa


def model_columns(table_name):
    """외부망 SQLAlchemy 모델에서 컬럼명 set 추출 (table_name 일치)."""
    for model in db.Model.__subclasses__():
        if getattr(model, '__tablename__', None) == table_name:
            return {c.name for c in model.__table__.columns}
    # 일부 모델은 __subclasses__ 1단계로 안 잡힐 수 있어서 metadata 도 시도
    table = db.metadata.tables.get(table_name)
    if table is not None:
        return {c.name for c in table.columns}
    return None


def sqlite_columns(conn, table):
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.OperationalError:
        return None
    return [r[1] for r in rows] if rows else None


def json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, bytes):
        return o.decode('utf-8', errors='replace')
    raise TypeError(f'unserializable: {type(o).__name__}')


def coerce(value):
    """sqlite row 값을 jsonl 안전한 타입으로 변환."""
    if value is None:
        return None
    if isinstance(value, (int, float, bool, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)


def export_table(conn, entry, summary):
    name = entry['name']
    sl_cols = sqlite_columns(conn, name)
    if sl_cols is None:
        summary.append((name, 0, 0, 0, '내부망에 테이블 없음'))
        return

    model_cols = model_columns(name)
    if model_cols is None:
        summary.append((name, 0, 0, 0, '외부망 모델 없음 — 스킵'))
        return

    cols = [c for c in sl_cols if c in model_cols]
    dropped = [c for c in sl_cols if c not in model_cols]
    if not cols:
        summary.append((name, 0, 0, len(dropped), '공통 컬럼 0 — 스킵'))
        return

    where = ''
    params = ()
    if entry.get('filters'):
        where = f' WHERE {entry["filters"]}'

    quoted = ', '.join(f'"{c}"' for c in cols)
    rows_total = conn.execute(f'SELECT COUNT(*) FROM "{name}"{where}', params).fetchone()[0]

    out_path = os.path.join(EXPORTS_DIR, f'{name}.jsonl')
    written = 0
    with open(out_path, 'w', encoding='utf-8') as f:
        cur = conn.execute(f'SELECT {quoted} FROM "{name}"{where}', params)
        for row in cur:
            record = {cols[i]: coerce(row[i]) for i in range(len(cols))}
            f.write(json.dumps(record, ensure_ascii=False, default=json_default))
            f.write('\n')
            written += 1

    note = f'필터: {entry["filters"]}' if entry.get('filters') else ''
    summary.append((name, rows_total, written, len(dropped), note))


def export_users(conn):
    """users.jsonl 별도 추출 — 매핑용. id, user_id, name, employee_number 만."""
    sl_cols = sqlite_columns(conn, 'users')
    if not sl_cols:
        return 0
    needed = [c for c in ('id', 'user_id', 'name', 'employee_number', 'email', 'department') if c in sl_cols]
    quoted = ', '.join(f'"{c}"' for c in needed)
    out_path = os.path.join(EXPORTS_DIR, 'users.jsonl')
    n = 0
    with open(out_path, 'w', encoding='utf-8') as f:
        cur = conn.execute(f'SELECT {quoted} FROM "users"')
        for row in cur:
            rec = {needed[i]: coerce(row[i]) for i in range(len(needed))}
            f.write(json.dumps(rec, ensure_ascii=False, default=json_default))
            f.write('\n')
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sqlite', default=os.path.join(MIGRATION_SRC_DIR, 'gbms.db'))
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        print(f'ERROR: SQLite 파일이 없습니다: {args.sqlite}', file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.sqlite)
    summary = []

    with app.app_context():
        # 모든 모델이 로딩되도록 expansion 모델 명시적 import
        try:
            from models import expansion  # noqa
        except ImportError:
            pass

        user_count = export_users(conn)
        for entry in TABLES:
            export_table(conn, entry, summary)

    # 리포트 출력
    lines = [
        '# 내부망 SQLite Export 요약',
        '',
        f'- SQLite 경로: `{args.sqlite}`',
        f'- 출력 디렉토리: `{EXPORTS_DIR}`',
        f'- users.jsonl: {user_count} 행',
        '',
        '| 테이블 | 원본행수 | 추출행수 | 제외컬럼수 | 비고 |',
        '|--------|----------|----------|------------|------|',
    ]
    for name, total, written, dropped, note in summary:
        lines.append(f'| {name} | {total} | {written} | {dropped} | {note} |')

    report_path = os.path.join(REPORTS_DIR, 'export_summary.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f'\nExport 완료. 리포트: {report_path}')
    print(f'users.jsonl: {user_count} 행')
    for name, total, written, dropped, note in summary:
        marker = '  ' if total == written else ' *'
        print(f'{marker} {name:<25} {written:>6} / {total:>6}  drop={dropped}  {note}')

    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
