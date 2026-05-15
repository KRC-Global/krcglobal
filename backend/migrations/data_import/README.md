# 내부망 → 외부망 데이터 마이그레이션 (해외기술용역 + 국제협력사업)

내부망(`E:\해외사업관리시스템`, SQLite + 로컬 파일)에 쌓인 사업 데이터와 첨부파일을 외부망(Supabase PostgreSQL + Cloudflare R2)로 이관하기 위한 일회성 스크립트 모음.

> 상세 의사결정 배경은 저장소 루트 `outer_plan.md` 참고.

## 정책 요약

- **코드**: 외부망 우선. HTML/JS/routes/모델은 건드리지 않는다.
- **데이터 충돌**: 자연 복합키로 SELECT → 존재하면 SKIP·로그, 없으면 INSERT. 외부망 기존 데이터는 보존.
- **부모 SKIP 시 자식**: 자식은 INSERT하되 FK는 외부망 기존 부모 ID로 재매핑.
- **재실행성**: 모든 스크립트 idempotent. 중단 후 재실행하면 manifest·id_mapping 기준으로 skip.
- **R2 키**: 결정적 규칙(`{prefix}/{sqlite_id}_{filename}`) 사용. timestamp 미사용.
- **제외 모듈**: CV·HR·PDS (외부망에 의도적으로 없음).

## 사전 준비

### 1. Python 의존성

```powershell
# 외부망 작업 디렉토리에서
pip install -r backend\requirements.txt
# 추가로 필요시
pip install psycopg2-binary boto3 tqdm
```

### 2. 환경 변수

외부망 [`backend/config.py`](../../config.py)의 `DEFAULT_DATABASE_URL` / R2 키가 그대로 사용된다. 따로 `.env` 가 필요하면:

```powershell
$env:DATABASE_URL = "postgresql://...:6543/postgres"
$env:R2_ACCESS_KEY_ID = "..."
$env:R2_SECRET_ACCESS_KEY = "..."
```

### 3. 내부망 자료 반입 (USB)

내부망에서 다음 항목을 USB로 외부망 PC에 복사한 뒤, `_migration_src/` 폴더 (저장소 루트) 아래 배치:

```
_migration_src/
├── gbms.db                       # E:\해외사업관리시스템\backend\database\gbms.db
└── uploads/
    ├── proposals/                # technical/, price/ 하위 포함
    ├── contracts/
    ├── performance/
    ├── tor_rfp/
    ├── eoi/                      # bidding.py 에서 EOI 첨부
    ├── oda_reports/
    ├── oda_notes/
    └── board/                    # 게시판 첨부 (overseas_tech, oda 카테고리만)
```

> `cv/`, `hr/`, `pds/` 디렉토리는 반입하지 않는다.

### 4. 백업

```powershell
# Supabase SQL dump (네트워크에서 pg_dump 가능하면)
pg_dump "postgresql://postgres.zzypdvwdwgwocczpaaiu:KrcGlobal2026!DB@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres" `
  -f "backup_$(Get-Date -Format yyyy-MM-dd_HHmmss).sql"

