"""
NUGUNA Global - Flask Application Entry Point
누구나글로벌 사업관리시스템
"""
import os
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
from config import config

# Create Flask app
# static_folder를 프로젝트 루트(이 파일과 동일한 디렉토리)로 설정
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=_PROJECT_ROOT, static_url_path='')

# Load configuration
config_name = os.environ.get('FLASK_ENV') or 'development'
app.config.from_object(config[config_name])

# Enable CORS for internal network
# 개발 환경: 모든 origin 허용 (포트 5500, 8000 등 포함)
# flask-cors가 모든 CORS 헤더를 자동으로 처리합니다
CORS(app, 
     resources={r"/*": {"origins": "*"}},  # 모든 경로에 CORS 적용
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     expose_headers=["Content-Type"],
     max_age=3600)  # preflight 캐시 시간

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'database'), exist_ok=True)

# Initialize database
from models import db
db.init_app(app)

# Enable WAL mode for SQLite (better concurrent access)
def setup_database():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Enable WAL mode for better concurrent write performance
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            try:
                from sqlalchemy import text
                with db.engine.connect() as conn:
                    conn.execute(text('PRAGMA journal_mode=WAL'))
                    conn.execute(text('PRAGMA synchronous=NORMAL'))
                    conn.execute(text('PRAGMA cache_size=-64000'))  # 64MB cache
                    conn.execute(text('PRAGMA busy_timeout=30000'))  # 30s timeout
                    conn.commit()
                    # 마이그레이션: board_posts에 category 컬럼 추가
                    try:
                        conn.execute(text("ALTER TABLE board_posts ADD COLUMN category VARCHAR(100)"))
                        conn.commit()
                        print("board_posts 테이블에 category 컬럼 추가됨")
                    except Exception:
                        pass  # 이미 존재하면 무시
            except Exception as e:
                print(f"SQLite 설정 오류 (무시 가능): {e}")

# 앱 시작 시 데이터베이스 설정
with app.app_context():
    setup_database()


# Register blueprints (API routes)
from routes.auth import auth_bp
from routes.projects import projects_bp
from routes.budgets import budgets_bp
from routes.documents import documents_bp
from routes.dashboard import dashboard_bp
from routes.users import users_bp
from routes.offices import offices_bp
from routes.gis import gis_bp
from routes.consulting import consulting_bp
from routes.oda import oda_bp
from routes.methane import methane_bp
from routes.profitability import profitability_bp
from routes.expansion import expansion_bp
from routes.proposals import proposals_bp
from routes.performance import performance_bp
from routes.oda_reports import oda_reports_bp
from routes.contracts import contracts_bp
from routes.cv import cv_bp
from routes.tor_rfp import tor_rfp_bp
from routes.utilities import utilities_bp
from routes.bidding import bidding_bp
from routes.board import board_bp
from routes.banners import banners_bp

app.register_blueprint(auth_bp, url_prefix='/api/auth')
app.register_blueprint(projects_bp, url_prefix='/api/projects')
app.register_blueprint(budgets_bp, url_prefix='/api/budgets')
app.register_blueprint(documents_bp, url_prefix='/api/documents')
app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
app.register_blueprint(users_bp, url_prefix='/api/users')
app.register_blueprint(offices_bp, url_prefix='/api/offices')
app.register_blueprint(gis_bp, url_prefix='/api/gis')
app.register_blueprint(consulting_bp, url_prefix='/api/consulting')
app.register_blueprint(oda_bp, url_prefix='/api/oda')
app.register_blueprint(methane_bp, url_prefix='/api/methane')
app.register_blueprint(profitability_bp, url_prefix='/api/profitability')
app.register_blueprint(expansion_bp)  # Already has /api/expansion prefix
app.register_blueprint(proposals_bp, url_prefix='/api/proposals')
app.register_blueprint(performance_bp, url_prefix='/api/performance')
app.register_blueprint(oda_reports_bp, url_prefix='/api/oda-reports')
app.register_blueprint(contracts_bp, url_prefix='/api/contracts')
app.register_blueprint(cv_bp, url_prefix='/api/cv')
app.register_blueprint(tor_rfp_bp, url_prefix='/api/tor-rfp')
app.register_blueprint(utilities_bp, url_prefix='/api/utilities')
app.register_blueprint(bidding_bp, url_prefix='/api/bidding')
app.register_blueprint(board_bp, url_prefix='/api/board')
app.register_blueprint(banners_bp, url_prefix='/api/banners')


