"""
GBMS - Database Models
글로벌사업처 해외사업관리시스템
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import re as _re

db = SQLAlchemy()

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """한국 시간 반환"""
    return datetime.now(KST).replace(tzinfo=None)


def normalize_date_dot(date_str):
    """날짜 문자열을 YYYY.MM 또는 YYYY.MM.DD 형식으로 정규화
    '72-10 → 1972.10  |  1972-10-01 → 1972.10.01  |  2025-03-06 → 2025.03.06
    """
    if not date_str:
        return date_str
    s = str(date_str).replace("'", "").replace("\u2018", "").replace("\u2019", "").strip()
    parts = _re.split(r'[.\-]', s)
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        yy = int(parts[0])
        year = 1900 + yy if (50 <= yy < 100) else (2000 + yy if yy < 50 else yy)
        mm = parts[1].zfill(2)
        if len(parts) >= 3 and parts[2].isdigit():
            dd = parts[2].zfill(2)
            return f"{year}.{mm}.{dd}"
        return f"{year}.{mm}"
    return date_str


def format_date_dot(d):
    """date/datetime 객체를 YYYY.MM.DD 문자열로 변환"""
    if d is None:
        return None
    if hasattr(d, 'strftime'):
        return d.strftime('%Y.%m.%d')
    return normalize_date_dot(str(d))


class User(db.Model):
    """사용자 모델"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True)
    department = db.Column(db.String(50), nullable=False)  # gad, gb, aidc
    role = db.Column(db.String(20), default='user')  # admin, manager, user
    permission_scope = db.Column(db.String(50), default='readonly')  # all, overseas_tech, expansion, oda, readonly
    employee_number = db.Column(db.String(20))   # 사번
    phone = db.Column(db.String(20))
    position = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    password_history = db.Column(db.Text)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, scope):
        """특정 권한이 있는지 확인"""
        if self.role == 'admin' or self.permission_scope == 'all':
            return True
        if self.permission_scope == scope:
            return True
        return False
    
    def to_dict(self):
        dept_names = {
            'gad': '글로벌농업개발부',
            'gb': '글로벌사업부',
            'aidc': '농식품국제개발협력센터'
        }
        return {
            'id': self.id,
            'userId': self.user_id,
            'name': self.name,
            'email': self.email,
            'department': self.department,
            'departmentName': dept_names.get(self.department, self.department),
            'role': self.role,
            'permissionScope': self.permission_scope or 'readonly',
            'employeeNumber': self.employee_number,
            'phone': self.phone,
            'position': self.position,
            'isActive': self.is_active
        }


class Project(db.Model):
    """사업 모델"""
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200))
    project_type = db.Column(db.String(50), nullable=False, index=True)
    # Types: consulting, oda_bilateral, oda_multilateral, k_rice_belt, investment, loan_support
    
    country = db.Column(db.String(50), nullable=False, index=True)
    country_code = db.Column(db.String(3))
    region = db.Column(db.String(50))
    
    # GIS coordinates
    latitude = db.Column(db.Numeric(10, 7))  # 위도
    longitude = db.Column(db.Numeric(10, 7))  # 경도
    
    department = db.Column(db.String(50), nullable=False, index=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    description = db.Column(db.Text)
    objectives = db.Column(db.Text)
    scope = db.Column(db.Text)
    
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    duration_months = db.Column(db.Integer)
    
    budget_total = db.Column(db.Numeric(15, 2), default=0)
    budget_krw = db.Column(db.Numeric(15, 2), default=0)  # 원화 예산
    budget_foreign = db.Column(db.Numeric(15, 2), default=0)  # 외화 예산
    currency = db.Column(db.String(10), default='KRW')
    
    status = db.Column(db.String(20), default='planning', index=True)
    # Status: planning, bidding, contracted, in_progress, completed, suspended, cancelled
    progress = db.Column(db.Integer, default=0)  # 0-100
    
    client = db.Column(db.String(200))  # 발주처
    partner = db.Column(db.String(200))  # 협력기관
    funding_source = db.Column(db.String(100))  # 재원조달처
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships
    manager = db.relationship('User', foreign_keys=[manager_id])
    phases = db.relationship('ProjectPhase', backref='project', lazy='dynamic')
    budgets = db.relationship('Budget', backref='project', lazy='dynamic')
    documents = db.relationship('Document', backref='project', lazy='dynamic')
    personnel = db.relationship('ProjectPersonnel', backref='project', lazy='dynamic')
    
    def to_dict(self, include_details=False):
        data = {
            'id': self.id,
            'code': self.code,
            'title': self.title,
            'titleEn': self.title_en,
            'projectType': self.project_type,
            'country': self.country,
            'countryCode': self.country_code,
            'region': self.region,
            'latitude': float(self.latitude) if self.latitude else None,
            'longitude': float(self.longitude) if self.longitude else None,
            'department': self.department,
            'startDate': self.start_date.isoformat() if self.start_date else None,
            'endDate': self.end_date.isoformat() if self.end_date else None,
            'budgetTotal': float(self.budget_total) if self.budget_total else 0,
            'status': self.status,
            'progress': self.progress,
            'client': self.client
        }
        
        if include_details:
            data.update({
                'description': self.description,
                'objectives': self.objectives,
                'scope': self.scope,
                'durationMonths': self.duration_months,
                'budgetKrw': float(self.budget_krw) if self.budget_krw else 0,
                'budgetForeign': float(self.budget_foreign) if self.budget_foreign else 0,
                'currency': self.currency,
                'partner': self.partner,
                'fundingSource': self.funding_source,
                'manager': self.manager.to_dict() if self.manager else None,
                'createdAt': self.created_at.isoformat() if self.created_at else None,
                'updatedAt': self.updated_at.isoformat() if self.updated_at else None
            })
        
        return data


class ProjectPhase(db.Model):
    """사업단계 모델"""
    __tablename__ = 'project_phases'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    order = db.Column(db.Integer, default=0)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='pending')
    progress = db.Column(db.Integer, default=0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'projectId': self.project_id,
            'name': self.name,
            'description': self.description,
            'order': self.order,
            'startDate': self.start_date.isoformat() if self.start_date else None,
            'endDate': self.end_date.isoformat() if self.end_date else None,
            'status': self.status,
            'progress': self.progress
        }


class Budget(db.Model):
    """예산 모델"""
    __tablename__ = 'budgets'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False)
    # Categories: personnel, equipment, travel, operating, subcontract, indirect, other
    
    sub_category = db.Column(db.String(100))
    description = db.Column(db.Text)
    
    amount_planned = db.Column(db.Numeric(15, 2), default=0)
    amount_executed = db.Column(db.Numeric(15, 2), default=0)
    amount_remaining = db.Column(db.Numeric(15, 2), default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    executions = db.relationship('BudgetExecution', backref='budget', lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'projectId': self.project_id,
            'year': self.year,
            'category': self.category,
            'subCategory': self.sub_category,
            'description': self.description,
            'amountPlanned': float(self.amount_planned) if self.amount_planned else 0,
            'amountExecuted': float(self.amount_executed) if self.amount_executed else 0,
            'amountRemaining': float(self.amount_remaining) if self.amount_remaining else 0,
            'executionRate': round(float(self.amount_executed) / float(self.amount_planned) * 100, 1) if self.amount_planned else 0
        }


class BudgetExecution(db.Model):
    """예산집행 모델"""
    __tablename__ = 'budget_executions'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False, index=True)
    execution_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    description = db.Column(db.Text)
    voucher_no = db.Column(db.String(50))  # 전표번호
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'budgetId': self.budget_id,
            'executionDate': self.execution_date.isoformat() if self.execution_date else None,
            'amount': float(self.amount) if self.amount else 0,
            'description': self.description,
            'voucherNo': self.voucher_no
        }


