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


def _force_psycopg2(url: str) -> str:
    """DB URL 의 드라이버를 psycopg2 로 명시한다.

    SQLAlchemy 2.1 부터 'postgresql://' 의 기본 DBAPI 가 psycopg2 에서
    psycopg(v3) 로 바뀌었다. 설치된 드라이버는 psycopg2-binary 뿐이라
    기본값에 의존하면 'ModuleNotFoundError: No module named psycopg' 로
    앱이 부팅 단계에서 죽는다(2026-10-08 운영 장애).

    requirements 에 SQLAlchemy 를 핀해두었지만, 환경변수 DATABASE_URL 이
    드라이버 없는 스킴으로 들어오는 경우까지 막으려면 여기서도 고정해야 한다.
    이미 드라이버가 지정된 URL('postgresql+psycopg2://' 등)은 건드리지 않는다.
    """
    if url and url.startswith('postgresql://'):
        return 'postgresql+psycopg2://' + url[len('postgresql://'):]
    if url and url.startswith('postgres://'):   # 구형 표기도 함께 정규화
        return 'postgresql+psycopg2://' + url[len('postgres://'):]
    return url


class Config:
    """Base configuration"""

    @staticmethod
    def init_app(app):
        pass

    # Secret key for session management
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'gbms-secret-key-change-in-production'

    # Database configuration (Supabase PostgreSQL)
    SQLALCHEMY_DATABASE_URI = _force_psycopg2(
        os.environ.get('DATABASE_URL') or DEFAULT_DATABASE_URL
    )
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

    # ── ddkkbot 작업 큐 / Discord 알림 ──
    # 발주공고 자동 수집 후 신규 공고를 Discord 채널에 알리고, ddkkbot 워커가
    # /api/notices/tasks 에서 작업을 가져가 처리한 뒤 결과를 다시 PUT 한다.
    # 환경변수 미설정 시 알림은 no-op (NullNotifier) — 큐잉/API 자체는 그대로 동작.
    DISCORD_NOTICE_WEBHOOK_URL = os.environ.get('DISCORD_NOTICE_WEBHOOK_URL', '').strip()
    # 워커(ddkkbot)용 인증 시크릿 — 미설정 시 admin JWT 만 허용.
    WORKER_SECRET = os.environ.get('WORKER_SECRET', '').strip()
    # 워커가 비정상 종료해 claimed 에 멈춘 작업을 pending 폴링 시 자동 회수한다.
    NOTICE_TASK_CLAIM_TIMEOUT_MINUTES = os.environ.get(
        'NOTICE_TASK_CLAIM_TIMEOUT_MINUTES', '30'
    )
    # Discord 메시지에 시스템 상세 페이지 링크를 만들 때 쓰는 베이스 URL.
    SITE_BASE_URL = os.environ.get('SITE_BASE_URL', '').rstrip('/')

    # ── Mac 카카오톡 릴레이 ──
    # true 일 때 번역 완료 → 서버 인포그래픽 생성 직후 kakao_deliveries 에 등록한다.
    # 실제 카카오톡 조작은 항상 켜진 Mac의 scripts/kakao_relay.py 가 담당한다.
    KAKAO_RELAY_ENABLED = os.environ.get(
        'KAKAO_RELAY_ENABLED', 'true'
    ).strip().lower() in ('1', 'true', 'yes', 'on')


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
