# 항공권검색 페이지 (Flight Search) 구현 플랜

## Context

KRC 직원들의 해외 출장(ODA·기술용역·해외사무소 출장 등) 빈도가 높은데, 현재 시스템에는 항공권 정보 도구가 없어 외부 사이트(스카이스캐너 등)를 별도로 사용해야 한다. 발주공고 페이지 옆에 **Skyscanner급 검색 UX**를 가진 항공권검색 페이지를 추가해서 사내 도구 단일화 + 출장 비용 사전 시뮬레이션이 가능하도록 한다.

**사용자 결정 사항**:
- 데이터 소스: **Travelpayouts (Aviasales) Data API** (기본). Amadeus Self-Service 는 2026-07-17 단종 예정이라 백업 프로바이더로만 유지. `FLIGHT_PROVIDER` 환경변수(`travelpayouts`|`amadeus`)로 런타임 전환 가능.
- 메뉴 위치: **별도 1단계 메뉴**(`항공권검색`) — 발주공고 메뉴는 건드리지 않음, 사이드바에서 발주공고와 인접 배치
- 1차 기능 범위: 기본 검색 + 가격 캘린더 + 경유/환승 조건 + 멀티시티 + 어디로든(Anywhere) + 정렬·필터
- 보조 시각화: 가격 추이 라인 차트(Chart.js) + 지도 시각화(Leaflet) + 체류일수↔가격 슬라이더

**환경변수**:
```
FLIGHT_PROVIDER=travelpayouts        # 기본값. 'amadeus'로 전환 시 백업 프로바이더 사용.
TRAVELPAYOUTS_TOKEN=<X-Access-Token> # https://www.travelpayouts.com/developers/api 에서 발급
TRAVELPAYOUTS_MARKER=<affiliate-id>  # 선택: 외부 OTA 링크에 어필리에이트 마커 부착용
# (Amadeus 백업 시) AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET / AMADEUS_BASE_URL
```

**핵심 제약**:
- 백엔드는 Vercel Lambda + Supabase Postgres 환경. 외부 HTTPS API 호출은 `backend/services/translator.py`(HuggingFace 호출)에서 이미 검증된 패턴 재사용
- API 키 노출 방지를 위해 반드시 백엔드 프록시 경유. 프론트는 자체 `/api/flights/*`만 호출
- 인증: `@token_required` 적용 (사내 직원만 접근). Amadeus OAuth2 토큰은 서버 메모리 캐싱

---

## 아키텍처 개요

```
[flight-search.html]                       [Browser]
   ├── 검색 폼 (편도/왕복/멀티시티/Anywhere)
   ├── 가격 캘린더 그리드 (Chart.js heatmap)
   ├── 결과 리스트 (KRDS .data-table / .card)
   ├── 가격 추이 라인 차트 (Chart.js)
   ├── 라우트 지도 (Leaflet)
   └── 체류일수 슬라이더
        │
        ▼ apiCall('/flights/search' …)
[Flask Blueprint /api/flights]            [Backend]
   ├── /search           → Flight Offers Search
   ├── /cheapest-dates   → Flight Cheapest Date
   ├── /inspiration      → Flight Inspiration Search (Anywhere)
   ├── /airports         → Airport & City Search (자동완성)
   └── /multi-city       → Flight Offers Search (multi OD)
        │
        ▼ HTTPS
[backend/services/amadeus.py]
   ├── OAuth2 토큰 발급 + 메모리 캐시 (만료 5분 전 갱신)
   ├── _request() — 재시도 + 에러 정규화
   └── 응답 단순화 (프론트 친화 JSON)
        │
        ▼
[Amadeus Self-Service API — test.api.amadeus.com (test) → api.amadeus.com (prod)]
```

---

## Backend

### 1) `backend/config.py` — 환경변수 추가

`Config` 클래스 끝부분에 추가:

```python
# Amadeus Self-Service API
AMADEUS_CLIENT_ID = os.environ.get('AMADEUS_CLIENT_ID', '')
AMADEUS_CLIENT_SECRET = os.environ.get('AMADEUS_CLIENT_SECRET', '')
AMADEUS_BASE_URL = os.environ.get(
    'AMADEUS_BASE_URL',
    'https://test.api.amadeus.com'  # 운영 시 https://api.amadeus.com 으로 교체
)
AMADEUS_DEFAULT_CURRENCY = 'KRW'
```

### 2) `backend/services/amadeus.py` — 신규 파일

`translator.py`의 패턴(환경변수 토큰, 재시도, `_last_error` 캡처)을 그대로 따른다.

