# 해외진출지원사업 (융자사업) 시스템 완성 보고서

## 목차
1. [시스템 개요](#시스템-개요)
2. [데이터베이스 구조](#데이터베이스-구조)
3. [API 엔드포인트](#api-엔드포인트)
4. [프론트엔드 페이지](#프론트엔드-페이지)
5. [데이터 임포트](#데이터-임포트)
6. [사용 방법](#사용-방법)
7. [관리 기능](#관리-기능)

---

## 시스템 개요

해외진출지원사업(융자사업) 관리 시스템은 한국농어촌공사의 해외 진출 기업 대상 융자 지원 사업을 관리하는 통합 시스템입니다.

### 주요 기능
- **기업관리**: 50개 기업 정보 관리
- **융자관리**: 308개 융자 계약 및 집행 현황 관리
- **정보표출**: 6개 하위 메뉴를 통한 다각적 데이터 분석
  - 융자사업 추진실적 (76건)
  - 연도별 상환내역 (76건)
  - 융자사업 관리 (312건)
  - 기업별 담보 현황 (180건)
  - 사후관리대장 (48건)
  - 근저당권 설정계약서 (124건)

---

## 데이터베이스 구조

### 1. Company (기업관리)
**테이블명**: `companies`

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| number | Integer | 번호 |
| name | String(200) | 기업명 (필수, 인덱스) |
| size | String(50) | 기업규모 (중소/중견/대기업) |
| address | Text | 기업주소 |
| email | String(200) | 메일주소 |
| phone | String(50) | 전화번호 |
| created_by | String(100) | 등록자 |
| created_at | DateTime | 등록일 |
| updated_by | String(100) | 수정자 |
| updated_at | DateTime | 수정일 |

**관계**:
- `Loan` 모델과 1:N 관계 (cascade delete)

---

### 2. Loan (융자관리)
**테이블명**: `loans`

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| number | Integer | 번호 |
| year | Integer | 연도 (인덱스) |
| company_id | Integer | 기업 FK |
| company_name | String(200) | 기업명 (인덱스) |
| country | String(100) | 국가 |
| crops | String(200) | 작물 |
| interest_rate | String(20) | 이율 |
| principal | BigInteger | 융자원금 (원) |
| repaid_amount | BigInteger | 상환액 |
| balance | BigInteger | 잔액 |
| contract_date | Date | 계약연월 |
| execution_deadline | Date | 집행기한 |
| maturity_date | Date | 만기일 |
| payment_due_date | Date | 납부예정일 |
| payment_month | String(10) | 납부약정월 |
| messenger_subscription | String(10) | 메신저 수신여부 |
| business_evaluation | String(50) | 사업평가 |
| post_management | String(50) | 사후관리 |

---

### 3. LoanPerformance (융자사업 추진실적)
**테이블명**: `loan_performance`

연도별 융자액을 추적하는 집계 테이블

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| country | String(100) | 대상국가 (인덱스) |
| company_count | Integer | 기업수 |
| company_name | String(200) | 기업명 |
| main_crop | String(100) | 주요작물 |
| year_2009 ~ year_2026 | Integer | 연도별 융자액 (백만원) |
| total | Integer | 계 |

---

### 4. LoanRepayment (연도별 상환내역)
**테이블명**: `loan_repayment`

연도별 상환액을 추적하는 집계 테이블

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| country | String(100) | 대상국가 |
| company_count | Integer | 기업수 |
| company_name | String(200) | 기업명 |
| main_crop | String(100) | 주요작물 |
| balance | BigInteger | 잔액 |
| year_2010 ~ year_2026 | Integer | 연도별 상환액 (백만원) |
| total | Integer | 계 |

---

### 5. LoanProject (융자사업 관리)
**테이블명**: `loan_projects`

융자사업의 상세 관리 정보

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| year | Integer | 연도 (인덱스) |
| company_name | String(200) | 융자기업 (인덱스) |
| country | String(100) | 국가 |
| crops | String(200) | 작물 |
| contract_date | String(100) | 계약년월(지급일) |
| execution_deadline | String(50) | 집행기한 |
| maturity_date | String(50) | 만기일 |
| payment_month | String(10) | 납부약정월 |
| loan_payment | BigInteger | 융자금 지급액 |
| principal_balance | BigInteger | 원잔금액 |
| collateral_type | Text | 담보종류 |
| bond_amount | String(200) | 채권채고액 |
| guarantee_period | String(100) | 보증기간 |
| business_evaluation | String(100) | 사업평가 |
| post_management | Text | 사후관리 |

---

### 6. CompanyCollateral (기업별 담보 현황)
**테이블명**: `company_collateral`

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| number | Integer | 번호 |
| company_name | String(200) | 기업명 (인덱스) |
| loan_amount | BigInteger | 융자액 |
| balance | BigInteger | 잔액 |
| deposit_pledge | BigInteger | 예금질권 (백만원) |
| payment_guarantee | BigInteger | 지급보증 |
| guarantee_insurance | BigInteger | 보증보험 |
| real_estate | BigInteger | 부동산 |
| total_collateral | BigInteger | 총담보금액 |
| deposit_pledge_ratio | Float | 예금질권 비율 (%) |
| payment_guarantee_ratio | Float | 지급보증 비율 |
| guarantee_insurance_ratio | Float | 보증보험 비율 |
| real_estate_ratio | Float | 부동산 비율 |
| bond_deposit | BigInteger | 채권-예금 |
| bond_payment_guarantee | BigInteger | 채권-지급보증 |
| bond_insurance | BigInteger | 채권-보험 |
| bond_real_estate | BigInteger | 채권-부동산 |
| bond_total | BigInteger | 채권 합계 |
| notes | Text | 비고 |

---

### 7. PostManagement (사후관리대장)
**테이블명**: `post_management`

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| year | Integer | 연도 (인덱스) |
| business_operator | String(200) | 사업자 (인덱스) |
| loan_amount | String(100) | 융자금액 |
| loan_date | Date | 융자일자 |
| repayment_completion_date | Date | 상환완료예정일 |
| annual_repayment_date | String(50) | 연도별상환일 |
| collateral_provider | String(200) | 담보제공자 |
| collateral_property | Text | 담보부동산 |
| established_right | String(100) | 설정한권리 |
| is_bare_land | String(10) | 나대지여부 |
| is_superficies_set | String(10) | 지상권설정여부 |
| notes | Text | 비고 |

---

### 8. MortgageContract (근저당권 설정계약서)
**테이블명**: `mortgage_contracts`

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| id | Integer | 기본키 |
| year | Integer | 연도 (인덱스) |
| business_operator | String(200) | 사업자 (인덱스) |
| loan_amount | String(100) | 융자금액 |
| remaining_principal | String(100) | 잔여원금 |
| mortgage_date | Date | 근저당권 설정일 |
| repayment_completion_date | Date | 상환완료 예정일 |
| collateral_provider | String(200) | 담보제공자 |
| collateral_property | Text | 담보부동산 |
| mortgage_amount | String(100) | 설정금액 |
| mortgage_history | Text | 근저당권 변동내역 |
| notes | Text | 비고 |

---

## API 엔드포인트

모든 API는 `/api/expansion` 프리픽스를 사용합니다.

### 1. 기업관리 API

#### GET /api/expansion/companies
기업 목록 조회

**Query Parameters**:
- `page` (int): 페이지 번호 (기본값: 1)
- `perPage` (int): 페이지당 개수 (기본값: 20)
- `search` (string): 기업명 검색
- `size` (string): 기업규모 필터

**Response**:
```json
{
  "success": true,
  "data": [...],
  "total": 50,
  "page": 1,
  "perPage": 20,
  "totalPages": 3
}
```

#### POST /api/expansion/companies/upload
Excel 파일 업로드 (Admin만)

**Request**: multipart/form-data
- `file`: Excel 파일

---

### 2. 융자관리 API

#### GET /api/expansion/loans
융자 목록 조회

**Query Parameters**:
- `page`, `perPage`: 페이지네이션
- `year` (int): 연도 필터
- `country` (string): 국가 필터
- `companyName` (string): 기업명 검색

#### GET /api/expansion/loans/stats
융자 통계 조회

**Response**:
```json
{
  "success": true,
  "data": {
    "totalPrincipal": 123456789,
    "totalRepaid": 12345678,
    "totalBalance": 111111111,
    "totalCompanies": 50,
    "byYear": [...],
    "byCountry": [...]
  }
}
```

#### POST /api/expansion/loans/upload
Excel 파일 업로드 (Admin만)

---

### 3. 정보표출 API

#### GET /api/expansion/performance
융자사업 추진실적 조회

#### GET /api/expansion/repayment
연도별 상환내역 조회

#### GET /api/expansion/projects
융자사업 관리 조회 (페이지네이션)

**Query Parameters**:
- `page`, `perPage`
- `year`, `companyName`

#### POST /api/expansion/projects/upload
융자사업 관리 Excel 업로드 (Admin만)

#### GET /api/expansion/collateral
기업별 담보현황 조회

#### GET /api/expansion/post-management
사후관리대장 조회 (페이지네이션)

#### POST /api/expansion/post-management/upload
사후관리대장 Excel 업로드 (Admin만)

#### GET /api/expansion/mortgage
근저당권 설정계약서 조회 (페이지네이션)

#### POST /api/expansion/mortgage/upload
근저당권 설정계약서 Excel 업로드 (Admin만)

---

## 프론트엔드 페이지

### 페이지 구조

```
pages/expansion/
├── company-management.html      # 기업관리
├── loan-management.html         # 융자관리
└── info/
    ├── loan-performance.html     # 융자사업 추진실적
    ├── loan-repayment.html       # 연도별 상환내역
    ├── loan-projects.html        # 융자사업 관리
    ├── company-collateral.html   # 기업별 담보 현황
    ├── post-management.html      # 사후관리대장
    └── mortgage-contract.html    # 근저당권 설정계약서
```

### 주요 기능

#### 1. 통합 메뉴 시스템
- 모든 페이지에서 일관된 사이드바 메뉴 제공
- Level 4 중첩 서브메뉴 지원 (정보표출 하위 6개 메뉴)
- 현재 페이지 자동 활성화 및 메뉴 확장

#### 2. 검색 및 필터링
- 기업명, 연도, 국가 등 다양한 검색 조건
- 실시간 검색 결과 업데이트

#### 3. 페이지네이션
- 20/50/100개씩 보기 옵션
- 이전/다음 페이지 네비게이션
- 총 건수 표시

#### 4. 데이터 테이블
- 반응형 테이블 디자인
- 정렬 가능한 컬럼
- 금액 포맷팅 (천단위 구분)

#### 5. Admin 기능
- Excel 파일 업로드
- 데이터 일괄 업데이트

---

## 데이터 임포트

### 임포트 스크립트 실행

```bash
cd backend
python3 scripts/import_loan_data.py
```

### 임포트 결과

```
==================================================
임포트 결과 요약
==================================================
  기업정보: 0개 (이미 존재)
  융자관리: 77개 (신규)
  융자사업 추진실적: 19개
  연도별 상환내역: 19개
  융자사업 관리: 78개
  기업별 담보현황: 45개
  사후관리대장: 12개
  근저당권 설정계약서: 31개

총 281개 레코드 임포트 완료
==================================================
```

### 데이터베이스 현황

| 테이블 | 레코드 수 |
|--------|-----------|
| Companies | 50 |
| Loans | 308 |
| Loan Performance | 76 |
| Loan Repayment | 76 |
| Loan Projects | 312 |
| Company Collateral | 180 |
| Post Management | 48 |
| Mortgage Contracts | 124 |

---

## 사용 방법

### 1. 서버 실행

```bash
# 백엔드 서버 시작
cd backend
python3 app.py

# 또는 루트 디렉토리에서
./start.sh
```

### 2. 로그인
- URL: `http://localhost:5001/index.html`
- 테스트 계정: `admin / admin123`

### 3. 해외진출지원사업 메뉴 접근
1. 좌측 사이드바에서 "사업관리" 클릭
2. "해외진출지원사업" 하위 메뉴 확장
3. 원하는 하위 메뉴 선택

### 4. 데이터 조회
- **기업관리**: 기업 목록, 검색, 필터링
- **융자관리**: 융자 계약 목록, 통계 대시보드
- **정보표출**: 6개 하위 메뉴에서 다각적 분석

### 5. 데이터 검색
- 검색창에 키워드 입력
- 필터 옵션 선택 (연도, 국가, 기업규모 등)
- "검색" 버튼 클릭

---

## 관리 기능

### Admin 전용 기능

#### 1. Excel 업로드
- 각 페이지 상단의 "Excel 업로드" 버튼 클릭
- Excel 파일 선택 및 업로드
- 자동으로 데이터베이스 업데이트

#### 2. 데이터 관리
- CRUD 작업 (생성, 조회, 수정, 삭제)
- 일괄 수정 기능
- 데이터 유효성 검증

#### 3. 통계 대시보드
- 융자 총액, 상환액, 잔액 현황
- 연도별/국가별 집계
- 기업별 담보 비율 분석

---

## 기술 스택

### Backend
- **Framework**: Flask 2.3.3
- **ORM**: SQLAlchemy 3.1.1
- **Database**: SQLite with WAL mode
- **Authentication**: JWT (8시간 만료)

### Frontend
- **HTML5/CSS3**: KRDS 디자인 시스템
- **JavaScript**: Vanilla JS (ES6+)
- **UI Framework**: 커스텀 컴포넌트 시스템

### Data Processing
- **pandas**: Excel 파일 처리
- **openpyxl**: Excel 읽기/쓰기

---

## API 응답 형식

### 성공 응답
```json
{
  "success": true,
  "data": [...],
  "total": 100,
  "page": 1,
  "perPage": 20,
  "totalPages": 5
}
```

### 오류 응답
```json
{
  "success": false,
  "message": "오류 메시지 (한국어)"
}
```

---

## 보안

### 인증
- JWT 토큰 기반 인증
- 8시간 토큰 만료
- 모든 API 엔드포인트에 `@token_required` 적용

### 권한
- **Admin**: 모든 기능 접근, Excel 업로드
- **Manager**: 부서별 데이터 관리
- **User**: 읽기 전용

### 데이터 보호
- SQL Injection 방지 (SQLAlchemy ORM)
- XSS 방지 (입력 검증)
- CSRF 보호 (토큰 검증)

---

## 문제 해결

### 1. 데이터가 표시되지 않음
- 서버가 실행 중인지 확인: `http://localhost:5001`
- 브라우저 콘솔에서 API 오류 확인
- JWT 토큰이 유효한지 확인 (로그아웃 후 재로그인)

### 2. Excel 업로드 실패
- 파일 형식 확인 (.xlsx)
- 컬럼명이 정확한지 확인
- Admin 권한 확인

### 3. 페이지네이션 오류
- API 응답에 `totalPages` 포함 확인
- 쿼리 파라미터 형식 확인

---

## 향후 개선 사항

### 1. 기능 개선
- [ ] 엑셀 다운로드 기능
- [ ] 차트 시각화 (연도별/국가별 통계)
- [ ] 알림 기능 (상환일 도래, 만기 임박)
- [ ] 첨부파일 관리 (계약서, 증빙서류)

### 2. UI/UX 개선
- [ ] 모바일 최적화
- [ ] 다크 모드 지원
- [ ] 인쇄 기능
- [ ] 즐겨찾기 필터

### 3. 성능 개선
- [ ] 데이터 캐싱
- [ ] 가상 스크롤 (대용량 데이터)
- [ ] API 응답 최적화

---

## 참고 자료

- [프로젝트 README](../README.md)
- [API 문서](../backend/CLAUDE.md)
- [GIS 가이드](../README_GIS.md)
- [빠른 시작](../QUICKSTART.md)

---

## 변경 이력

### 2026-01-20
- 초기 시스템 구축 완료
- 8개 모델, 17개 API 엔드포인트 구현
- 8개 프론트엔드 페이지 완성
- 데이터 임포트 스크립트 작성 및 실행
- 총 1,194개 레코드 적재

---

**문서 작성일**: 2026-01-20
**작성자**: Claude Code
**버전**: 1.0
