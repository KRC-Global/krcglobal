# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NUGUNA Global (Global Business Management System) - 누구나글로벌 사업관리시스템**

Web application for managing KRC's (Korea Rural Community Corporation) global agricultural development projects including ODA initiatives, technical consulting, K-Rice Belt programs, methane reduction, overseas expansion support, and overseas office operations. Designed for ~100 concurrent users on internal network (Windows-based).

**Stack**: Python Flask 2.3.3 backend, SQLite with WAL mode, Vanilla JavaScript frontend, KRDS (Korea Design System) UI framework, Leaflet GIS integration

## Development Commands

### Server Execution

```bash
# Start both backend and frontend (recommended)
./start.sh              # Unix/Mac
start.bat               # Windows

# Manual backend only (port 5001)
cd backend
python app.py

# Frontend server separately (port 8000)
python -m http.server 8000
```

### Database Operations

```bash
# Initialize database with sample data
cd backend
python init_db.py

# Reset admin password
python reset_admin_password.py

# Check database contents
cd ..
python check_db.py

# Complete database reset (CAUTION: destroys all data)
rm -f backend/database/gbms.db backend/database/gbms.db-shm backend/database/gbms.db-wal
cd backend && python init_db.py
```

### Data Import Scripts

```bash
# Import ODA project data
python import_oda.py

# Import KRC coordinates (requires data files)
cd backend
python scripts/import_krc_coordinates.py
python scripts/import_consulting_projects.py
```

### Testing & Validation

```bash
# Test GIS API endpoints
python test_gis_api.py

# Check for duplicate records
python check_duplicate.py

# View server logs
tail -f backend/server.log
```

## Architecture

### Application Entry Points

**Frontend Entry**: `index.html` (login) → `dashboard.html` (main dashboard)
- KRDS design system files in root directory, NOT `frontend/` (legacy)
- Dynamic API base URL detection: auto-connects to `http://{hostname}:5001/api`

**Backend Entry**: `backend/app.py`
- Flask server with CORS enabled for all origins (internal network)
- Static file serving from project root (serves KRDS UI files)
- SQLite database with WAL mode configured on startup
- Blueprint registration for modular API routes

### Configuration Pattern

`backend/config.py` provides environment-based config:
- **Development**: DEBUG=True, SQL logging enabled (SQLALCHEMY_ECHO=True)
- **Production**: DEBUG=False, requires SECRET_KEY and JWT_SECRET_KEY env vars
- **Testing**: In-memory SQLite (`:memory:`)
- **SQLite Optimization**: WAL mode, 30s busy timeout, 64MB cache, pool_recycle=300
- **Pagination**: ITEMS_PER_PAGE=20 default
- **JWT**: Access token 8 hours, refresh token 30 days

Database automatically created at `backend/database/gbms.db` with WAL files (`-shm`, `-wal`)

### Data Model Architecture

39 models across two files:

**`backend/models/__init__.py`** (28 models):
- **Core**: User, Project, Budget, BudgetExecution, Document, Office
- **Consulting**: ConsultingProject, ConsultingPersonnel, PersonnelCV, TorRfp, Eoi
- **ODA**: OdaProject, OdaReport, OdaManualData
- **Methane**: MethaneProject, MethaneBudgetData
- **Workflow**: Proposal, ProposalStatus, Contract, PerformanceRecord
- **Reporting**: ProfitabilityData
- **Community**: BoardPost, Banner
- **System**: ProjectPhase, ProjectPersonnel, ActivityLog, AccessLog, SystemConfig

**`backend/models/expansion.py`** (8 models):
- Company, Loan, LoanPerformance, LoanRepayment, LoanProject, CompanyCollateral, PostManagement, MortgageContract

Key details:
- **User**: Department-based (gad/gb/aidc), role hierarchy (admin/manager/user)
- All models include `to_dict()` with camelCase JSON keys
- GIS coordinates stored on Project, ConsultingProject, OdaProject, and MethaneProject models
- Expansion models imported separately via `backend/models/expansion.py`

### API Blueprint Structure

23 blueprints registered in `backend/app.py`, all routes under `/api/` prefix:

| Blueprint | URL Prefix | Purpose |
|-----------|-----------|---------|
| auth_bp | `/api/auth` | JWT login/logout, token validation |
| projects_bp | `/api/projects` | Project CRUD with filters |
| oda_bp | `/api/oda` | ODA-specific project management |
| oda_reports_bp | `/api/oda-reports` | ODA reporting and analysis |
| consulting_bp | `/api/consulting` | Technical consulting operations |
| methane_bp | `/api/methane` | Methane reduction projects |
| budgets_bp | `/api/budgets` | Budget management and execution |
| profitability_bp | `/api/profitability` | Profitability analysis |
| documents_bp | `/api/documents` | File upload/download (500MB limit) |
| dashboard_bp | `/api/dashboard` | Aggregated statistics and KPIs |
| users_bp | `/api/users` | User management (admin only) |
| offices_bp | `/api/offices` | Overseas office CRUD |
| gis_bp | `/api/gis` | Geospatial project data for mapping |
| expansion_bp | (internal prefix) | Overseas expansion support |
| proposals_bp | `/api/proposals` | Proposal management |
| performance_bp | `/api/performance` | Performance metrics |
| contracts_bp | `/api/contracts` | Contract management |
| cv_bp | `/api/cv` | Personnel CV management |
| tor_rfp_bp | `/api/tor-rfp` | TOR/RFP document management |
| bidding_bp | `/api/bidding` | Bidding/입찰 management |
| board_bp | `/api/board` | Board/게시판 posts |
| banners_bp | `/api/banners` | Dashboard banner management |
| utilities_bp | `/api/utilities` | Utility tools (exchange rates, etc.) |

**Important**: Blueprint routes must NOT duplicate the url_prefix. Use empty string `''` or `/` for root endpoint, not `/methane` when registering with `url_prefix='/api/methane'`.

Authentication: `@token_required` decorator injects `current_user`, `@admin_required` restricts to admin role

### Frontend Architecture (KRDS Design System)

**CSS Structure** (`assets/css/`):
- `variables.css`: Design tokens (colors, spacing, typography)
- `base.css`: Reset, global styles, accessibility
- `components.css`: Reusable UI components
- `pages.css`: Page-specific layouts

**JavaScript Modules** (`assets/js/`):
- `api.js`: API communication with JWT auto-injection
- `common.js`: Utility functions, auth checks, navigation, menuMap
- `components/modal.js`: Modal dialog system
- `components/toast.js`: Toast notification system

**Page Structure**:
```
index.html              # Login page (entry point)
dashboard.html          # Main dashboard
pages/
  projects/
    overseas-tech.html                  # 해외기술용역 목록
    overseas-tech-proposals.html        # 제안서 관리
    overseas-tech-tor-rfp.html          # TOR/RFP 관리
    overseas-tech-performance.html      # 실적관리
    overseas-tech-contracts.html        # 계약관리
    overseas-tech-bidding.html          # 입찰관리
    overseas-tech-board.html            # 게시판
    international-cooperation.html      # 국제협력사업 (ODA)
    intl-coop-performance.html          # ODA 실적관리
    intl-coop-feasibility.html          # 타당성조사
    intl-coop-grant-plan.html           # 무상원조 계획
    intl-coop-mou.html                  # MOU 관리
    intl-coop-pcp.html                  # PCP 관리
    intl-coop-pmc.html                  # PMC 관리
    intl-coop-vendor-proposal.html      # 업체제안서
    intl-coop-board.html                # ODA 게시판
    oda-reports.html                    # ODA 보고서
    methane.html                        # 메탄감축사업
  expansion/                            # 해외진출지원사업
    company-management.html             # 기업관리
    loan-management.html                # 융자관리
    expansion-board.html                # 게시판
    info/
      loan-performance.html             # 융자사업 추진실적
      loan-repayment.html               # 연도별 상환내역
      loan-projects.html                # 융자사업 관리
      company-collateral.html           # 기업별 담보 현황
      post-management.html              # 사후관리대장
      mortgage-contract.html            # 근저당권 설정계약서
  hr/
    dispatch-management.html            # 파견인력 관리
    personnel-analysis.html             # 인력현황 분석
    cv-management.html                  # 이력서 관리
  admin/
    offices.html                        # 해외사무소 관리
    users.html                          # 사용자 관리
  budget/
    profitability.html                  # 수익성 분석
  gis.html                              # 글로벌맵
  consulting.html                       # 컨설팅 관리
  utilities.html                        # 편의기능
```