핵심 함수:
- `_get_access_token()` — Client Credentials Flow. `(token, expires_at)`을 모듈 레벨 캐시. 만료 30초 전 자동 재발급.
- `_request(method, path, params=None, json=None)` — 토큰 첨부 + 401 시 1회 재발급 후 재시도, 5xx는 최대 2회 재시도.
- `search_flight_offers(origin, destination, departure_date, return_date=None, adults=1, children=0, travel_class=None, non_stop=None, max_stops=None, max_price=None, currency='KRW', max=50)` — `/v2/shopping/flight-offers`
- `search_cheapest_dates(origin, destination, departure_date_range, duration=None, one_way=False, currency='KRW')` — `/v1/shopping/flight-dates` (가격 캘린더 데이터)
- `search_inspiration(origin, max_price=None, departure_date_range=None, currency='KRW')` — `/v1/shopping/flight-destinations` (Anywhere 검색)
- `search_airports(keyword)` — `/v1/reference-data/locations?subType=AIRPORT,CITY` (검색 폼 자동완성)
- `search_multi_city(origin_destinations: list, adults=1, travel_class=None, currency='KRW')` — `/v2/shopping/flight-offers` POST 바디로 멀티시티 OD 페어 전송

응답 정규화: 항공편을 다음 형태로 단순화해서 반환.

```python
{
    'id': 'offer-id',
    'price': {'total': 1234567, 'currency': 'KRW'},
    'itineraries': [
        {
            'duration_minutes': 750,
            'segments': [
                {'carrier': 'KE', 'flight_number': '907', 'from': 'ICN',
                 'to': 'CDG', 'departure': '2026-05-10T10:30',
                 'arrival': '2026-05-10T15:50', 'duration_minutes': 740,
                 'aircraft': '388'}
            ],
            'stops': 0
        }
    ],
    'travelers': 1,
    'class': 'ECONOMY',
    'seats_available': 9,
    'last_ticketing_date': '2026-05-09'
}
```

### 3) `backend/routes/flights.py` — 신규 Blueprint

```python
flights_bp = Blueprint('flights', __name__)

@flights_bp.route('/search', methods=['GET'])
@token_required
def search(current_user):
    # query params 파싱 → amadeus.search_flight_offers() → 정규화 응답
    ...

@flights_bp.route('/cheapest-dates', methods=['GET'])
@token_required
def cheapest_dates(current_user): ...

@flights_bp.route('/inspiration', methods=['GET'])
@token_required
def inspiration(current_user): ...

@flights_bp.route('/airports', methods=['GET'])
@token_required
def airports(current_user): ...

@flights_bp.route('/multi-city', methods=['POST'])
@token_required
def multi_city(current_user): ...
```

표준 응답 포맷 (CLAUDE.md 준수):
- 성공: `{'success': True, 'data': [...], 'meta': {'count': N, 'currency': 'KRW'}}`
- 실패: `{'success': False, 'message': '...한국어 메시지...'}`, HTTP 400/502 등

서버 측 캐시: 동일 검색 파라미터 5분 메모리 캐시(LRU 128). API 호출량 절감 + 같은 사용자 반복 클릭 방지.

### 4) `backend/app.py` — Blueprint 등록

```python
from routes.flights import flights_bp
app.register_blueprint(flights_bp, url_prefix='/api/flights')
```

(89번째 줄 부근 import 그룹과 100번째 줄 부근 register_blueprint 그룹에 각각 추가)

### 5) DB 모델 (선택)

1차 범위에서는 **DB 모델 추가하지 않음**. 검색은 stateless이고 서버 메모리 캐시로 충분. 향후 "최근 검색 기록 / 즐겨찾기 노선" 요구가 들어오면 그때 `FlightSearchHistory` 모델 추가.

---

## Frontend

### 1) `pages/flight-search.html` — 신규 페이지

상대경로: `pages/` 직속이므로 CSS/JS는 `../assets/...`, 대시보드는 `../dashboard.html`, 메뉴는 `../`.

