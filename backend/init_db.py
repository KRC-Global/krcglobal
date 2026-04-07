"""
NUGUNA Global - Database Initialization Script
누구나글로벌 사업관리시스템 - 초기 데이터 생성

Run with: python init_db.py
"""
import os
import sys
from datetime import datetime, date

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, User, Project, Budget, Office, SystemConfig


def init_database():
    """Initialize database with tables and sample data"""
    
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Enable WAL mode for SQLite
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text('PRAGMA journal_mode=WAL'))
                conn.execute(text('PRAGMA synchronous=NORMAL'))
                conn.execute(text('PRAGMA cache_size=-64000'))
                conn.commit()
        
        print("✓ 데이터베이스 테이블 생성 완료")

        print("\n🎉 데이터베이스 초기화 완료!")
        print("ℹ Google 로그인 후 관리자를 지정하세요.")


if __name__ == '__main__':
    init_database()