**Design System Values**:
- Primary: `#1A4B7C` (KRC navy blue)
- Secondary: `#CEC0AC` (ivory)
- Font: Pretendard, Noto Sans KR
- Responsive: Mobile (<768px), Tablet (768-1200px), Desktop (>1200px)

## Project Types & Workflows

Seven distinct project types managed:
1. **consulting**: Technical consulting services (overseas-tech.html)
2. **oda_bilateral**: Bilateral ODA (KOICA projects) (international-cooperation.html)
3. **oda_multilateral**: Multilateral ODA (FAO, AfDB) (international-cooperation.html)
4. **k_rice_belt**: K-Rice Belt strategic food security
5. **investment**: Overseas agricultural investment
6. **loan_support**: Development loan programs
7. **methane**: Methane reduction projects (methane.html)

Each type has distinct status workflows, budget category emphases, document requirements, and GIS visualization needs.

## GIS Integration

**Leaflet Setup**: Library files in `assets/lib/leaflet/`

**Map Configuration**:
- Base tiles: Google Maps tile layer (accessible on internal network)
- Coordinates stored as Numeric(10,7) in Project model
- API: `/api/gis/projects` returns GeoJSON-compatible data
- Markers clustered by project type and status

**Offline Consideration**: System designed for internal network where Google Maps API is accessible but other external resources may be blocked

## Authentication & Authorization

**JWT Flow**:
1. Login via `/api/auth/login` → returns 8-hour token
2. Store in localStorage (remember me) or sessionStorage
3. All API requests include `Authorization: Bearer {token}`
4. Auto-redirect to login on 401 responses

**Departments** (부서):
- `gad`: 글로벌농업개발부
- `gb`: 글로벌사업부
- `aidc`: 농식품국제개발협력센터

**Roles**: `admin` (full CRUD) > `manager` (department CRUD) > `user` (read + own records)

**Permission Scopes** (`permission_scope` field on User model):
- `all`: 모든 메뉴 접근 (관리자용)
- `overseas_tech`: 해외기술용역 하위 메뉴만
- `oda`: 국제협력사업 하위 메뉴만
- `expansion`: 해외진출지원사업 하위 메뉴만
- `methane`: 메탄감축사업 메뉴만
- `readonly`: 모든 메뉴 조회만 (수정 불가)

Permission enforcement: frontend uses `filterMenuByPermission()` in `common.js` to hide menus; backend uses `@permission_required('scope')` decorator from `backend/utils/permissions.py` on POST/PUT/DELETE routes.

```python
# Usage pattern in routes
from utils.permissions import permission_required

@bp.route('', methods=['POST'])
@token_required
@permission_required('overseas_tech')
def create_item(current_user):
    ...
```

**Test Accounts** (after `init_db.py`):
- admin / admin123 (관리자, scope: all)
- krcoda / user123 (국제협력사업 담당, scope: oda)
- krcgisul / user123 (해외기술용역 담당, scope: overseas_tech)
- krcgb / user123 (해외진출지원사업 담당, scope: expansion)
- user1 / user123 (글로벌사업부)
- user2 / user123 (농식품국제개발협력센터)

**Permission bulk setup**:
```bash
python setup_user_permissions.py
```

## Common Development Patterns

### Adding New API Route
```python
# 1. Create blueprint in backend/routes/new_feature.py
from flask import Blueprint, jsonify, request
from models import db
from routes.auth import token_required

new_feature_bp = Blueprint('new_feature', __name__)

@new_feature_bp.route('/', methods=['GET'])
@token_required
def list_items(current_user):
    # current_user injected by decorator
    items = Model.query.filter_by(department=current_user.department).all()
    return jsonify({'success': True, 'data': [item.to_dict() for item in items]})

# 2. Register in backend/app.py
from routes.new_feature import new_feature_bp
app.register_blueprint(new_feature_bp, url_prefix='/api/new_feature')
```

### Adding New Model
```python
# In backend/models/__init__.py
class NewModel(db.Model):
    __tablename__ = 'new_models'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }

# Then reset database (destroys data!)
```

### Schema Migrations (without data loss)
For adding columns to existing tables without resetting, use a standalone migration script (see `backend/migrations/` for examples):