**필수 구조** (CLAUDE.md "페이지 생성 가이드"):
```html
<body class="app-layout">
  <a href="#main-content" class="skip-nav">본문 바로가기</a>
  <header class="app-header">…표준 헤더(다른 페이지와 동일)…</header>
  <aside class="app-sidebar">…표준 사이드바(아래 "메뉴 통합" 참고)…</aside>
  <main id="main-content" class="app-main">
    <!-- 1. 검색 폼 영역 -->
    <section class="search-panel card">
      <div class="trip-type-tabs">
        <button data-tab="round-trip" class="tab-btn active">왕복</button>
        <button data-tab="one-way" class="tab-btn">편도</button>
        <button data-tab="multi-city" class="tab-btn">다구간</button>
        <button data-tab="anywhere" class="tab-btn">어디로든</button>
      </div>

      <form id="searchForm" class="filter-bar flight-search-form">
        <!-- 출발지/도착지 (자동완성) -->
        <!-- 가는 날 / 오는 날 -->
        <!-- 인원 (성인/어린이/유아) 드롭다운 -->
        <!-- 좌석 등급 -->
        <!-- 직항/환승/최대 환승시간 -->
        <!-- 검색 버튼 -->
      </form>

      <!-- 다구간 OD 추가 영역 (multi-city 탭에서만) -->
      <div id="multiCityRows" hidden></div>
    </section>

    <!-- 2. 가격 캘린더 (검색 후 노출) -->
    <section id="priceCalendar" class="card" hidden>
      <h2 class="card-title">가격 캘린더 (±N일)</h2>
      <div class="calendar-grid"><!-- 7×N 그리드, 셀 클릭 시 해당 날짜로 재검색 --></div>
    </section>

    <!-- 3. 결과 영역: 리스트 / 차트 / 지도 탭 -->
    <section class="results-section">
      <aside class="results-filters">
        <!-- 가격 슬라이더, 항공사 체크박스, 환승횟수, 출발시간대,
             경유공항 필터, 체류일수 슬라이더 (왕복일 때) -->
      </aside>
      <div class="results-main">
        <div class="results-tabs">
          <button data-view="list" class="tab-btn active">리스트</button>
          <button data-view="chart" class="tab-btn">가격추이</button>
          <button data-view="map" class="tab-btn">지도</button>
        </div>
        <div id="sortBar" class="sort-bar">
          <button data-sort="price">최저가</button>
          <button data-sort="duration">최단시간</button>
          <button data-sort="stops">환승적은순</button>
          <button data-sort="departure">출발시간</button>
        </div>
        <div id="resultList" class="result-list"><!-- 카드 리스트 --></div>
        <canvas id="priceTrendChart" hidden></canvas>
        <div id="routeMap" class="route-map" hidden></div>
      </div>
    </section>

    <!-- 4. 항공편 상세 모달 -->
    <div id="offerDetailModal" class="modal-overlay" hidden>…</div>
  </main>

  <!-- Scripts: KRDS 표준 순서 -->
  <script src="../assets/js/common.js"></script>
  <script src="../assets/js/api.js"></script>
  <script src="../assets/js/components/toast.js"></script>
  <script src="../assets/js/components/modal.js"></script>
  <script src="../assets/lib/chart.min.js"></script>
  <script src="../assets/lib/leaflet/leaflet.js"></script>
  <link rel="stylesheet" href="../assets/lib/leaflet/leaflet.css">
  <script src="../assets/js/pages/flight-search.js"></script>
</body>
```

**스타일 정책**: KRDS만 사용. 페이지 고유 클래스(예: `.flight-search-form`, `.calendar-grid`, `.result-list`)는 페이지 하단 `<style>` 또는 `assets/css/pages.css`에 추가하되 색상·타이포는 반드시 `var(--color-primary-500)`, `var(--font-size-sm)` 등 토큰만 사용. 추가 색 정의 금지.

### 2) `assets/js/pages/flight-search.js` — 신규 JS 모듈

기능:
- **상태 관리**: `state = { tripType, origins, destinations, dates, passengers, cabinClass, filters, sort, view, results, calendar, lastQuery }`
- **자동완성**: 출발/도착 input에 debounce 250ms로 `apiCall('/flights/airports?keyword=…')` 호출. 결과를 `<datalist>` 또는 커스텀 드롭다운에 렌더.
- **검색**: 탭별로 `/flights/search`, `/flights/multi-city`, `/flights/inspiration` 분기. 로딩 중 스켈레톤 표시.
- **가격 캘린더**: 검색 성공 시 `/flights/cheapest-dates` 병렬 호출 → ±15일 그리드 렌더. 셀 클릭 시 그 날짜로 재검색.
- **결과 정렬·필터**: 클라이언트 측에서 `state.results` 배열을 정렬·필터링. 항공사 카운트, 가격 분포는 `results`에서 동적 산출.
- **가격 추이 차트**: Chart.js line, x축=날짜, y축=최저가. 캘린더 데이터 재사용.
- **지도**: Leaflet에 출도착 공항 마커 + 비행 경로 polyline(대권 곡선은 `L.Polyline.curve` 없이 단순 직선 OK). Anywhere 검색 시 후보 도시들을 마커 클러스터로 표시.
- **체류일수 슬라이더**: 왕복 결과에서 체류일별 최저가 매핑 → 슬라이더 이동 시 결과 리스트 자동 필터.
- **에러 처리**: 모든 API 실패는 `Toast.error('항공권 정보를 불러오지 못했습니다.')`. 401은 `apiCall`이 자동 처리.

