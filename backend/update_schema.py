"""
260330 DB 스키마 업데이트 스크립트
backend/ 폴더에서 실행: python ../migration/260330/update_schema.py
또는 이 파일을 backend/ 에 복사 후 실행: python update_schema.py
"""
import sqlite3
import os

# DB 경로 자동 탐색
db_path = None
for candidate in [
    'database/gbms.db',
    'backend/database/gbms.db',
    os.path.join(os.path.dirname(__file__), '..', '..', 'backend', 'database', 'gbms.db'),
]:
    if os.path.exists(candidate):
        db_path = candidate
        break

if not db_path:
    print("ERROR: database/gbms.db 파일을 찾을 수 없습니다.")
    print("backend/ 폴더에서 실행해주세요.")
    exit(1)

print(f"DB: {os.path.abspath(db_path)}")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# 1. project_lifecycles 테이블 생성
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_lifecycles'")
if c.fetchone():
    print("[OK] project_lifecycles 테이블 이미 존재")
else:
    c.execute('''CREATE TABLE project_lifecycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consulting_project_id INTEGER NOT NULL UNIQUE,
        kickoff_date VARCHAR(20),
        kickoff_completed BOOLEAN DEFAULT 0,
        design_date VARCHAR(20),
        design_completed BOOLEAN DEFAULT 0,
        construction_date VARCHAR(20),
        construction_completed BOOLEAN DEFAULT 0,
        completion_date VARCHAR(20),
        completion_completed BOOLEAN DEFAULT 0,
        eoi_date VARCHAR(20),
        eoi_completed BOOLEAN DEFAULT 0,
        eoi_progress BOOLEAN DEFAULT 0,
        shortlist_date VARCHAR(20),
        shortlist_completed BOOLEAN DEFAULT 0,
        shortlist_progress BOOLEAN DEFAULT 0,
        proposal_date VARCHAR(20),
        proposal_completed BOOLEAN DEFAULT 0,
        proposal_progress BOOLEAN DEFAULT 0,
        contract_date VARCHAR(20),
        contract_completed BOOLEAN DEFAULT 0,
        contract_progress BOOLEAN DEFAULT 0,
        kickoff_progress BOOLEAN DEFAULT 0,
        design_progress BOOLEAN DEFAULT 0,
        construction_progress BOOLEAN DEFAULT 0,
        completion_progress BOOLEAN DEFAULT 0,
        created_at DATETIME,
        updated_at DATETIME,
        FOREIGN KEY (consulting_project_id) REFERENCES consulting_projects(id)
    )''')
    print("[추가] project_lifecycles 테이블 생성 완료")

# 2. consulting_projects에 체크박스 컬럼 추가
existing = {r[1] for r in c.execute('PRAGMA table_info(consulting_projects)').fetchall()}
new_cols = [
    ('type_feasibility', 'BOOLEAN DEFAULT 0'),
    ('type_masterplan', 'BOOLEAN DEFAULT 0'),
    ('type_basic_design', 'BOOLEAN DEFAULT 0'),
    ('type_detailed_design', 'BOOLEAN DEFAULT 0'),
    ('type_construction', 'BOOLEAN DEFAULT 0'),
    ('type_pmc', 'BOOLEAN DEFAULT 0'),
    ('project_type_etc', 'VARCHAR(200)'),
]
for name, typ in new_cols:
    if name in existing:
        print(f"[OK] {name} 컬럼 이미 존재")
    else:
        c.execute(f'ALTER TABLE consulting_projects ADD COLUMN {name} {typ}')
        print(f"[추가] {name} 컬럼 추가 완료")

conn.commit()
conn.close()
print("\nDB 스키마 업데이트 완료!")