# Security headers
@app.after_request
def set_security_headers(response):
    """국정원 권고 보안 헤더 설정"""
    # XSS Protection
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'

    # Content Security Policy (내부망 환경에 맞게 조정)
    # connect-src에 백엔드 서버 포트 포함 (프론트엔드와 포트가 다를 수 있음)
    host = request.host.split(':')[0] if request.host else 'localhost'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https: http:; "
        "font-src 'self' data:; "
        f"connect-src 'self' http://{host}:5001 http://localhost:5001 http://127.0.0.1:5001;"
    )

    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Permissions Policy (불필요한 브라우저 기능 차단)
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

    # HSTS (HTTPS 사용 시 활성화)
    # response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    return response


# CORS preflight 핸들러 - catch-all route보다 먼저 OPTIONS 요청 처리
@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Max-Age'] = '3600'
        return response


# Serve frontend files
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    # frontend 디렉토리에서 파일 찾기 (메인)
    frontend_path = os.path.join(app.static_folder, path)
    if os.path.exists(frontend_path) and os.path.isfile(frontend_path):
        return send_from_directory(app.static_folder, path)
    
    # assets / pages 경로: static_folder(=프로젝트 루트)에서 직접 탐색
    # (frontend_path 검사에서 이미 처리되지만, 명시적으로 유지)
    for prefix in ('assets/', 'pages/'):
        if path.startswith(prefix):
            full = os.path.join(_PROJECT_ROOT, path)
            if os.path.exists(full) and os.path.isfile(full):
                return send_from_directory(_PROJECT_ROOT, path)
    
    # 기본적으로 index.html 반환
    return send_from_directory(app.static_folder, 'index.html')


# Error handlers
@app.errorhandler(404)
def not_found(error):
    response = jsonify({'error': '요청한 리소스를 찾을 수 없습니다.'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': '서버 내부 오류가 발생했습니다.'}), 500


@app.errorhandler(413)
def file_too_large(error):
    return jsonify({'error': '파일 크기가 너무 큽니다. 최대 50MB까지 업로드 가능합니다.'}), 413


# Health check endpoint
@app.route('/api/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'NUGUNA Global',
        'version': '1.0.0'
    })


if __name__ == '__main__':
    import sys
    import importlib.util
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from werkzeug.middleware.proxy_fix import ProxyFix
    from werkzeug.serving import run_simple

    mounts = {}

    # ── 침수흔적 (FastAPI → WSGI 변환) ──────────────────────────
    flood_root = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '침수흔적'))
    if os.path.isdir(flood_root):
        sys.path.insert(0, flood_root)
        try:
            from a2wsgi import ASGIMiddleware
            from app.main import app as _flood_asgi
            mounts['/flood'] = ASGIMiddleware(_flood_asgi)
            print("[침수흔적] FastAPI 앱 로드됨 → /flood")
        except ImportError as e:
            print(f"[침수흔적] 로드 실패 (pip install a2wsgi 필요): {e}")
        except Exception as e:
            print(f"[침수흔적] 로드 실패: {e}")

    # ── CN_web (Flask) ────────────────────────────────────────────
    cn_root = os.path.normpath(os.path.join(os.path.dirname(__file__), 'CN_web', 'cn_web'))
    if os.path.isdir(cn_root):
        try:
            spec = importlib.util.spec_from_file_location(
                'cn_web_app', os.path.join(cn_root, 'app.py')
            )
            cn_module = importlib.util.module_from_spec(spec)
            sys.modules['cn_web_app'] = cn_module
            spec.loader.exec_module(cn_module)
            cn_flask = cn_module.app
            cn_flask.wsgi_app = ProxyFix(cn_flask.wsgi_app, x_prefix=1)
            mounts['/cn'] = cn_flask
            print("[CN_web] Flask 앱 로드됨 → /cn")
        except Exception as e:
            print(f"[CN_web] 로드 실패: {e}")

    combined = DispatcherMiddleware(app, mounts)

    run_simple(
        '0.0.0.0', 5001, combined,
        use_reloader=app.config['DEBUG'],
        use_debugger=False
    )
