"""
bid_notices 테이블에 아카이브 컬럼 추가
- archived_at: 아카이브 시각 (NULL=활성, 값있음=비활성)
- archive_reason: 아카이브 사유 (deadline_passed / aged_out / source_removed)

기존 일자 경과/마감 공고를 폐기 대신 아카이브로 보존하기 위한 인프라.
ARCHIVE_RETENTION_DAYS 경과 시점에 별도 cleanup 단계에서 hard-delete 된다.

멱등: 컬럼별 존재 여부 확인 후 ALTER. SQLite/Postgres 모두 동작.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import inspect, text


COLUMNS = [
    ('archived_at',    'TIMESTAMP'),
    ('archive_reason', 'VARCHAR(30)'),
]

INDEX_NAME = 'idx_bid_notices_archived_at'


def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        if 'bid_notices' not in inspector.get_table_names():
            print("bid_notices 테이블이 없습니다. init_db.py 먼저 실행 필요.")
            return

        existing = {c['name'] for c in inspector.get_columns('bid_notices')}
        added = []
        for name, sql_type in COLUMNS:
            if name in existing:
                continue
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE bid_notices ADD COLUMN {name} {sql_type}'))
            added.append(name)

        # archived_at 인덱스 — 활성 필터(WHERE archived_at IS NULL) 가속용
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('bid_notices')}
        index_added = False
        if INDEX_NAME not in existing_indexes:
            with db.engine.begin() as conn:
                conn.execute(text(
                    f'CREATE INDEX IF NOT EXISTS {INDEX_NAME} '
                    f'ON bid_notices(archived_at)'
                ))
            index_added = True

        msgs = []
        if added:
            msgs.append(f"컬럼 추가: {', '.join(added)}")
        if index_added:
            msgs.append(f"인덱스 추가: {INDEX_NAME}")
        if msgs:
            print("bid_notices " + " / ".join(msgs))
        else:
            print("이미 적용된 마이그레이션입니다.")


if __name__ == '__main__':
    migrate()
