# NUGUNA Global 시스템 구성도

## 1. 목표 서비스 구성도 (Target Service Architecture)

NUGUNA Global 시스템이 제공하는 주요 서비스 모듈과 사용자별 접근 흐름을 나타냅니다.

```mermaid
graph TD
    %% 사용자 계층
    subgraph Users [사용자 계층]
        Admin[시스템 관리자]
        Manager[사업 담당자]
        Exec[경영진]
    end

    %% 채널 계층
    subgraph Channel [채널 계층]
        Web[Web Portal (PC)]
        Mobile[Mobile Web (Tablet/Phone)]
    end

    %% 서비스 모듈 계층
    subgraph Services [서비스 모듈]
        direction TB
        subgraph ProjectMgmt [사업관리]
            Consulting[해외기술용역]
            ODA[국제협력사업]
            Methane[메탄감축사업]
        end
        
        subgraph BusinessSupport [업무지원]
            Budget[예산/정산 (수익성분석)]
            Doc[문서관리]
            Office[해외사무소]
            Personnel[인력/성과]
        end
        
        subgraph GIS [GIS 공간정보]
            GlobalMap[글로벌 맵]
            Cluster[사업 분포/통계]
        end
        
        subgraph AdminSvc [관리자 서비스]
            UserMgmt[사용자 관리]
            Batch[데이터 일괄처리]
            Log[접속/활동 로그]
        end
    end

    %% 데이터/연계 계층
    subgraph DataLayer [데이터 및 연계]
        DB[(GBMS 통합 DB)]
        SAP[SAP ERP (수익성 데이터)]
        NICE[나이스 (인사정보)]
        Groupware[전자결재]
    end

    %% 연결 관계
    Users --> Web
    Users --> Mobile
    
    Web --> ProjectMgmt
    Web --> BusinessSupport
    Web --> GIS
    Web --> AdminSvc

    ProjectMgmt --> DB
    BusinessSupport --> DB
    GIS --> DB
    AdminSvc --> DB

    %% 외부 연계 (현재 반자동/파일 업로드 포함)
    SAP -.-> |HTML/Excel 업로드| Budget
    NICE -.-> |CSV 업로드| Personnel
    Doc -.-> Groupware

    style Users fill:#f9f9f9,stroke:#333
    style Services fill:#e1f5fe,stroke:#0277bd
    style DataLayer fill:#fff3e0,stroke:#ff9800
```

---

## 2. 시스템 구성도 (System Configuration)

내부망 환경에서의 하드웨어 및 소프트웨어 구성 요소 간의 관계를 나타냅니다.

```mermaid
graph LR
    %% 클라이언트 영역
    subgraph Client [Client Side]
        Browser[Web Browser (Chrome/Edge)]
        chartJS[Chart.js (시각화)]
        leaflet[Leaflet.js (지도)]
        vanilla[Vanilla JS / CSS (KRDS)]
    end

    %% 서버 영역
    subgraph Server [Server Side (App/Web Server)]
        Flask[Python Flask 3.11+]
        JWT[PyJWT (인증/보안)]
        
        subgraph Modules [Backend Modules]
            AuthBP[Auth Blueprint]
            ProjectBP[Project Blueprint]
            ProfitBP[Profitability Blueprint]
            OdaBP[ODA Blueprint]
        end
        
        SQLAlchemy[SQLAlchemy ORM]
    end

    %% 데이터베이스 영역
    subgraph Database [Database]
        SQLite[(SQLite 3 + WAL Mode)]
        Files[File System (문서/이미지)]
    end

    %% 네트워크/인프라
    subgraph Infra [Internal Infrastructure]
        Firewall{사내 방화벽}
        InternalNet[사내망 (Intranet)]
    end

    %% 흐름 연결
    Browser <--> |HTTP/JSON (REST API)| Firewall
    Firewall <--> Flask
    
    Flask --> JWT
    Flask --> Modules
    Modules --> SQLAlchemy
    SQLAlchemy <--> SQLite
    Modules <--> Files

    %% 부가 설명
    chartJS -.- Browser
    leaflet -.- Browser
    
    style Client fill:#f1f8e9,stroke:#558b2f
    style Server fill:#f3e5f5,stroke:#7b1fa2
    style Database fill:#e0f7fa,stroke:#006064
    style Infra fill:#eeeeee,stroke:#616161,stroke-dasharray: 5 5
```

### 시스템 특징
1.  **Framework**: Python Flask 기반의 경량화된 웹 애플리케이션 프레임워크 사용
2.  **Database**: SQLite와 WAL(Write-Ahead Logging) 모드를 통한 동시성 처리 최적화 (별도 DB 서버 불필요)
3.  **Frontend**: 외부 라이브러리 의존성을 최소화하고 KRDS(Korea Design System)를 적용한 표준 웹 호환성 준수
4.  **Network**: 사내 내부망 전용 운영 환경에 최적화된 오플라인 패키지 구조
