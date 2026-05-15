"""Stage 1: 내부망 SQLite vs 외부망 Supabase 컬럼 차이 보고 (read-only).

사용법:
    python backend/migrations/data_import/01_check_schema.py \
      --sqlite _migration_src/gbms.db

산출물: reports/schema_diff.md
"""
import argparse
import os
import sqlite3
import sys

from _bootstrap import app, db, REPORTS_DIR, MIGRATION_SRC_DIR  # noqa
from _tables import TABLES  # noqa
from sqlalchemy import text


def sqlite_columns(conn, table):
    """SQLite PRAGMA table_info → {col_name: (type, notnull, default, pk)}"""
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.OperationalError:
        return None
    if not rows:
        return None
    cols = {}
    for cid, name, ctype, notnull, dflt, pk in rows:
        cols[name] = {
            'type': (ctype or '').upper(),
            'notnull': bool(notnull),
            'default': dflt,
            'pk': bool(pk),
        }
    return cols


def pg_columns(table):
    """information_schema.columns → {col_name: meta}"""
    sql = text("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t
    """)
    rows = db.session.execute(sql, {'t': table}).fetchall()
    if not rows:
        return None
    cols = {}
    for name, dtype, is_nullable, dflt in rows:
        cols[name] = {
            'type': (dtype or '').upper(),
            'notnull': is_nullable == 'NO',
            'default': dflt,
            'pk': False,  # PK는 별도 쿼리 필요. 본 스크립트 목적상 생략
        }
    return cols


def diff_table(name, sl, pg):
    lines = []
    lines.append(f'### `{name}`')
    if sl is None and pg is None:
        lines.append('- ⚠️  내부망·외부망 모두 테이블 없음')
        return lines
    if sl is None:
        lines.append('- ⚠️  내부망 SQLite에 테이블 없음 (마이그레이션 대상 아님)')
        return lines
    if pg is None:
        lines.append('- ❌ **외부망 Supabase에 테이블 없음** — 신규 생성 필요')
        lines.append(f'  - 내부망 컬럼 수: {len(sl)}')
        return lines

    sl_names = set(sl.keys())
    pg_names = set(pg.keys())
    only_sl = sorted(sl_names - pg_names)
    only_pg = sorted(pg_names - sl_names)
    both = sorted(sl_names & pg_names)

    if only_sl:
        lines.append(f'- 내부망에만 있음 (export 시 제외): {", ".join(f"`{c}`" for c in only_sl)}')
    if only_pg:
        lines.append(f'- 외부망에만 있음 (default/NULL로 INSERT): {", ".join(f"`{c}`" for c in only_pg)}')
    if not only_sl and not only_pg:
        lines.append(f'- ✅ 컬럼 집합 일치 ({len(both)}개)')
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sqlite', default=os.path.join(MIGRATION_SRC_DIR, 'gbms.db'),
                        help='내부망 SQLite 파일 경로')
    parser.add_argument('--out', default=os.path.join(REPORTS_DIR, 'schema_diff.md'))
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        print(f'ERROR: SQLite 파일이 없습니다: {args.sqlite}', file=sys.stderr)
        print('내부망에서 USB로 _migration_src/gbms.db 를 반입해주세요.', file=sys.stderr)
        return 2

    sqlite_conn = sqlite3.connect(args.sqlite)

    out_lines = [
        '# 스키마 비교 보고서',
        '',
        f'- 내부망 SQLite: `{args.sqlite}`',
        f'- 외부망 Supabase: `{app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1]}`',
        '',
        '## 테이블별 차이',
        '',
    ]

    with app.app_context():
        total_missing_table = 0
        total_only_sl = 0
        total_only_pg = 0
        for entry in TABLES:
            name = entry['name']
            sl = sqlite_columns(sqlite_conn, name)
            try:
                pg = pg_columns(name)
            except Exception as e:
                pg = None
                out_lines.append(f'### `{name}`')
                out_lines.append(f'- ERROR Supabase 조회 실패: `{e}`')
                out_lines.append('')
                continue
            if pg is None:
                total_missing_table += 1
            else:
                if sl:
                    only_sl = set(sl.keys()) - set(pg.keys())
                    only_pg = set(pg.keys()) - set(sl.keys())
                    total_only_sl += len(only_sl)
                    total_only_pg += len(only_pg)
            out_lines.extend(diff_table(name, sl, pg))
            out_lines.append('')

    out_lines.insert(4, f'- 외부망 결측 테이블: **{total_missing_table}**')
    out_lines.insert(5, f'- 내부망 단독 컬럼 (export 제외): **{total_only_sl}**')
    out_lines.insert(6, f'- 외부망 단독 컬럼 (NULL/default): **{total_only_pg}**')

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines))

    print(f'Schema diff: {args.out}')
    print(f'  외부망 결측 테이블: {total_missing_table}')
    print(f'  내부망 단독 컬럼 (export 제외): {total_only_sl}')
    print(f'  외부망 단독 컬럼 (default/NULL): {total_only_pg}')

    sqlite_conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