# R2 객체 listing
python backend\migrations\data_import\00_r2_list_backup.py > backend\migrations\data_import\reports\r2_objects_before.txt
```

## 실행 순서

| 순서 | 스크립트 | 입력 | 출력 | 영향 |
|------|----------|------|------|------|
| 1 | `00_r2_list_backup.py` | (외부망 R2) | `reports/r2_objects_before.txt` | read-only |
| 2 | `01_check_schema.py` | `_migration_src/gbms.db` + Supabase | `reports/schema_diff.md` | read-only |
| 3 | `10_export_sqlite.py` | `_migration_src/gbms.db` | `exports/*.jsonl` | read-only (SQLite만 읽음) |
| 4 | `15_build_user_map.py` | `exports/users.jsonl` + Supabase users | `manifests/user_map.json` | read-only |
| 5 | `20_import_to_supabase.py` | `exports/*.jsonl`, `manifests/user_map.json` | Supabase INSERT + `manifests/id_mapping.json` + `reports/conflicts_report.csv` | **DB 변경** |
| 6 | `30_upload_files_to_r2.py` | `_migration_src/uploads/`, `manifests/id_mapping.json` | R2 PUT + `manifests/uploaded_manifest.jsonl` + Supabase UPDATE | **R2 + DB 변경** |
| 7 | `40_verify.py` | (외부망 DB + R2) | `reports/migration_report.md` | read-only |
| ⛔ | `99_rollback_r2.py` | `manifests/uploaded_manifest.jsonl` | R2 DELETE + DB UPDATE → NULL | **롤백 전용** |

각 스크립트는 `--help` 로 옵션 확인 가능. 대부분 `--dry-run` 지원.

## Flask app context

스크립트 일부([`30_upload_files_to_r2.py`])는 외부망 [`backend/utils/r2_storage.py`](../../utils/r2_storage.py)를 재사용하며 이 모듈은 `flask.current_app` 에 의존한다. 스크립트 내부에서 아래 패턴으로 app context를 만든다:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from app import app  # backend/app.py 의 Flask 객체
with app.app_context():
    ...
```

## 사용자 매핑 (Stage 15)

내부망 SQLite `users.user_id` (string, 예: `krcoda`) 와 외부망 Supabase `users.user_id` 를 매칭한다. 외부망 [`User`](../../models/__init__.py) line 53 의 `user_id` 가 unique 키.

산출물 `manifests/user_map.json`:
```json
{
  "1": 1,
  "5": 12,
  "9": null
}
```
키는 내부망 sqlite `users.id` (int), 값은 외부망 `users.id` (int) 또는 `null` (미매칭). null인 사용자가 created_by였던 레코드는 admin id (`--fallback-user-id`) 로 폴백한다.

## 충돌 키 (Stage 20)

| 테이블 | Conflict Key |
|--------|--------------|
| consulting_projects | (number, contract_year, title_kr) |
| oda_projects | (number, country, title) |
| methane_projects | (number, country, title) |
| consulting_personnel | (consulting_project_id, name, role) |
| proposals | (consulting_project_id, title, submission_date) |
| proposal_statuses | (project_name, funding) |
| contracts | (consulting_project_id, document_type, order_number) |
| tor_rfp | (consulting_project_id, title) |
| eois | (consulting_project_id, title, submission_date) |
| performance_records | (consulting_project_id, title, contract_date) |
| oda_reports | (oda_project_id, report_type, file_name) |
| oda_manual_data | (oda_project_id, year) |
| oda_notes | (oda_project_id,) |
| methane_budget_data | (methane_project_id, year) |
| board_posts | (board_type, title, created_at) |

NULL 컬럼이 키 일부에 포함되는 경우(예: 내부망에 `submission_date` 가 NULL) 해당 행은 conflict 보고서에 별도 기록되며 SKIP 또는 INSERT 결정은 `--null-conflict={skip,insert}` 옵션으로 제어.

## R2 키 규칙 (Stage 30)

마이그레이션 전용 결정적 키:
```
{prefix}/migrated_{sqlite_id}_{safe_filename}
```

| 테이블/필드 | prefix |
|-------------|--------|
| proposals.technical_file_path | `proposals/` |
| proposals.price_file_path | `proposals/` |
| proposals.file_path (단일파일 레거시) | `proposals/` |
| contracts.file_path | `contracts/` |
| performance_records.file_path | `performance/` |
| tor_rfp.tor_file_path, rfp_file_path | `tor_rfp/` |
| eois.eoi_file_path | `eoi/` |
| oda_reports.file_path | `oda_reports/` |
| oda_notes.file_path | `oda_notes/` |
| board_posts.file_path | `board/` |

`migrated_` 접두사로 일반 사용자 업로드와 구분된다.

## 롤백

| 시나리오 | 절차 |
|----------|------|
| Stage 20 도중 실패 | 트랜잭션이 테이블 단위. 자동 롤백. `id_mapping.json` 미생성 상태면 영향 없음. 일부 테이블 적용 후라면 해당 신규 ID만 직접 DELETE (id_mapping 기준). |
| Stage 20 완료 후 전체 되돌리기 | `psql ... < backup_*.sql` 로 복원. |
| Stage 30 도중/완료 후 R2 되돌리기 | `python 99_rollback_r2.py` 실행. `uploaded_manifest.jsonl` 에 기록된 모든 r2_key를 `delete_file()` 호출 + Supabase의 file_path NULL로 업데이트. |
| 전체 완전 롤백 | (1) `99_rollback_r2.py`, (2) `pg_restore`, (3) 산출물 폐기 (`exports/`, `manifests/`, `reports/`). |

## 산출물·gitignore

[`/.gitignore`](../../../.gitignore) 가 산출물(`*.jsonl`, `id_mapping*.json`, `backup_*.sql` 등)을 차단한다. 스크립트(`*.py`)와 이 README만 커밋된다.
