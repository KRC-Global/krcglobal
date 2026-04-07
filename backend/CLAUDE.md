# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GBMS (Global Business Management System) - 글로벌사업처 해외사업관리시스템**

A Flask-based web application for managing KRC's (Korea Rural Community Corporation) global agricultural development projects, including ODA projects, consulting services, K-Rice Belt initiatives, and overseas office operations. The system supports approximately 100 concurrent users on an internal network.

**Tech Stack**: Flask 2.3.3, SQLAlchemy 3.1.1, SQLite with WAL mode, JWT authentication, vanilla JavaScript frontend

## Development Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database with sample data
python init_db.py

# Import KRC coordinates from JSON files (requires ../KRC/data/)
python scripts/import_krc_coordinates.py
```

### Running the Application
```bash
# Development server (port 5000)
python app.py

# With environment configuration
FLASK_ENV=development python app.py

# Production mode
FLASK_ENV=production python app.py
```

### Database Operations
```bash
# Recreate database (drops all data)
rm -f database/gbms.db database/gbms.db-shm database/gbms.db-wal
python init_db.py
```

## Architecture

### Application Structure

**Entry Point**: `app.py` - Configures Flask app, initializes database, registers blueprints, sets up CORS for internal network

**Configuration**: `config.py` - Environment-based config (development/production/testing) with SQLite optimization settings:
- WAL mode enabled for concurrent access
- 30-second busy timeout
- 64MB cache size
- Connection pooling configured for ~100 users

**Database**: SQLite with WAL (Write-Ahead Logging) mode in `database/gbms.db`
- Automatically created/configured on app startup
- WAL files (`gbms.db-shm`, `gbms.db-wal`) are normal operation artifacts

### Data Model (models/__init__.py)

Core entities with relationships:
- **User**: Department-based access (gad/gb/aidc), role-based permissions (admin/manager/user)
- **Project**: Main entity with GIS coordinates, budget tracking, multiple statuses
- **Budget**: Per-project/year with categories (personnel, equipment, travel, operating, subcontract)
- **Document**: File uploads with versioning and access control
- **Office**: Overseas offices with types (regular/oda_desk)
- **ProjectPhase**, **ProjectPersonnel**, **BudgetExecution**, **ActivityLog**: Supporting entities

**Relationships**:
- Project → Budget (one-to-many)
- Project → Document (one-to-many)
- Project → ProjectPhase/ProjectPersonnel (one-to-many)
- Budget → BudgetExecution (one-to-many)
- User → ActivityLog (one-to-many for audit trail)

### API Routes (Blueprints)

All routes prefixed with `/api/`:
- **auth** (`/api/auth`): JWT-based login/logout, token validation, password management
- **projects** (`/api/projects`): CRUD operations with filtering (type, department, status, country, year, search)
- **budgets** (`/api/budgets`): Budget management and execution tracking
- **documents** (`/api/documents`): File upload/download with 50MB limit
- **dashboard** (`/api/dashboard`): Aggregated statistics and metrics
- **users** (`/api/users`): User management (admin only)
- **offices** (`/api/offices`): Overseas office management
- **gis** (`/api/gis`): Geospatial data for project mapping

### Authentication & Authorization

**JWT Authentication**:
- Token required for all API routes (except login)
- 8-hour token expiration (work day)
- Decorators: `@token_required`, `@admin_required`
- Token format: `Authorization: Bearer <token>`

**Departments**:
- `gad`: 글로벌농업개발부
- `gb`: 글로벌사업부
- `aidc`: 농식품국제개발협력센터

**Roles**: admin (full access) | manager | user (basic access)

### Frontend Integration

Frontend located in `../frontend/` directory:
- Served as static files by Flask (`static_folder='../frontend'`)
- SPA-style routing: all routes fall back to `index.html`
- CORS enabled for all origins (`*`) - internal network deployment
- Main pages: `index.html` (login), `dashboard.html`, `gis.html`

## Project Types

System handles 6 project types with distinct characteristics:
- `consulting`: Technical consulting services
- `oda_bilateral`: Bilateral ODA projects (typically KOICA)
- `oda_multilateral`: Multilateral ODA (FAO, AfDB, etc.)
- `k_rice_belt`: K-Rice Belt strategic initiatives
- `investment`: Overseas agricultural investment
- `loan_support`: Loan-based development support

## Database Patterns

### Querying with Filters
All list endpoints support pagination and filters. Example pattern from `routes/projects.py`:
```python
query = Project.query
if project_type:
    query = query.filter(Project.project_type == project_type)
if search:
    query = query.filter(db.or_(
        Project.title.ilike(f'%{search}%'),
        Project.code.ilike(f'%{search}%')
    ))
pagination = query.paginate(page=page, per_page=per_page)
```

### JSON Serialization
Models include `to_dict()` methods for consistent JSON output with camelCase keys. Some support `include_details` flag for nested data.

### Activity Logging
All significant actions (login, logout, CRUD operations) are logged to `ActivityLog` with user context, IP address, and description.

## File Upload

Configured in `config.py`:
- **Upload folder**: `uploads/` directory (auto-created)
- **Max size**: 50MB (`MAX_CONTENT_LENGTH`)
- **Allowed extensions**: pdf, doc, docx, xls, xlsx, ppt, pptx, hwp, txt, jpg, jpeg, png, gif, zip

File paths stored in database, physical files in `uploads/`

## Authentication

Google OAuth via Supabase Auth. After first login, admins are assigned via Supabase SQL Editor.

## Important Constraints

- SQLite optimized for ~100 concurrent users with WAL mode
- Internal network deployment - CORS allows all origins
- Korean language UI/messages throughout
- GIS coordinates (latitude/longitude) stored as Numeric(10, 7)
- Budget amounts stored as Numeric(15, 2) for precision
- All datetime fields use UTC (`datetime.utcnow()`)

## Common Patterns

**Adding new routes**:
1. Create route file in `routes/` with Blueprint
2. Import and register in `app.py`
3. Apply `@token_required` decorator for protected endpoints
4. Use `current_user` parameter injected by decorator

**Adding new models**:
1. Define in `models/__init__.py`
2. Include `to_dict()` method with camelCase keys
3. Run database recreation (deletes all data - see Database Operations)

**Error handling**:
- Return JSON with `success: False` and Korean error messages
- Use appropriate HTTP status codes (400 bad request, 401 unauthorized, 403 forbidden, 404 not found, 500 internal error)
- Database errors auto-rollback via error handler in `app.py`
