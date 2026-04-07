"""
Migration: lifecycle_refactor
- proposals 테이블에 price_password 컬럼 추가
- project_lifecycle 테이블에서 shortlist 관련 컬럼 제거 (SQLite 호환)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
import sqlalchemy as sa
from sqlalchemy import text, inspect

def run_migration():
    with app.app_context():
        with db.engine.connect() as conn:
            # 1. proposals 테이블에 price_password 컬럼 추가
            try:
                conn.execute(text('ALTER TABLE proposals ADD COLUMN price_password TEXT'))
                conn.commit()
                print("✅ proposals.price_password 컬럼 추가 완료")
            except Exception as e:
                print(f"ℹ️  proposals.price_password 이미 존재하거나 오류: {e}")

            # 2. project_lifecycle 테이블에서 shortlist 컬럼 제거
            # SQLite는 DROP COLUMN을 3.35+ 에서만 지원하므로 테이블 재생성 방식 사용
            try:
                inspector = inspect(db.engine)
                if 'project_lifecycle' in inspector.get_table_names():
                    cols = [c['name'] for c in inspector.get_columns('project_lifecycle')]
                    shortlist_cols = [c for c in cols if 'shortlist' in c]

                    if shortlist_cols:
                        print(f"ℹ️  제거할 shortlist 컬럼: {shortlist_cols}")
                        # 기존 컬럼에서 shortlist 제외한 컬럼 목록
                        keep_cols = [c for c in cols if 'shortlist' not in c]
                        keep_cols_str = ', '.join(keep_cols)

                        conn.execute(text(f'''
                            CREATE TABLE project_lifecycle_new AS
                            SELECT {keep_cols_str}
                            FROM project_lifecycle
                        '''))
                        conn.execute(text('DROP TABLE project_lifecycle'))
                        conn.execute(text('ALTER TABLE project_lifecycle_new RENAME TO project_lifecycle'))
                        conn.commit()
                        print("✅ project_lifecycle shortlist 컬럼 제거 완료")
                    else:
                        print("ℹ️  shortlist 컬럼 없음 - 스킵")
                else:
                    print("ℹ️  project_lifecycle 테이블 없음 - 스킵")
            except Exception as e:
                print(f"⚠️  project_lifecycle 마이그레이션 오류: {e}")

        print("\n✅ 마이그레이션 완료")

if __name__ == '__main__':
    run_migration()