```python
# backend/migrations/add_new_column.py
from app import app, db
import sqlalchemy as sa

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(sa.text('ALTER TABLE table_name ADD COLUMN new_col TEXT'))
            conn.commit()
            print("Migration complete")
        except Exception as e:
            print(f"Already applied or error: {e}")
```

Run from `backend/` directory: `python migrations/add_new_column.py`

Many root-level `migrate_*.py` scripts follow this same pattern for ad-hoc migrations.

### Frontend API Call Pattern
```javascript
// In page JS file
async function loadData() {
    try {
        const response = await apiCall('/endpoint', 'GET');
        if (response.success) {
            renderData(response.data);
        } else {
            Toast.error(response.message);
        }
    } catch (error) {
        Toast.error('데이터를 불러오는데 실패했습니다.');
    }
}
```

## Internal Network Deployment (Windows)

**Preinstall Package**: `preinstall2/` directory contains offline installation:
- Python 3.11 installer
- All wheel files for dependencies
- Batch scripts for server management
- Database initialization scripts

**Installation Steps**:
1. Install Python from `preinstall2/01_Python설치/`
2. Install packages: `preinstall2/02_Python패키지/install_packages.bat`
3. Initialize database: `preinstall2/04_데이터베이스초기화/init_db.py`
4. Start server: `preinstall2/03_서버실행스크립트/start_server.bat`
5. Access: `http://127.0.0.1:5001`

## Important Constraints

- **Internal network only**: CORS allows all origins, no external auth services
- **SQLite limitations**: Optimized for ~100 concurrent users with WAL mode
- **Korean language**: All UI text, error messages, and documentation in Korean
- **File size limit**: 500MB per upload (MAX_CONTENT_LENGTH in config.py)
- **Allowed extensions**: pdf, doc, docx, xls, xlsx, ppt, pptx, hwp, txt, jpg, jpeg, png, gif, zip
- **Port usage**: Backend 5001, Frontend 8000 (development)
- **Numeric precision**: Budget (15,2), Coordinates (10,7)
- **UTC timestamps**: All datetime fields use `datetime.utcnow()`

## Key Files & Locations

**Don't use**: `frontend/` directory - legacy files, use root-level HTML and `assets/` instead

**Database**: `backend/database/gbms.db` (with `-shm`, `-wal` files)

**Uploads**: `backend/uploads/` (subdirectories: `documents/`, `tor_rfp/`, `cv/`, etc.)

**Logs**: `backend/server.log` or `server.log`

**Data Import**: KRC data JSON files expected in `KRC/data/` (sibling directory for import scripts)

**Admin utilities**:
- `reset_admin_password.py`: Reset admin password to default
- `check_db.py`: Database inspection tool
- `check_duplicate.py`: Data validation utility

## Frontend Menu Management

**Menu Initialization** (`assets/js/common.js`):
- `initMenuForCurrentPage()`: Auto-expands relevant menu items based on current URL
- Uses `menuMap` object to match filenames to menu paths
- Applies `.active` class to current and parent menu items
- Supports nested submenus up to Level 4 (Level 4 CSS class: `.submenu-nested-level4`)

**toggleSubmenu() function**:
- Requires `event.stopPropagation()` to prevent parent menu collapse
- Updates arrow indicators (▾/▸) dynamically
- Must be called with `onclick="toggleSubmenu(event)"` on submenu toggle links

**Menu Consistency**:
- All pages have sidebar menu in identical order
- "해외진출지원사업" is the only parent item with Level 4 children
- Each page must call `initCommonUI()` in DOMContentLoaded to activate menu

## Error Handling Standards

- Return JSON: `{'success': True, 'data': [items], 'currentPage': N, 'pages': N}` for paginated lists
- Return JSON: `{'success': False, 'message': 'Korean error message'}` for errors
- HTTP codes: 400 (bad request), 401 (unauthorized), 403 (forbidden), 404 (not found), 500 (internal error)
- Database errors trigger auto-rollback
- Frontend: Display errors via Toast.error() system
- Logging: All significant actions logged to ActivityLog table

**API Response Format (Pagination)**:
- Paginated endpoints return: `data` (array), `total`, `currentPage`, `pages`, `perPage`
- Frontend expects `data.currentPage` and `data.pages` properties for pagination

## Common Issues & Troubleshooting

