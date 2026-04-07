"""
해외진출지원사업(Loan) API Routes
"""
from flask import Blueprint, request, jsonify, current_app
from functools import wraps
import jwt
from datetime import datetime
import pandas as pd
import io

from models import db
from models.expansion import (
    Company, Loan, LoanPerformance, LoanRepayment,
    LoanProject, CompanyCollateral, PostManagement, MortgageContract
)

expansion_bp = Blueprint('expansion', __name__, url_prefix='/api/expansion')


# ═══════════════════════════════════════════════════════════════════════════
# Auth Decorator - Using JWT_SECRET_KEY from app config
# ═══════════════════════════════════════════════════════════════════════════

def get_secret_key():
    return current_app.config['JWT_SECRET_KEY']


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'success': False, 'message': '토큰이 필요합니다'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, get_secret_key(), algorithms=['HS256'])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': '토큰이 만료되었습니다'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'success': False, 'message': '토큰이 필요합니다'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, get_secret_key(), algorithms=['HS256'])
            
            if data.get('role') != 'admin':
                return jsonify({'success': False, 'message': '관리자 권한이 필요합니다'}), 403
            
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': '토큰이 만료되었습니다'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated


def expansion_write_required(f):
    """해외진출지원사업 쓰기 권한 확인 데코레이터
    - admin 역할 또는
    - expansion/all permission_scope를 가진 사용자가 접근 가능
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'success': False, 'message': '토큰이 필요합니다'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, get_secret_key(), algorithms=['HS256'])
            
            # admin 역할은 항상 허용
            if data.get('role') == 'admin':
                return f(data, *args, **kwargs)
            
            # User 테이블에서 permission_scope 확인
            from models import User
            user = User.query.get(data.get('user_id'))
            if not user:
                return jsonify({'success': False, 'message': '사용자를 찾을 수 없습니다'}), 401
            
            user_scope = getattr(user, 'permission_scope', 'readonly')
            
            # expansion 또는 all 권한이면 허용
            if user_scope in ('expansion', 'all'):
                return f(data, *args, **kwargs)
            
            return jsonify({'success': False, 'message': '해외진출지원사업 수정 권한이 없습니다'}), 403
            
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': '토큰이 만료되었습니다'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': '유효하지 않은 토큰입니다'}), 401
    
    return decorated



# ═══════════════════════════════════════════════════════════════════════════
# 1. Company Management (기업관리)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/companies', methods=['GET'])
@token_required
def get_companies(current_user):
    """기업 목록 조회"""
    try:
        # Query parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        search = request.args.get('search', '').strip()
        size = request.args.get('size', '').strip()
        
        # Base query
        query = Company.query
        
        # Filters
        if search:
            query = query.filter(Company.name.like(f'%{search}%'))
        if size:
            query = query.filter(Company.size == size)
        
        # Pagination
        pagination = query.order_by(Company.number.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [c.to_dict() for c in pagination.items],
            'total': pagination.total,
            'page': page,
            'perPage': per_page,
            'totalPages': pagination.pages
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@expansion_bp.route('/companies/upload', methods=['POST'])
@expansion_write_required
def upload_companies(current_user):
    """Excel 업로드 - 기업정보"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '파일이 선택되지 않았습니다'}), 400
        
        # Read Excel
        df = pd.read_excel(io.BytesIO(file.read()))
        
        # Clear existing data
        Company.query.delete()
        
        # Insert data
        for _, row in df.iterrows():
            company = Company(
                number=int(row['번호']) if pd.notna(row['번호']) else None,
                name=str(row['기업명']) if pd.notna(row['기업명']) else '',
                size=str(row['기업규모']) if pd.notna(row['기업규모']) else '',
                address=str(row['기업주소']) if pd.notna(row['기업주소']) and row['기업주소'] != '-' else '',
                email=str(row['메일주소']) if pd.notna(row['메일주소']) and row['메일주소'] != '-' else '',
                phone=str(row['전화번호']) if pd.notna(row['전화번호']) and row['전화번호'] != '-' else '',
                created_by=str(row['등록자']) if pd.notna(row['등록자']) else '',
                updated_by=str(row['수정자']) if pd.notna(row['수정자']) else ''
            )
            db.session.add(company)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(df)}개의 기업 정보가 업로드되었습니다',
            'count': len(df)
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 2. Loan Management (융자관리)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/loans', methods=['GET'])
@token_required
def get_loans(current_user):
    """융자 목록 조회"""
    try:
        # Query parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        year = request.args.get('year', type=int)
        country = request.args.get('country', '').strip()
        company_name = request.args.get('companyName', '').strip()
        
        # Base query
        query = Loan.query
        
        # Filters
        if year:
            query = query.filter(Loan.year == year)
        if country:
            query = query.filter(Loan.country.like(f'%{country}%'))
        if company_name:
            query = query.filter(Loan.company_name.like(f'%{company_name}%'))
        
        # Pagination
        pagination = query.order_by(Loan.year.desc(), Loan.number.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [loan.to_dict() for loan in pagination.items],
            'total': pagination.total,
            'page': page,
            'perPage': per_page,
            'totalPages': pagination.pages
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@expansion_bp.route('/loans/stats', methods=['GET'])
@token_required
def get_loan_stats(current_user):
    """융자 통계"""
    try:
        from sqlalchemy import func
        
        # Total stats
        total_principal = db.session.query(func.sum(Loan.principal)).scalar() or 0
        total_repaid = db.session.query(func.sum(Loan.repaid_amount)).scalar() or 0
        total_balance = db.session.query(func.sum(Loan.balance)).scalar() or 0
        total_companies = db.session.query(func.count(func.distinct(Loan.company_name))).scalar() or 0
        
        # By year
        by_year = db.session.query(
            Loan.year,
            func.sum(Loan.principal).label('principal'),
            func.sum(Loan.balance).label('balance'),
            func.count(Loan.id).label('count')
        ).group_by(Loan.year).order_by(Loan.year.desc()).all()
        
        # By country
        by_country = db.session.query(
            Loan.country,
            func.sum(Loan.principal).label('principal'),
            func.sum(Loan.balance).label('balance'),
            func.count(Loan.id).label('count')
        ).group_by(Loan.country).order_by(func.sum(Loan.principal).desc()).limit(10).all()
        
        return jsonify({
            'success': True,
            'data': {
                'totalPrincipal': int(total_principal),
                'totalRepaid': int(total_repaid),
                'totalBalance': int(total_balance),
                'totalCompanies': total_companies,
                'byYear': [
                    {
                        'year': y,
                        'principal': int(p),
                        'balance': int(b),
                        'count': c
                    }
                    for y, p, b, c in by_year
                ],
                'byCountry': [
                    {
                        'country': country,
                        'principal': int(p),
                        'balance': int(b),
                        'count': c
                    }
                    for country, p, b, c in by_country
                ]
            }
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@expansion_bp.route('/loans/upload', methods=['POST'])
@expansion_write_required
def upload_loans(current_user):
    """Excel 업로드 - 융자관리"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다'}), 400
        
        file = request.files['file']
        df = pd.read_excel(io.BytesIO(file.read()))
        
        # Clear existing data
        Loan.query.delete()
        
        # Helper function to parse Korean currency
        def parse_currency(value):
            if pd.isna(value) or value == '' or value == '-':
                return 0
            s = str(value).replace(',', '').replace('원', '').replace(' ', '')
            try:
                return int(float(s))
            except:
                return 0
        
        # Helper to parse date
        def parse_date(value):
            if pd.isna(value) or value == '' or value == '-':
                return None
            try:
                if isinstance(value, str):
                    # Format: "2025.10.15"
                    return datetime.strptime(value.split()[0], '%Y.%m.%d').date()
                elif isinstance(value, datetime):
                    return value.date()
                else:
                    return None
            except:
                return None
        
        # Insert data
        for _, row in df.iterrows():
            loan = Loan(
                number=int(row['번호']) if pd.notna(row['번호']) else None,
                year=int(row['연도']) if pd.notna(row['연도']) else None,
                company_name=str(row['기업명']) if pd.notna(row['기업명']) else '',
                country=str(row['국가']) if pd.notna(row['국가']) else '',
                crops=str(row['작물']) if pd.notna(row['작물']) else '',
                interest_rate=str(row['이율']) if pd.notna(row['이율']) else '',
                principal=parse_currency(row['융자원금']),
                repaid_amount=parse_currency(row['상환액']),
                balance=parse_currency(row['잔액']),
                contract_date=parse_date(row['계약연월']) if '계약연월' in row else None,
                execution_deadline=parse_date(row['집행기한']) if '집행기한' in row else None,
                maturity_date=parse_date(row['만기일']) if '만기일' in row else None,
                payment_month=str(row['납부약정월']) if pd.notna(row.get('납부약정월')) else '',
                messenger_subscription=str(row['메신저 수신여부']) if pd.notna(row.get('메신저 수신여부')) else '',
                business_evaluation=str(row['사업평가']) if pd.notna(row.get('사업평가')) else '',
                post_management=str(row['사후관리']) if pd.notna(row.get('사후관리')) else '',
                created_by=str(row['등록자']) if pd.notna(row.get('등록자')) else '',
                updated_by=str(row['수정자']) if pd.notna(row.get('수정자')) else ''
            )
            db.session.add(loan)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(df)}개의 융자 정보가 업로드되었습니다',
            'count': len(df)
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 3. Loan Performance (융자사업 추진실적)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/performance', methods=['GET'])
@token_required
def get_performance(current_user):
    """추진실적 조회"""
    try:
        records = LoanPerformance.query.order_by(LoanPerformance.country).all()
        
        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records]
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# Note: Excel upload for performance will be more complex due to pivot table format
# Skipping for now as requested (표출만)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Loan Repayment (연도별 상환내역)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/repayment', methods=['GET'])
@token_required
def get_repayment(current_user):
    """상환내역 조회"""
    try:
        records = LoanRepayment.query.order_by(LoanRepayment.country).all()
        
        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records]
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 5. Loan Projects (융자사업 관리)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/projects', methods=['GET'])
@token_required
def get_loan_projects(current_user):
    """융자사업관리 조회"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        year = request.args.get('year', type=int)
        company_name = request.args.get('companyName', '').strip()
        
        query = LoanProject.query
        
        if year:
            query = query.filter(LoanProject.year == year)
        if company_name:
            query = query.filter(LoanProject.company_name.like(f'%{company_name}%'))
        
        pagination = query.order_by(LoanProject.year.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in pagination.items],
            'total': pagination.total,
            'page': page,
            'perPage': per_page,
            'totalPages': pagination.pages
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@expansion_bp.route('/projects/upload', methods=['POST'])
@expansion_write_required
def upload_loan_projects(current_user):
    """Excel 업로드 - 융자사업 관리"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다'}), 400
        
        file = request.files['file']
        df = pd.read_excel(io.BytesIO(file.read()))
        
        LoanProject.query.delete()
        
        for _, row in df.iterrows():
            project = LoanProject(
                year=int(row['연도']) if pd.notna(row['연도']) else None,
                company_name=str(row['융자기업']) if pd.notna(row['융자기업']) else '',
                country=str(row['국가']) if pd.notna(row['국가']) else '',
                crops=str(row['작물']) if pd.notna(row['작물']) else '',
                contract_date=str(row['계약년월\n(지급일)']) if pd.notna(row['계약년월\n(지급일)']) else '',
                execution_deadline=str(row['집행기한']) if pd.notna(row.get('집행기한')) else '',
                maturity_date=str(row['만기일']) if pd.notna(row.get('만기일')) else '',
                payment_month=str(row['납부약정월']) if pd.notna(row.get('납부약정월')) else '',
                loan_payment=int(row['융자금 지급액']) if pd.notna(row['융자금 지급액']) else 0,
                principal_balance=int(row['원잔금액\n(단위:원)']) if pd.notna(row['원잔금액\n(단위:원)']) else 0,
                collateral_type=str(row['담보종류']) if pd.notna(row.get('담보종류')) else '',
                bond_amount=str(row['채권채고액\n((보증금액), 단위:원)']) if pd.notna(row.get('채권채고액\n((보증금액), 단위:원)')) else '',
                guarantee_period=str(row['보증기간']) if pd.notna(row.get('보증기간')) else '',
                business_evaluation=str(row['사업평가']) if pd.notna(row.get('사업평가')) else '',
                post_management=str(row['사후관리']) if pd.notna(row.get('사후관리')) else ''
            )
            db.session.add(project)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(df)}개의 융자사업 정보가 업로드되었습니다',
            'count': len(df)
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 6. Company Collateral (기업별 담보 현황)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/collateral', methods=['GET'])
@token_required
def get_collateral(current_user):
    """담보현황 조회"""
    try:
        records = CompanyCollateral.query.order_by(CompanyCollateral.number).all()
        
        return jsonify({
            'success': True,
            'data': [r.to_dict() for r in records]
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 7. Post Management (사후관리대장)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/post-management', methods=['GET'])
@token_required
def get_post_management(current_user):
    """사후관리대장 조회"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        year = request.args.get('year', type=int)
        business_operator = request.args.get('businessOperator', '').strip()

        query = PostManagement.query

        if year:
            query = query.filter(PostManagement.year == year)
        if business_operator:
            query = query.filter(PostManagement.business_operator.like(f'%{business_operator}%'))

        pagination = query.order_by(PostManagement.year.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in pagination.items],
            'total': pagination.total,
            'page': page,
            'perPage': per_page,
            'totalPages': pagination.pages
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@expansion_bp.route('/post-management/upload', methods=['POST'])
@expansion_write_required
def upload_post_management(current_user):
    """Excel 업로드 - 사후관리대장"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다'}), 400
        
        file = request.files['file']
        df = pd.read_excel(io.BytesIO(file.read()))
        
        PostManagement.query.delete()
        
        def parse_date(value):
            if pd.isna(value):
                return None
            try:
                if isinstance(value, str):
                    return datetime.strptime(value, '%Y-%m-%d').date()
                elif isinstance(value, datetime):
                    return value.date()
                else:
                    return None
            except:
                return None
        
        for _, row in df.iterrows():
            post = PostManagement(
                year=int(row['연도']) if pd.notna(row['연도']) else None,
                business_operator=str(row['사업자']) if pd.notna(row['사업자']) else '',
                loan_amount=str(row['융자금액']) if pd.notna(row['융자금액']) else '',
                loan_date=parse_date(row['융자일자']) if pd.notna(row.get('융자일자')) else None,
                repayment_completion_date=parse_date(row['상환완료예정일']) if pd.notna(row.get('상환완료예정일')) else None,
                annual_repayment_date=str(row['연도별상환일']) if pd.notna(row.get('연도별상환일')) else '',
                collateral_provider=str(row['담보제공자']) if pd.notna(row.get('담보제공자')) else '',
                collateral_property=str(row['담보부동산']) if pd.notna(row.get('담보부동산')) else '',
                established_right=str(row['설정한권리']) if pd.notna(row.get('설정한권리')) else '',
                is_bare_land=str(row['나대지여부']) if pd.notna(row.get('나대지여부')) else '',
                is_superficies_set=str(row['지상권설정여부']) if pd.notna(row.get('지상권설정여부')) else '',
                notes=str(row['비고']) if pd.notna(row.get('비고')) else ''
            )
            db.session.add(post)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(df)}개의 사후관리 정보가 업로드되었습니다',
            'count': len(df)
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# 8. Mortgage Contract (근저당권 설정계약서)
# ═══════════════════════════════════════════════════════════════════════════

@expansion_bp.route('/mortgage', methods=['GET'])
@token_required
def get_mortgage(current_user):
    """근저당권 계약서 조회"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('perPage', 20, type=int)
        
        pagination = MortgageContract.query.order_by(MortgageContract.year.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'data': [m.to_dict() for m in pagination.items],
            'total': pagination.total,
            'page': page,
            'perPage': per_page,
            'totalPages': pagination.pages
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@expansion_bp.route('/mortgage/upload', methods=['POST'])
@expansion_write_required
def upload_mortgage(current_user):
    """Excel 업로드 - 근저당권 설정계약서"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다'}), 400
        
        file = request.files['file']
        df = pd.read_excel(io.BytesIO(file.read()))
        
        MortgageContract.query.delete()
        
        def parse_date(value):
            if pd.isna(value):
                return None
            try:
                if isinstance(value, str):
                    return datetime.strptime(value, '%Y-%m-%d').date()
                elif isinstance(value, datetime):
                    return value.date()
                else:
                    return None
            except:
                return None
        
        for _, row in df.iterrows():
            mortgage = MortgageContract(
                year=int(row['연도']) if pd.notna(row['연도']) else None,
                business_operator=str(row['사업자']) if pd.notna(row['사업자']) else '',
                loan_amount=str(row['융자금액']) if pd.notna(row['융자금액']) else '',
                remaining_principal=str(row['(잔여원금)']) if pd.notna(row.get('(잔여원금)')) else '',
                mortgage_date=parse_date(row['근저당권 설정일']) if pd.notna(row.get('근저당권 설정일')) else None,
                repayment_completion_date=parse_date(row['상환완료 예정일']) if pd.notna(row.get('상환완료 예정일')) else None,
                collateral_provider=str(row['담보제공자']) if pd.notna(row.get('담보제공자')) else '',
                collateral_property=str(row['담보부동산']) if pd.notna(row.get('담보부동산')) else '',
                mortgage_amount=str(row['설정금액']) if pd.notna(row.get('설정금액')) else '',
                mortgage_history=str(row['근저당권 변동내역']) if pd.notna(row.get('근저당권 변동내역')) else '',
                notes=str(row['비고']) if pd.notna(row.get('비고')) else ''
            )
            db.session.add(mortgage)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(df)}개의 근저당권 정보가 업로드되었습니다',
            'count': len(df)
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
