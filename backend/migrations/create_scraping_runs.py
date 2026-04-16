"""
scraping_runs 테이블 생성 마이그레이션
- 디스코드 봇의 발주공고 수집 실행 이력을 저장
- SQLAlchemy Inspector로 DB-agnostic 확인 (SQLite/Postgres 모두 지원)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import ScrapingRun
from sqlalchemy import inspect


def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('scraping_runs'):
            print("scraping_runs 테이블이 이미 존재합니다. 마이그레이션 불필요.")
            return

        ScrapingRun.__table__.create(bind=db.engine)
        print("scraping_runs 테이블 생성 완료.")


if __name__ == '__main__':
    migrate()
