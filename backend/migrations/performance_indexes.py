"""
성능 개선 인덱스 추가 마이그레이션

실행 방법: cd backend && python migrations/add_performance_indexes.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
import sqlalchemy as sa

INDEXES = [
    # Priority 1: 복합 인덱스 (다중 필터 조회 최적화)
    ('idx_consulting_country_status',   'consulting_projects', 'country, status'),
    ('idx_consulting_year_status',      'consulting_projects', 'contract_year, status'),
    ('idx_oda_country_status',          'oda_projects',        'country, status'),
    ('idx_oda_contract_year',           'oda_projects',        'contract_year'),
    ('idx_methane_country_status',      'methane_projects',    'country, status'),
    ('idx_methane_year_status',         'methane_projects',    'contract_year, status'),
    ('idx_board_post_type_category',    'board_posts',         'board_type, category'),
    ('idx_board_post_type_created',     'board_posts',         'board_type, created_at DESC'),
    ('idx_proposal_country_result',     'proposals',           'country, result'),
    ('idx_loan_company_year',           'loans',               'company_id, year'),
    ('idx_loan_year_country',           'loans',               'year, country'),
    ('idx_budget_project_year',         'budgets',             'project_id, year'),

    # Priority 2: FK 인덱스 (JOIN 속도 개선)
    ('idx_proposal_project_id',         'proposals',               'consulting_project_id'),
    ('idx_performance_project_id',      'performance_records',     'consulting_project_id'),
    ('idx_contract_project_id',         'contracts',               'consulting_project_id'),
    ('idx_tor_rfp_project_id',          'tor_rfp',                 'consulting_project_id'),
    ('idx_eoi_project_id',              'eois',                    'consulting_project_id'),
    ('idx_oda_report_project_id',       'oda_reports',             'oda_project_id'),
    ('idx_budget_exec_budget_id',       'budget_executions',       'budget_id'),

    # Priority 3: created_at 정렬 인덱스
    ('idx_consulting_created_at',       'consulting_projects',     'created_at DESC'),
    ('idx_oda_created_at',              'oda_projects',            'created_at DESC'),
    ('idx_proposal_created_at',         'proposals',               'created_at DESC'),
    ('idx_performance_created_at',      'performance_records',     'created_at DESC'),
]

def run_migration():
    with app.app_context():
        with db.engine.connect() as conn:
            created = 0
            skipped = 0
            failed = 0

            for index_name, table_name, columns in INDEXES:
                sql = (
                    f'CREATE INDEX IF NOT EXISTS {index_name} '
                    f'ON {table_name}({columns})'
                )
                try:
                    conn.execute(sa.text(sql))
                    conn.commit()
                    print(f'  ✅ {index_name}')
                    created += 1
                except Exception as e:
                    err = str(e).lower()
                    if 'no such table' in err:
                        print(f'  ⚠️  {index_name} — 테이블 없음 ({table_name}), 건너뜀')
                        skipped += 1
                    else:
                        print(f'  ❌ {index_name} — {e}')
                        failed += 1

            print(f'\n완료: 생성 {created}개 / 건너뜀 {skipped}개 / 실패 {failed}개')


if __name__ == '__main__':
    print('성능 인덱스 추가 마이그레이션 시작...')
    run_migration()
