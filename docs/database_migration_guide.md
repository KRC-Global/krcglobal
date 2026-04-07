# 데이터베이스 마이그레이션 가이드

## 📋 목차
1. [현재 시스템의 문제점](#현재-시스템의-문제점)
2. [마이그레이션 전략](#마이그레이션-전략)
3. [Flask-Migrate 설정 (권장)](#flask-migrate-설정-권장)
4. [수동 마이그레이션](#수동-마이그레이션)
5. [실전 시나리오](#실전-시나리오)

---

## 현재 시스템의 문제점

### ❌ 현재 방식: `init_db.py` (위험)
```python
db.create_all()  # 신규 테이블만 생성, 기존 테이블은 무시
```

**문제점:**
- ✅ 신규 테이블 추가: 가능
- ❌ 기존 테이블 수정: 불가능 (컬럼 추가/삭제/변경)
- ❌ 데이터 유지: 보장 안됨
- ❌ 롤백: 불가능

**결과:** DB 구조 변경 시 수동으로 SQL 실행하거나 전체 DB 재생성 (데이터 손실!)

---

## 마이그레이션 전략

### 방법 비교

| 방법 | 장점 | 단점 | 추천 |
|------|------|------|------|
| **Flask-Migrate** | 자동 스크립트 생성, 버전 관리, 롤백 가능 | 초기 설정 필요 | ⭐⭐⭐⭐⭐ |
| **수동 SQL** | 즉시 실행 가능, 간단한 변경 | 오류 위험, 버전 관리 어려움 | ⭐⭐⭐ |
| **재생성** | 구조 완전 변경 가능 | 데이터 전부 삭제됨 | ❌ (운영 환경) |

---

## Flask-Migrate 설정 (권장)

### 1. 설치

```bash
# requirements.txt에 추가
Flask-Migrate==4.0.5

# 설치
pip install Flask-Migrate
```

### 2. app.py 수정

```python
# backend/app.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate  # 추가

app = Flask(__name__)
db = SQLAlchemy(app)
migrate = Migrate(app, db)  # 추가
```

### 3. 초기화

```bash
cd backend

# 마이그레이션 폴더 생성
flask db init

# 현재 DB 구조 스냅샷
flask db migrate -m "초기 마이그레이션"

# 적용 (이미 테이블이 있으면 스킵됨)
flask db upgrade
```

### 4. 구조 변경 시 사용법

#### 시나리오: `proposals` 테이블에 `priority` 컬럼 추가

```python
# 1. models/__init__.py 수정
class Proposal(db.Model):
    # ... 기존 컬럼들 ...
    priority = db.Column(db.String(20), default='보통')  # 새 컬럼 추가
```

```bash
# 2. 마이그레이션 스크립트 자동 생성
flask db migrate -m "proposals 테이블에 priority 컬럼 추가"

# 3. 생성된 스크립트 확인
# migrations/versions/xxxx_proposals_테이블에_priority_컬럼_추가.py

# 4. DB에 적용
flask db upgrade

# 5. 문제 발생 시 롤백
flask db downgrade
```

### 5. 생성된 마이그레이션 스크립트 예시

```python
# migrations/versions/xxxx_add_priority.py
"""proposals 테이블에 priority 컬럼 추가

Revision ID: abc123
Revises: def456
Create Date: 2025-01-28 14:00:00
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 업그레이드 시 실행
    op.add_column('proposals',
        sa.Column('priority', sa.String(20), server_default='보통')
    )

def downgrade():
    # 롤백 시 실행
    op.drop_column('proposals', 'priority')
```

---

## 수동 마이그레이션

Flask-Migrate 없이 직접 SQL 실행 (간단한 변경에만 권장)

### 준비: 백업 스크립트

```bash
# backup_db.sh
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p backend/database/backups

cp backend/database/gbms.db backend/database/backups/gbms_${DATE}.db
cp backend/database/gbms.db-wal backend/database/backups/gbms_${DATE}.db-wal
cp backend/database/gbms.db-shm backend/database/backups/gbms_${DATE}.db-shm

echo "백업 완료: backend/database/backups/gbms_${DATE}.db"
```

### 수동 마이그레이션 실행

```python
# backend/manual_migration.py
import sqlite3

DB_PATH = 'database/gbms.db'

def add_column():
    """컬럼 추가 (SQLite 지원)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # proposals 테이블에 priority 컬럼 추가
        cursor.execute("""
            ALTER TABLE proposals
            ADD COLUMN priority VARCHAR(20) DEFAULT '보통'
        """)

        conn.commit()
        print("✅ 컬럼 추가 완료")

    except sqlite3.Error as e:
        print(f"❌ 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    # ⚠️ 반드시 백업 후 실행!
    add_column()
```

### SQLite 제약사항

SQLite는 다음 작업을 **직접 지원하지 않음**:
- ❌ 컬럼 삭제 (DROP COLUMN)
- ❌ 컬럼 이름 변경
- ❌ 컬럼 타입 변경
- ❌ 제약조건 수정

**해결책:** 임시 테이블로 데이터 이전

```sql
-- 1. 새 구조로 임시 테이블 생성
CREATE TABLE proposals_new (
    id INTEGER PRIMARY KEY,
    title VARCHAR(500),
    priority VARCHAR(20) DEFAULT '보통',  -- 새 컬럼
    -- budget 컬럼 삭제됨
    ...
);

-- 2. 데이터 복사
INSERT INTO proposals_new (id, title, ...)
SELECT id, title, ... FROM proposals;

-- 3. 기존 테이블 삭제
DROP TABLE proposals;

-- 4. 이름 변경
ALTER TABLE proposals_new RENAME TO proposals;
```

---

## 실전 시나리오

### 시나리오 1: 컬럼 추가

**요구사항:** `proposals` 테이블에 `submission_status` 컬럼 추가

#### Flask-Migrate 방식 (권장)
```bash
# 1. models/__init__.py 수정
class Proposal(db.Model):
    submission_status = db.Column(db.String(20), default='대기중')

# 2. 마이그레이션
flask db migrate -m "proposals에 submission_status 추가"
flask db upgrade
```

#### 수동 방식
```bash
# 1. 백업
./backup_db.sh

# 2. SQL 실행
sqlite3 backend/database/gbms.db
> ALTER TABLE proposals ADD COLUMN submission_status VARCHAR(20) DEFAULT '대기중';
> .quit
```

---

### 시나리오 2: 컬럼 타입 변경

**요구사항:** `proposals.budget`을 `NUMERIC` → `DECIMAL(15,2)`로 변경

#### Flask-Migrate 방식
```bash
# 1. models/__init__.py 수정
class Proposal(db.Model):
    budget = db.Column(db.Numeric(15, 2))  # 타입 변경

# 2. 마이그레이션 생성
flask db migrate -m "proposals.budget 타입 변경"

# 3. 생성된 스크립트 확인 및 수정 (필요 시)
# migrations/versions/xxxx_....py

# 4. 적용
flask db upgrade
```

#### 수동 방식 (복잡함!)
```python
# manual_migration_example.py 참고
# 임시 테이블 생성 → 데이터 복사 → 교체
```

---

### 시나리오 3: 테이블 추가

**요구사항:** 새로운 `notifications` 테이블 추가

#### Flask-Migrate 방식
```python
# 1. models/__init__.py에 추가
class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

```bash
# 2. 마이그레이션
flask db migrate -m "notifications 테이블 추가"
flask db upgrade
```

#### 수동 방식
```bash
# init_db.py 실행하면 자동으로 생성됨
python backend/init_db.py
# (기존 테이블은 유지, 신규 테이블만 생성)
```

---

### 시나리오 4: 기존 데이터 변환

**요구사항:** 모든 `proposals`의 `result`를 영문 → 한글로 변환

```python
# data_migration.py
import sqlite3

def migrate_proposal_results():
    conn = sqlite3.connect('backend/database/gbms.db')
    cursor = conn.cursor()

    # 매핑 테이블
    mapping = {
        'pending': '심사중',
        'selected': '선정',
        'rejected': '탈락'
    }

    try:
        for eng, kor in mapping.items():
            cursor.execute("""
                UPDATE proposals
                SET result = ?
                WHERE result = ?
            """, (kor, eng))

        conn.commit()
        print(f"✅ {cursor.rowcount}개 레코드 업데이트 완료")

    except sqlite3.Error as e:
        print(f"❌ 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    migrate_proposal_results()
```

---

## 백업 및 복구

### 정기 백업 스크립트

```bash
#!/bin/bash
# backup_daily.sh

BACKUP_DIR="backend/database/backups"
DATE=$(date +%Y%m%d)
DB_PATH="backend/database/gbms.db"

# 7일 이상 된 백업 삭제
find $BACKUP_DIR -name "gbms_*.db" -mtime +7 -delete

# 오늘 백업
if [ ! -f "$BACKUP_DIR/gbms_${DATE}.db" ]; then
    cp $DB_PATH $BACKUP_DIR/gbms_${DATE}.db
    cp ${DB_PATH}-wal $BACKUP_DIR/gbms_${DATE}.db-wal 2>/dev/null
    cp ${DB_PATH}-shm $BACKUP_DIR/gbms_${DATE}.db-shm 2>/dev/null
    echo "✅ 백업 완료: $BACKUP_DIR/gbms_${DATE}.db"
else
    echo "ℹ️  오늘 백업이 이미 존재합니다"
fi
```

### 복구 방법

```bash
# 1. 서버 중지
pkill -f "python.*app.py"

# 2. 백업에서 복구
cp backend/database/backups/gbms_20250128.db backend/database/gbms.db
cp backend/database/backups/gbms_20250128.db-wal backend/database/gbms.db-wal
cp backend/database/backups/gbms_20250128.db-shm backend/database/gbms.db-shm

# 3. 서버 재시작
./start.sh
```

---

## 체크리스트

### 🔧 마이그레이션 전
- [ ] 데이터베이스 백업 완료
- [ ] uploads/ 폴더 백업 완료
- [ ] 변경 내용 문서화 (어떤 테이블, 어떤 컬럼)
- [ ] 개발 환경에서 테스트 완료
- [ ] 사용자에게 작업 시간 공지 (서비스 중단 필요 시)

### 🚀 마이그레이션 중
- [ ] 서버 중지 (필요 시)
- [ ] 마이그레이션 스크립트 실행
- [ ] 로그 확인 (오류 없는지)
- [ ] 테이블 구조 확인 (`PRAGMA table_info(테이블명)`)

### ✅ 마이그레이션 후
- [ ] 서버 재시작
- [ ] 주요 기능 동작 확인
- [ ] 데이터 무결성 확인 (건수, 필수값)
- [ ] 백업 파일 보관 (최소 7일)
- [ ] 변경 이력 문서 업데이트

---

## 추천 워크플로우

### 개발 단계
```
1. 로컬 개발 환경에서 모델 변경
2. Flask-Migrate로 마이그레이션 생성
3. 마이그레이션 스크립트 검토 및 수정
4. 로컬 DB에 적용 및 테스트
5. Git 커밋 (마이그레이션 스크립트 포함)
```

### 배포 단계
```
1. 운영 DB 백업
2. uploads/ 폴더 백업
3. 서버 중지 (필요 시)
4. 코드 업데이트 (git pull)
5. flask db upgrade 실행
6. 서버 재시작
7. 동작 확인
8. 문제 발생 시 롤백 (flask db downgrade 또는 백업 복구)
```

---

## 참고 자료

- [Flask-Migrate 공식 문서](https://flask-migrate.readthedocs.io/)
- [SQLite ALTER TABLE 제약사항](https://www.sqlite.org/lang_altertable.html)
- [Alembic 마이그레이션 가이드](https://alembic.sqlalchemy.org/)

---

## 문의

DB 구조 변경 관련 문제 발생 시:
1. 백업 파일 확인
2. 마이그레이션 로그 확인
3. `backend/server.log` 확인
4. 이 문서의 복구 절차 참고
