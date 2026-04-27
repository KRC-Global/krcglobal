"""
NUGUNA Global - Flask Application Entry Point
누구나글로벌 사업관리시스템
"""
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from config import config

# Create Flask app
# static_folder를 프로젝트 루트로 설정 (KRDS 디자인 시스템, HTML 파일 서빙)
app = Flask(__name__, static_folder='..', static_url_path='')

# Load configuration
config_name = os.environ.get('FLASK_ENV') or 'default'
app.config.from_object(config[config_name])

# Enable CORS
CORS(app,
     resources={r"/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     expose_headers=["Content-Type"],
     max_age=3600)

# Ensure upload directory exists (skip on read-only filesystem like Vercel)
try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
except OSError:
    pass

# Initialize database
from models import db
db.init_app(app)

# Create tables (lazy - 첫 요청 시 실행)
_tables_created = False

@app.before_request
def ensure_tables():
    global _tables_created
    if not _tables_created:
        db.create_all()
        _run_migrations()
        _tables_created = True


def _run_migrations():
    """기존 테이블에 누락된 컬럼을 ALTER TABLE 로 추가.
    이미 존재하면 에러를 무시 (idempotent)."""
    migrations = [
        "ALTER TABLE bid_notices ADD COLUMN title_ko VARCHAR(500)",
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(db.text(sql))
                conn.commit()
                print(f'[migration] OK: {sql[:60]}')
            except Exception:
                conn.rollback()

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
from routes.tor_rfp import tor_rfp_bp
from routes.utilities import utilities_bp
from routes.bidding import bidding_bp
from routes.board import board_bp
from routes.banners import banners_bp
from routes.cn_analysis import cn_bp
from routes.webhook import webhook_bp
from routes.notice_collector import collector_bp
from routes.flights import flights_bp

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
app.register_blueprint(expansion_bp)
app.register_blueprint(proposals_bp, url_prefix='/api/proposals')
app.register_blueprint(performance_bp, url_prefix='/api/performance')
app.register_blueprint(oda_reports_bp, url_prefix='/api/oda-reports')
app.register_blueprint(contracts_bp, url_prefix='/api/contracts')
app.register_blueprint(tor_rfp_bp, url_prefix='/api/tor-rfp')
app.register_blueprint(utilities_bp, url_prefix='/api/utilities')
app.register_blueprint(bidding_bp, url_prefix='/api/bidding')
app.register_blueprint(board_bp, url_prefix='/api/board')
app.register_blueprint(banners_bp, url_prefix='/api/banners')
app.register_blueprint(cn_bp, url_prefix='/api/cn')
app.register_blueprint(webhook_bp, url_prefix='/api/webhook')
app.register_blueprint(collector_bp, url_prefix='/api/notices')
app.register_blueprint(flights_bp, url_prefix='/api/flights')


# Security headers
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https: http:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://*.supabase.co; "
        "frame-ancestors 'self';"
    )
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    return response


# CORS preflight
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


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '요청한 리소스를 찾을 수 없습니다.'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': '서버 내부 오류가 발생했습니다.'}), 500

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({'error': '파일 크기가 너무 큽니다.'}), 413


# Root → index.html
@app.route('/')
def serve_index():
    return app.send_static_file('index.html')


# Health check
@app.route('/api/health')
def health_check():
    return jsonify({'status': 'healthy', 'service': 'NUGUNA Global'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=True)
