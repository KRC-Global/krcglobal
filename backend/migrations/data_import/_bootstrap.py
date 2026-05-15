"""공통 부트스트랩 — 외부망 Flask app context 설정.

모든 data_import 스크립트는 다음과 같이 시작한다:

    from _bootstrap import app, db, models  # noqa
    with app.app_context():
        ...

backend/migrations/data_import/ 에서 3단계 위가 프로젝트 루트(krcglobal/).
"""
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, '..', '..', '..'))
_BACKEND = os.path.join(_PROJECT_ROOT, 'backend')

for p in (_PROJECT_ROOT, _BACKEND):
    if p not in sys.path:
        sys.path.insert(0, p)

# Flask app (sets up db, config, blueprints)
from app import app  # noqa: E402
from models import db  # noqa: E402
import models  # noqa: E402

PROJECT_ROOT = _PROJECT_ROOT
DATA_IMPORT_DIR = _THIS
EXPORTS_DIR = os.path.join(_THIS, 'exports')
MANIFESTS_DIR = os.path.join(_THIS, 'manifests')
REPORTS_DIR = os.path.join(_THIS, 'reports')
MIGRATION_SRC_DIR = os.path.join(_PROJECT_ROOT, '_migration_src')

for d in (EXPORTS_DIR, MANIFESTS_DIR, REPORTS_DIR):
    os.makedirs(d, exist_ok=True)

__all__ = ['app', 'db', 'models', 'PROJECT_ROOT', 'DATA_IMPORT_DIR',
           'EXPORTS_DIR', 'MANIFESTS_DIR', 'REPORTS_DIR', 'MIGRATION_SRC_DIR']