class Document(db.Model):
    """문서 모델"""
    __tablename__ = 'documents'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), index=True)
    
    title = db.Column(db.String(200), nullable=False)
    doc_type = db.Column(db.String(50), nullable=False)
    # Types: proposal, contract, report, meeting, correspondence, other
    
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(20))
    
    description = db.Column(db.Text)
    version = db.Column(db.String(20), default='1.0')
    
    is_public = db.Column(db.Boolean, default=False)
    department = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'projectId': self.project_id,
            'title': self.title,
            'docType': self.doc_type,
            'fileName': self.file_name,
            'fileSize': self.file_size,
            'fileType': self.file_type,
            'description': self.description,
            'version': self.version,
            'isPublic': self.is_public,
            'department': self.department,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class Office(db.Model):
    """해외사무소 등 모델"""
    __tablename__ = 'offices'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(50), nullable=False)
    country_code = db.Column(db.String(3))
    region = db.Column(db.String(50))
    city = db.Column(db.String(50))
    address = db.Column(db.String(300))

    office_type = db.Column(db.String(50))  # ODA사무소, 센터, 국제기구, 해외사무소
    status = db.Column(db.String(20), default='파견중')  # 파견중, 미파견
    
    contact_person = db.Column(db.String(100))
    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(50))
    
    established_date = db.Column(db.Date)
    annual_budget = db.Column(db.Numeric(15, 2))

    # 파견 기간 (사무소장 파견 기간)
    dispatch_start_date = db.Column(db.Date)
    dispatch_end_date = db.Column(db.Date)

    latitude = db.Column(db.Numeric(10, 7))
    longitude = db.Column(db.Numeric(10, 7))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'country': self.country,
            'countryCode': self.country_code,
            'region': self.region,
            'city': self.city,
            'address': self.address,
            'officeType': self.office_type,
            'status': self.status,
            'contactPerson': self.contact_person,
            'contactEmail': self.contact_email,
            'contactPhone': self.contact_phone,
            'establishedDate': self.established_date.isoformat() if self.established_date else None,
            'annualBudget': float(self.annual_budget) if self.annual_budget else 0,
            'dispatchStartDate': self.dispatch_start_date.isoformat() if self.dispatch_start_date else None,
            'dispatchEndDate': self.dispatch_end_date.isoformat() if self.dispatch_end_date else None,
            'latitude': float(self.latitude) if self.latitude else None,
            'longitude': float(self.longitude) if self.longitude else None
        }


class ProjectPersonnel(db.Model):
    """사업인력 모델"""
    __tablename__ = 'project_personnel'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100))  # PM, 팀장, 팀원, 전문가 등
    position = db.Column(db.String(100))
    affiliation = db.Column(db.String(200))  # 소속
    
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_deployed = db.Column(db.Boolean, default=False)  # 파견 여부
    
    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'projectId': self.project_id,
            'name': self.name,
            'role': self.role,
            'position': self.position,
            'affiliation': self.affiliation,
            'startDate': self.start_date.isoformat() if self.start_date else None,
            'endDate': self.end_date.isoformat() if self.end_date else None,
            'isDeployed': self.is_deployed
        }


class ActivityLog(db.Model):
    """활동 로그 모델"""
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    action = db.Column(db.String(50), nullable=False)  # create, update, delete, login, logout
    entity_type = db.Column(db.String(50))  # project, document, budget, etc.
    entity_id = db.Column(db.Integer)
    description = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', foreign_keys=[user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'userId': self.user_id,
            'userName': self.user.name if self.user else None,
            'action': self.action,
            'entityType': self.entity_type,
            'entityId': self.entity_id,
            'description': self.description,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


