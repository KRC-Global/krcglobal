"""
NUGUNA Global - Flask Configuration
누구나글로벌 사업관리시스템
"""
import os
from datetime import timedelta

# Base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Supabase PostgreSQL (Transaction Pooler - 포트 6543)
# Session 모드(5432)는 동시 연결 수 제한 엄격 → Transaction 모드(6543) 사용
DEFAULT_DATABASE_URL = 'postgresql://postgres.zzypdvwdwgwocczpaaiu:KrcGlobal2026!DB@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres'


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

    # PostgreSQL pool settings for Supabase Transaction Pooler (포트 6543)
    # Transaction 모드: 연결을 트랜잭션 단위로 공유 → 동시 클라이언트 수 제한 없음
    # statement_timeout 등 세션 옵션은 Transaction 모드와 비호환 → 제거
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': False,
        'pool_recycle': 300,         # 5분 (Transaction 모드 권장)
        'pool_size': 5,              # Transaction 모드는 소수 연결로 충분
        'max_overflow': 10,
        'pool_timeout': 10,
        'connect_args': {
            'connect_timeout': 5,
        }
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

    # ── 항공권검색 데이터 프로바이더 ──
    # FLIGHT_PROVIDER 로 전환 가능: 'travelpayouts' (기본) | 'amadeus'
    # Amadeus Self-Service 는 2026-07-17 단종 예정 → Travelpayouts 가 기본값.
    FLIGHT_PROVIDER = os.environ.get('FLIGHT_PROVIDER', 'travelpayouts').strip().lower()

    # Travelpayouts (Aviasales) Data API
    # https://www.travelpayouts.com/developers/api  (어필리에이트 가입 → 토큰 발급)
    TRAVELPAYOUTS_TOKEN = os.environ.get('TRAVELPAYOUTS_TOKEN', '')
    TRAVELPAYOUTS_MARKER = os.environ.get('TRAVELPAYOUTS_MARKER', '')  # 어필리에이트 마커(선택)
    TRAVELPAYOUTS_BASE_URL = os.environ.get(
        'TRAVELPAYOUTS_BASE_URL',
        'https://api.travelpayouts.com'
    )
    TRAVELPAYOUTS_AUTOCOMPLETE_URL = os.environ.get(
        'TRAVELPAYOUTS_AUTOCOMPLETE_URL',
        'https://autocomplete.travelpayouts.com'
    )

    # Amadeus Self-Service (백업용 / 폐기 예정)
    AMADEUS_CLIENT_ID = os.environ.get('AMADEUS_CLIENT_ID', '')
    AMADEUS_CLIENT_SECRET = os.environ.get('AMADEUS_CLIENT_SECRET', '')
    AMADEUS_BASE_URL = os.environ.get(
        'AMADEUS_BASE_URL',
        'https://test.api.amadeus.com'
    )
    FLIGHT_DEFAULT_CURRENCY = os.environ.get('FLIGHT_DEFAULT_CURRENCY', 'KRW').upper()


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
