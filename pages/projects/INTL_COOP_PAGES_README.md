# International Cooperation Document Management Pages

## Overview

7 document management pages created with EXACT template structure from `overseas-tech-proposals.html` (1572 lines each).

## Files Created

### 1. intl-coop-pcp.html - PCP 관리
- **Title**: PCP 관리 (Project Concept Paper 문서 관리)
- **Stats**: 전체 PCP / 승인 / 검토중 / 반려
- **Status Types**: pending, approved, rejected
- **API Endpoint**: `/api/intl-coop-pcp`
- **Extra Fields**: None
- **Table Columns**: 번호, 사업명, 국가, 협력기관, 제출일, 상태, 첨부문서, 관리

### 2. intl-coop-grant-plan.html - 무상원조시행계획서 관리
- **Title**: 무상원조시행계획서 관리
- **Stats**: 전체 계획서 / 승인 / 검토중 / 반려
- **Status Types**: pending, approved, rejected
- **API Endpoint**: `/api/intl-coop-grant-plan`
- **Extra Fields**: None
- **Table Columns**: 번호, 사업명, 국가, 협력기관, 제출일, 상태, 첨부문서, 관리

### 3. intl-coop-feasibility.html - 타당성조사보고서 관리
- **Title**: 타당성조사보고서 관리
- **Stats**: 전체 보고서 / 승인 / 검토중 / 재검토
- **Status Types**: pending, approved, revised
- **API Endpoint**: `/api/intl-coop-feasibility`
- **Extra Fields**: 
  - `surveyOrg` (조사기관) - text, required
- **Table Columns**: 번호, 사업명, 국가, 조사기관, 제출일, 상태, 첨부문서, 관리

### 4. intl-coop-mou.html - 협의의사록 관리
- **Title**: 협의의사록 관리 (R/D, MOU)
- **Stats**: 전체 의사록 / 체결완료 / 협의중 / 갱신필요
- **Status Types**: pending, signed, renewal
- **API Endpoint**: `/api/intl-coop-mou`
- **Extra Fields**:
  - `docType` (문서유형) - select (rd/mou/contract), required
  - `validUntil` (유효기간) - date, optional
- **Table Columns**: 번호, 사업명, 국가, 문서유형, 체결일, 유효기간, 상태, 첨부문서, 관리

### 5. intl-coop-vendor-proposal.html - 업체제안서 및 발표자료 관리
- **Title**: 업체제안서 및 발표자료 관리
- **Stats**: 전체 제안서 / 선정 / 검토중 / 탈락
- **Status Types**: pending, selected, rejected
- **API Endpoint**: `/api/intl-coop-vendor-proposal`
- **Extra Fields**:
  - `vendorName` (업체명) - text, required
- **Table Columns**: 번호, 사업명, 국가, 업체명, 제출일, 상태, 첨부문서, 관리

### 6. intl-coop-pmc.html - PMC보고서 관리
- **Title**: PMC보고서 관리 (사업관리용역)
- **Stats**: 전체 보고서 / 월간보고 / 분기보고 / 최종보고
- **Report Types**: monthly, quarterly, final
- **API Endpoint**: `/api/intl-coop-pmc`
- **Extra Fields**:
  - `reportType` (보고서유형) - select (monthly/quarterly/final), required
  - `reportPeriodStart` (보고기간 시작) - date, required
  - `reportPeriodEnd` (보고기간 종료) - date, required
- **Table Columns**: 번호, 사업명, 국가, 보고서유형, 보고기간, 제출일, 첨부문서, 관리

### 7. intl-coop-performance.html - 성과관리보고서 관리
- **Title**: 성과관리보고서 관리
- **Stats**: 전체 보고서 / 중간평가 / 종료평가 / 사후평가
- **Evaluation Types**: midterm, final, post
- **API Endpoint**: `/api/intl-coop-performance`
- **Extra Fields**:
  - `evaluationType` (평가유형) - select (midterm/final/post), required
  - `evaluationPeriodStart` (평가기간 시작) - date, required
  - `evaluationPeriodEnd` (평가기간 종료) - date, required