class ConsultingProject(db.Model):
    """해외기술용역 프로젝트 모델"""
    __tablename__ = 'consulting_projects'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, index=True)  # 번호
    contract_year = db.Column(db.Integer, index=True)  # 수주년도
    status = db.Column(db.String(20), default='준공', index=True)  # 진행여부: 준공, 진행중

    country = db.Column(db.String(100), nullable=False, index=True)  # 국가별
    latitude = db.Column(db.Numeric(10, 7))  # Y (위도)
    longitude = db.Column(db.Numeric(10, 7))  # X (경도)

    title_en = db.Column(db.String(500))  # 영문사업명
    title_kr = db.Column(db.String(500), nullable=False)  # 국문사업명
    project_type = db.Column(db.String(200))  # 사업형태 (기존 자유텍스트, 원본 보존용)

    # 사업형태 체크박스 (복수 선택 가능)
    type_feasibility = db.Column(db.Boolean, default=False)     # 타당성조사 (F/S)
    type_masterplan = db.Column(db.Boolean, default=False)      # 마스터플랜 (M/P)
    type_basic_design = db.Column(db.Boolean, default=False)    # 기본설계 (B/D)
    type_detailed_design = db.Column(db.Boolean, default=False) # 실시설계 (D/D)
    type_construction = db.Column(db.Boolean, default=False)    # 시공감리 (C/S)
    type_pmc = db.Column(db.Boolean, default=False)             # 사업관리 (PMC)
    project_type_etc = db.Column(db.String(200))                # 기타 사업형태

    start_date = db.Column(db.String(20))  # 착수일 (예: '72-10)
    end_date = db.Column(db.String(20))  # 준공일 (예: '73-09)

    budget = db.Column(db.Numeric(15, 2))  # 전체용역비(백만원)
    total_budget = db.Column(db.Numeric(15, 2))  # 총사업비(백만USD)
    krc_budget = db.Column(db.Numeric(15, 2))  # 공사지분 용역비(백만원)
    krc_share_ratio = db.Column(db.Numeric(5, 4))  # 공사지분율
    client = db.Column(db.String(200))  # 발주처
    funding_source = db.Column(db.String(200))  # 재원
    description = db.Column(db.Text)  # 사업 개요 (국문)
    description_en = db.Column(db.Text)  # 사업 개요 (영문)

    # US$ 백만 단위 용역비
    budget_usd = db.Column(db.Numeric(15, 2))  # 전체용역비(US$ 백만)
    krc_budget_usd = db.Column(db.Numeric(15, 2))  # 공사지분 용역비(US$ 백만)

    # 컨소시엄 구성
    lead_company = db.Column(db.String(200))  # 주관사
    lead_company_ratio = db.Column(db.Numeric(5, 4))  # 주관사 지분율
    jv1 = db.Column(db.String(200))  # JV1
    jv1_ratio = db.Column(db.Numeric(5, 4))  # JV1 지분율
    jv2 = db.Column(db.String(200))  # JV2
    jv2_ratio = db.Column(db.Numeric(5, 4))  # JV2 지분율
    jv3 = db.Column(db.String(200))  # JV3
    jv3_ratio = db.Column(db.Numeric(5, 4))  # JV3 지분율
    jv4 = db.Column(db.String(200))  # JV4
    jv4_ratio = db.Column(db.Numeric(5, 4))  # JV4 지분율
    jv5 = db.Column(db.String(200))  # JV5
    jv5_ratio = db.Column(db.Numeric(5, 4))  # JV5 지분율

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    creator = db.relationship('User', foreign_keys=[created_by])
    personnel = db.relationship('ConsultingPersonnel', backref='consulting_project', lazy='dynamic', cascade='all, delete-orphan')

    TYPE_LABELS = {
        'type_feasibility': ('F/S', '타당성조사'),
        'type_masterplan': ('M/P', '마스터플랜'),
        'type_basic_design': ('B/D', '기본설계'),
        'type_detailed_design': ('D/D', '실시설계'),
        'type_construction': ('C/S', '시공감리'),
        'type_pmc': ('PMC', '사업관리'),
    }

    def _get_type_label(self):
        """체크된 사업형태의 한글 라벨을 조합하여 반환"""
        labels = []
        for field, (abbr, name) in self.TYPE_LABELS.items():
            if getattr(self, field, False):
                labels.append(name)
        if self.project_type_etc:
            labels.append(self.project_type_etc)
        return ', '.join(labels) if labels else (self.project_type or '')

    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'contractYear': self.contract_year,
            'status': self.status,
            'country': self.country,
            'latitude': float(self.latitude) if self.latitude else None,
            'longitude': float(self.longitude) if self.longitude else None,
            'titleEn': self.title_en,
            'titleKr': self.title_kr,
            'projectType': self.project_type,
            'typeFeasibility': self.type_feasibility or False,
            'typeMasterplan': self.type_masterplan or False,
            'typeBasicDesign': self.type_basic_design or False,
            'typeDetailedDesign': self.type_detailed_design or False,
            'typeConstruction': self.type_construction or False,
            'typePmc': self.type_pmc or False,
            'projectTypeEtc': self.project_type_etc,
            'projectTypeLabel': self._get_type_label(),
            'startDate': normalize_date_dot(self.start_date),
            'endDate': normalize_date_dot(self.end_date),
            'budget': float(self.budget) if self.budget else 0,
            'totalBudget': float(self.total_budget) if self.total_budget else 0,
            'krcBudget': float(self.krc_budget) if self.krc_budget else 0,
            'krcShareRatio': float(self.krc_share_ratio) if self.krc_share_ratio else 0,
            'client': self.client,
            'fundingSource': self.funding_source,
            'budgetUsd': float(self.budget_usd) if self.budget_usd else None,
            'krcBudgetUsd': float(self.krc_budget_usd) if self.krc_budget_usd else None,
            'description': self.description,
            'descriptionEn': self.description_en,
            'leadCompany': self.lead_company,
            'leadCompanyRatio': float(self.lead_company_ratio) if self.lead_company_ratio else None,
            'jv1': self.jv1,
            'jv1Ratio': float(self.jv1_ratio) if self.jv1_ratio else None,
            'jv2': self.jv2,
            'jv2Ratio': float(self.jv2_ratio) if self.jv2_ratio else None,
            'jv3': self.jv3,
            'jv3Ratio': float(self.jv3_ratio) if self.jv3_ratio else None,
            'jv4': self.jv4,
            'jv4Ratio': float(self.jv4_ratio) if self.jv4_ratio else None,
            'jv5': self.jv5,
            'jv5Ratio': float(self.jv5_ratio) if self.jv5_ratio else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class ConsultingPersonnel(db.Model):
    """해외기술용역 인력 모델"""
    __tablename__ = 'consulting_personnel'

    id = db.Column(db.Integer, primary_key=True)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100))  # PM, 팀장, 팀원, 전문가 등
    position = db.Column(db.String(100))
    affiliation = db.Column(db.String(200))  # 소속

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_deployed = db.Column(db.Boolean, default=False)  # 파견 여부

    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(50))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'name': self.name,
            'role': self.role,
            'position': self.position,
            'affiliation': self.affiliation,
            'startDate': format_date_dot(self.start_date),
            'endDate': format_date_dot(self.end_date),
            'isDeployed': self.is_deployed
        }


class OdaProject(db.Model):
    """ODA 사업 전용 모델"""
    __tablename__ = 'oda_projects'
    
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, index=True)  # 번호
    
    country = db.Column(db.String(100), nullable=False, index=True)  # 국가
    latitude = db.Column(db.Numeric(10, 7))  # 위도
    longitude = db.Column(db.Numeric(10, 7))  # 경도
    
    title = db.Column(db.String(500), nullable=False)  # 국문사업명
    title_en = db.Column(db.String(500))  # 영문사업명
    description = db.Column(db.Text)  # 사업 설명 (content)

    contract_year = db.Column(db.Integer)  # 수주년도
    period = db.Column(db.String(50))  # 사업기간 (예: '20-'25)
    budget = db.Column(db.Numeric(15, 2))  # 예산(백만원)

    project_type = db.Column(db.String(100))  # 사업형태 (양자무상, 다자성양자 등)
    status = db.Column(db.String(50))  # 진행상태
    continent = db.Column(db.String(50))  # 대륙
    client = db.Column(db.String(200))  # 발주처
    
    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # nullable로 변경
    
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'country': self.country,
            'latitude': float(self.latitude) if self.latitude else None,
            'longitude': float(self.longitude) if self.longitude else None,
            'title': self.title,
            'titleKr': self.title,
            'titleEn': self.title_en,
            'description': self.description,
            'contractYear': self.contract_year,
            'period': self.period,
            'budget': float(self.budget) if self.budget else 0,
            'projectType': self.project_type,
            'status': self.status,
            'continent': self.continent,
            'client': self.client,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator and hasattr(self, 'creator') else None
        }


