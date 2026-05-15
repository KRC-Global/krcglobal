# 해외기술용역·국제협력사업: 내부망 → 외부망 데이터 마이그레이션 플랜 (v2)

## Context

망분리 환경의 내부망(`E:\해외사업관리시스템`) ↔ 외부망(`c:\Users\EKR\...\krcglobal`, Vercel + Supabase + Cloudflare R2)이 분기 발전 중. 내부망에 쌓인 **사업관리 > 해외기술용역사업·국제협력사업** 데이터(consulting 177건, ODA 보고서 237건 등)와 첨부파일(~5.4GB)을 외부망으로 이관하되, 외부망 코드와 기존 데이터는 보존한다.

> v2 변경: 사용자 리뷰 피드백 반영 — `.gitignore` 충돌, 비-unique number 컬럼, R2 prefix 오류, 재실행성, Flask app context, user 매핑 키, PowerShell 문법, 롤백 절차 등 보완.

## 사용자 결정사항 (확정)

1. **범위**: 해외기술용역 + 국제협력사업(ODA) 메뉴의 DB 데이터 + 첨부파일. 외부망 코드는 그대로(외부망 우선).
2. **CV·HR·PDS**: 외부망 복원 안 함.
3. **데이터 충돌**: 외부망 기존 레코드는 보존(SKIP), 내부망 신규만 INSERT.
4. **실행**: 사용자 본인이 외부망 PC(현재 디렉토리)에서 직접 실행.

## 아키텍처 차이

| 항목 | 내부망 | 외부망 |
|------|--------|--------|
| 배포 | 로컬 Flask | Vercel serverless |
| DB | SQLite (4.26MB) | Supabase PostgreSQL (`:6543` Transaction Pooler) |
| 파일 | 로컬 `backend/uploads/` (~5.4GB) | Cloudflare R2 `krcglobal` 버킷 (9GB 한도) |

## 마이그레이션 대상 테이블 + 충돌 키

