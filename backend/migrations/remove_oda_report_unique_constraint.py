"""
ODA 보고서 UniqueConstraint 제거 마이그레이션
- 동일 (oda_project_id, report_type)에 여러 파일을 등록할 수 있도록 변경
- SQLite는 ALTER TABLE DROP CONSTRAINT 미지원 → 테이블 재생성 방식
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
import sqlalchemy as sa


def migrate():
    with app.app_context():
        with db.engine.connect() as conn:
            # 1. 현재 테이블 존재 확인
            result = conn.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='oda_reports'"
            ))
            if not result.fetchone():
                print("oda_reports 테이블이 없습니다. 마이그레이션 불필요.")
                return

            # 2. UniqueConstraint 존재 확인
            result = conn.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='oda_reports'"))
            create_sql = result.fetchone()[0]
            if 'uq_oda_report_project_type' not in create_sql and 'UNIQUE' not in create_sql.upper().split('CONSTRAINT')[0] if 'CONSTRAINT' in create_sql else 'uq_oda_report_project_type' not in create_sql:
                print("UniqueConstraint가 이미 제거되어 있습니다. 마이그레이션 불필요.")
                return

            print("UniqueConstraint 제거 마이그레이션 시작...")
            print(f"현재 DDL: {create_sql[:200]}...")

            # 3. 새 테이블 생성 (UniqueConstraint 없이, Index만 유지)
            conn.execute(sa.text("""
                CREATE TABLE oda_reports_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    oda_project_id INTEGER NOT NULL,
                    report_type VARCHAR(50) NOT NULL,
                    file_name VARCHAR(255) NOT NULL,
                    file_path VARCHAR(500) NOT NULL,
                    file_size INTEGER,
                    file_type VARCHAR(20),
                    description TEXT,
                    upload_date DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    created_by INTEGER,
                    FOREIGN KEY (oda_project_id) REFERENCES oda_projects(id),
                    FOREIGN KEY (created_by) REFERENCES users(id)
                )
            """))

            # 4. 데이터 복사
            conn.execute(sa.text("""
                INSERT INTO oda_reports_new
                SELECT id, oda_project_id, report_type, file_name, file_path,
                       file_size, file_type, description, upload_date,
                       created_at, updated_at, created_by
                FROM oda_reports
            """))

            # 5. 기존 테이블 삭제 및 이름 변경
            conn.execute(sa.text("DROP TABLE oda_reports"))
            conn.execute(sa.text("ALTER TABLE oda_reports_new RENAME TO oda_reports"))

            # 6. 인덱스 재생성 (UniqueConstraint 없이)
            conn.execute(sa.text(
                "CREATE INDEX idx_oda_report_project_type ON oda_reports(oda_project_id, report_type)"
            ))

            conn.commit()
            print("마이그레이션 완료: UniqueConstraint 제거됨")

            # 검증
            result = conn.execute(sa.text("SELECT COUNT(*) FROM oda_reports"))
            count = result.fetchone()[0]
            print(f"데이터 보존 확인: {count}건")


if __name__ == '__main__':
    migrate()
