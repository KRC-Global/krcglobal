"""
NUGUNA Global - Flask Configuration
누구나글로벌 사업관리시스템
"""
import os
from datetime import timedelta

# Base directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration"""

    @staticmethod
    def init_app(app):
        pass

    # Secret key for session management
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'gbms-secret-key-change-in-production'
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'sqlite:///{os.path.join(BASE_DIR, "database", "gbms.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # SQLite optimization for 100 concurrent users
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'connect_args': {
            'check_same_thread': False,
            'timeout': 30
        }
    }
    
    # JWT configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'gbms-jwt-secret-change-in-production'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)  # Token expires after 8 hours (work day)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    
    # Upload configuration
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'hwp', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'zip'}
    
    # Pagination defaults
    ITEMS_PER_PAGE = 20

    # CORS settings (for internal network)
    CORS_ORIGINS = ['*']  # Allow all origins in internal network

    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # Token valid for session duration
    WTF_CSRF_SSL_STRICT = False  # Set to True when using HTTPS


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True  # Log SQL queries


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_ECHO = False

    # 프로덕션 환경에서는 환경 변수 필수
    @staticmethod
    def init_app(app):
        Config.init_app(app)

        # 환경 변수 검증 (프로덕션 배포 시 필수)
        import os
        if not os.environ.get('SECRET_KEY'):
            raise ValueError(
                "프로덕션 환경에서는 SECRET_KEY 환경 변수가 필수입니다.\n"
                "설정 방법: setx SECRET_KEY \"랜덤생성된32자이상의키\""
            )
        if not os.environ.get('JWT_SECRET_KEY'):
            raise ValueError(
                "프로덕션 환경에서는 JWT_SECRET_KEY 환경 변수가 필수입니다.\n"
                "설정 방법: setx JWT_SECRET_KEY \"랜덤생성된32자이상의키\""
            )

    # 환경 변수에서 키 로드 (프로덕션 필수)
    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
