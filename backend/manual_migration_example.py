"""
수동 마이그레이션 예시 스크립트
Flask-Migrate 없이 SQLite 직접 수정

⚠️ 주의: 반드시 백업 후 실행!

사용 예시:
  python manual_migration_example.py
"""
import os
import sys
import sqlite3
from datetime import datetime

# Database path
DB_PATH = 'database/gbms.db'
BACKUP_DIR = 'database/backups'

def backup_database():
    """데이터베이스 백업"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f'gbms_backup_{timestamp}.db')

    print(f"📦 백업 생성 중: {backup_path}")

    # WAL 파일도 함께 백업
    import shutil
    shutil.copy2(DB_PATH, backup_path)

    if os.path.exists(f'{DB_PATH}-wal'):
        shutil.copy2(f'{DB_PATH}-wal', f'{backup_path}-wal')
    if os.path.exists(f'{DB_PATH}-shm'):
        shutil.copy2(f'{DB_PATH}-shm', f'{backup_path}-shm')

    print(f"✅ 백업 완료: {backup_path}")
    return backup_path

def add_column_example():
    """예시: proposals 테이블에 새 컬럼 추가"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("\n📝 마이그레이션: proposals 테이블에 'status' 컬럼 추가")

        # 1. 컬럼이 이미 존재하는지 확인
        cursor.execute("PRAGMA table_info(proposals)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'status' in columns:
            print("ℹ️  'status' 컬럼이 이미 존재합니다")
            return

        # 2. 컬럼 추가 (SQLite는 ALTER TABLE ADD COLUMN만 지원)
        cursor.execute("""
            ALTER TABLE proposals
            ADD COLUMN status VARCHAR(20) DEFAULT '제출완료'
        """)

        conn.commit()
        print("✅ 컬럼 추가 완료")

    except sqlite3.Error as e:
        print(f"❌ 오류 발생: {e}")
        conn.rollback()
    finally:
        conn.close()

def modify_column_example():
    """
    예시: 컬럼 타입 변경 (SQLite는 직접 변경 불가)

    SQLite 제약사항:
    - ALTER TABLE로 컬럼 타입/제약조건 변경 불가
    - 임시 테이블로 데이터 이전 필요
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("\n📝 마이그레이션: proposals 테이블의 budget 컬럼 타입 변경")
        print("   (이 방법은 데이터가 많을 경우 시간이 걸릴 수 있음)")

        # 1. 임시 테이블 생성 (새로운 구조)
        cursor.execute("""
            CREATE TABLE proposals_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title VARCHAR(500) NOT NULL,
                country VARCHAR(100),
                client VARCHAR(200),
                submission_date DATE,
                budget DECIMAL(15, 2),  -- 변경된 부분 (기존: NUMERIC)
                -- ... 나머지 컬럼들
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 기존 데이터 복사
        cursor.execute("""
            INSERT INTO proposals_new
            SELECT * FROM proposals
        """)

        # 3. 기존 테이블 삭제
        cursor.execute("DROP TABLE proposals")

        # 4. 임시 테이블 이름 변경
        cursor.execute("ALTER TABLE proposals_new RENAME TO proposals")

        conn.commit()
        print("✅ 테이블 구조 변경 완료")

    except sqlite3.Error as e:
        print(f"❌ 오류 발생: {e}")
        conn.rollback()
    finally:
        conn.close()

def check_table_structure():
    """현재 테이블 구조 확인"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\n📊 proposals 테이블 구조:")
    cursor.execute("PRAGMA table_info(proposals)")

    columns = cursor.fetchall()
    print(f"\n{'ID':<5} {'컬럼명':<30} {'타입':<15} {'NULL':<8} {'기본값':<15}")
    print("-" * 80)
    for col in columns:
        col_id, name, type_, notnull, default, pk = col
        null_str = "NOT NULL" if notnull else "NULL"
        default_str = str(default) if default else ""
        print(f"{col_id:<5} {name:<30} {type_:<15} {null_str:<8} {default_str:<15}")

    conn.close()

def main():
    """메인 실행 함수"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 데이터베이스를 찾을 수 없습니다: {DB_PATH}")
        sys.exit(1)

    print("=" * 80)
    print("🗄️  수동 데이터베이스 마이그레이션 도구")
    print("=" * 80)

    # 1. 백업
    backup_path = backup_database()

    # 2. 현재 구조 확인
    check_table_structure()

    # 3. 마이그레이션 실행 선택
    print("\n실행할 마이그레이션을 선택하세요:")
    print("  1. 컬럼 추가 예시 (proposals.status)")
    print("  2. 컬럼 타입 변경 예시 (proposals.budget)")
    print("  0. 취소")

    choice = input("\n선택 (0-2): ").strip()

    if choice == '1':
        add_column_example()
    elif choice == '2':
        print("\n⚠️  경고: 이 작업은 테이블을 재생성합니다.")
        confirm = input("계속하시겠습니까? (yes/no): ").strip().lower()
        if confirm == 'yes':
            modify_column_example()
        else:
            print("❌ 취소되었습니다")
    elif choice == '0':
        print("❌ 취소되었습니다")
    else:
        print("❌ 잘못된 선택입니다")

    # 4. 변경 후 구조 확인
    check_table_structure()

    print(f"\n💾 백업 파일 위치: {backup_path}")
    print("   문제 발생 시 이 파일로 복구 가능합니다")

if __name__ == '__main__':
    main()