자연 unique 컬럼이 부족하므로(예: `consulting_projects.number`, `oda_projects.number` 모두 `index=True` 만, [`backend/models/__init__.py:460`](backend/models/__init__.py#L460), [`backend/models/__init__.py:628`](backend/models/__init__.py#L628)) **복합 자연키**로 conflict를 판정한다. 일치하는 외부망 레코드가 있으면 SKIP·로그, 없으면 INSERT.

| 테이블 | 내부망 건수 | Conflict Key (복합) | 비고 |
|--------|-------------|---------------------|------|
| consulting_projects | 177 | (`number`, `contract_year`, `title_kr`) | 부모. number만으로는 unique 아님 |
| oda_projects | (미확인) | (`number`, `country`, `title`) | 부모 |
| methane_projects | (미확인) | (`number`, `country`, `title`) | 부모, ODA에 포함할지 사용자 확인 |
| consulting_personnel | 15 | (`consulting_project_id`, `name`, `role`) | FK 매핑 후 |
| proposals | 32 | (`consulting_project_id`, `title`, `submission_date`) | |
| proposal_statuses | 12 | (`project_name`, `funding`) | |
| contracts | 73 | (`consulting_project_id`, `document_type`, `order_number`) | unique index 존재 (`idx_contract_project_order`) |
| tor_rfp | 24 | (`consulting_project_id`, `title`) | |
| eois | 18 | (`consulting_project_id`, `title`, `submission_date`) | |
| performance_records | 27 | (`consulting_project_id`, `title`, `contract_date`) | |
| oda_reports | 237 | (`oda_project_id`, `report_type`, `file_name`) | unique 제거됨 — 다중 파일 |
| oda_manual_data | (미확인) | (`oda_project_id`, `year`) | |
| oda_notes | (미확인) | (`oda_project_id`) | oda_project당 1행 |
| methane_budget_data | (미확인) | (`methane_project_id`, `year`) | |
| board_posts | (필터링) | (`board_type`, `title`, `created_at`) | `board_type IN ('overseas_tech','oda')` 만 |

**부모 SKIP 시 자식 처리 (중요)**:
- 부모(consulting/oda/methane_projects)가 SKIP되어도 자식 INSERT는 계속 진행한다. 단 자식의 FK는 외부망 기존 부모 ID로 재매핑.
- `id_mapping.json` 구조: `{ "consulting_projects": { "<sqlite_id>": <supabase_id_or_existing_id> }, ... }`
- INSERT 결과뿐 아니라 **SKIP 시에도** sqlite_id → 외부망 기존 id 를 매핑에 기록한다.

## R2 업로드 대상 (정정)

[`backend/routes/`](backend/routes/) 코드의 실제 prefix와 일치:

| 디렉토리 | 파일 수 | 용량 | R2 prefix | 출처 |
|----------|---------|------|-----------|------|
| proposals/technical/ + price/ | 41 | 1.16 GB | `proposals/` | [`backend/routes/proposals.py`](backend/routes/proposals.py) 참고 후 확정 |
| contracts/ | 76 | 1.63 GB | `contracts/` | [`backend/routes/contracts.py`](backend/routes/contracts.py) |
| performance/ | 42 | 147 MB | `performance/` | [`backend/routes/performance.py`](backend/routes/performance.py) 참고 후 확정 |
| tor_rfp/ | 30 | 122 MB | `tor_rfp/` | [`backend/routes/tor_rfp.py:199`](backend/routes/tor_rfp.py#L199) |
| eoi (입찰 EOI) | (별도) | 소량 | `eoi/` | [`backend/routes/bidding.py:344`](backend/routes/bidding.py#L344) |
| board/ (overseas_tech + oda 첨부) | (별도) | 소량 | `board/` | [`backend/routes/board.py:117`](backend/routes/board.py#L117) |
| oda_reports/ | 237 | 2.30 GB | `oda_reports/` | [`backend/routes/oda_reports.py`](backend/routes/oda_reports.py) |
| oda_notes/ | (별도) | 소량 | `oda_notes/` | [`backend/routes/oda_reports.py:441`](backend/routes/oda_reports.py#L441) |
| **총합** | **~430+** | **~5.4 GB** | (R2 9GB 한도 사전 점검 필수) | |

## 구현 단계

### Stage 0 — 사전 준비 (사용자 수작업 + 환경 정합화)

**0-a. .gitignore 정합화 (커밋 사고 방지)** — 현재 [`.gitignore:57`](.gitignore#L57)이 `scripts/` 전체를 ignore하므로 마이그레이션 스크립트가 커밋되지 않음. **두 안 중 택일**:

- **권장**: 스크립트를 `backend/migrations/data_import/` 에 둔다 ([`backend/migrations/`](backend/migrations/) 는 현재 git tracking됨 → 자연스럽게 커밋).
- 대안: `.gitignore` 끝에 `!scripts/migrate/` 예외 + `!scripts/migrate/**` 추가.

또한 데이터·산출물은 명시적으로 ignore (현재 `.gitignore` 에는 `*.csv`, `*.zip`, `*.txt` 만 있어 `.jsonl`/`.sql`/`.json` 누락):

```
# Migration intermediates (절대 커밋 금지)
_migration_src/
backend/migrations/data_import/exports/
backend/migrations/data_import/manifests/
*.jsonl
*.sql
id_mapping*.json
uploaded_manifest*.jsonl
failed_uploads*.csv
conflicts_report*.csv
migration_report*.md
backup_*.sql
r2_objects_before*.txt
```

**0-b. 백업**
- Supabase: 대시보드 Backups (자동) + 수동 SQL dump
  ```powershell
  pg_dump "postgresql://postgres.zzypdvwdwgwocczpaaiu:KrcGlobal2026!DB@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres" `
    -f "backup_$(Get-Date -Format yyyy-MM-dd_HHmmss).sql"
  ```
- R2 객체 listing: `python backend/migrations/data_import/00_r2_list_backup.py > r2_objects_before.txt`

**0-c. 내부망 자료 반입** (USB 등):
- `E:\해외사업관리시스템\backend\database\gbms.db` → `_migration_src\gbms.db`
- `E:\해외사업관리시스템\backend\uploads\` 의 7개 디렉토리 (proposals, contracts, performance, tor_rfp, eoi, oda_reports, oda_notes, board) → `_migration_src\uploads\`
- cv·hr·pds 디렉토리는 반입 제외

### Stage 1 — 스키마 검증 (read-only)

`backend/migrations/data_import/01_check_schema.py`:
- Flask app context 안에서 SQLAlchemy로 외부망 PostgreSQL에 연결 (psycopg2 / SQLAlchemy 사용)
- `information_schema.columns` 와 내부망 SQLite `PRAGMA table_info` 비교
- 결과: `schema_diff.md` 출력 (외부망에만 있는 컬럼 / 내부망에만 있는 컬럼 / 타입 차이)
- **ALTER 자동실행 안 함** — 외부망 코드 우선 정책. 보고만.

### Stage 2 — SQLite → JSONL 추출

`backend/migrations/data_import/10_export_sqlite.py`:
- 인자: `--db _migration_src/gbms.db --out _migration_src/exports/`
- **컬럼 화이트리스트**: 외부망 [`backend/models/__init__.py`](backend/models/__init__.py) 에 정의된 컬럼만 추출 (PDS, CV 등 자동 배제)
- `board_posts` 는 `board_type IN ('overseas_tech','oda')` 필터
- 출력: `{table}.jsonl` (한 줄 한 레코드, datetime은 ISO 8601)
- `users.jsonl` 별도 추출 — 매핑용 (user_id, name, employee_number)

### Stage 3 — User 매핑 생성 (Stage 4 의존)

`backend/migrations/data_import/15_build_user_map.py`:
- 외부망 [`User`](backend/models/__init__.py#L48) 의 unique 키는 `user_id` (line 53). `username` 아님.
- 내부망 users 와 외부망 users 를 `user_id` 로 매칭 → `user_map.json`: `{ "<sqlite_user_id_int>": <supabase_users_id_int>, ... }`
- 미매칭 사용자는 보고서 출력, 사용자가 (1) 외부망에 신규 사용자 수동 생성 or (2) admin id로 폴백 결정.
- 모든 후속 단계는 `created_by`, `updated_by` 컬럼을 이 매핑으로 치환.

### Stage 4 — Supabase Upsert (skip-conflict)

`backend/migrations/data_import/20_import_to_supabase.py`:
- Flask app + `current_app` context 안에서 실행 (모델 재사용)
- 임포트 순서:
  1. 부모: `consulting_projects` → `oda_projects` → `methane_projects`
  2. 자식 1차: `consulting_personnel`, `proposals`, `proposal_statuses`, `tor_rfp`, `eois`, `contracts`, `performance_records`
  3. 자식 2차: `oda_reports`, `oda_manual_data`, `oda_notes`, `methane_budget_data`
  4. `board_posts` (마지막)
- 각 테이블마다:
  - Conflict key 로 SELECT → 존재 시 SKIP, sqlite_id → 기존 id 매핑 기록
  - 없을 시 INSERT (id는 외부망 자동할당), sqlite_id → 신규 id 매핑 기록
  - FK 컬럼은 `id_mapping.json` 기반 자동 치환
- 트랜잭션은 테이블 단위. 중단 후 재실행 가능.
- `--dry-run` 지원. `--limit N` 으로 일부만 테스트.
- 결과: `id_mapping.json`, `conflicts_report.csv`, `insert_report.csv`.

### Stage 5 — R2 업로드 (재실행 가능)

`backend/migrations/data_import/30_upload_files_to_r2.py`:

**Flask app context 필수**: [`backend/utils/r2_storage.py:5`](backend/utils/r2_storage.py#L5) 가 `from flask import current_app` 이고 line 14-15 에서 `current_app.config` 에 접근. 스크립트 진입부에서:
```python
from app import create_app  # or 외부망 app.py 의 팩토리/모듈
app = create_app('production')
with app.app_context():
    ...
```
(README에 명시.)

**재실행성 (Idempotency)**:
- 기존 disk filename 규칙 [`backend/utils/file_naming.py:61`](backend/utils/file_naming.py#L61) 의 `datetime.now()` 타임스탬프 사용은 비결정적 → **마이그레이션 전용 결정적 키 생성기** 별도 함수:
  - consulting계: `make_overseas_tech_filename(...)` (타임스탬프 없는 버전) + `_migrated` 접미사 옵션
  - ODA 보고서: `make_oda_report_filename(...)` 그대로 사용 (타임스탬프 없음)
  - 이미 외부망 함수는 다운로드용은 결정적, 디스크용만 비결정적임 → 디스크용은 쓰지 않고 다운로드용 규칙 + `_<sqlite_id>` 접미사로 충돌 방지
- `uploaded_manifest.jsonl` 에 `(table, sqlite_id, r2_key, sha256, file_size, uploaded_at)` 기록
- 업로드 전 단계:
  1. manifest에 동일 (table, sqlite_id) 있으면 SKIP
  2. R2 `head_object(r2_key)` 호출, 존재 시 SKIP (DB만 업데이트)
  3. 미존재 시 [`upload_file()`](backend/utils/r2_storage.py) 호출
  4. 성공 후 외부망 DB의 file_path/file_size 업데이트 + manifest 기록
- 실패: `failed_uploads.csv` 에 사유 기록, exit code 비-0

**용량 사전 점검**: 시작 시 `get_bucket_usage()` 호출하여 현재 + 예상 합계 < 9GB 확인. 초과 시 사용자에게 알리고 abort.

### Stage 6 — 검증

`backend/migrations/data_import/40_verify.py`:
- 테이블별: export 행 수 vs (insert + skip) vs Supabase 신규 COUNT
- R2: 각 prefix(`contracts/`, `oda_reports/`, `tor_rfp/`, `eoi/`, `board/`, `oda_notes/`, `proposals/`, `performance/`)에서 신규 객체 3건 head_object
- FK 무결성: `consulting_personnel.consulting_project_id NOT NULL`, `oda_reports.oda_project_id NOT NULL` 등 부모 존재 확인
- 결과: `migration_report.md`
- 웹 수동 smoke test:
  - 해외기술용역 목록에서 내부망 신규 사업 표시 확인
  - 임의 사업 → 제안서·계약서·실적·TOR/RFP·EOI 미리보기/다운로드
  - 국제협력사업 → ODA 보고서 다운로드, 비고 첨부 다운로드
  - 외부망 기존 사업 미변경 확인 (SKIP 정책 검증)

### Stage 7 — 정리

- 결과 스크립트·README는 `backend/migrations/data_import/` 에 커밋
- `_migration_src/` 임시 폴더는 외장 디스크 백업 후 작업 PC에서 삭제
- 산출물(`*.jsonl`, `id_mapping.json`, manifest, csv, sql) 은 git에 커밋하지 않음 (Stage 0-a 참조)

## 롤백 절차 (README에 포함)

각 Stage 별 실패 지점 기준:

| 실패 지점 | 롤백 동작 |
|----------|----------|
| Stage 4 도중(INSERT) | 트랜잭션 자동 롤백. 부분 적용된 테이블이 있다면 `id_mapping.json` 의 신규 id 목록으로 해당 행만 `DELETE`. |
| Stage 4 완료 후 전체 되돌리기 | `pg_restore` 로 Stage 0-b 의 SQL dump 복원. id_mapping.json 폐기. |
| Stage 5 도중(R2) | `uploaded_manifest.jsonl` 의 신규 r2_key 만 `delete_file()` 일괄 호출하는 `99_rollback_r2.py` 실행. DB의 file_path도 NULL로 되돌림. |
| 전체 완전 롤백 | (1) R2: manifest 기준 신규 객체 일괄 삭제, (2) DB: `pg_restore` 백업 복원, (3) 산출물 폐기. |

## 작성·수정할 파일

**신규 (모두 [`backend/migrations/data_import/`](backend/migrations/data_import/) 에 배치 — `.gitignore` 와 충돌 없음)**
- `00_r2_list_backup.py`
- `01_check_schema.py`
- `10_export_sqlite.py`
- `15_build_user_map.py`
- `20_import_to_supabase.py`
- `30_upload_files_to_r2.py`
- `40_verify.py`
- `99_rollback_r2.py`
- `README.md` (실행 순서, Flask app context 사용법, 사용자 매핑 가이드, 롤백 절차)

**수정**
- [`.gitignore`](.gitignore) — Stage 0-a 의 ignore 패턴 추가

**참조 전용 (수정 X)**
- [`backend/config.py`](backend/config.py)
- [`backend/models/__init__.py`](backend/models/__init__.py)
- [`backend/utils/r2_storage.py`](backend/utils/r2_storage.py)
- [`backend/utils/file_naming.py`](backend/utils/file_naming.py)
- [`backend/routes/`](backend/routes/) 내 proposals/contracts/performance/tor_rfp/oda_reports/bidding/board

**의도적 미반영 (외부망 코드 우선 정책)**
- 내부망 `overseas-tech.html` 무한 스크롤
- 내부망 `common.js` menuMap '계약서관리' 라벨
- 내부망 `migrate_*.py` (외부망은 `backend/migrations/` 와 `_run_migrations()` 사용)

## 위험 요소 및 대응 (보강)

| 위험 | 대응 |
|------|------|
| `.gitignore` 가 `scripts/` 전체 무시 + 데이터 산출물 untracked로 노출 | Stage 0-a 에서 `backend/migrations/data_import/` 사용 + 산출물 ignore 패턴 추가 |
| `consulting_projects.number` 등이 unique 아님 → 단일 키 충돌검사 위험 | 위 표의 복합 자연키 사용. SKIP 시에도 id_mapping 기록 |
| R2 prefix 코드와 불일치 시 미리보기 깨짐 | 위 표의 정정된 prefix 사용. 라우트 코드와 1:1 일치 |
| timestamp 기반 disk filename → 재실행 시 중복 객체 | 결정적 key + `uploaded_manifest.jsonl` + R2 head_object 사전 체크 |
| `r2_storage.py` 가 `current_app` 의존 | 모든 스크립트가 `with app.app_context():` 안에서 동작 (README 명시) |
| 외부망 User 키가 `user_id` (string) 인데 매핑을 `username` 으로 짜면 매칭 실패 | `user_map.json` = `{sqlite_user_id_int → supabase_users_id_int}`, 매칭 기준은 `User.user_id` |
| 한글 파일명/인코딩 (CP949 vs UTF-8) | `secure_filename()` 만 쓰지 말고 정규화 함수 별도 작성. 원본 파일명은 DB `file_name` 에 보존 |
| Supabase Transaction Pooler(:6543) prepared stmt 미지원 | SQLAlchemy `execution_options(compiled_cache=None)` 또는 직접 `executemany` |
| R2 9GB 한도 | Stage 0-b 에서 현재 사용량 확인. Stage 5 시작 시 사전 합계 점검 |
| 마이그레이션 중 외부망 사용자 동시 입력 | 야간/주말 실행. SKIP 정책으로 신규 입력은 영향 없음 |
| 부분 실패 후 재실행 | 모든 스크립트 idempotent: 매핑·매니페스트 기반 skip + 트랜잭션 단위 |

## Verification (체크리스트)

1. `python backend/migrations/data_import/40_verify.py --report migration_report.md` 실행 → 신규 INSERT 수와 SKIP 수 보고
2. 외부망 Vercel URL 접속 → 해외기술용역·국제협력사업 목록에 내부망 신규 사업 표시
3. 임의 신규 사업: 제안서(이중파일)·계약서·실적·TOR/RFP·EOI 미리보기 정상
4. ODA 사업: 보고서·비고 첨부 다운로드 정상
5. 외부망 기존 사업 무변경 확인 (사전·사후 sample SELECT diff)
6. R2 사용량 9GB 미만 (`00_r2_list_backup.py` 재실행 후 diff)
7. `failed_uploads.csv`, `conflicts_report.csv` 비어있거나 모두 사용자 검토 완료

## 다음 액션

승인 후 Stage 0-a (`.gitignore` 패치) → Stage 0-b (백업) → Stage 0-c (자료 반입) → Stage 1 (`01_check_schema.py` 작성·실행) 순으로 진행. 첫 코드 작업은 `.gitignore` 수정 + `01_check_schema.py` + `10_export_sqlite.py` 페어.
