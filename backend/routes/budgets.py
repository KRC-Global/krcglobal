"""
GBMS - Budget Routes
글로벌사업처 해외사업관리시스템 - 예산관리 API
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Budget, BudgetExecution, Project, ActivityLog
from routes.auth import token_required

budgets_bp = Blueprint('budgets', __name__)


@budgets_bp.route('', methods=['GET'])
@token_required
def get_budgets(current_user):
    """Get all budgets with filters"""
    project_id = request.args.get('project_id', type=int)
    year = request.args.get('year', type=int)
    category = request.args.get('category')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    query = Budget.query
    
    if project_id:
        query = query.filter(Budget.project_id == project_id)
    
    if year:
        query = query.filter(Budget.year == year)
    
    if category:
        query = query.filter(Budget.category == category)
    
    query = query.order_by(Budget.year.desc(), Budget.category)
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'data': [b.to_dict() for b in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'currentPage': page
    })


@budgets_bp.route('/<int:budget_id>', methods=['GET'])
@token_required
def get_budget(current_user, budget_id):
    """Get single budget by ID"""
    budget = Budget.query.get_or_404(budget_id)
    
    data = budget.to_dict()
    data['executions'] = [e.to_dict() for e in budget.executions.order_by(BudgetExecution.execution_date.desc())]
    
    return jsonify({
        'success': True,
        'data': data
    })


@budgets_bp.route('', methods=['POST'])
@token_required
def create_budget(current_user):
    """Create new budget"""
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'message': '요청 데이터가 없습니다.'}), 400
    
    required_fields = ['projectId', 'year', 'category', 'amountPlanned']
    for field in required_fields:
        if field not in data:
            return jsonify({'success': False, 'message': f'{field} 필드는 필수입니다.'}), 400
    
    budget = Budget(
        project_id=data['projectId'],
        year=data['year'],
        category=data['category'],
        sub_category=data.get('subCategory'),
        description=data.get('description'),
        amount_planned=data['amountPlanned'],
        amount_executed=data.get('amountExecuted', 0),
        amount_remaining=data['amountPlanned'] - data.get('amountExecuted', 0)
    )
    
    db.session.add(budget)
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='create',
        entity_type='budget',
        entity_id=budget.id,
        description=f'예산 항목 생성: {budget.category}',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '예산 항목이 등록되었습니다.',
        'data': budget.to_dict()
    }), 201


@budgets_bp.route('/<int:budget_id>', methods=['PUT'])
@token_required
def update_budget(current_user, budget_id):
    """Update budget"""
    budget = Budget.query.get_or_404(budget_id)
    data = request.get_json()
    
    if 'category' in data:
        budget.category = data['category']
    if 'subCategory' in data:
        budget.sub_category = data['subCategory']
    if 'description' in data:
        budget.description = data['description']
    if 'amountPlanned' in data:
        budget.amount_planned = data['amountPlanned']
        budget.amount_remaining = budget.amount_planned - budget.amount_executed
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '예산 항목이 수정되었습니다.',
        'data': budget.to_dict()
    })


@budgets_bp.route('/<int:budget_id>', methods=['DELETE'])
@token_required
def delete_budget(current_user, budget_id):
    """Delete budget"""
    budget = Budget.query.get_or_404(budget_id)
    
    db.session.delete(budget)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '예산 항목이 삭제되었습니다.'
    })


@budgets_bp.route('/<int:budget_id>/executions', methods=['POST'])
@token_required
def add_execution(current_user, budget_id):
    """Add budget execution"""
    budget = Budget.query.get_or_404(budget_id)
    data = request.get_json()
    
    if not data.get('amount'):
        return jsonify({'success': False, 'message': '집행 금액을 입력해주세요.'}), 400
    
    execution = BudgetExecution(
        budget_id=budget.id,
        execution_date=datetime.strptime(data['executionDate'], '%Y-%m-%d').date() if data.get('executionDate') else datetime.now().date(),
        amount=data['amount'],
        description=data.get('description'),
        voucher_no=data.get('voucherNo'),
        created_by=current_user.id
    )
    
    db.session.add(execution)
    
    # Update budget amounts
    budget.amount_executed = float(budget.amount_executed or 0) + float(data['amount'])
    budget.amount_remaining = float(budget.amount_planned or 0) - float(budget.amount_executed)
    
    # Log activity
    log = ActivityLog(
        user_id=current_user.id,
        action='create',
        entity_type='budget_execution',
        entity_id=execution.id,
        description=f'예산 집행 등록: {data["amount"]:,.0f}원',
        ip_address=request.remote_addr
    )
    db.session.add(log)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '예산 집행이 등록되었습니다.',
        'data': execution.to_dict()
    }), 201


@budgets_bp.route('/stats', methods=['GET'])
@token_required
def get_budget_stats(current_user):
    """Get budget statistics"""
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Total planned and executed by department
    dept_stats = db.session.query(
        Project.department,
        db.func.sum(Budget.amount_planned).label('planned'),
        db.func.sum(Budget.amount_executed).label('executed')
    ).join(Project).filter(Budget.year == year).group_by(Project.department).all()
    
    # Total by category
    category_stats = db.session.query(
        Budget.category,
        db.func.sum(Budget.amount_planned).label('planned'),
        db.func.sum(Budget.amount_executed).label('executed')
    ).filter(Budget.year == year).group_by(Budget.category).all()
    
    # Overall totals
    total_planned = db.session.query(db.func.sum(Budget.amount_planned)).filter(Budget.year == year).scalar() or 0
    total_executed = db.session.query(db.func.sum(Budget.amount_executed)).filter(Budget.year == year).scalar() or 0
    
    return jsonify({
        'success': True,
        'data': {
            'year': year,
            'totalPlanned': float(total_planned),
            'totalExecuted': float(total_executed),
            'executionRate': round(float(total_executed) / float(total_planned) * 100, 1) if total_planned else 0,
            'byDepartment': [
                {
                    'department': d[0],
                    'planned': float(d[1]) if d[1] else 0,
                    'executed': float(d[2]) if d[2] else 0,
                    'rate': round(float(d[2]) / float(d[1]) * 100, 1) if d[1] else 0
                }
                for d in dept_stats
            ],
            'byCategory': [
                {
                    'category': c[0],
                    'planned': float(c[1]) if c[1] else 0,
                    'executed': float(c[2]) if c[2] else 0,
                    'rate': round(float(c[2]) / float(c[1]) * 100, 1) if c[1] else 0
                }
                for c in category_stats
            ]
        }
    })
