"""
해외진출지원사업(Loan) 관련 모델
"""
from datetime import datetime
from models import db


class Company(db.Model):
    """기업관리 모델"""
    __tablename__ = 'companies'
    
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer)  # 번호
    name = db.Column(db.String(200), nullable=False, index=True)  # 기업명
    size = db.Column(db.String(50))  # 기업규모 (중소기업, 중견기업, 대기업)
    address = db.Column(db.Text)  # 기업주소
    email = db.Column(db.String(200))  # 메일주소
    phone = db.Column(db.String(50))  # 전화번호
    
    created_by = db.Column(db.String(100))  # 등록자
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 등록일
    updated_by = db.Column(db.String(100))  # 수정자
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 수정일
    
    # Relationships
    loans = db.relationship('Loan', backref='company', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'name': self.name,
            'size': self.size,
            'address': self.address,
            'email': self.email,
            'phone': self.phone,
            'createdBy': self.created_by,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedBy': self.updated_by,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class Loan(db.Model):
    """융자관리 모델"""
    __tablename__ = 'loans'
    
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer)  # 번호
    year = db.Column(db.Integer, index=True)  # 연도
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True)  # 기업 FK
    company_name = db.Column(db.String(200), index=True)  # 기업명 (비정규화)
    country = db.Column(db.String(100))  # 국가
    crops = db.Column(db.String(200))  # 작물
    interest_rate = db.Column(db.String(20))  # 이율
    principal = db.Column(db.BigInteger)  # 융자원금 (원)
    repaid_amount = db.Column(db.BigInteger, default=0)  # 상환액
    balance = db.Column(db.BigInteger)  # 잔액
    
    contract_date = db.Column(db.Date)  # 계약연월
    execution_deadline = db.Column(db.Date)  # 집행기한
    maturity_date = db.Column(db.Date)  # 만기일
    payment_due_date = db.Column(db.Date)  # 납부예정일
    payment_month = db.Column(db.String(10))  # 납부약정월
    
    messenger_subscription = db.Column(db.String(10))  # 메신저 수신여부
    business_evaluation = db.Column(db.String(50))  # 사업평가
    post_management = db.Column(db.String(50))  # 사후관리
    
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.String(100))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'year': self.year,
            'companyId': self.company_id,
            'companyName': self.company_name,
            'country': self.country,
            'crops': self.crops,
            'interestRate': self.interest_rate,
            'principal': self.principal,
            'repaidAmount': self.repaid_amount,
            'balance': self.balance,
            'contractDate': self.contract_date.isoformat() if self.contract_date else None,
            'executionDeadline': self.execution_deadline.isoformat() if self.execution_deadline else None,
            'maturityDate': self.maturity_date.isoformat() if self.maturity_date else None,
            'paymentDueDate': self.payment_due_date.isoformat() if self.payment_due_date else None,
            'paymentMonth': self.payment_month,
            'messengerSubscription': self.messenger_subscription,
            'businessEvaluation': self.business_evaluation,
            'postManagement': self.post_management,
            'createdBy': self.created_by,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedBy': self.updated_by,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class LoanPerformance(db.Model):
    """융자사업 추진실적 - 집계 데이터 (표출용)"""
    __tablename__ = 'loan_performance'
    
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(100), index=True)  # 대상국가
    company_count = db.Column(db.Integer)  # 기업수
    company_name = db.Column(db.String(200))  # 기업명
    main_crop = db.Column(db.String(100))  # 주요작물
    
    # 연도별 융자액 (백만원)
    year_2005 = db.Column(db.Integer, default=0)
    year_2006 = db.Column(db.Integer, default=0)
    year_2007 = db.Column(db.Integer, default=0)
    year_2008 = db.Column(db.Integer, default=0)
    year_2009 = db.Column(db.Integer, default=0)
    year_2010 = db.Column(db.Integer, default=0)
    year_2011 = db.Column(db.Integer, default=0)
    year_2012 = db.Column(db.Integer, default=0)
    year_2013 = db.Column(db.Integer, default=0)
    year_2014 = db.Column(db.Integer, default=0)
    year_2015 = db.Column(db.Integer, default=0)
    year_2016 = db.Column(db.Integer, default=0)
    year_2017 = db.Column(db.Integer, default=0)
    year_2018 = db.Column(db.Integer, default=0)
    year_2019 = db.Column(db.Integer, default=0)
    year_2020 = db.Column(db.Integer, default=0)
    year_2021 = db.Column(db.Integer, default=0)
    year_2022 = db.Column(db.Integer, default=0)
    year_2023 = db.Column(db.Integer, default=0)
    year_2024 = db.Column(db.Integer, default=0)
    year_2025 = db.Column(db.Integer, default=0)
    year_2026 = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer)  # 계
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'country': self.country,
            'companyCount': self.company_count,
            'companyName': self.company_name,
            'mainCrop': self.main_crop,
            'year2005': self.year_2005,
            'year2006': self.year_2006,
            'year2007': self.year_2007,
            'year2008': self.year_2008,
            'year2009': self.year_2009,
            'year2010': self.year_2010,
            'year2011': self.year_2011,
            'year2012': self.year_2012,
            'year2013': self.year_2013,
            'year2014': self.year_2014,
            'year2015': self.year_2015,
            'year2016': self.year_2016,
            'year2017': self.year_2017,
            'year2018': self.year_2018,
            'year2019': self.year_2019,
            'year2020': self.year_2020,
            'year2021': self.year_2021,
            'year2022': self.year_2022,
            'year2023': self.year_2023,
            'year2024': self.year_2024,
            'year2025': self.year_2025,
            'year2026': self.year_2026,
            'total': self.total,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class LoanRepayment(db.Model):
    """융자사업 연도별 상환내역 - 집계 데이터 (표출용)"""
    __tablename__ = 'loan_repayment'
    
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(100), index=True)
    company_count = db.Column(db.Integer)
    company_name = db.Column(db.String(200))
    main_crop = db.Column(db.String(100))
    balance = db.Column(db.BigInteger)  # 잔액
    
    # 연도별 상환액 (백만원)
    year_2010 = db.Column(db.Integer, default=0)
    year_2011 = db.Column(db.Integer, default=0)
    year_2012 = db.Column(db.Integer, default=0)
    year_2013 = db.Column(db.Integer, default=0)
    year_2014 = db.Column(db.Integer, default=0)
    year_2015 = db.Column(db.Integer, default=0)
    year_2016 = db.Column(db.Integer, default=0)
    year_2017 = db.Column(db.Integer, default=0)
    year_2018 = db.Column(db.Integer, default=0)
    year_2019 = db.Column(db.Integer, default=0)
    year_2020 = db.Column(db.Integer, default=0)
    year_2021 = db.Column(db.Integer, default=0)
    year_2022 = db.Column(db.Integer, default=0)
    year_2023 = db.Column(db.Integer, default=0)
    year_2024 = db.Column(db.Integer, default=0)
    year_2025 = db.Column(db.Integer, default=0)
    year_2026 = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer)
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'country': self.country,
            'companyCount': self.company_count,
            'companyName': self.company_name,
            'mainCrop': self.main_crop,
            'balance': self.balance,
            'year2010': self.year_2010,
            'year2011': self.year_2011,
            'year2012': self.year_2012,
            'year2013': self.year_2013,
            'year2014': self.year_2014,
            'year2015': self.year_2015,
            'year2016': self.year_2016,
            'year2017': self.year_2017,
            'year2018': self.year_2018,
            'year2019': self.year_2019,
            'year2020': self.year_2020,
            'year2021': self.year_2021,
            'year2022': self.year_2022,
            'year2023': self.year_2023,
            'year2024': self.year_2024,
            'year2025': self.year_2025,
            'year2026': self.year_2026,
            'total': self.total,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class LoanProject(db.Model):
    """융자사업 관리 (표출용)"""
    __tablename__ = 'loan_projects'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, index=True)
    company_name = db.Column(db.String(200), index=True)
    country = db.Column(db.String(100))
    crops = db.Column(db.String(200))
    contract_date = db.Column(db.String(100))  # 계약년월(지급일)
    execution_deadline = db.Column(db.String(50))
    maturity_date = db.Column(db.String(50))
    payment_month = db.Column(db.String(10))
    
    loan_payment = db.Column(db.BigInteger)  # 융자금 지급액
    principal_balance = db.Column(db.BigInteger)  # 원잔금액
    
    collateral_type = db.Column(db.Text)  # 담보종류
    bond_amount = db.Column(db.String(200))  # 채권채고액
    guarantee_period = db.Column(db.String(100))  # 보증기간
    
    business_evaluation = db.Column(db.String(100))
    post_management = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'companyName': self.company_name,
            'country': self.country,
            'crops': self.crops,
            'contractDate': self.contract_date,
            'executionDeadline': self.execution_deadline,
            'maturityDate': self.maturity_date,
            'paymentMonth': self.payment_month,
            'loanPayment': self.loan_payment,
            'principalBalance': self.principal_balance,
            'collateralType': self.collateral_type,
            'bondAmount': self.bond_amount,
            'guaranteePeriod': self.guarantee_period,
            'businessEvaluation': self.business_evaluation,
            'postManagement': self.post_management,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class CompanyCollateral(db.Model):
    """기업별 담보 현황 (표출용)"""
    __tablename__ = 'company_collateral'
    
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer)
    company_name = db.Column(db.String(200), index=True)
    loan_amount = db.Column(db.BigInteger)  # 융자액
    balance = db.Column(db.BigInteger)  # 잔액
    
    # 담보현황 (백만원)
    deposit_pledge = db.Column(db.BigInteger, default=0)  # 예금질권
    payment_guarantee = db.Column(db.BigInteger, default=0)  # 지급보증
    guarantee_insurance = db.Column(db.BigInteger, default=0)  # 보증보험
    real_estate = db.Column(db.BigInteger, default=0)  # 부동산
    total_collateral = db.Column(db.BigInteger)  # 총담보금액
    
    # 비율 (%)
    deposit_pledge_ratio = db.Column(db.Float)
    payment_guarantee_ratio = db.Column(db.Float)
    guarantee_insurance_ratio = db.Column(db.Float)
    real_estate_ratio = db.Column(db.Float)
    
    # 채권
    bond_deposit = db.Column(db.BigInteger, default=0)
    bond_payment_guarantee = db.Column(db.BigInteger, default=0)
    bond_insurance = db.Column(db.BigInteger, default=0)
    bond_real_estate = db.Column(db.BigInteger, default=0)
    bond_total = db.Column(db.BigInteger)
    
    notes = db.Column(db.Text)  # 비고
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'companyName': self.company_name,
            'loanAmount': self.loan_amount,
            'balance': self.balance,
            'depositPledge': self.deposit_pledge,
            'paymentGuarantee': self.payment_guarantee,
            'guaranteeInsurance': self.guarantee_insurance,
            'realEstate': self.real_estate,
            'totalCollateral': self.total_collateral,
            'depositPledgeRatio': self.deposit_pledge_ratio,
            'paymentGuaranteeRatio': self.payment_guarantee_ratio,
            'guaranteeInsuranceRatio': self.guarantee_insurance_ratio,
            'realEstateRatio': self.real_estate_ratio,
            'bondDeposit': self.bond_deposit,
            'bondPaymentGuarantee': self.bond_payment_guarantee,
            'bondInsurance': self.bond_insurance,
            'bondRealEstate': self.bond_real_estate,
            'bondTotal': self.bond_total,
            'notes': self.notes,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class PostManagement(db.Model):
    """사후관리대장 (표출용)"""
    __tablename__ = 'post_management'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, index=True)
    business_operator = db.Column(db.String(200), index=True)  # 사업자
    loan_amount = db.Column(db.String(100))  # 융자금액
    loan_date = db.Column(db.Date)  # 융자일자
    repayment_completion_date = db.Column(db.Date)  # 상환완료예정일
    annual_repayment_date = db.Column(db.String(50))  # 연도별상환일
    
    collateral_provider = db.Column(db.String(200))  # 담보제공자
    collateral_property = db.Column(db.Text)  # 담보부동산
    established_right = db.Column(db.String(100))  # 설정한권리
    
    is_bare_land = db.Column(db.String(10))  # 나대지여부
    is_superficies_set = db.Column(db.String(10))  # 지상권설정여부
    notes = db.Column(db.Text)  # 비고
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'businessOperator': self.business_operator,
            'loanAmount': self.loan_amount,
            'loanDate': self.loan_date.isoformat() if self.loan_date else None,
            'repaymentCompletionDate': self.repayment_completion_date.isoformat() if self.repayment_completion_date else None,
            'annualRepaymentDate': self.annual_repayment_date,
            'collateralProvider': self.collateral_provider,
            'collateralProperty': self.collateral_property,
            'establishedRight': self.established_right,
            'isBareLand': self.is_bare_land,
            'isSuperficiesSet': self.is_superficies_set,
            'notes': self.notes,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }


class MortgageContract(db.Model):
    """근저당권 설정계약서 (표출용)"""
    __tablename__ = 'mortgage_contracts'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, index=True)
    business_operator = db.Column(db.String(200), index=True)  # 사업자
    loan_amount = db.Column(db.String(100))  # 융자금액
    remaining_principal = db.Column(db.String(100))  # 잔여원금
    mortgage_date = db.Column(db.Date)  # 근저당권 설정일
    repayment_completion_date = db.Column(db.Date)  # 상환완료 예정일
    
    collateral_provider = db.Column(db.String(200))  # 담보제공자
    collateral_property = db.Column(db.Text)  # 담보부동산
    mortgage_amount = db.Column(db.String(100))  # 설정금액
    mortgage_history = db.Column(db.Text)  # 근저당권 변동내역
    notes = db.Column(db.Text)  # 비고
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'businessOperator': self.business_operator,
            'loanAmount': self.loan_amount,
            'remainingPrincipal': self.remaining_principal,
            'mortgageDate': self.mortgage_date.isoformat() if self.mortgage_date else None,
            'repaymentCompletionDate': self.repayment_completion_date.isoformat() if self.repayment_completion_date else None,
            'collateralProvider': self.collateral_provider,
            'collateralProperty': self.collateral_property,
            'mortgageAmount': self.mortgage_amount,
            'mortgageHistory': self.mortgage_history,
            'notes': self.notes,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None
        }
