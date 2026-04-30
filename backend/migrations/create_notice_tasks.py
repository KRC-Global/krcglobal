"""
notice_tasks 테이블 생성 마이그레이션
- ddkkbot 워커가 가져갈 발주공고 작업 큐를 보관.
- SQLAlchemy Inspector 로 DB-agnostic 확인 (SQLite/Postgres 모두 지원).
- 멱등: 이미 존재하면 skip.

로컬 실행:
    cd backend && python migrations/create_notice_tasks.py

운영(Vercel)에서는 backend/app.py 의 _run_migrations() 가
db.create_all() 직후 자동으로 모델을 만들어 주므로 별도 실행 불필요.
이 스크립트는 수동 점검 / 마이그레이션 단독 실행용.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import NoticeTask
from sqlalchemy import inspect


def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('notice_tasks'):
            print("notice_tasks 테이블이 이미 존재합니다. 마이그레이션 불필요.")
            return

        NoticeTask.__table__.create(bind=db.engine)
        print("notice_tasks 테이블 생성 완료.")


if __name__ == '__main__':
    migrate()
