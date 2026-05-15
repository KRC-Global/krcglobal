"""마이그레이션 대상 테이블 정의.

- TABLES: 임포트 순서대로 정렬됨 (부모 → 자식)
- conflict_key: 외부망에서 중복 판정에 쓰는 (NOT NULL인 자연 컬럼들)
- parent_fks: { 'fk_column': 'parent_table' } — id_mapping 으로 재매핑할 컬럼
- filters: 특정 row만 export 할 때 적용할 WHERE 절 (선택)
- file_fields: R2 업로드 대상 (path, name, size) 컬럼 그룹
"""

TABLES = [
    # ── 부모 테이블 ──────────────────────────────────────
    {
        'name': 'consulting_projects',
        'conflict_key': ('number', 'contract_year', 'title_kr'),
        'parent_fks': {'created_by': 'users'},
        'filters': None,
        'file_fields': [],  # 본인은 첨부 없음
    },
    {
        'name': 'oda_projects',
        'conflict_key': ('number', 'country', 'title'),
        'parent_fks': {'created_by': 'users'},
        'filters': None,
        'file_fields': [],
    },
    {
        'name': 'methane_projects',
        'conflict_key': ('number', 'country', 'title'),
        'parent_fks': {'created_by': 'users'},
        'filters': None,
        'file_fields': [],
    },

    # ── 자식 테이블 (consulting_projects FK) ────────────
    {
        'name': 'consulting_personnel',
        'conflict_key': ('consulting_project_id', 'name', 'role'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
        },
        'filters': None,
        'file_fields': [],
    },
    {
        'name': 'proposals',
        'conflict_key': ('consulting_project_id', 'title', 'submission_date'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
            'created_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'proposals', 'path_col': 'file_path',
             'name_col': 'file_name', 'size_col': 'file_size'},
            {'prefix': 'proposals', 'path_col': 'technical_file_path',
             'name_col': 'technical_file_name', 'size_col': 'technical_file_size'},
            {'prefix': 'proposals', 'path_col': 'price_file_path',
             'name_col': 'price_file_name', 'size_col': 'price_file_size'},
        ],
    },
    {
        'name': 'proposal_statuses',
        'conflict_key': ('project_name', 'funding'),
        'parent_fks': {'created_by': 'users'},
        'filters': None,
        'file_fields': [],
    },
    {
        'name': 'contracts',
        'conflict_key': ('consulting_project_id', 'document_type', 'order_number'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
            'created_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'contracts', 'path_col': 'file_path',
             'name_col': 'file_name', 'size_col': 'file_size'},
        ],
    },
    {
        'name': 'tor_rfp',
        'conflict_key': ('consulting_project_id', 'title'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
            'created_by': 'users',
            'updated_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'tor_rfp', 'path_col': 'tor_file_path',
             'name_col': 'tor_file_name', 'size_col': 'tor_file_size'},
            {'prefix': 'tor_rfp', 'path_col': 'rfp_file_path',
             'name_col': 'rfp_file_name', 'size_col': 'rfp_file_size'},
        ],
    },
    {
        'name': 'eois',
        'conflict_key': ('consulting_project_id', 'title', 'submission_date'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
            'created_by': 'users',
            'updated_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'eoi', 'path_col': 'eoi_file_path',
             'name_col': 'eoi_file_name', 'size_col': 'eoi_file_size'},
        ],
    },
    {
        'name': 'performance_records',
        'conflict_key': ('consulting_project_id', 'title', 'contract_date'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
            'created_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'performance', 'path_col': 'file_path',
             'name_col': 'file_name', 'size_col': 'file_size'},
        ],
    },

    # ── ODA 자식 ────────────────────────────────────────
    {
        'name': 'oda_reports',
        'conflict_key': ('oda_project_id', 'report_type', 'file_name'),
        'parent_fks': {
            'oda_project_id': 'oda_projects',
            'created_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'oda_reports', 'path_col': 'file_path',
             'name_col': 'file_name', 'size_col': 'file_size'},
        ],
    },
    {
        'name': 'oda_manual_data',
        'conflict_key': ('oda_project_id', 'year'),
        'parent_fks': {
            'oda_project_id': 'oda_projects',
            'created_by': 'users',
            'updated_by': 'users',
        },
        'filters': None,
        'file_fields': [],
    },
    {
        'name': 'oda_notes',
        'conflict_key': ('oda_project_id',),
        'parent_fks': {
            'oda_project_id': 'oda_projects',
            'created_by': 'users',
        },
        'filters': None,
        'file_fields': [
            {'prefix': 'oda_notes', 'path_col': 'file_path',
             'name_col': 'file_name', 'size_col': 'file_size'},
        ],
    },

    # ── Methane 자식 ────────────────────────────────────
    {
        'name': 'methane_budget_data',
        'conflict_key': ('methane_project_id', 'year'),
        'parent_fks': {
            'methane_project_id': 'methane_projects',
            'created_by': 'users',
            'updated_by': 'users',
        },
        'filters': None,
        'file_fields': [],
    },

    # ── 게시판 (마지막) ─────────────────────────────────
    {
        'name': 'board_posts',
        'conflict_key': ('board_type', 'title', 'created_at'),
        'parent_fks': {
            'consulting_project_id': 'consulting_projects',
            'oda_project_id': 'oda_projects',
            'created_by': 'users',
        },
        # 해외기술용역과 ODA 카테고리만 가져온다
        'filters': "board_type IN ('overseas_tech', 'oda')",
        'file_fields': [
            {'prefix': 'board', 'path_col': 'file_path',
             'name_col': 'file_name', 'size_col': 'file_size'},
        ],
    },
]


def by_name(table_name):
    for t in TABLES:
        if t['name'] == table_name:
            return t
    return None


TABLE_NAMES = [t['name'] for t in TABLES]
