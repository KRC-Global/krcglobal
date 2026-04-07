"""
NUGUNA Global - Flask Configuration
누구나글로벌 사업관리시스템
"""
import os
from datetime import timedelta

# Base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Supabase PostgreSQL (Transaction Pooler)
DEFAULT_DATABASE_URL = 'postgresql://postgres.zzypdvwdwgwocczpaaiu:gksshdrhdshddjchs1!@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres'


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