### 3) `assets/css/pages.css` 또는 `<style>` 추가

KRDS 변수를 활용한 페이지 전용 클래스 정의. 약 200줄 이내. 새 색상 토큰 추가 금지.

---

## 메뉴 통합

### 1) `assets/js/common.js` menuMap 추가

556번 줄 `'bid-notices': ['발주공고']` 바로 다음에:

```javascript
'flight-search': ['항공권검색'],
```

### 2) 사이드바 HTML 업데이트 — 모든 페이지 일괄

이 코드베이스는 사이드바가 페이지마다 인라인으로 하드코딩되어 있다(공통 템플릿 없음). 새 1단계 메뉴는 모든 사이드바에 추가해야 다른 페이지에서도 보인다.

전략:
- `pages/` 하위 + 루트의 모든 HTML 파일에서 `<a href="…/notices/bid-notices.html" class="nav-link…">발주공고</a>` 직후에 `<a href="…/flight-search.html" class="nav-link">항공권검색</a>` 추가
- 상대경로(`../`, `../../`)는 위치별로 다르므로 grep으로 발주공고 라인을 찾아 케이스별 Edit 적용
- 발주공고 메뉴 항목은 **건드리지 않음** (텍스트·href·클래스 모두 그대로)

대상 파일 식별:
```bash
grep -rl 'bid-notices\.html' --include='*.html' .
```

### 3) `dashboard.html`

대시보드의 상단 빠른 진입 위젯이나 메뉴 그리드가 있다면 "항공권검색" 카드 추가는 **선택**. 1차 범위에서는 사이드바만 추가하고, 사용 빈도 확인 후 위젯 추가 여부 결정.

---

## 환경변수 / 시크릿 설정

`.env`(로컬) 및 Vercel 환경변수에 추가:

```
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
AMADEUS_BASE_URL=https://test.api.amadeus.com   # 운영 전환 시 변경
```

Amadeus 가입 절차(개발자가 1회 수행):
1. https://developers.amadeus.com 가입 → 자동 승인
2. "Self-Service Workspace"에서 새 앱 생성 → API Key/Secret 발급
3. Test 환경은 즉시 사용 가능 (월 1만 콜)
4. Production 전환은 신청 필요 (1~2일 심사)

**내부망 테스트 필수**: 배포 전 KRC 내부망에서 `curl https://test.api.amadeus.com/v1/security/oauth2/token` 응답을 받을 수 있는지 확인. 차단되면 별도 프록시·화이트리스트 협의 필요.

---

## 핵심 수정·신규 파일 목록

| 종류 | 경로 | 비고 |
|---|---|---|
| 신규 | `backend/services/amadeus.py` | OAuth2 + 5개 엔드포인트 래퍼 |
| 신규 | `backend/routes/flights.py` | `/api/flights/*` Blueprint |
| 수정 | `backend/config.py` | AMADEUS_* 환경변수 추가 |
| 수정 | `backend/app.py` | Blueprint import & 등록 |
| 신규 | `pages/flight-search.html` | 검색 페이지 (KRDS 레이아웃) |
| 신규 | `assets/js/pages/flight-search.js` | 페이지 로직 |
| 수정 | `assets/css/pages.css` (또는 페이지 내 style) | 페이지 전용 KRDS 컴포넌트 |
| 수정 | `assets/js/common.js` (line 556 부근) | menuMap 항목 추가 |
| 수정 | 모든 사이드바 포함 HTML | 발주공고 직후 메뉴 링크 삽입 |

**재사용 자산** (새로 만들지 않음):
- `assets/js/api.js` — `apiCall(path, method, body)` (api.js:15-85)
- `assets/js/components/toast.js` — `Toast.success/error/info`
- `assets/js/components/modal.js` — 항공편 상세 모달
- `assets/lib/chart.min.js` — 가격 캘린더 + 추이 차트
- `assets/lib/leaflet/` — 라우트 지도 (bid-notices.html에서 검증된 통합 패턴)
- `backend/services/translator.py`의 재시도 패턴 — Amadeus 서비스에 그대로 적용

---

## 단계별 구현 순서