class OdaReport(db.Model):
    """ODA 사업 보고서 관리 모델"""
    __tablename__ = 'oda_reports'
    __table_args__ = (
        db.Index('idx_oda_report_project_type', 'oda_project_id', 'report_type'),
    )

    id = db.Column(db.Integer, primary_key=True)
    oda_project_id = db.Column(db.Integer, db.ForeignKey('oda_projects.id'), nullable=False)

    # 보고서 타입: pcp, implementation_plan, fs, rod, proposal, pmc, performance
    report_type = db.Column(db.String(50), nullable=False)

    # 파일 정보
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(20))

    # 메타 정보
    description = db.Column(db.Text)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    oda_project = db.relationship('OdaProject', backref='reports')
    creator = db.relationship('User', foreign_keys=[created_by])

    def to_dict(self):
        report_type_names = {
            'pcp': 'PCP',
            'implementation_plan': '무상원조시행계획서',
            'fs': '타당성조사보고서(F/S)',
            'rod': '협의의사록(ROD)',
            'proposal': '업체제안서 및 발표자료',
            'pmc': '실적보고서',
            'performance': '성과관리보고서',
            'post_evaluation': '사후평가'
        }

        return {
            'id': self.id,
            'odaProjectId': self.oda_project_id,
            'reportType': self.report_type,
            'reportTypeName': report_type_names.get(self.report_type, self.report_type),
            'fileName': self.file_name,
            'filePath': self.file_path,
            'fileSize': self.file_size,
            'fileType': self.file_type,
            'description': self.description,
            'uploadDate': self.upload_date.isoformat() if self.upload_date else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class OdaNote(db.Model):
    """ODA 사업 비고(메모+파일) 모델"""
    __tablename__ = 'oda_notes'

    id = db.Column(db.Integer, primary_key=True)
    oda_project_id = db.Column(db.Integer, db.ForeignKey('oda_projects.id'), nullable=False, unique=True)

    # 메모 (500자 이내)
    memo = db.Column(db.String(500))

    # 첨부 파일 정보
    file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(20))

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    oda_project = db.relationship('OdaProject', backref=db.backref('note', uselist=False))
    creator = db.relationship('User', foreign_keys=[created_by])

    def to_dict(self):
        return {
            'id': self.id,
            'odaProjectId': self.oda_project_id,
            'memo': self.memo,
            'fileName': self.file_name,
            'filePath': self.file_path,
            'fileSize': self.file_size,
            'fileType': self.file_type,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class OdaManualData(db.Model):
    """ODA 수기 입력 데이터 (2024년 이전)"""
    __tablename__ = 'oda_manual_data'

    id = db.Column(db.Integer, primary_key=True)
    oda_project_id = db.Column(db.Integer, db.ForeignKey('oda_projects.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)  # 연도
    revenue = db.Column(db.Integer, default=0)  # 수익(천원)
    cost = db.Column(db.Integer, default=0)  # 비용(천원)

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    oda_project = db.relationship('OdaProject', backref='manual_data')
    creator = db.relationship('User', foreign_keys=[created_by])
    updater = db.relationship('User', foreign_keys=[updated_by])

    # Unique constraint: 한 프로젝트의 한 연도에 하나의 레코드만
    __table_args__ = (
        db.UniqueConstraint('oda_project_id', 'year', name='uix_oda_project_year'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'odaProjectId': self.oda_project_id,
            'year': self.year,
            'revenue': self.revenue,
            'cost': self.cost,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None,
            'updatedBy': self.updater.name if self.updater else None
        }


class MethaneBudgetData(db.Model):
    """메탄감축사업 연도별 예산 데이터"""
    __tablename__ = 'methane_budget_data'

    id = db.Column(db.Integer, primary_key=True)
    methane_project_id = db.Column(db.Integer, db.ForeignKey('methane_projects.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)  # 연도
    budget_amount = db.Column(db.Integer, default=0)  # 예산(천원)

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    methane_project = db.relationship('MethaneProject', backref='budget_data')
    creator = db.relationship('User', foreign_keys=[created_by])
    updater = db.relationship('User', foreign_keys=[updated_by])

    # Unique constraint: 한 프로젝트의 한 연도에 하나의 레코드만
    __table_args__ = (
        db.UniqueConstraint('methane_project_id', 'year', name='uix_methane_project_year'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'methaneProjectId': self.methane_project_id,
            'year': self.year,
            'budgetAmount': self.budget_amount,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None,
            'updatedBy': self.updater.name if self.updater else None
        }


class MethaneProject(db.Model):
    """메탄감축사업 전용 모델"""
    __tablename__ = 'methane_projects'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(50))  # 사업번호
    contract_year = db.Column(db.Integer, index=True)  # 계약연도

    country = db.Column(db.String(100), nullable=False, index=True)
    location = db.Column(db.String(200))  # 지역명 (예: 캄퐁톰)

    latitude = db.Column(db.Numeric(10, 7))
    longitude = db.Column(db.Numeric(10, 7))

    # 사업 정보
    title_kr = db.Column(db.String(500))  # 한글 사업명
    title_en = db.Column(db.String(500))  # 영문 사업명
    project_type = db.Column(db.String(100))  # 사업 유형

    start_date = db.Column(db.Date)  # 시작일
    end_date = db.Column(db.Date)  # 종료일
    period = db.Column(db.String(50))  # 사업기간 (텍스트)

    budget = db.Column(db.Numeric(15, 2))  # 사업비(백만원)
    client = db.Column(db.String(200))  # 발주처
    description = db.Column(db.Text)  # 사업 설명

    # 메탄감축 관련 정보
    reduction_target = db.Column(db.Numeric(15, 2))  # 목표 감축량 (톤)
    reduction_achieved = db.Column(db.Numeric(15, 2))  # 실제 감축량 (톤)
    technology_type = db.Column(db.String(100))  # 기술 유형

    status = db.Column(db.String(50))  # 진행상태

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'contractYear': self.contract_year,
            'country': self.country,
            'location': self.location,
            'latitude': float(self.latitude) if self.latitude else None,
            'longitude': float(self.longitude) if self.longitude else None,
            'titleKr': self.title_kr,
            'titleEn': self.title_en,
            'projectType': self.project_type,
            'startDate': self.start_date.isoformat() if self.start_date else None,
            'endDate': self.end_date.isoformat() if self.end_date else None,
            'period': self.period,
            'budget': float(self.budget) if self.budget else 0,
            'client': self.client,
            'description': self.description,
            'reductionTarget': float(self.reduction_target) if self.reduction_target else None,
            'reductionAchieved': float(self.reduction_achieved) if self.reduction_achieved else None,
            'technologyType': self.technology_type,
            'status': self.status,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class ProfitabilityData(db.Model):
    """수익성분석 데이터 모델"""
    __tablename__ = 'profitability_data'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, index=True)  # 조회년도
    month_from = db.Column(db.Integer, default=1)  # 시작월
    month_to = db.Column(db.Integer, default=12)  # 종료월
    
    category = db.Column(db.String(50), nullable=False, index=True)  # 국제협력, 해외농업개발지원, 해외용역
    project_name = db.Column(db.String(300), nullable=False)  # 프로젝트명
    wbs_code = db.Column(db.String(50))  # WBS 코드
    
    revenue = db.Column(db.Numeric(15, 0), default=0)  # 수익(A) (천원)
    direct_cost = db.Column(db.Numeric(15, 0), default=0)  # 직접비(B)
    labor_cost = db.Column(db.Numeric(15, 0), default=0)  # 인건비
    expense = db.Column(db.Numeric(15, 0), default=0)  # 경비
    total_cost = db.Column(db.Numeric(15, 0), default=0)  # 합계(C)
    profit = db.Column(db.Numeric(15, 0), default=0)  # 사업손익
    earned_revenue = db.Column(db.Numeric(15, 0), default=0)  # 가득수익
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    creator = db.relationship('User', foreign_keys=[created_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'monthFrom': self.month_from,
            'monthTo': self.month_to,
            'category': self.category,
            'projectName': self.project_name,
            'wbsCode': self.wbs_code,
            'revenue': int(self.revenue) if self.revenue else 0,
            'directCost': int(self.direct_cost) if self.direct_cost else 0,
            'laborCost': int(self.labor_cost) if self.labor_cost else 0,
            'expense': int(self.expense) if self.expense else 0,
            'totalCost': int(self.total_cost) if self.total_cost else 0,
            'profit': int(self.profit) if self.profit else 0,
            'earnedRevenue': int(self.earned_revenue) if self.earned_revenue else 0,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class Proposal(db.Model):
    """제안서 관리 모델"""
    __tablename__ = 'proposals'

    id = db.Column(db.Integer, primary_key=True)

    # 프로젝트 참조 (사업 선택 시 연결, 직접입력 시 NULL)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=True, index=True)

    # 기본 정보
    title = db.Column(db.String(500), nullable=False)  # 사업명
    country = db.Column(db.String(100), index=True)  # 대상국가
    client = db.Column(db.String(200))  # 발주처

    # 제안 정보
    submission_date = db.Column(db.Date)  # 제출일
    budget = db.Column(db.Numeric(15, 2))  # 제안 예산(백만원)
    project_period = db.Column(db.String(100))  # 사업기간

    # 결과
    result = db.Column(db.String(20), default='심사중')  # 심사중, 선정, 탈락
    result_date = db.Column(db.Date)  # 결과발표일

    # 상세 정보
    description = db.Column(db.Text)  # 사업개요
    team_members = db.Column(db.Text)  # 참여인력
    remarks = db.Column(db.Text)  # 비고

    # 파일 정보 (기존 - 하위 호환성)
    file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)

    # 기술제안서
    technical_file_name = db.Column(db.String(255))
    technical_file_path = db.Column(db.String(500))
    technical_file_size = db.Column(db.Integer)

    # 가격제안서
    price_file_name = db.Column(db.String(255))
    price_file_path = db.Column(db.String(500))
    price_file_size = db.Column(db.Integer)
    price_password = db.Column(db.Text)  # 가격제안서 비밀번호 (암호화 PDF용)

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by])
    consulting_project = db.relationship('ConsultingProject', foreign_keys=[consulting_project_id])

    def to_dict(self):
        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'title': self.title,
            'country': self.country,
            'client': self.client,
            'submissionDate': format_date_dot(self.submission_date),
            'budget': float(self.budget) if self.budget else 0,
            'projectPeriod': self.project_period,
            'result': self.result,
            'resultDate': format_date_dot(self.result_date),
            'description': self.description,
            'teamMembers': self.team_members,
            'remarks': self.remarks,
            'fileName': self.file_name,
            'filePath': self.file_path,
            'fileSize': self.file_size,
            'technicalFileName': self.technical_file_name,
            'technicalFilePath': self.technical_file_path,
            'technicalFileSize': self.technical_file_size,
            'priceFileName': self.price_file_name,
            'priceFilePath': self.price_file_path,
            'priceFileSize': self.price_file_size,
            'pricePassword': bool(self.price_password),
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class ProposalStatus(db.Model):
    """사업제안 및 수주현황 모델"""
    __tablename__ = 'proposal_statuses'

    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(500), nullable=False)
    funding = db.Column(db.String(100))  # 재원 (EDCF, WB, KOICA 등)
    sort_order = db.Column(db.Integer, default=0)  # 정렬순서

    # 각 단계별 일자
    eoi_date = db.Column(db.String(20))           # EOI제출 일자
    shortlist_date = db.Column(db.String(20))      # Short-list 일자
    announcement_date = db.Column(db.String(20))   # 사업공고 일자
    proposal_date = db.Column(db.String(20))       # 제안서제출 일자
    selection_date = db.Column(db.String(20))      # 선정발표 일자
    negotiation_date = db.Column(db.String(20))    # 가격기술협상 일자
    contract_date = db.Column(db.String(20))       # 계약 일자

    # 각 단계별 진행중 여부
    eoi_progress = db.Column(db.Boolean, default=False)
    shortlist_progress = db.Column(db.Boolean, default=False)
    announcement_progress = db.Column(db.Boolean, default=False)
    proposal_progress = db.Column(db.Boolean, default=False)
    selection_progress = db.Column(db.Boolean, default=False)
    negotiation_progress = db.Column(db.Boolean, default=False)
    contract_progress = db.Column(db.Boolean, default=False)

    # 컨소시엄/지분율
    consortium = db.Column(db.String(500))  # 컨소시엄 구성 (예: "KRC/○○엔지니어링")
    share_ratio = db.Column(db.String(50))  # 지분율 (예: "30%", "단독")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'projectName': self.project_name,
            'funding': self.funding,
            'sortOrder': self.sort_order,
            'consortium': self.consortium,
            'shareRatio': self.share_ratio,
            'eoiDate': normalize_date_dot(self.eoi_date),
            'shortlistDate': normalize_date_dot(self.shortlist_date),
            'announcementDate': normalize_date_dot(self.announcement_date),
            'proposalDate': normalize_date_dot(self.proposal_date),
            'selectionDate': normalize_date_dot(self.selection_date),
            'negotiationDate': normalize_date_dot(self.negotiation_date),
            'contractDate': normalize_date_dot(self.contract_date),
            'eoiProgress': self.eoi_progress,
            'shortlistProgress': self.shortlist_progress,
            'announcementProgress': self.announcement_progress,
            'proposalProgress': self.proposal_progress,
            'selectionProgress': self.selection_progress,
            'negotiationProgress': self.negotiation_progress,
            'contractProgress': self.contract_progress,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }


class PerformanceRecord(db.Model):
    """실적관리 (준공증명서) 모델"""
    __tablename__ = 'performance_records'

    id = db.Column(db.Integer, primary_key=True)

    # 프로젝트 참조 (계약서처럼 프로젝트 선택 방식으로 변경)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=True, index=True)

    # 기본 정보
    title = db.Column(db.String(500), nullable=False)  # 사업명
    country = db.Column(db.String(100), index=True)  # 대상국가
    client = db.Column(db.String(200))  # 발주처
    funding_source = db.Column(db.String(200))  # 재원

    # 계약 정보
    contract_amount = db.Column(db.Numeric(15, 2))  # 계약금액(백만원)
    krc_amount = db.Column(db.Numeric(15, 2))  # 공사지분(백만원)

    # 계약금액 통화 정보
    contract_amount_usd = db.Column(db.Numeric(15, 2))  # 계약금액 USD
    contract_amount_exchange_rate = db.Column(db.Numeric(10, 4))  # 계약금액 환율
    contract_amount_currency = db.Column(db.String(10), default='KRW')  # 계약금액 통화

    # 공사지분 통화 정보
    krc_amount_usd = db.Column(db.Numeric(15, 2))  # 공사지분 USD
    krc_amount_exchange_rate = db.Column(db.Numeric(10, 4))  # 공사지분 환율
    krc_amount_currency = db.Column(db.String(10), default='KRW')  # 공사지분 통화

    # 기간 정보
    contract_date = db.Column(db.Date)  # 계약일
    start_date = db.Column(db.Date)  # 착수일
    end_date = db.Column(db.Date)  # 준공일

    # 상세 정보
    project_type = db.Column(db.String(100))  # 사업유형
    consortium_info = db.Column(db.Text)  # 컨소시엄 구성
    description = db.Column(db.Text)  # 사업개요
    achievements = db.Column(db.Text)  # 주요성과
    remarks = db.Column(db.Text)  # 비고

    # 파일 정보 (준공증명서)
    file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by])
    consulting_project = db.relationship('ConsultingProject', foreign_keys=[consulting_project_id])

    def to_dict(self):
        # 시작일/종료일: 레코드 자체 값 우선, 없으면 연결된 프로젝트에서 가져오기
        start_date = self.start_date
        end_date = self.end_date
        funding_source = self.funding_source
        client = self.client

        if self.consulting_project:
            if not start_date and self.consulting_project.start_date:
                start_date = self.consulting_project.start_date
            if not end_date and self.consulting_project.end_date:
                end_date = self.consulting_project.end_date
            if not funding_source and self.consulting_project.funding_source:
                funding_source = self.consulting_project.funding_source
            if not client and self.consulting_project.client:
                client = self.consulting_project.client

        # 날짜 포맷팅 (Date 객체 또는 문자열 모두 처리)
        def format_date(d):
            return format_date_dot(d) if hasattr(d, 'strftime') else normalize_date_dot(d)

        # 한글/영문 사업명 및 컨소시엄
        title_kr = None
        title_en = None
        lead_company = None
        jv_partners = []
        if self.consulting_project:
            title_kr = self.consulting_project.title_kr
            title_en = self.consulting_project.title_en
            lead_company = self.consulting_project.lead_company
            for jv in [self.consulting_project.jv1, self.consulting_project.jv2,
                        self.consulting_project.jv3, self.consulting_project.jv4,
                        self.consulting_project.jv5]:
                if jv:
                    jv_partners.append(jv)

        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'title': self.title,
            'titleKr': title_kr,
            'titleEn': title_en,
            'country': self.country,
            'client': client,
            'fundingSource': funding_source,
            'contractAmount': float(self.contract_amount) if self.contract_amount else 0,
            'contractAmountUsd': float(self.contract_amount_usd) if self.contract_amount_usd else None,
            'contractAmountExchangeRate': float(self.contract_amount_exchange_rate) if self.contract_amount_exchange_rate else None,
            'contractAmountCurrency': self.contract_amount_currency or 'KRW',
            'krcAmount': float(self.krc_amount) if self.krc_amount else 0,
            'krcAmountUsd': float(self.krc_amount_usd) if self.krc_amount_usd else None,
            'krcAmountExchangeRate': float(self.krc_amount_exchange_rate) if self.krc_amount_exchange_rate else None,
            'krcAmountCurrency': self.krc_amount_currency or 'KRW',
            'contractDate': format_date_dot(self.contract_date),
            'startDate': format_date(start_date),
            'endDate': format_date(end_date),
            'projectType': self.project_type,
            'consortiumInfo': self.consortium_info,
            'leadCompany': lead_company,
            'jvPartners': jv_partners,
            'description': self.description,
            'achievements': self.achievements,
            'remarks': self.remarks,
            'fileName': self.file_name,
            'filePath': self.file_path,
            'fileSize': self.file_size,
            'krcShareRatio': float(self.consulting_project.krc_share_ratio) if self.consulting_project and self.consulting_project.krc_share_ratio else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class BoardPost(db.Model):
    """기타 게시판 모델 (해외기술용역/국제협력/해외진출지원)"""
    __tablename__ = 'board_posts'

    id = db.Column(db.Integer, primary_key=True)
    board_type = db.Column(db.String(50), default='overseas_tech', index=True)  # overseas_tech, oda, expansion
    category = db.Column(db.String(100), index=True)  # 구분 (색인용)
    title = db.Column(db.String(500), nullable=False)
    content = db.Column(db.Text)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=True)
    oda_project_id = db.Column(db.Integer, db.ForeignKey('oda_projects.id'), nullable=True)

    # 파일 정보
    file_name = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    creator = db.relationship('User', foreign_keys=[created_by])
    consulting_project = db.relationship('ConsultingProject', foreign_keys=[consulting_project_id])
    oda_project = db.relationship('OdaProject', foreign_keys=[oda_project_id])

    def to_dict(self):
        # 관련사업명 결정
        project_name = '관련없음'
        if self.board_type == 'oda' and self.oda_project:
            project_name = self.oda_project.title
        elif self.consulting_project:
            project_name = self.consulting_project.title_kr

        return {
            'id': self.id,
            'boardType': self.board_type,
            'category': self.category,
            'title': self.title,
            'content': self.content,
            'consultingProjectId': self.consulting_project_id,
            'odaProjectId': self.oda_project_id,
            'projectName': project_name,
            'fileName': self.file_name,
            'filePath': self.file_path,
            'fileSize': self.file_size,
            'createdAt': self.created_at.strftime('%Y-%m-%d') if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None,
            'createdById': self.created_by
        }


