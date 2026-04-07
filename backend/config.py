"""
NUGUNA Global - Flask Configuration
누구나글로벌 사업관리시스템
"""
import os
from datetime import timedelta

# Base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Supabase PostgreSQL (Transaction Pooler)
DEFAULT_DATABASE_URL = 'postgresql://postgres.zzypdvwdwgwocczpaaiu:KrcGlobal2026!DB@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres'


class Config:
    """Base configuration"""

    @staticmethod
    def init_app(app):
        pass

    # Secret key for session management
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'gbms-secret-key-change-in-production'

    # Database configuration (Supabase PostgreSQL)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or DEFAULT_DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # PostgreSQL pool settings for serverless
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 5,
        'max_overflow': 10,
    }

    # JWT configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'gbms-jwt-secret-change-in-production'

    # Supabase configuration
    SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET') or 'C7SBYCSFxaj25E+StqlcBL4pCI11R5QefkSP/vu3u1VadlOUG+P2YQixNQJfKMFCYpQGDPUwzDxnxHGsuECovw=='
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    # Upload configuration
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'hwp', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'zip'}

    # Cloudflare R2 Storage
    R2_ACCOUNT_ID = '5aa1dd1ae651bd73136aacb2a1c43a48'
    R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID') or 'ae27d9620b401a1aa78218840abfde75'
    R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY') or '94a316548aabb871579e3786364d02d6eb4bd1063179f22bf956c8956deb64f1'
    R2_BUCKET_NAME = 'krcglobal'
    R2_ENDPOINT = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
    R2_MAX_STORAGE_BYTES = 9 * 1024 * 1024 * 1024  # 9GB limit

    # Pagination defaults
    ITEMS_PER_PAGE = 20

    # CORS settings
    CORS_ORIGINS = ['*']


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_ECHO = False


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {}


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