1. **백엔드 서비스 + 라우트 (1차 검증)** — `amadeus.py` + `/api/flights/airports`만 먼저 구현해 토큰 발급/외부 호출 가능 여부 확인
2. **검색 폼 + 기본 검색** — 편도/왕복 + 결과 카드 리스트
3. **가격 캘린더 + 가격 추이 차트** — Cheapest Dates API 연동
4. **경유/환승 필터 + 정렬** — 클라이언트 측 필터링
5. **멀티시티 + Anywhere(Inspiration)** — 추가 탭
6. **지도 시각화 + 체류일수 슬라이더** — Leaflet + 슬라이더
7. **사이드바 일괄 업데이트 + menuMap** — 모든 페이지에서 메뉴 노출
8. **상세 모달, 에러/빈 상태 UI, 모바일 반응형 점검**

각 단계 완료 시점에 `python backend/app.py`로 로컬 서버를 띄워 브라우저로 동작 확인.

---

## Verification (E2E 검증 절차)

### 1. 백엔드 단독 테스트
```bash
cd backend
# .env 에 AMADEUS_CLIENT_ID/SECRET 설정 후
FLASK_ENV=development python app.py
```

JWT 토큰 획득 후 (admin / admin123):
```bash
TOKEN="..."
# 공항 자동완성
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5001/api/flights/airports?keyword=Seoul"

# 기본 검색 (인천 → 파리, 2026-05-10 ~ 05-20)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5001/api/flights/search?origin=ICN&destination=CDG&departureDate=2026-05-10&returnDate=2026-05-20&adults=1&currency=KRW"

# 가격 캘린더
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5001/api/flights/cheapest-dates?origin=ICN&destination=CDG&departureDateRange=2026-05-01,2026-05-31"

# Anywhere
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5001/api/flights/inspiration?origin=ICN&maxPrice=1500000"
```

각 응답이 `{"success": true, "data": [...]}` 구조로 오는지 확인. 빈 결과·에러도 검증.

### 2. 프론트 시나리오 (브라우저)
- `http://localhost:5001/pages/flight-search.html` 접속
- 로그인된 상태에서 페이지 로드 시 사이드바에 "항공권검색"이 active 표시됨
- **시나리오 A**: ICN → CDG 왕복 검색 → 결과 카드 리스트 + 가격 캘린더 + 정렬/필터 동작
- **시나리오 B**: 다구간 탭 → ICN→HAN, HAN→BKK, BKK→ICN 3구간 → 결과 표시
- **시나리오 C**: 어디로든 탭 → 출발지 ICN + 예산 150만원 → 후보 도시 카드 + 지도 마커
- **시나리오 D**: 결과의 가격 슬라이더, 항공사 필터, 환승횟수 필터 적용 시 즉시 반영
- **시나리오 E**: 가격 캘린더 셀 클릭 → 해당 날짜로 재검색
- **시나리오 F**: 모바일 폭 (DevTools <768px) → 필터 카드화, 검색 폼 스택
- **시나리오 G**: 다른 페이지(예: bid-notices) → 사이드바에 항공권검색 보임 → 클릭 시 페이지 전환

### 3. 회귀 점검
- 발주공고 페이지(`bid-notices.html`)가 사이드바 변경 후에도 정상 동작 (발주공고 메뉴 active 표시, 데이터 로드)
- 다른 페이지의 사이드바 토글 동작 정상
- 백엔드 다른 라우트 영향 없음 (`pytest backend/tests` 또는 수동 스모크)

### 4. API 키 보안 확인
- 브라우저 DevTools Network 탭에서 `AMADEUS_CLIENT_SECRET`이 응답에 포함되지 않는지 확인
- `Authorization: Bearer …`에 Amadeus 토큰이 노출되지 않는지(우리 백엔드 → Amadeus 호출에서만 사용) 확인

---

## 알려진 한계 및 후속 과제

- **실시간 좌석 잔여 ≠ 예약 가능**: Amadeus Self-Service의 가격은 캐시된 GDS 데이터로 실시간 예약 시 가격이 변할 수 있음. 페이지에 안내문 노출.
- **예약 흐름 없음**: 1차 범위는 검색·시뮬레이션만. 실제 예약은 외부 OTA 링크 이동 또는 사내 출장담당자 안내로 충분.
- **Production 전환 후 트래픽 한도**: 무료 티어 월 1만 콜. 100명 동시 사용 + 캘린더(다중 호출) 시 한도 초과 가능 → 서버 캐시 효율이 핵심. 초과 시 유료 플랜 전환 또는 Kiwi Tequila 듀얼 소스 검토.
- **검색 기록·즐겨찾기**: 1차 미포함. 사용 데이터 쌓이면 `FlightSearchHistory` 모델 추가 검토.