### API Data Not Loading
**Problem**: API returns 404 or data shows "요청한 리소스를 찾을 수 없습니다"
**Cause**: Blueprint route path duplicates the url_prefix. Example: `@methane_bp.route('/methane')` with `url_prefix='/api/methane'` → path becomes `/api/methane/methane`
**Solution**: Routes should use empty string `''` or `/` as route path, not `/endpoint_name`. The url_prefix handles the namespace.

**Example - Correct**:
```python
# In backend/routes/methane.py
@methane_bp.route('', methods=['GET'])  # Correct
def get_methane_projects():
    ...

# In backend/app.py
app.register_blueprint(methane_bp, url_prefix='/api/methane')
# → Results in /api/methane
```

**Example - Incorrect**:
```python
@methane_bp.route('/methane', methods=['GET'])  # Wrong
# → Results in /api/methane/methane (not found)
```

### Menu Not Expanding/Collapsing
**Problem**: Submenu stays open or doesn't toggle
**Cause**: Missing `event.stopPropagation()` in toggleSubmenu() function
**Solution**: Ensure toggleSubmenu() includes:
```javascript
function toggleSubmenu(event) {
    event.preventDefault();
    event.stopPropagation();  // Required to prevent parent collapse
    // ... rest of logic
}
```

### Page Not Finding CSS/JS Files
**Problem**: Styling not applied, JavaScript functions undefined
**Cause**: Incorrect relative paths from nested page directories
**Solution** (see also 상대 경로 계산 table below):
- Pages in `pages/`, `pages/projects/`, `pages/admin/`, `pages/hr/`, `pages/budget/`: Use `../../assets/...`
- Pages in `pages/expansion/`: Use `../../assets/...`
- Pages in `pages/expansion/info/`: Use `../../../assets/...`

### PDF Preview Not Working (404 Error)
**Problem**: PDF preview/download fails with 404 error in 실적관리 or other file upload features
**Cause**: Database file_path missing file extension while physical file has the extension
**Prevention**: Verify upload logic properly preserves file extensions from `secure_filename()`

### Cross-Platform File Path Issues
**Problem**: File download fails when DB has Windows absolute paths but running on Mac/Linux
**Cause**: `tor_rfp.py` and other routes store absolute paths that differ across OS
**Solution**: Routes include `resolve_file_path()` helper that extracts filename from stored path and looks in local uploads/ directory

## 페이지 생성 가이드

### 필수 페이지 구조

모든 페이지는 다음 구조를 따라야 합니다:

```html
<body class="app-layout">
    <a href="#main-content" class="skip-nav">본문 바로가기</a>
    <header class="app-header">...</header>
    <aside class="app-sidebar">...</aside>
    <main id="main-content" class="app-main">...</main>
</body>
```

**중요**: `class="app-layout"` 누락 시 레이아웃 깨짐 발생

### 상대 경로 계산

| 디렉토리 | CSS/JS | Dashboard | Menu |
|---------|--------|-----------|------|
| pages/ | ../ | ../ | ../ |
| pages/projects/ | ../../ | ../../ | ../ |
| pages/expansion/ | ../../ | ../../ | ../ |
| pages/expansion/info/ | ../../../ | ../../../ | ../../ |
| pages/hr/ | ../../ | ../../ | ../ |
| pages/admin/ | ../../ | ../../ | ../ |
| pages/budget/ | ../../ | ../../ | ../ |

### 필수 스크립트 순서

```html
<script src="{{PATH}}assets/js/common.js"></script>
<script src="{{PATH}}assets/js/api.js"></script>
<script src="{{PATH}}assets/js/components/toast.js"></script>
```

### menuMap 업데이트

새 페이지 생성 시 `assets/js/common.js`의 menuMap에 추가 필요:

```javascript
const menuMap = {
    // ... 기존 항목 ...
    'new-page': ['메뉴그룹', '서브메뉴', '페이지명']
};
```

### 자주 발생하는 문제

1. **레이아웃 깨짐**: `<body class="app-layout">` 확인
2. **메뉴 위치 이상**: app-layout 클래스 또는 main 태그 확인
3. **로그아웃 버튼 깨짐**: user-dropdown 구조 확인
4. **서브메뉴 토글 안 됨**: toggleSubmenu(event) 확인
5. **API 호출 실패**: toast.js 포함 확인