class SystemConfig(db.Model):
    """시스템 설정 모델"""
    __tablename__ = 'system_config'

    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    config_value = db.Column(db.Text)
    description = db.Column(db.String(500))  # 설정 설명
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'configKey': self.config_key,
            'configValue': self.config_value,
            'description': self.description,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class AccessLog(db.Model):
    """접속 로그 모델"""
    __tablename__ = 'access_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    username = db.Column(db.String(50))  # 로그인 시도 ID (실패 시에도 기록)
    ip_address = db.Column(db.String(45))  # IPv6 지원
    user_agent = db.Column(db.String(500))  # 브라우저 정보
    action = db.Column(db.String(50), default='login')  # login, logout, login_failed
    success = db.Column(db.Boolean, default=True)  # 성공 여부
    message = db.Column(db.String(200))  # 추가 메시지
    created_at = db.Column(db.DateTime, default=get_kst_now, index=True)  # 한국 시간

    user = db.relationship('User', foreign_keys=[user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'userId': self.user_id,
            'username': self.username,
            'userName': self.user.name if self.user else self.username,
            'ipAddress': self.ip_address,
            'userAgent': self.user_agent,
            'action': self.action,
            'success': self.success,
            'message': self.message,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


class Contract(db.Model):
    """해외기술용역 계약서 관리 모델"""
    __tablename__ = 'contracts'
    __table_args__ = (
        db.Index('idx_contract_project_order', 'consulting_project_id', 'order_number'),
    )

    id = db.Column(db.Integer, primary_key=True)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=False)
    document_type = db.Column(db.String(20), default='contract')  # 'contract' (계약서) 또는 'final_report' (최종보고서)
    order_number = db.Column(db.Integer, default=1)  # 차수 (1차, 2차, ...) - 계약서만 사용

    # 파일 정보
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(20))

    # 메타 정보
    description = db.Column(db.Text)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    consulting_project = db.relationship('ConsultingProject', backref='contracts')
    creator = db.relationship('User', foreign_keys=[created_by])

    def to_dict(self):
        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'documentType': self.document_type,
            'orderNumber': self.order_number,
            'fileName': self.file_name,
            'filePath': self.file_path,
            'fileSize': self.file_size,
            'fileType': self.file_type,
            'description': self.description,
            'uploadDate': self.upload_date.isoformat() if self.upload_date else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None
        }