- **Table Columns**: 번호, 사업명, 국가, 평가유형, 평가기간, 제출일, 첨부문서, 관리

## Features (Inherited from Template)

All pages include the EXACT template structure with:

### Complete KRDS Design System
- Full header with user dropdown menu
- Responsive sidebar navigation with nested menus
- Professional card-based layout
- KRDS color variables and design tokens
- Consistent spacing and typography

### Full Functionality
- **PDF Preview Modal**: Password protection capability for sensitive documents
- **File Upload**: 500MB limit with validation
- **Role-Based Access**: Admin/Manager/User visibility controls
- **Filters**: Country, Status, Year, Search with reset
- **Pagination**: Full pagination support
- **Statistics Cards**: Real-time stats display
- **Toast Notifications**: Success/error messaging
- **Modal Dialogs**: Registration and editing forms

### Security & Validation
- JWT authentication integration
- File size validation (500MB max)
- Required field validation
- Role-based button visibility
- CSRF protection ready

### API Integration Ready
- Consistent API endpoint pattern: `/api/intl-coop-[type]`
- FormData handling for file uploads
- Error handling with user-friendly messages
- Loading states and empty states

## Menu Integration

All pages are integrated into the sidebar menu under "국제협력사업" submenu:
- 사업현황 (international-cooperation.html)
- **PCP** (intl-coop-pcp.html)
- **무상원조시행계획서** (intl-coop-grant-plan.html)
- **타당성조사보고서** (intl-coop-feasibility.html)
- **협의의사록** (intl-coop-mou.html)
- **업체제안서 및 발표자료** (intl-coop-vendor-proposal.html)
- **PMC보고서** (intl-coop-pmc.html)
- **성과관리보고서** (intl-coop-performance.html)

Each page has the active menu item highlighted correctly.

## Next Steps - Backend Implementation

To make these pages functional, implement the following API endpoints:

1. **GET /api/intl-coop-[type]** - List documents with pagination
2. **POST /api/intl-coop-[type]** - Create new document with file upload
3. **PUT /api/intl-coop-[type]/:id** - Update document
4. **DELETE /api/intl-coop-[type]/:id** - Delete document
5. **GET /api/intl-coop-[type]/:id/file** - Download/preview file
6. **GET /api/intl-coop-[type]/stats** - Get statistics

### Database Schema Considerations

Each document type should include:
- `id`, `project_id`, `submission_date`, `status`
- `file_name`, `file_path`, `file_size`
- `notes`, `created_by`, `created_at`, `updated_at`
- **Type-specific fields**:
  - feasibility: `survey_org`
  - mou: `doc_type`, `valid_until`
  - vendor-proposal: `vendor_name`
  - pmc: `report_type`, `report_period_start`, `report_period_end`
  - performance: `evaluation_type`, `evaluation_period_start`, `evaluation_period_end`

## File Locations

```
pages/projects/
├── intl-coop-pcp.html
├── intl-coop-grant-plan.html
├── intl-coop-feasibility.html
├── intl-coop-mou.html
├── intl-coop-vendor-proposal.html
├── intl-coop-pmc.html
└── intl-coop-performance.html
```

## Template Source

All files based on: `pages/projects/overseas-tech-proposals.html` (1572 lines)

## Verification

✅ All 7 files created at 1572 lines each  
✅ Titles and descriptions customized  
✅ Stats cards with proper labels and IDs  
✅ Status options per page type  
✅ Extra form fields where specified  
✅ Table headers matching requirements  
✅ API endpoints properly configured  
✅ Active menu items correctly set  
✅ Full KRDS design system included  
✅ Complete functionality (PDF preview, upload, etc.)  

---

**Created**: 2026-01-30  
**Template**: overseas-tech-proposals.html  
**Status**: Ready for backend API implementation
