// ═══════════════════════════════════════════════════════════════
// 항공권검색 페이지 동작
//
// 데이터 소스: 백엔드 /api/flights/* (Amadeus Self-Service 프록시)
// 의존: common.js (debounce, formatNumber, initCommonUI), api.js (apiCall),
//       toast.js (Toast), Chart.js, Leaflet
// ═══════════════════════════════════════════════════════════════

(function () {
    'use strict';

    // ───── 상태 ─────
    const state = {
        tripType: 'round-trip',          // round-trip | one-way | multi-city | anywhere
        tripView: 'list',                // list | chart | map
        sort: 'price',
        currency: 'KRW',
        results: [],                      // 정규화된 offer 배열
        filteredResults: [],
        carriers: {},                     // code → name
        selectedOrigin: null,             // {iata, name, city, ...}
        selectedDestination: null,
        airportNames: {},                 // IATA → {iata, name, city, country, ...}
        calendar: [],                     // cheapest-dates 결과
        priceTrendChart: null,
        routeMap: null,
        anywhere: [],                     // inspiration 결과
        filters: {
            maxPrice: null,
            minPrice: null,
            stops: { 0: true, 1: true, 2: true, 3: true },
            carriers: {},                 // code → bool
            timeBuckets: { dawn: true, morning: true, afternoon: true, evening: true },
            maxDuration: null,
            minDuration: null,
            stayDays: null,
            stayEnabled: false,
        },
    };

    // 프로바이더 표시 이름
    const PROVIDER_LABELS = {
        travelpayouts: 'Travelpayouts (Aviasales)',
        amadeus: 'Amadeus Self-Service',
    };

    // ───── 초기화 ─────
    document.addEventListener('DOMContentLoaded', () => {
        if (typeof initCommonUI === 'function') {
            try { initCommonUI(); } catch (e) { console.warn('initCommonUI failed', e); }
        }
        wireTabs();
        wireForm();
        wireMultiCity();
        wireFilters();
        wireSort();
        wireResultViewTabs();
        wireDetailModal();
        setDefaultDates();
        // 다구간 첫 행을 미리 두 개 추가
        addMultiCityRow();
        addMultiCityRow();
        // 활성 프로바이더 정보 비동기 로드 (배너·칩 표시용, 실패해도 페이지 동작)
        loadProviderInfo();
    });

    async function loadProviderInfo() {
        try {
            const resp = await apiCall('/flights/health');
            if (!resp || !resp.success || !resp.data) return;
            applyProviderInfo(resp.data);
        } catch (e) {
            // 401 은 apiCall 이 처리. 기타 실패는 조용히.
            console.warn('[flight-search] provider info load failed', e);
        }
    }

    function applyProviderInfo(info) {
        const name = info.provider || 'unknown';
        state.providerName = name;
        state.providerConfigured = !!info.configured;
        const label = PROVIDER_LABELS[name] || name;
        const chip = $('#fsProviderChip');
        if (chip) {
            const dot = info.configured ? '🟢' : '🟠';
            const status = info.configured ? '연동됨' : '자격증명 미설정';
            chip.textContent = `${dot} ${label} · ${status}`;
            chip.title = info.last_error ? `마지막 오류: ${info.last_error}` : '';
        }
        const nameSpan = $('#fsProviderName');
        if (nameSpan) nameSpan.textContent = label;
    }

    // ───── 유틸 ─────
    function $(sel, root = document) { return root.querySelector(sel); }
    function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

    function fmtKRW(n) {
        const v = Math.round(Number(n) || 0);
        return '₩' + (typeof formatNumber === 'function' ? formatNumber(v) : v.toLocaleString('ko-KR'));
    }

    function fmtMinutes(min) {
        const m = Math.max(0, Math.round(Number(min) || 0));
        const h = Math.floor(m / 60);
        const r = m % 60;
        return r ? `${h}시간 ${r}분` : `${h}시간`;
    }

    function fmtTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }
    function fmtDateShort(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return `${d.getMonth() + 1}/${d.getDate()} (${'일월화수목금토'[d.getDay()]})`;
    }
    function isoDate(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const da = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${da}`;
    }
    function addDays(date, n) {
        const d = new Date(date.getTime());
        d.setDate(d.getDate() + n);
        return d;
    }

    // ───── 공항 이름 캐시 ─────
    function cacheAirport(item) {
        if (!item || !item.iata) return;
        const code = String(item.iata).toUpperCase();
        // 기존 정보가 더 풍부하면 유지
        const prev = state.airportNames[code];
        if (prev && prev.city && prev.country && (!item.country || prev.country.length >= (item.country || '').length)) return;
        state.airportNames[code] = item;
    }

    function airportInfo(code) {
        if (!code) return null;
        return state.airportNames[String(code).toUpperCase()] || null;
    }

    // 결과 카드용: IATA 아래에 표시할 도시/공항명 한 줄
    function airportSubtitle(code) {
        const info = airportInfo(code);
        if (!info) return '';
        const city = info.city || '';
        const name = info.name || '';
        if (city && name && city !== name) return `${city} · ${name}`;
        return city || name || '';
    }

    // 검색 결과에 등장하는 모든 IATA 중 캐시에 없는 것을 일괄 조회
    async function enrichAirportNames(codes) {
        const need = Array.from(new Set((codes || []).filter(Boolean).map((c) => String(c).toUpperCase())))
            .filter((c) => !state.airportNames[c]);
        if (!need.length) return false;
        // 한 번에 30개 제한
        const chunks = [];
        for (let i = 0; i < need.length; i += 25) chunks.push(need.slice(i, i + 25));
        let updated = false;
        for (const chunk of chunks) {
            try {
                const resp = await apiCall(`/flights/airports/batch?codes=${encodeURIComponent(chunk.join(','))}`);
                if (resp && resp.success && resp.data) {
                    Object.entries(resp.data).forEach(([code, item]) => {
                        cacheAirport({ ...item, iata: code });
                    });
                    updated = true;
                }
            } catch (e) {
                console.warn('[airports/batch] failed', e);
            }
        }
        return updated;
    }

    // 결과 셋에서 등장하는 모든 IATA 수집
    function collectIatasFromOffers(offers) {
        const set = new Set();
        (offers || []).forEach((o) => {
            (o.itineraries || []).forEach((it) => {
                (it.segments || []).forEach((s) => {
                    if (s.from) set.add(s.from);
                    if (s.to) set.add(s.to);
                });
            });
        });
        return Array.from(set);
    }

    function safeToast(kind, msg) {
        if (typeof Toast !== 'undefined' && Toast && Toast[kind]) {
            try { Toast[kind](msg); return; } catch (_) { /* noop */ }
        }
        console[kind === 'error' ? 'error' : 'log'](`[flight-search] ${msg}`);
    }

    function setDefaultDates() {
        const today = new Date();
        const dep = addDays(today, 14);
        const ret = addDays(today, 21);
        $('#fsDeparture').value = isoDate(dep);
        $('#fsReturn').value = isoDate(ret);
        // 과거 날짜 선택 방지
        const minIso = isoDate(today);
        $('#fsDeparture').min = minIso;
        $('#fsReturn').min = minIso;
    }

    // ───── 탭 (왕복/편도/다구간/어디로든) ─────
    function wireTabs() {
        const tabs = $$('#fsTripTabs .fs-tab');
        tabs.forEach((tab) => {
            tab.addEventListener('click', () => {
                tabs.forEach((t) => {
                    t.classList.remove('active');
                    t.setAttribute('aria-selected', 'false');
                });
                tab.classList.add('active');
                tab.setAttribute('aria-selected', 'true');
                state.tripType = tab.dataset.tab;
                applyTripType();
            });
        });
    }

    function applyTripType() {
        const isMulti = state.tripType === 'multi-city';
        const isAnywhere = state.tripType === 'anywhere';
        const isOneWay = state.tripType === 'one-way';

        // 폼 표시 토글
        $('#fsForm').hidden = isMulti;
        $('#fsMultiCity').hidden = !isMulti;

        // 오는 날 / 예산 / 도착지 표시
        $('#fsReturnField').style.display = (isOneWay || isAnywhere) ? 'none' : '';
        $('#fsBudgetField').style.display = isAnywhere ? '' : 'none';

        // Anywhere 모드: 도착지 입력 비활성화
        const destInput = $('#fsDestination');
        if (isAnywhere) {
            destInput.value = '';
            destInput.placeholder = '— Amadeus 추천 도시 자동 검색 —';
            destInput.disabled = true;
            state.selectedDestination = null;
        } else {
            destInput.disabled = false;
            destInput.placeholder = '도시/공항 (예: CDG)';
        }

        // 체류일수 슬라이더는 왕복일 때만 의미 있음
        const staySlider = $('#fsStaySliderGroup');
        if (staySlider) staySlider.hidden = !(state.tripType === 'round-trip');

        // 기존 결과 정리
        hideAllResultSections();
    }

    function hideAllResultSections() {
        $('#fsCalendarSection').hidden = true;
        $('#fsResultsSection').hidden = true;
        $('#fsAnywhereSection').hidden = true;
        $('#fsEmptyState').hidden = true;
        const synth = $('#fsSynthesizedBanner');
        if (synth) synth.hidden = true;
        const fb = $('#fsFallbackBanner');
        if (fb) fb.hidden = true;
    }

    // ───── 자동완성 ─────
    function wireForm() {
        wireAutocomplete($('#fsOrigin'), $('#fsOriginSuggest'), 'origin');
        wireAutocomplete($('#fsDestination'), $('#fsDestinationSuggest'), 'destination');

        // 경유 토글 (검색 폼)
        $$('#fsStopsToggle button').forEach((btn) => {
            btn.addEventListener('click', () => {
                $$('#fsStopsToggle button').forEach((b) => {
                    b.classList.remove('active');
                    b.setAttribute('aria-checked', 'false');
                });
                btn.classList.add('active');
                btn.setAttribute('aria-checked', 'true');
            });
        });

        $('#fsForm').addEventListener('submit', (e) => {
            e.preventDefault();
            handleSearchSubmit();
        });

        $('#fsResetBtn').addEventListener('click', () => {
            $('#fsForm').reset();
            state.selectedOrigin = null;
            state.selectedDestination = null;
            $$('#fsStopsToggle button').forEach((b, i) => {
                b.classList.toggle('active', i === 0);
                b.setAttribute('aria-checked', i === 0 ? 'true' : 'false');
            });
            setDefaultDates();
            hideAllResultSections();
        });
    }

    // 종류별 메타 (아이콘/라벨/그룹 우선순위)
    const SUBTYPE_META = {
        AIRPORT: { icon: '✈️', label: '공항', order: 1 },
        CITY:    { icon: '🏙️', label: '도시', order: 2 },
        COUNTRY: { icon: '🌍', label: '국가', order: 3 },
    };

    function groupSuggestionsForRender(items) {
        // AIRPORT > CITY > COUNTRY 그룹 순서, 그룹 내부는 원래 순서 유지
        const sorted = (items || []).slice().sort((a, b) => {
            const oa = (SUBTYPE_META[a.subtype] || {}).order || 9;
            const ob = (SUBTYPE_META[b.subtype] || {}).order || 9;
            return oa - ob;
        });
        const groups = [];
        let currentType = null;
        sorted.forEach((it) => {
            if (it.subtype !== currentType) {
                groups.push({ subtype: it.subtype, items: [] });
                currentType = it.subtype;
            }
            groups[groups.length - 1].items.push(it);
        });
        return { sorted, groups };
    }

    function wireAutocomplete(input, listEl, role) {
        if (!input || !listEl) return;
        let selectedIdx = -1;
        let flatResults = [];   // 화면 순서 그대로의 평탄화된 배열 (키보드 nav 용)

        const render = (items) => {
            listEl.innerHTML = '';
            if (!items || !items.length) {
                listEl.classList.remove('show');
                flatResults = [];
                return;
            }
            const { sorted, groups } = groupSuggestionsForRender(items);
            flatResults = sorted;

            let runningIdx = 0;
            groups.forEach((g) => {
                const meta = SUBTYPE_META[g.subtype] || { icon: '·', label: '기타' };
                const header = document.createElement('div');
                header.className = 'fs-suggest-group';
                header.innerHTML = `<span>${meta.icon} ${meta.label}</span><span class="count">${g.items.length}</span>`;
                listEl.appendChild(header);

                g.items.forEach((item) => {
                    const idx = runningIdx++;
                    const div = document.createElement('div');
                    div.className = 'fs-suggest-item';
                    div.dataset.idx = String(idx);
                    div.dataset.subtype = g.subtype;
                    div.setAttribute('role', 'option');

                    if (g.subtype === 'COUNTRY') {
                        // 국가: 코드(ISO-2) + 국가명 + 추가 안내
                        div.innerHTML = `
                            <span class="iata country">${item.iata || ''}</span>
                            <span class="primary">${item.name || ''}</span>
                            <span class="meta">국가 · 도시명을 함께 입력하면 더 정확합니다</span>
                        `;
                    } else {
                        const primary = item.subtype === 'CITY'
                            ? (item.city || item.name || '')
                            : (item.name || item.city || '');
                        const sub = [
                            item.subtype === 'AIRPORT' && item.city && item.city !== primary ? item.city : null,
                            item.country,
                        ].filter(Boolean).join(' · ');
                        div.innerHTML = `
                            <span class="iata">${item.iata || ''}</span>
                            <span class="primary">${primary}</span>
                            <span class="meta">${meta.label}${sub ? ' · ' + sub : ''}</span>
                        `;
                    }
                    div.addEventListener('mousedown', (e) => {
                        e.preventDefault();
                        pick(item);
                    });
                    listEl.appendChild(div);
                });
            });
            listEl.classList.add('show');
        };

        const pick = (item) => {
            cacheAirport(item);
            if (item.subtype === 'COUNTRY') {
                // 국가는 검색 가능한 IATA 가 아님 → 클릭 시 input 에 국가명만 채우고
                // 그 국가의 도시/공항으로 다시 자동완성 (같은 keyword 재호출)
                input.value = item.name || '';
                input.dataset.iata = '';
                if (role === 'origin') state.selectedOrigin = null;
                else state.selectedDestination = null;
                fetcher(item.name || '');
                return;
            }
            input.value = `${item.iata} · ${item.name || item.city || ''}`;
            input.dataset.iata = item.iata || '';
            if (role === 'origin') state.selectedOrigin = item;
            else state.selectedDestination = item;
            listEl.classList.remove('show');
        };

        const fetcher = (typeof debounce === 'function' ? debounce : (fn) => fn)(async (q) => {
            try {
                const resp = await apiCall(`/flights/airports?keyword=${encodeURIComponent(q)}`);
                if (resp && resp.success) {
                    render(resp.data || []);
                } else if (resp && resp.message) {
                    safeToast('error', resp.message);
                }
            } catch (e) {
                // apiCall 자체에서 401 리다이렉트 처리됨. 그 외엔 조용히 실패.
                console.warn('[autocomplete] failed', e);
            }
        }, 220);

        input.addEventListener('input', (e) => {
            const q = e.target.value.trim();
            input.dataset.iata = '';
            if (role === 'origin') state.selectedOrigin = null;
            else state.selectedDestination = null;
            if (q.length < 2) {
                listEl.classList.remove('show');
                return;
            }
            // 사용자가 직접 IATA 코드 3자를 입력했다면 패스스루로 인정
            if (/^[A-Za-z]{3}$/.test(q)) {
                if (role === 'origin') state.selectedOrigin = { iata: q.toUpperCase(), name: '' };
                else state.selectedDestination = { iata: q.toUpperCase(), name: '' };
            }
            fetcher(q);
        });

        input.addEventListener('keydown', (e) => {
            if (!listEl.classList.contains('show')) return;
            const items = $$('.fs-suggest-item', listEl);
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIdx = Math.min(items.length - 1, selectedIdx + 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIdx = Math.max(0, selectedIdx - 1);
            } else if (e.key === 'Enter' && selectedIdx >= 0) {
                e.preventDefault();
                pick(flatResults[selectedIdx]);
                return;
            } else if (e.key === 'Escape') {
                listEl.classList.remove('show');
                return;
            }
            items.forEach((it, i) => it.classList.toggle('active', i === selectedIdx));
        });

        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !listEl.contains(e.target)) {
                listEl.classList.remove('show');
            }
        });

        input.addEventListener('focus', () => {
            if (flatResults.length) listEl.classList.add('show');
        });
    }

    // ───── 검색 처리 ─────
    function getStopsParam() {
        const btn = $('#fsStopsToggle .active');
        return btn ? btn.dataset.stops || '' : '';
    }

    function getOriginIata() {
        if (state.selectedOrigin && state.selectedOrigin.iata) return state.selectedOrigin.iata;
        const raw = $('#fsOrigin').value.trim();
        const m = raw.match(/^([A-Za-z]{3})/);
        return m ? m[1].toUpperCase() : '';
    }
    function getDestIata() {
        if (state.selectedDestination && state.selectedDestination.iata) return state.selectedDestination.iata;
        const raw = $('#fsDestination').value.trim();
        const m = raw.match(/^([A-Za-z]{3})/);
        return m ? m[1].toUpperCase() : '';
    }

    async function handleSearchSubmit() {
        if (state.tripType === 'anywhere') {
            return runAnywhere();
        }
        const origin = getOriginIata();
        const destination = getDestIata();
        const departure = $('#fsDeparture').value;
        const ret = $('#fsReturn').value;
        if (!origin || !destination) {
            return safeToast('error', '출발지와 도착지를 선택해 주세요.');
        }
        if (!departure) {
            return safeToast('error', '출발일을 선택해 주세요.');
        }
        const params = {
            origin,
            destination,
            departureDate: departure,
            returnDate: state.tripType === 'round-trip' ? ret : '',
            adults: $('#fsAdults').value,
            children: $('#fsChildren').value,
            infants: $('#fsInfants').value,
            travelClass: $('#fsCabin').value,
        };
        const stops = getStopsParam();
        if (stops === '0') params.nonStop = 'true';
        // 1회 환승까지는 클라이언트 필터에서 제거 (Amadeus는 nonStop 만 지원)

        await runSearch(params);
    }

    async function runSearch(params) {
        const btn = $('#fsSearchBtn');
        btn.disabled = true;
        const oldLabel = btn.innerHTML;
        btn.innerHTML = '⏳ 검색 중…';

        showSkeletons();
        hideAllResultSections();
        $('#fsResultsSection').hidden = false;

        try {
            const qs = new URLSearchParams();
            Object.entries(params).forEach(([k, v]) => {
                if (v !== '' && v !== undefined && v !== null) qs.append(k, v);
            });
            qs.append('currency', state.currency);
            qs.append('max', '50');

            const [searchResp, calResp] = await Promise.all([
                apiCall(`/flights/search?${qs.toString()}`).catch((e) => ({ __err: e })),
                fetchCalendar(params).catch(() => null),
            ]);

            if (searchResp && searchResp.__err) throw searchResp.__err;
            if (!searchResp || !searchResp.success) {
                throw new Error((searchResp && searchResp.message) || '검색에 실패했습니다.');
            }

            state.results = searchResp.data || [];
            state.carriers = ((searchResp.meta || {}).dictionaries || {}).carriers || {};
            state.calendar = (calResp && calResp.success) ? (calResp.data || []) : [];

            // 인근 날짜 폴백 안내
            const fbBanner = $('#fsFallbackBanner');
            if (fbBanner) {
                if ((searchResp.meta || {}).fallback) {
                    const reqDate = (searchResp.meta || {}).requested_date || params.departureDate || '';
                    const target = $('#fsFallbackTarget');
                    if (target) target.textContent = reqDate || '선택한 날짜';
                    fbBanner.hidden = false;
                } else {
                    fbBanner.hidden = true;
                }
            }

            if (!state.results.length) {
                $('#fsResultsSection').hidden = true;
                $('#fsEmptyState').hidden = false;
                renderCalendar(); // 캘린더는 결과가 없어도 표시 시도
                return;
            }

            initFiltersFromResults();
            applyFiltersAndRender();
            renderCalendar();
            renderPriceTrendChart();
            renderRouteMap(params.origin, params.destination);
            // 결과에 등장하는 IATA 일괄 풀네임 조회 → 완료되면 카드 재렌더
            const iatas = collectIatasFromOffers(state.results).concat([params.origin, params.destination]);
            enrichAirportNames(iatas).then((updated) => {
                if (updated) {
                    applyFiltersAndRender();
                    renderRouteMap(params.origin, params.destination);
                }
            });
        } catch (err) {
            console.error('[search] failed', err);
            $('#fsResultsSection').hidden = true;
            $('#fsEmptyState').hidden = true;
            safeToast('error', err.message || '항공권 정보를 불러오지 못했습니다.');
        } finally {
            btn.disabled = false;
            btn.innerHTML = oldLabel;
        }
    }

    async function fetchCalendar(params) {
        // 가격 캘린더 데이터: 출발일 ±15일 범위
        if (!params.origin || !params.destination || !params.departureDate) return null;
        const dep = new Date(params.departureDate);
        if (isNaN(dep.getTime())) return null;
        const from = isoDate(addDays(dep, -15));
        const to = isoDate(addDays(dep, 15));
        const qs = new URLSearchParams({
            origin: params.origin,
            destination: params.destination,
            departureDateRange: `${from},${to}`,
            currency: state.currency,
            oneWay: params.returnDate ? 'false' : 'true',
        });
        try {
            return await apiCall(`/flights/cheapest-dates?${qs.toString()}`);
        } catch (e) {
            console.warn('[calendar] failed', e);
            return null;
        }
    }

    function showSkeletons() {
        const list = $('#fsResultList');
        list.innerHTML = Array.from({ length: 4 }).map(() => '<div class="fs-skeleton"></div>').join('');
    }

    // ───── 필터 ─────
    function initFiltersFromResults() {
        const prices = state.results.map((o) => Number(o.price.total) || 0);
        const minP = Math.min(...prices);
        const maxP = Math.max(...prices);
        state.filters.minPrice = minP;
        state.filters.maxPrice = maxP;

        const durations = state.results.map((o) => totalDuration(o));
        const minD = Math.min(...durations);
        const maxD = Math.max(...durations);
        state.filters.minDuration = minD;
        state.filters.maxDuration = maxD;

        // 가격 슬라이더
        const priceSlider = $('#fsPriceSlider');
        priceSlider.min = String(minP);
        priceSlider.max = String(maxP);
        priceSlider.value = String(maxP);
        priceSlider.step = String(Math.max(1, Math.round((maxP - minP) / 100)));
        $('#fsPriceMin').textContent = fmtKRW(minP);
        $('#fsPriceMax').textContent = fmtKRW(maxP);
        $('#fsPriceCurrent').textContent = fmtKRW(maxP);

        // 소요시간 슬라이더 (분 단위)
        const durSlider = $('#fsDurationSlider');
        durSlider.min = String(minD);
        durSlider.max = String(maxD);
        durSlider.value = String(maxD);
        durSlider.step = String(Math.max(15, Math.round((maxD - minD) / 100)));
        $('#fsDurMin').textContent = `${Math.floor(minD / 60)}h`;
        $('#fsDurMax').textContent = `${Math.floor(maxD / 60)}h`;
        $('#fsDurCurrent').textContent = fmtMinutes(maxD);

        // 항공사 체크박스 동적 생성
        const carrierCounts = {};
        state.results.forEach((o) => {
            (o.validating_carriers || []).forEach((c) => {
                carrierCounts[c] = (carrierCounts[c] || 0) + 1;
            });
            (o.itineraries || []).forEach((it) => {
                (it.segments || []).forEach((s) => {
                    if (s.carrier) carrierCounts[s.carrier] = (carrierCounts[s.carrier] || 0) + 1;
                });
            });
        });
        const list = $('#fsCarriersList');
        list.innerHTML = '';
        const entries = Object.entries(carrierCounts).sort((a, b) => b[1] - a[1]);
        if (!entries.length) {
            list.innerHTML = '<span style="font-size:12px; color: var(--color-neutral-500);">표시할 항공사가 없습니다</span>';
        }
        state.filters.carriers = {};
        entries.forEach(([code, cnt]) => {
            state.filters.carriers[code] = true;
            const label = document.createElement('label');
            const name = state.carriers[code] || code;
            label.innerHTML = `<input type="checkbox" data-carrier="${code}" checked> ${name} <span style="margin-left:auto; color: var(--color-neutral-500); font-size:11px;">${cnt}</span>`;
            list.appendChild(label);
        });
        list.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
            cb.addEventListener('change', () => {
                state.filters.carriers[cb.dataset.carrier] = cb.checked;
                applyFiltersAndRender();
            });
        });

        // 환승/시간대 체크박스 초기화
        $$('#fsStopsFilterGroup input[type="checkbox"]').forEach((cb) => {
            const k = Number(cb.dataset.stops);
            cb.checked = true;
            state.filters.stops[k] = true;
        });
        $$('.fs-results-filters [data-time]').forEach((cb) => {
            cb.checked = true;
            state.filters.timeBuckets[cb.dataset.time] = true;
        });

        // 체류일수 슬라이더
        const stayGroup = $('#fsStaySliderGroup');
        if (stayGroup) {
            stayGroup.hidden = state.tripType !== 'round-trip';
        }
    }

    function totalDuration(offer) {
        return (offer.itineraries || []).reduce((sum, it) => sum + (it.duration_minutes || 0), 0);
    }

    function timeBucket(iso) {
        if (!iso) return null;
        const d = new Date(iso);
        if (isNaN(d.getTime())) return null;
        const h = d.getHours();
        if (h < 6) return 'dawn';
        if (h < 12) return 'morning';
        if (h < 18) return 'afternoon';
        return 'evening';
    }

    function offerStays(offer) {
        // 왕복 체류일수: outbound 도착 ↔ inbound 출발
        if (!offer.itineraries || offer.itineraries.length < 2) return null;
        const out = offer.itineraries[0];
        const back = offer.itineraries[1];
        const lastOut = (out.segments || [])[out.segments.length - 1];
        const firstBack = (back.segments || [])[0];
        if (!lastOut || !firstBack) return null;
        const a = new Date(lastOut.arrival);
        const b = new Date(firstBack.departure);
        if (isNaN(a.getTime()) || isNaN(b.getTime())) return null;
        return Math.round((b - a) / (24 * 3600 * 1000));
    }

    function wireFilters() {
        // 가격 슬라이더
        $('#fsPriceSlider').addEventListener('input', (e) => {
            state.filters.maxPrice = Number(e.target.value);
            $('#fsPriceCurrent').textContent = fmtKRW(state.filters.maxPrice);
            applyFiltersAndRender();
        });
        // 소요시간 슬라이더
        $('#fsDurationSlider').addEventListener('input', (e) => {
            state.filters.maxDuration = Number(e.target.value);
            $('#fsDurCurrent').textContent = fmtMinutes(state.filters.maxDuration);
            applyFiltersAndRender();
        });
        // 환승 체크박스
        $$('#fsStopsFilterGroup input[type="checkbox"]').forEach((cb) => {
            cb.addEventListener('change', () => {
                state.filters.stops[Number(cb.dataset.stops)] = cb.checked;
                applyFiltersAndRender();
            });
        });
        // 시간대
        $$('.fs-results-filters [data-time]').forEach((cb) => {
            cb.addEventListener('change', () => {
                state.filters.timeBuckets[cb.dataset.time] = cb.checked;
                applyFiltersAndRender();
            });
        });
        // 체류일수
        const stayEnable = $('#fsStayEnable');
        const staySlider = $('#fsStaySlider');
        const stayCurrent = $('#fsStayCurrent');
        if (stayEnable && staySlider) {
            stayEnable.addEventListener('change', () => {
                state.filters.stayEnabled = stayEnable.checked;
                applyFiltersAndRender();
            });
            staySlider.addEventListener('input', () => {
                state.filters.stayDays = Number(staySlider.value);
                if (stayCurrent) stayCurrent.textContent = staySlider.value;
                if (state.filters.stayEnabled) applyFiltersAndRender();
            });
        }
    }

    function applyFiltersAndRender() {
        const f = state.filters;
        const filtered = state.results.filter((o) => {
            const p = Number(o.price.total) || 0;
            if (f.maxPrice != null && p > f.maxPrice) return false;
            // 환승: 가장 환승 많은 itinerary 기준
            const maxStops = Math.max(...((o.itineraries || []).map((it) => it.stops || 0)));
            if (maxStops <= 2) {
                if (!f.stops[maxStops]) return false;
            } else {
                if (!f.stops[3]) return false;
            }
            // 소요시간
            if (f.maxDuration != null && totalDuration(o) > f.maxDuration) return false;
            // 항공사 (validating 또는 첫 segment)
            const carrier = (o.validating_carriers && o.validating_carriers[0]) ||
                (o.itineraries[0] && o.itineraries[0].segments && o.itineraries[0].segments[0] && o.itineraries[0].segments[0].carrier);
            if (carrier && f.carriers[carrier] === false) return false;
            // 출발 시간대 (가는 편)
            const dep = (o.itineraries[0] && o.itineraries[0].segments && o.itineraries[0].segments[0] && o.itineraries[0].segments[0].departure);
            const bucket = timeBucket(dep);
            if (bucket && f.timeBuckets[bucket] === false) return false;
            // 체류일수
            if (f.stayEnabled && f.stayDays != null && state.tripType === 'round-trip') {
                const stay = offerStays(o);
                if (stay != null && Math.abs(stay - f.stayDays) > 2) return false;
            }
            return true;
        });

        const sorted = sortOffers(filtered, state.sort);
        state.filteredResults = sorted;
        renderResultList(sorted);
        renderResultSummary(sorted.length, state.results.length);
    }

    function sortOffers(offers, key) {
        const arr = offers.slice();
        if (key === 'price') {
            arr.sort((a, b) => Number(a.price.total) - Number(b.price.total));
        } else if (key === 'duration') {
            arr.sort((a, b) => totalDuration(a) - totalDuration(b));
        } else if (key === 'stops') {
            arr.sort((a, b) => {
                const sa = Math.max(...((a.itineraries || []).map((it) => it.stops || 0)));
                const sb = Math.max(...((b.itineraries || []).map((it) => it.stops || 0)));
                if (sa !== sb) return sa - sb;
                return Number(a.price.total) - Number(b.price.total);
            });
        } else if (key === 'departure') {
            arr.sort((a, b) => {
                const da = new Date(((a.itineraries[0] || {}).segments || [])[0]?.departure || 0).getTime();
                const db = new Date(((b.itineraries[0] || {}).segments || [])[0]?.departure || 0).getTime();
                return da - db;
            });
        }
        return arr;
    }

    function wireSort() {
        $$('#fsSortBar .fs-sort-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                $$('#fsSortBar .fs-sort-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                state.sort = btn.dataset.sort;
                applyFiltersAndRender();
            });
        });
    }

    function renderResultSummary(showing, total) {
        const summary = $('#fsResultSummary');
        const cheapest = state.filteredResults[0];
        let leftHtml = `<span><strong>${showing}</strong>건 / 전체 ${total}건</span>`;
        if (cheapest) {
            leftHtml += `<span style="margin-left:12px;">최저가 <strong style="color: var(--color-primary-600);">${fmtKRW(cheapest.price.total)}</strong></span>`;
        }
        summary.innerHTML = leftHtml;
    }

    // ───── 결과 카드 렌더 ─────
    function renderResultList(offers) {
        const list = $('#fsResultList');
        if (!offers.length) {
            list.innerHTML = '<div class="fs-empty"><span class="emoji">🔎</span><div style="font-size:14px;">필터에 맞는 항공편이 없습니다. 조건을 완화해 보세요.</div></div>';
            return;
        }
        list.innerHTML = offers.map((o, idx) => renderOfferCard(o, idx)).join('');
        // 상세 버튼
        list.querySelectorAll('[data-detail]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const id = btn.dataset.detail;
                const offer = offers.find((x) => String(x.id) === String(id));
                if (offer) showDetailModal(offer);
            });
        });
    }

    function buildExternalLink(offer) {
        // Travelpayouts 는 OTA 리다이렉트 경로(`link`)를 'external_link' 로 전달.
        // 절대 URL 이 아니면 aviasales 도메인 prepend, 마커 쿼리는 그대로 보존.
        const raw = offer && offer.external_link;
        if (!raw) return '';
        if (/^https?:\/\//i.test(raw)) return raw;
        // 상대경로면 aviasales.com 으로 prepend
        if (raw.startsWith('/')) return 'https://www.aviasales.com' + raw;
        return raw;
    }

    function renderOfferCard(offer, idx) {
        const itHtml = (offer.itineraries || []).map((it) => renderItinerary(it)).join('');
        const carrier = (offer.validating_carriers && offer.validating_carriers[0]) || '';
        const carrierName = state.carriers[carrier] || carrier || '';
        const externalUrl = buildExternalLink(offer);
        return `
            <article class="fs-offer-card" data-idx="${idx}">
                <div class="fs-offer-itineraries">
                    ${itHtml}
                    ${carrierName ? `<div class="fs-itin-carriers">발권 항공사: ${carrierName}${carrier ? ' (' + carrier + ')' : ''}</div>` : ''}
                </div>
                <div class="fs-offer-price">
                    <div>
                        <div class="total">${fmtKRW(offer.price.total)}</div>
                        <div class="per">${offer.travelers || 1}인 총액</div>
                    </div>
                    <div style="display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;">
                        <button type="button" class="btn-detail" data-detail="${offer.id}">상세 보기</button>
                        ${externalUrl ? `<a class="btn-detail" style="background: var(--color-neutral-700); text-decoration:none; display:inline-flex; align-items:center; gap:4px;" target="_blank" rel="noopener noreferrer" href="${externalUrl}">예약 페이지 ↗</a>` : ''}
                    </div>
                </div>
            </article>
        `;
    }

    function renderItinerary(it) {
        const segs = it.segments || [];
        if (!segs.length) return '';
        const first = segs[0];
        const last = segs[segs.length - 1];
        const stops = it.stops || 0;
        const stopText = stops === 0 ? '직항' : (stops === 1 ? '1회 환승' : `${stops}회 환승`);
        const stopList = stops > 0 ? segs.slice(0, -1).map((s) => s.to).join('·') : '';
        const carriers = Array.from(new Set(segs.map((s) => state.carriers[s.carrier] || s.carrier).filter(Boolean))).join(' · ');
        return `
            <div class="fs-itin">
                <div class="fs-itin-end">
                    <div class="time">${fmtTime(first.departure)}</div>
                    <div class="iata">${first.from || ''}</div>
                    ${airportSubtitle(first.from) ? `<div class="airport-name">${airportSubtitle(first.from)}</div>` : ''}
                    <div class="date">${fmtDateShort(first.departure)}</div>
                </div>
                <div class="fs-itin-mid">
                    <span class="duration">${fmtMinutes(it.duration_minutes)}</span>
                    <div class="line"></div>
                    <span class="stops">${stopText}${stopList ? ' · ' + stopList : ''}</span>
                </div>
                <div class="fs-itin-end right">
                    <div class="time">${fmtTime(last.arrival)}</div>
                    <div class="iata">${last.to || ''}</div>
                    ${airportSubtitle(last.to) ? `<div class="airport-name">${airportSubtitle(last.to)}</div>` : ''}
                    <div class="date">${fmtDateShort(last.arrival)}</div>
                </div>
                <div class="fs-itin-carriers" style="grid-column:1/-1;">${carriers}</div>
            </div>
        `;
    }

    // ───── 결과 뷰 탭 (리스트/차트/지도) ─────
    function wireResultViewTabs() {
        $$('.fs-results-tabs .fs-tab').forEach((btn) => {
            btn.addEventListener('click', () => {
                $$('.fs-results-tabs .fs-tab').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                state.tripView = btn.dataset.view;
                $('#fsListView').hidden = state.tripView !== 'list';
                $('#fsChartView').hidden = state.tripView !== 'chart';
                $('#fsMapView').hidden = state.tripView !== 'map';
                if (state.tripView === 'map' && state.routeMap) {
                    setTimeout(() => state.routeMap.invalidateSize(), 80);
                }
                if (state.tripView === 'chart' && state.priceTrendChart) {
                    setTimeout(() => state.priceTrendChart.update(), 80);
                }
            });
        });
    }

    // ───── 가격 캘린더 렌더 ─────
    function renderCalendar() {
        const grid = $('#fsCalendarGrid');
        const section = $('#fsCalendarSection');
        const empty = $('#fsCalendarEmpty');
        const loading = $('#fsCalendarLoading');
        loading.hidden = true;
        if (!state.calendar || !state.calendar.length) {
            section.hidden = false;
            grid.innerHTML = '';
            empty.hidden = false;
            return;
        }
        empty.hidden = true;
        section.hidden = false;

        // 가격 → 색상 분류
        const prices = state.calendar.map((d) => d.price_total).filter((n) => n > 0);
        if (!prices.length) {
            grid.innerHTML = '';
            empty.hidden = false;
            return;
        }
        const minP = Math.min(...prices);
        const maxP = Math.max(...prices);
        const cheapThr = minP + (maxP - minP) * 0.33;
        const expThr = minP + (maxP - minP) * 0.66;

        // 출발일 ±15일 그리드 (요일 정렬)
        const dep = $('#fsDeparture').value;
        const center = dep ? new Date(dep) : new Date();
        const start = addDays(center, -15);
        const dayMap = {};
        state.calendar.forEach((d) => {
            if (d.departure_date) dayMap[d.departure_date] = d;
        });

        // 시작일의 요일에 맞춰 빈 셀 추가
        const startDow = start.getDay();
        const cells = [];
        for (let i = 0; i < startDow; i++) {
            cells.push('<div class="fs-cal-cell empty"></div>');
        }
        for (let i = 0; i < 31; i++) {
            const d = addDays(start, i);
            const key = isoDate(d);
            const data = dayMap[key];
            const selectedDep = dep === key ? 'selected' : '';
            if (!data) {
                cells.push(`<div class="fs-cal-cell no-data ${selectedDep}">
                    <span class="cal-date">${d.getDate()}</span>
                    <span class="cal-price">—</span>
                </div>`);
                continue;
            }
            let cls = '';
            if (data.price_total <= cheapThr) cls = 'cheap';
            else if (data.price_total >= expThr) cls = 'expensive';
            cells.push(`<button type="button" class="fs-cal-cell ${cls} ${selectedDep}" data-date="${key}">
                <span class="cal-date">${d.getDate()}</span>
                <span class="cal-price">${fmtKRW(data.price_total)}</span>
            </button>`);
        }
        grid.innerHTML = cells.join('');
        // 클릭 시 해당 날짜로 재검색
        grid.querySelectorAll('[data-date]').forEach((btn) => {
            btn.addEventListener('click', () => {
                $('#fsDeparture').value = btn.dataset.date;
                handleSearchSubmit();
            });
        });
    }

    // ───── 가격 추이 차트 ─────
    function renderPriceTrendChart() {
        if (typeof Chart === 'undefined') return;
        const data = (state.calendar || []).slice().sort((a, b) => (a.departure_date || '').localeCompare(b.departure_date || ''));
        const labels = data.map((d) => d.departure_date);
        const points = data.map((d) => d.price_total);
        const ctx = $('#fsPriceTrend').getContext('2d');
        if (state.priceTrendChart) {
            state.priceTrendChart.data.labels = labels;
            state.priceTrendChart.data.datasets[0].data = points;
            state.priceTrendChart.update();
            return;
        }
        state.priceTrendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: '일자별 최저가',
                    data: points,
                    borderColor: '#1A4B7C',
                    backgroundColor: 'rgba(26, 75, 124, 0.12)',
                    pointRadius: 3,
                    pointHoverRadius: 6,
                    tension: 0.25,
                    fill: true,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx2) => fmtKRW(ctx2.parsed.y),
                        },
                    },
                },
                scales: {
                    y: {
                        ticks: { callback: (v) => fmtKRW(v) },
                    },
                },
                onClick: (_, elements) => {
                    if (!elements || !elements.length) return;
                    const idx = elements[0].index;
                    const date = labels[idx];
                    if (date) {
                        $('#fsDeparture').value = date;
                        handleSearchSubmit();
                    }
                },
            },
        });
    }

    // ───── 라우트 지도 ─────
    function renderRouteMap(originIata, destIata) {
        if (typeof L === 'undefined') return;
        // selectedOrigin/Destination 우선, 없으면 enrichAirportNames 캐시(좌표 포함)
        const o = (state.selectedOrigin && state.selectedOrigin.iata === originIata && state.selectedOrigin.latitude != null)
            ? state.selectedOrigin
            : airportInfo(originIata);
        const d = (state.selectedDestination && state.selectedDestination.iata === destIata && state.selectedDestination.latitude != null)
            ? state.selectedDestination
            : airportInfo(destIata);
        if (!o || !d || o.latitude == null || d.latitude == null) return;

        const oLatLng = [Number(o.latitude), Number(o.longitude)];
        const dLatLng = [Number(d.latitude), Number(d.longitude)];

        if (!state.routeMap) {
            state.routeMap = L.map('fsRouteMap', { zoomControl: true, attributionControl: true });
            L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 8,
                attribution: '&copy; OpenStreetMap &copy; CARTO',
            }).addTo(state.routeMap);
        } else {
            state.routeMap.eachLayer((ly) => {
                if (ly instanceof L.Marker || ly instanceof L.Polyline) state.routeMap.removeLayer(ly);
            });
        }

        L.marker(oLatLng).addTo(state.routeMap)
            .bindPopup(`<strong>${o.iata}</strong> ${o.name || o.city || ''}`);
        L.marker(dLatLng).addTo(state.routeMap)
            .bindPopup(`<strong>${d.iata}</strong> ${d.name || d.city || ''}`);
        L.polyline([oLatLng, dLatLng], { color: '#1A4B7C', weight: 3, dashArray: '6, 6' }).addTo(state.routeMap);
        state.routeMap.fitBounds(L.latLngBounds([oLatLng, dLatLng]).pad(0.4));
    }

    // ───── 다구간 ─────
    function wireMultiCity() {
        $('#fsMcAddBtn').addEventListener('click', () => addMultiCityRow());
        $('#fsMcSearchBtn').addEventListener('click', runMultiCity);
    }

    function addMultiCityRow() {
        const rows = $('#fsMcRows');
        const idx = rows.children.length + 1;
        const row = document.createElement('div');
        row.className = 'fs-mc-row';
        row.innerHTML = `
            <div class="fs-field fs-col-3">
                <label>구간 ${idx} 출발지</label>
                <input type="text" class="fs-input" data-mc-origin="${idx}" placeholder="예: ICN" autocomplete="off">
                <div class="fs-suggest" data-mc-suggest-origin="${idx}"></div>
            </div>
            <div class="fs-field fs-col-3">
                <label>구간 ${idx} 도착지</label>
                <input type="text" class="fs-input" data-mc-dest="${idx}" placeholder="예: HAN" autocomplete="off">
                <div class="fs-suggest" data-mc-suggest-dest="${idx}"></div>
            </div>
            <div class="fs-field fs-col-3">
                <label>출발일</label>
                <input type="date" class="fs-input" data-mc-date="${idx}">
            </div>
            <div class="fs-field fs-col-2">
                <label style="opacity:0">.</label>
                <button type="button" class="fs-remove" aria-label="구간 삭제">— 삭제</button>
            </div>
        `;
        rows.appendChild(row);

        // 자동완성 + 삭제 버튼
        const oInput = row.querySelector(`[data-mc-origin="${idx}"]`);
        const dInput = row.querySelector(`[data-mc-dest="${idx}"]`);
        const oSugg = row.querySelector(`[data-mc-suggest-origin="${idx}"]`);
        const dSugg = row.querySelector(`[data-mc-suggest-dest="${idx}"]`);
        wireAutocompleteSimple(oInput, oSugg);
        wireAutocompleteSimple(dInput, dSugg);
        // 출발일 기본값
        const today = new Date();
        row.querySelector(`[data-mc-date="${idx}"]`).value = isoDate(addDays(today, 14 + (idx - 1) * 5));
        row.querySelector(`[data-mc-date="${idx}"]`).min = isoDate(today);
        row.querySelector('.fs-remove').addEventListener('click', () => {
            if (rows.children.length <= 2) {
                safeToast('warning', '다구간은 최소 2개 구간이 필요합니다.');
                return;
            }
            rows.removeChild(row);
            renumberMcRows();
        });
    }

    function renumberMcRows() {
        const rows = $('#fsMcRows').children;
        Array.from(rows).forEach((row, i) => {
            const idx = i + 1;
            const labels = row.querySelectorAll('label');
            if (labels[0]) labels[0].textContent = `구간 ${idx} 출발지`;
            if (labels[1]) labels[1].textContent = `구간 ${idx} 도착지`;
        });
    }

    function wireAutocompleteSimple(input, listEl) {
        if (!input || !listEl) return;

        const renderInto = (items) => {
            listEl.innerHTML = '';
            if (!items || !items.length) {
                listEl.classList.remove('show');
                return;
            }
            const { groups } = groupSuggestionsForRender(items);
            groups.forEach((g) => {
                const meta = SUBTYPE_META[g.subtype] || { icon: '·', label: '기타' };
                const header = document.createElement('div');
                header.className = 'fs-suggest-group';
                header.innerHTML = `<span>${meta.icon} ${meta.label}</span><span class="count">${g.items.length}</span>`;
                listEl.appendChild(header);

                g.items.forEach((item) => {
                    const div = document.createElement('div');
                    div.className = 'fs-suggest-item';
                    div.dataset.subtype = g.subtype;

                    if (g.subtype === 'COUNTRY') {
                        div.innerHTML = `
                            <span class="iata country">${item.iata || ''}</span>
                            <span class="primary">${item.name || ''}</span>
                            <span class="meta">국가 · 도시명을 함께 입력하면 더 정확합니다</span>
                        `;
                        div.addEventListener('mousedown', (e) => {
                            e.preventDefault();
                            input.value = item.name || '';
                            input.dataset.iata = '';
                            cacheAirport(item);
                            fetcher(item.name || '');
                        });
                    } else {
                        const primary = g.subtype === 'CITY'
                            ? (item.city || item.name || '')
                            : (item.name || item.city || '');
                        const sub = [
                            g.subtype === 'AIRPORT' && item.city && item.city !== primary ? item.city : null,
                            item.country,
                        ].filter(Boolean).join(' · ');
                        div.innerHTML = `
                            <span class="iata">${item.iata || ''}</span>
                            <span class="primary">${primary}</span>
                            <span class="meta">${meta.label}${sub ? ' · ' + sub : ''}</span>
                        `;
                        div.addEventListener('mousedown', (e) => {
                            e.preventDefault();
                            input.value = `${item.iata} · ${item.name || item.city || ''}`;
                            input.dataset.iata = item.iata;
                            cacheAirport(item);
                            listEl.classList.remove('show');
                        });
                    }
                    listEl.appendChild(div);
                });
            });
            listEl.classList.add('show');
        };

        const fetcher = (typeof debounce === 'function' ? debounce : (fn) => fn)(async (q) => {
            try {
                const resp = await apiCall(`/flights/airports?keyword=${encodeURIComponent(q)}`);
                if (resp && resp.success) renderInto(resp.data || []);
            } catch (_) { /* noop */ }
        }, 220);

        input.addEventListener('input', () => {
            const q = input.value.trim();
            input.dataset.iata = '';
            if (/^[A-Za-z]{3}$/.test(q)) input.dataset.iata = q.toUpperCase();
            if (q.length < 2) { listEl.classList.remove('show'); return; }
            fetcher(q);
        });
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !listEl.contains(e.target)) {
                listEl.classList.remove('show');
            }
        });
    }

    async function runMultiCity() {
        const rows = $('#fsMcRows').children;
        const ods = [];
        for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            const idx = i + 1;
            const o = row.querySelector(`[data-mc-origin="${idx}"]`);
            const d = row.querySelector(`[data-mc-dest="${idx}"]`);
            const dt = row.querySelector(`[data-mc-date="${idx}"]`);
            const oIata = (o.dataset.iata || (o.value.match(/^[A-Za-z]{3}/) ? o.value.slice(0, 3).toUpperCase() : '')).trim();
            const dIata = (d.dataset.iata || (d.value.match(/^[A-Za-z]{3}/) ? d.value.slice(0, 3).toUpperCase() : '')).trim();
            if (!oIata || !dIata || !dt.value) {
                return safeToast('error', `구간 ${idx}의 출발지/도착지/날짜를 모두 입력해 주세요.`);
            }
            ods.push({ origin: oIata, destination: dIata, date: dt.value });
        }
        if (ods.length < 2) return safeToast('error', '최소 2개 구간이 필요합니다.');

        const btn = $('#fsMcSearchBtn');
        btn.disabled = true;
        const oldLabel = btn.innerHTML;
        btn.innerHTML = '⏳ 검색 중…';
        showSkeletons();
        hideAllResultSections();
        $('#fsResultsSection').hidden = false;
        $('#fsCalendarSection').hidden = true;

        try {
            const body = {
                originDestinations: ods,
                adults: Number($('#fsMcAdults').value || 1),
                travelClass: $('#fsMcCabin').value || '',
                currency: state.currency,
                max: 50,
            };
            const resp = await apiCall('/flights/multi-city', {
                method: 'POST',
                body: JSON.stringify(body),
            });
            if (!resp || !resp.success) throw new Error((resp && resp.message) || '다구간 검색 실패');
            state.results = resp.data || [];
            state.carriers = ((resp.meta || {}).dictionaries || {}).carriers || {};
            state.calendar = [];
            // 합성 멀티시티 경고 (Travelpayouts 의 경우 백엔드가 synthesized=true 로 시그널)
            const synthBanner = $('#fsSynthesizedBanner');
            if (synthBanner) synthBanner.hidden = !((resp.meta || {}).synthesized);
            if (!state.results.length) {
                $('#fsResultsSection').hidden = true;
                $('#fsEmptyState').hidden = false;
                return;
            }
            initFiltersFromResults();
            applyFiltersAndRender();
            // 다구간은 캘린더/차트/지도 의미가 약하므로 리스트 위주
            $('#fsCalendarSection').hidden = true;
            // 다구간 결과 IATA 일괄 풀네임 조회
            const iatas = collectIatasFromOffers(state.results).concat(ods.flatMap((od) => [od.origin, od.destination]));
            enrichAirportNames(iatas).then((updated) => {
                if (updated) applyFiltersAndRender();
            });
        } catch (err) {
            console.error(err);
            $('#fsResultsSection').hidden = true;
            safeToast('error', err.message || '다구간 검색에 실패했습니다.');
        } finally {
            btn.disabled = false;
            btn.innerHTML = oldLabel;
        }
    }

    // ───── Anywhere ─────
    async function runAnywhere() {
        const origin = getOriginIata();
        if (!origin) return safeToast('error', '출발지를 선택해 주세요.');
        const maxPrice = Number($('#fsMaxPrice').value || 0);
        const departure = $('#fsDeparture').value || '';

        const btn = $('#fsSearchBtn');
        btn.disabled = true;
        const oldLabel = btn.innerHTML;
        btn.innerHTML = '⏳ 검색 중…';
        hideAllResultSections();

        try {
            const qs = new URLSearchParams({
                origin,
                currency: state.currency,
                oneWay: 'false',
            });
            if (maxPrice > 0) qs.append('maxPrice', String(maxPrice));
            if (departure) qs.append('departureDate', departure);
            const resp = await apiCall(`/flights/inspiration?${qs.toString()}`);
            if (!resp || !resp.success) throw new Error((resp && resp.message) || '추천 도시 조회 실패');
            state.anywhere = (resp.data || []).slice().sort((a, b) => a.price_total - b.price_total);
            renderAnywhere(origin);
            // 추천 도시 IATA 풀네임 조회 → 도착하면 카드 다시 그림
            const iatas = state.anywhere.map((d) => d.destination).concat([origin]);
            enrichAirportNames(iatas).then((updated) => {
                if (updated) renderAnywhere(origin);
            });
        } catch (err) {
            console.error(err);
            safeToast('error', err.message || '추천 도시를 불러오지 못했습니다.');
        } finally {
            btn.disabled = false;
            btn.innerHTML = oldLabel;
        }
    }

    function renderAnywhere(origin) {
        const grid = $('#fsAnywhereGrid');
        const section = $('#fsAnywhereSection');
        section.hidden = false;
        if (!state.anywhere.length) {
            grid.innerHTML = '<div class="fs-empty"><span class="emoji">🌍</span><div style="font-size:14px;">예산 안에 갈 수 있는 도시를 찾지 못했어요. 예산이나 출발일을 조정해 보세요.</div></div>';
            return;
        }
        grid.innerHTML = state.anywhere.map((d) => {
            const info = airportInfo(d.destination);
            const cityLabel = info ? (info.city || info.name || d.destination) : d.destination;
            const country = info && info.country ? info.country : '';
            return `
            <div class="fs-anywhere-card" data-iata="${d.destination}" data-date="${d.departure_date || ''}" data-return="${d.return_date || ''}">
                <div class="city">${cityLabel}</div>
                <div class="iata">${origin} → ${d.destination}${country ? ' · ' + country : ''}</div>
                <div class="date-range">${d.departure_date || ''}${d.return_date ? ' ~ ' + d.return_date : ''}</div>
                <div class="price">${fmtKRW(d.price_total)}</div>
            </div>
            `;
        }).join('');
        grid.querySelectorAll('.fs-anywhere-card').forEach((card) => {
            card.addEventListener('click', () => {
                // 클릭 시 해당 도시로 정식 검색
                $$('#fsTripTabs .fs-tab').forEach((t) => {
                    t.classList.remove('active');
                    if (t.dataset.tab === (card.dataset.return ? 'round-trip' : 'one-way')) {
                        t.classList.add('active');
                        state.tripType = t.dataset.tab;
                    }
                });
                applyTripType();
                $('#fsDestination').value = card.dataset.iata;
                $('#fsDestination').dataset.iata = card.dataset.iata;
                state.selectedDestination = airportInfo(card.dataset.iata) || { iata: card.dataset.iata };
                if (card.dataset.date) $('#fsDeparture').value = card.dataset.date;
                if (card.dataset.return) $('#fsReturn').value = card.dataset.return;
                handleSearchSubmit();
            });
        });
    }

    // ───── 상세 모달 ─────
    function wireDetailModal() {
        $('#fsDetailClose').addEventListener('click', closeDetailModal);
        $('#fsDetailModal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) closeDetailModal();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeDetailModal();
        });
    }
    function closeDetailModal() {
        $('#fsDetailModal').classList.remove('show');
    }

    function showDetailModal(offer) {
        const body = $('#fsDetailBody');
        const title = $('#fsDetailTitle');
        title.textContent = '항공편 상세';
        const sections = (offer.itineraries || []).map((it, i) => {
            const segs = (it.segments || []).map((s) => {
                const fromSub = airportSubtitle(s.from);
                const toSub = airportSubtitle(s.to);
                return `
                <div class="fs-segment">
                    <div class="row">
                        <span class="codes">${s.from || ''}${fromSub ? ` <small style="font-weight:500; color: var(--color-neutral-500);">(${fromSub})</small>` : ''} → ${s.to || ''}${toSub ? ` <small style="font-weight:500; color: var(--color-neutral-500);">(${toSub})</small>` : ''}</span>
                        <span class="meta">${s.carrier || ''}${s.flight_number ? ' ' + s.flight_number : ''} · ${s.aircraft || ''}</span>
                    </div>
                    <div class="row" style="margin-top:6px;">
                        <span class="meta">${fmtTime(s.departure)} · ${fmtDateShort(s.departure)} · 터미널 ${s.from_terminal || '-'}</span>
                        <span class="meta">${fmtTime(s.arrival)} · ${fmtDateShort(s.arrival)} · 터미널 ${s.to_terminal || '-'}</span>
                    </div>
                    <div class="row" style="margin-top:6px;">
                        <span class="meta">소요 ${fmtMinutes(s.duration_minutes)}</span>
                        ${s.carrier_name ? `<span class="meta">${s.carrier_name}</span>` : ''}
                    </div>
                </div>
                `;
            }).join('');
            return `
                <div style="margin-bottom:16px;">
                    <div style="font-weight:700; color: var(--color-neutral-700); margin-bottom:8px;">
                        ${i === 0 ? '가는 편' : (i === 1 ? '오는 편' : `구간 ${i + 1}`)}
                        — ${fmtMinutes(it.duration_minutes)} · ${it.stops === 0 ? '직항' : (it.stops + '회 환승')}
                    </div>
                    ${segs}
                </div>
            `;
        }).join('');

        const externalUrl = buildExternalLink(offer);
        body.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:12px; flex-wrap:wrap;">
                <div>
                    <div style="font-size:24px; font-weight:700; color: var(--color-primary-600);">${fmtKRW(offer.price.total)}</div>
                    <div style="font-size:12px; color: var(--color-neutral-500);">${offer.travelers || 1}인 총액 · ${offer.class || 'ECONOMY'}</div>
                </div>
                <div style="font-size:12px; color: var(--color-neutral-600); text-align:right;">
                    ${offer.last_ticketing_date ? '발권 마감 ' + offer.last_ticketing_date : ''}
                    ${offer.seats_available ? ' · 잔여 ' + offer.seats_available + '석' : ''}
                    ${externalUrl ? `<div style="margin-top:8px;"><a class="btn-detail" style="background: var(--color-primary-500); color:#fff; text-decoration:none; padding:8px 16px; border-radius:8px; font-weight:600;" target="_blank" rel="noopener noreferrer" href="${externalUrl}">예약 페이지로 이동 ↗</a></div>` : ''}
                </div>
            </div>
            ${sections}
        `;
        $('#fsDetailModal').classList.add('show');
    }

    // ───── 노출 (디버그) ─────
    window.__flightSearch = { state };
})();