class TorRfp(db.Model):
    """해외기술용역 TOR/RFP 관리 모델"""
    __tablename__ = 'tor_rfp'

    id = db.Column(db.Integer, primary_key=True)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=True, index=True)

    # 직접입력용 필드 (consulting_project_id가 NULL일 때 사용)
    title = db.Column(db.String(500))  # 사업명
    country = db.Column(db.String(100))  # 국가

    # TOR 파일 정보 (과업설명서)
    tor_file_name = db.Column(db.String(255))
    tor_file_path = db.Column(db.String(500))
    tor_file_size = db.Column(db.Integer)
    tor_file_type = db.Column(db.String(20))

    # RFP 파일 정보 (제안요청서)
    rfp_file_name = db.Column(db.String(255))
    rfp_file_path = db.Column(db.String(500))
    rfp_file_size = db.Column(db.Integer)
    rfp_file_type = db.Column(db.String(20))

    # 메타 정보
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relationships
    consulting_project = db.relationship('ConsultingProject', backref='tor_rfp')
    creator = db.relationship('User', foreign_keys=[created_by])
    updater = db.relationship('User', foreign_keys=[updated_by])

    def to_dict(self):
        project = self.consulting_project
        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'projectTitle': project.title_kr if project else self.title,
            'projectCountry': project.country if project else self.country,
            'torFileName': self.tor_file_name,
            'torFilePath': self.tor_file_path,
            'torFileSize': self.tor_file_size,
            'torFileType': self.tor_file_type,
            'rfpFileName': self.rfp_file_name,
            'rfpFilePath': self.rfp_file_path,
            'rfpFileSize': self.rfp_file_size,
            'rfpFileType': self.rfp_file_type,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None,
            'updatedBy': self.updater.name if self.updater else None
        }


# EOI (Expression of Interest) 모델
class Eoi(db.Model):
    """EOI 제출 관리"""
    __tablename__ = 'eois'

    id = db.Column(db.Integer, primary_key=True)

    # 프로젝트 연결 (선택적) - 수기 입력도 가능하므로 nullable=True
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=True)

    # 수기 입력 필드
    title = db.Column(db.String(500), nullable=True)  # 사업명 (수기 입력 또는 프로젝트에서)
    country = db.Column(db.String(100), nullable=True)  # 대상국
    client = db.Column(db.String(200), nullable=True)  # 발주처

    # EOI 정보
    submission_date = db.Column(db.Date, nullable=True)  # 제출일
    result = db.Column(db.String(50), nullable=True)  # 결과 (대기중, 통과, 탈락)
    remarks = db.Column(db.Text, nullable=True)  # 비고

    # EOI 파일
    eoi_file_name = db.Column(db.String(255), nullable=True)
    eoi_file_path = db.Column(db.String(500), nullable=True)
    eoi_file_size = db.Column(db.Integer, nullable=True)
    eoi_file_type = db.Column(db.String(50), nullable=True)

    # 타임스탬프
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # 관계
    consulting_project = db.relationship('ConsultingProject', backref='eois')
    creator = db.relationship('User', foreign_keys=[created_by])
    updater = db.relationship('User', foreign_keys=[updated_by])

    def to_dict(self):
        project = self.consulting_project
        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'projectTitle': project.title_kr if project else self.title,
            'projectCountry': project.country if project else self.country,
            'client': self.client,
            'submissionDate': format_date_dot(self.submission_date),
            'result': self.result,
            'remarks': self.remarks,
            'eoiFileName': self.eoi_file_name,
            'eoiFilePath': self.eoi_file_path,
            'eoiFileSize': self.eoi_file_size,
            'eoiFileType': self.eoi_file_type,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
            'createdBy': self.creator.name if self.creator else None,
            'updatedBy': self.updater.name if self.updater else None
        }


class Banner(db.Model):
    """배너 모델"""
    __tablename__ = 'banners'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    image_path = db.Column(db.String(500), nullable=False)
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_kst_now)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'imagePath': self.image_path,
            'displayOrder': self.display_order,
            'isActive': self.is_active,
            'createdAt': self.created_at.isoformat() if self.created_at else None
        }


class ProjectLifecycle(db.Model):
    """사업 라이프사이클 모델 - 계약 이후 단계 추적"""
    __tablename__ = 'project_lifecycles'

    id = db.Column(db.Integer, primary_key=True)
    consulting_project_id = db.Column(db.Integer, db.ForeignKey('consulting_projects.id'), nullable=False, unique=True, index=True)

    # 착수
    kickoff_date = db.Column(db.String(20))
    kickoff_completed = db.Column(db.Boolean, default=False)
    # 설계완료 (설계 사업용)
    design_date = db.Column(db.String(20))
    design_completed = db.Column(db.Boolean, default=False)
    # 시공완료 (시공감리 사업용)
    construction_date = db.Column(db.String(20))
    construction_completed = db.Column(db.Boolean, default=False)
    # 준공
    completion_date = db.Column(db.String(20))
    completion_completed = db.Column(db.Boolean, default=False)

    # EOI ~ 계약 단계 (수동 입력 지원)
    eoi_date = db.Column(db.String(20))
    eoi_completed = db.Column(db.Boolean, default=False)
    eoi_progress = db.Column(db.Boolean, default=False)
    shortlist_date = db.Column(db.String(20))
    shortlist_completed = db.Column(db.Boolean, default=False)
    shortlist_progress = db.Column(db.Boolean, default=False)
    proposal_date = db.Column(db.String(20))
    proposal_completed = db.Column(db.Boolean, default=False)
    proposal_progress = db.Column(db.Boolean, default=False)
    contract_date = db.Column(db.String(20))
    contract_completed = db.Column(db.Boolean, default=False)
    contract_progress = db.Column(db.Boolean, default=False)
    kickoff_progress = db.Column(db.Boolean, default=False)
    design_progress = db.Column(db.Boolean, default=False)
    construction_progress = db.Column(db.Boolean, default=False)
    completion_progress = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=get_kst_now)
    updated_at = db.Column(db.DateTime, default=get_kst_now, onupdate=get_kst_now)

    consulting_project = db.relationship('ConsultingProject', backref='lifecycle')

    def to_dict(self):
        return {
            'id': self.id,
            'consultingProjectId': self.consulting_project_id,
            'eoiDate': self.eoi_date,
            'eoiCompleted': self.eoi_completed,
            'eoiProgress': self.eoi_progress,
            'shortlistDate': self.shortlist_date,
            'shortlistCompleted': self.shortlist_completed,
            'shortlistProgress': self.shortlist_progress,
            'proposalDate': self.proposal_date,
            'proposalCompleted': self.proposal_completed,
            'proposalProgress': self.proposal_progress,
            'contractDate': self.contract_date,
            'contractCompleted': self.contract_completed,
            'contractProgress': self.contract_progress,
            'kickoffDate': self.kickoff_date,
            'kickoffCompleted': self.kickoff_completed,
            'kickoffProgress': self.kickoff_progress,
            'designDate': self.design_date,
            'designCompleted': self.design_completed,
            'designProgress': self.design_progress,
            'constructionDate': self.construction_date,
            'constructionCompleted': self.construction_completed,
            'constructionProgress': self.construction_progress,
            'completionDate': self.completion_date,
            'completionCompleted': self.completion_completed,
            'completionProgress': self.completion_progress,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class BidNotice(db.Model):
    """발주공고 모델 - 디스코드 봇이 수집한 국제기구 발주공고"""
    __tablename__ = 'bid_notices'

    id             = db.Column(db.Integer, primary_key=True)
    source         = db.Column(db.String(50),  nullable=False, index=True)   # worldbank, adb, koica 등
    title          = db.Column(db.String(500), nullable=False)
    title_ko       = db.Column(db.String(500))                               # HF NLLB 번역 결과 (없으면 NULL)
    text_excerpt_ko = db.Column(db.Text)                                     # 본문발췌 한국어 번역 (NULL=미번역, ''=발췌 없음)
    country        = db.Column(db.String(100))
    client         = db.Column(db.String(200))                               # 발주처
    sector         = db.Column(db.String(100))                               # agriculture, irrigation 등
    contract_value = db.Column(db.String(100))                               # "$2.3M" 형태 문자열
    deadline       = db.Column(db.String(50))                                # "2026-05-30" 문자열
    source_url     = db.Column(db.String(500), nullable=False, unique=True)  # 중복 방지
    status         = db.Column(db.String(20),  default='new', index=True)    # new / reviewed / applied / closed
    raw_data       = db.Column(db.JSON)                                      # 봇이 보낸 원본 전체

    # ddkkbot 작업 결과 저장 (PR1 신규)
    summary_ko     = db.Column(db.Text)                                      # 한국어 요약 (1차 미사용, 컬럼만 확보)
    slides_path       = db.Column(db.String(500))                            # backend/uploads/slides/<id>_<safe>.pptx
    slides_url        = db.Column(db.String(500))                            # 다운로드 경로 또는 NotebookLM 공유 URL
    infographic_path  = db.Column(db.String(500))                            # backend/uploads/infographics/<id>_<safe>.png
    infographic_url   = db.Column(db.String(500))                            # 다운로드 API 경로 또는 외부 URL
    last_task_at      = db.Column(db.DateTime)                               # 마지막 작업 완료 시각

    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    # 아카이브 — NULL 이면 활성, 값 있으면 비활성. ARCHIVE_RETENTION_DAYS 경과 시 hard-delete.
    archived_at    = db.Column(db.DateTime, index=True)
    archive_reason = db.Column(db.String(30))                                # deadline_passed / aged_out / source_removed

    def to_dict(self):
        details = None
        if isinstance(self.raw_data, dict):
            details = (self.raw_data.get('wb_details')
                       or self.raw_data.get('adb_details')
                       or self.raw_data.get('afdb_details'))
        if isinstance(details, dict) and self.text_excerpt_ko:
            details = {**details, 'text_excerpt_ko': self.text_excerpt_ko}
        return {
            'id': self.id,
            'source': self.source,
            'title': self.title,
            'titleKo': self.title_ko,
            'country': self.country,
            'client': self.client,
            'sector': self.sector,
            'contractValue': self.contract_value,
            'deadline': self.deadline,
            'sourceUrl': self.source_url,
            'status': self.status,
            'summaryKo': self.summary_ko,
            'slidesUrl': self.slides_url,
            'infographicUrl': self.infographic_url,
            'lastTaskAt': self.last_task_at.isoformat() if self.last_task_at else None,
            'createdAt': self.created_at.strftime('%Y-%m-%d') if self.created_at else None,
            'archivedAt': self.archived_at.isoformat() if self.archived_at else None,
            'archiveReason': self.archive_reason,
            'details': details,
        }


class ScrapingRun(db.Model):
    """발주공고 수집 실행 이력 - 소스별 건수/에러, 트리거 타입을 기록"""
    __tablename__ = 'scraping_runs'

    id            = db.Column(db.Integer, primary_key=True)
    run_at        = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    total_found   = db.Column(db.Integer, default=0)
    total_created = db.Column(db.Integer, default=0)
    total_skipped = db.Column(db.Integer, default=0)
    send_error    = db.Column(db.String(500))    # GBMS 전송 실패 메시지
    sources       = db.Column(db.JSON)           # [{name, count, error}]
    trigger       = db.Column(db.String(20))     # scheduled / manual

    def to_dict(self):
        return {
            'id': self.id,
            'runAt': self.run_at.isoformat() if self.run_at else None,
            'totalFound': self.total_found,
            'totalCreated': self.total_created,
            'totalSkipped': self.total_skipped,
            'sendError': self.send_error,
            'sources': self.sources or [],
            'trigger': self.trigger,
        }


class NoticeTask(db.Model):
    """발주공고 작업 큐 — ddkkbot 워커가 가져가서 처리하는 단위 작업.

    수집 직후 신규 BidNotice 마다 task_type='translate' / 'slides' 가 enqueue 되고,
    워커가 claim → complete/fail 사이클로 소화한다.
    """
    __tablename__ = 'notice_tasks'

    id           = db.Column(db.Integer, primary_key=True)
    notice_id    = db.Column(db.Integer, db.ForeignKey('bid_notices.id'), nullable=False, index=True)
    task_type    = db.Column(db.String(30), nullable=False, index=True)   # translate | slides | summary | review
    status       = db.Column(db.String(20), nullable=False, default='pending', index=True)
                  # pending → claimed → done | failed
    priority     = db.Column(db.Integer, default=0, index=True)            # 작을수록 먼저
    attempts     = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=3)
    worker_id    = db.Column(db.String(100))           # ddkkbot 인스턴스 식별자
    claimed_at   = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    error        = db.Column(db.Text)
    payload      = db.Column(db.JSON)                  # 작업 입력 (예: 번역 대상 필드 list)
    result       = db.Column(db.JSON)                  # 결과 메타 (예: 슬라이드 파일명)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('notice_id', 'task_type', name='uq_notice_task_type'),
        db.Index('ix_notice_tasks_status_priority', 'status', 'priority'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'noticeId': self.notice_id,
            'taskType': self.task_type,
            'status': self.status,
            'priority': self.priority,
            'attempts': self.attempts,
            'maxAttempts': self.max_attempts,
            'workerId': self.worker_id,
            'error': self.error,
            'payload': self.payload,
            'result': self.result,
            'claimedAt': self.claimed_at.isoformat() if self.claimed_at else None,
            'completedAt': self.completed_at.isoformat() if self.completed_at else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }


# Import expansion models
from models.expansion import (
    Company, Loan, LoanPerformance, LoanRepayment,
    LoanProject, CompanyCollateral, PostManagement, MortgageContract
)
