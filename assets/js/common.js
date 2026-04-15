// ═══════════════════════════════════════════════════════
// KRC GLOBAL 공통 유틸리티 함수
// ═══════════════════════════════════════════════════════

/**
 * 날짜 포맷팅
 * @param {Date|string} date - 날짜 객체 또는 문자열
 * @param {string} format - 포맷 (기본: 'YYYY-MM-DD')
 * @returns {string} 포맷된 날짜 문자열
 */
function formatDate(date, format = 'YYYY-MM-DD') {
    const d = new Date(date);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    const seconds = String(d.getSeconds()).padStart(2, '0');

    return format
        .replace('YYYY', year)
        .replace('MM', month)
        .replace('DD', day)
        .replace('HH', hours)
        .replace('mm', minutes)
        .replace('ss', seconds);
}

/**
 * 숫자 포맷팅 (천 단위 구분)
 * @param {number} num - 숫자
 * @returns {string} 포맷된 숫자 문자열
 */
function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/**
 * 통화 포맷팅
 * @param {number} amount - 금액
 * @param {string} currency - 통화 기호 (기본: '₩')
 * @returns {string} 포맷된 통화 문자열
 */
function formatCurrency(amount, currency = '₩') {
    return `${currency}${formatNumber(amount)}`;
}

/**
 * 파일 크기 포맷팅
 * @param {number} bytes - 바이트 크기
 * @returns {string} 포맷된 파일 크기
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

/**
 * 디바운스 함수
 * @param {Function} func - 실행할 함수
 * @param {number} wait - 대기 시간 (ms)
 * @returns {Function} 디바운스된 함수
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 쿼리 파라미터 파싱
 * @returns {Object} 파라미터 객체
 */
function getQueryParams() {
    const params = {};
    const queryString = window.location.search.substring(1);
    const pairs = queryString.split('&');

    pairs.forEach(pair => {
        const [key, value] = pair.split('=');
        if (key) {
            params[decodeURIComponent(key)] = decodeURIComponent(value || '');
        }
    });

    return params;
}

/**
 * 로컬 스토리지 헬퍼
 */
const storage = {
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.error('Storage set error:', e);
            return false;
        }
    },

    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (e) {
            console.error('Storage get error:', e);
            return defaultValue;
        }
    },

    remove(key) {
        try {
            localStorage.removeItem(key);
            return true;
        } catch (e) {
            console.error('Storage remove error:', e);
            return false;
        }
    },

    clear() {
        try {
            localStorage.clear();
            return true;
        } catch (e) {
            console.error('Storage clear error:', e);
            return false;
        }
    }
};

/**
 * 사용자 인증 확인
 * @returns {Object|null} 사용자 정보 또는 null
 */
function checkAuth() {
    const userInfo = storage.get('userInfo') || JSON.parse(sessionStorage.getItem('gbms_user') || sessionStorage.getItem('userInfo') || 'null');
    return userInfo;
}

/**
 * 관리자 권한 확인 및 리다이렉트
 * @param {string} redirectUrl - 권한 없을 때 리다이렉트할 URL (기본: 대시보드)
 * @returns {boolean} 관리자 여부
 */
function checkAdminRole(redirectUrl = '../../dashboard.html') {
    const token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');
    const userInfo = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');

    // 인증 확인
    if (!token || !userInfo) {
        console.warn('인증 정보가 없습니다. 로그인 페이지로 이동합니다.');
        window.location.href = '../../index.html';
        return false;
    }

    // 사용자 정보 파싱
    try {
        const user = JSON.parse(userInfo);

        // 관리자 권한 확인
        if (user.role !== 'admin') {
            console.warn('관리자 권한이 필요합니다. 대시보드로 이동합니다.');
            alert('관리자 권한이 필요한 페이지입니다.');
            window.location.href = redirectUrl;
            return false;
        }

        return true;
    } catch (error) {
        console.error('사용자 정보 파싱 오류:', error);
        window.location.href = '../../index.html';
        return false;
    }
}

/**
 * 페이지 접근 권한 확인 및 리다이렉트 (DEPRECATED)
 * 모든 사용자는 읽기 권한이 있으므로 페이지 접근을 차단하지 않음
 * 쓰기 권한은 hasWritePermission() 함수로 체크
 * @param {string} requiredPermission - 필요한 권한 (overseas_tech, oda, expansion, methane)
 * @param {string} redirectUrl - 권한 없을 때 리다이렉트할 URL (기본: 대시보드)
 * @returns {boolean} 항상 true 반환 (하위 호환성 유지)
 */
function checkPagePermission(requiredPermission, redirectUrl = '../../dashboard.html') {
    // 모든 사용자가 모든 페이지를 볼 수 있음 (읽기 권한)
    // 쓰기 권한은 hasWritePermission() 함수로 체크
    return true;
}

/**
 * 쓰기 권한 확인 (등록/수정/삭제 버튼 표시 여부)
 * @param {string} requiredPermission - 필요한 권한 (overseas_tech, oda, expansion, methane)
 * @returns {boolean} 쓰기 권한 여부
 */
function hasWritePermission(requiredPermission) {
    const token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');
    const userInfo = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');

    // 인증 확인
    if (!token || !userInfo) {
        console.log('🔍 hasWritePermission: 토큰 또는 사용자 정보 없음');
        return false;
    }

    // 사용자 정보 파싱
    try {
        const user = JSON.parse(userInfo);
        const userPermission = user.permissionScope || user.permission_scope || 'readonly';

        console.log('🔍 hasWritePermission:', {
            requiredPermission,
            userRole: user.role,
            userPermission,
            userId: user.user_id || user.userId
        });

        // 관리자 또는 all 권한은 모든 쓰기 가능
        if (user.role === 'admin' || userPermission === 'all') {
            console.log('✅ 관리자 또는 all 권한');
            return true;
        }

        // manager role은 자신의 permission_scope에서 쓰기 가능
        if (user.role === 'manager') {
            const hasPermission = userPermission === requiredPermission;
            console.log(hasPermission ? '✅ manager 권한 일치' : '❌ manager 권한 불일치', `(${userPermission} vs ${requiredPermission})`);
            return hasPermission;
        }

        // readonly 권한은 쓰기 불가
        if (userPermission === 'readonly') {
            console.log('❌ readonly 권한');
            return false;
        }

        // 사용자 권한과 필요 권한 비교 (user role)
        const hasPermission = userPermission === requiredPermission;
        console.log(hasPermission ? '✅ 권한 일치' : '❌ 권한 불일치', `(${userPermission} vs ${requiredPermission})`);
        return hasPermission;
    } catch (error) {
        console.error('사용자 정보 파싱 오류:', error);
        return false;
    }
}

/**
 * 인증 필요 페이지 보호 — 토큰 없으면 로그인 페이지로 리다이렉트
 */
function requireAuth(loginPath) {
    const token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');
    const path = window.location.pathname;

    // 경로 깊이에 따른 상대 경로 계산 헬퍼
    function getRelativePath(targetFile) {
        const pagesIdx = path.indexOf('/pages/');
        if (pagesIdx < 0) return targetFile;
        // /pages/ 이후 경로에서 슬래시 개수로 깊이 계산
        const afterPages = path.substring(pagesIdx + '/pages/'.length);
        const depth = afterPages.split('/').filter(Boolean).length;
        // depth 1 = pages/file.html → ../
        // depth 2 = pages/admin/file.html → ../../
        // depth 3 = pages/expansion/info/file.html → ../../../
        if (depth <= 1) return '../' + targetFile;
        return '../'.repeat(depth) + targetFile;
    }

    // 토큰 없으면 로그인으로
    if (!token) {
        if (loginPath) {
            window.location.href = loginPath;
            return;
        }
        if (path.includes('/pages/')) {
            window.location.href = getRelativePath('index.html');
        } else {
            window.location.href = 'index.html';
        }
        return;
    }

    // pending 사용자는 대기 페이지로
    const userInfo = JSON.parse(localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user') || '{}');
    const scope = userInfo.permissionScope || userInfo.permission_scope || 'pending';
    if (scope === 'pending' && !path.includes('pending.html')) {
        if (path.includes('/pages/')) {
            window.location.href = getRelativePath('pending.html');
        } else {
            window.location.href = 'pending.html';
        }
        return;
    }
}

/**
 * 로그아웃
 */
async function logout() {
    // Supabase 세션 완전 삭제 (Google OAuth 세션 포함)
    if (window.supabaseClient) {
        try { await window.supabaseClient.auth.signOut(); } catch (e) {}
    }

    localStorage.removeItem('gbms_token');
    localStorage.removeItem('gbms_user');
    sessionStorage.removeItem('gbms_token');
    sessionStorage.removeItem('gbms_user');
    storage.remove('userInfo');
    sessionStorage.removeItem('userInfo');

    // 현재 페이지 경로에 따라 로그인 페이지 경로 결정
    const path = window.location.pathname;

    // 경로 깊이 계산 (예: /pages/expansion/info/ = 3단계)
    if (path.includes('/pages/expansion/info/')) {
        window.location.href = '../../../index.html';
    } else if (path.includes('/pages/admin/') || path.includes('/pages/projects/') ||
        path.includes('/pages/budget/') || path.includes('/pages/expansion/')) {
        window.location.href = '../../index.html';
    } else if (path.includes('/pages/')) {
        window.location.href = '../index.html';
    } else {
        window.location.href = 'index.html';
    }
}

/**
 * 데이터분석 드롭다운 토글
 */
function toggleAnalysisMenu(event) {
    event.stopPropagation();
    const dropdown = document.getElementById('analysisDropdown');
    if (dropdown) dropdown.classList.toggle('show');
}
document.addEventListener('click', function() {
    const dropdown = document.getElementById('analysisDropdown');
    if (dropdown) dropdown.classList.remove('show');
});
window.toggleAnalysisMenu = toggleAnalysisMenu;

/**
 * 사용자 드롭다운 초기화
 */
function initUserDropdown() {
    const userMenuButton = document.getElementById('userMenuButton');
    const userDropdown = document.getElementById('userDropdown');

    if (!userMenuButton || !userDropdown) return;

    userMenuButton.addEventListener('click', function (e) {
        e.stopPropagation();
        userDropdown.classList.toggle('show');
        userMenuButton.setAttribute('aria-expanded', userDropdown.classList.contains('show'));
    });

    // 외부 클릭 시 닫기
    document.addEventListener('click', function (e) {
        if (!userDropdown.contains(e.target) && !userMenuButton.contains(e.target)) {
            userDropdown.classList.remove('show');
            userMenuButton.setAttribute('aria-expanded', 'false');
        }
    });
}

/**
 * 사용자 정보 표시 + admin 메뉴 제어
 */
function displayUserInfo() {
    const userInfo = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');
    if (!userInfo) return;

    try {
        const user = JSON.parse(userInfo);
        const initial = user.name ? user.name.charAt(0) : '?';
        const isAdmin = user.role === 'admin' || user.permissionScope === 'all';
        const scopeMap = {
            'all': '관리자',
            'overseas_tech': '해외기술용역',
            'expansion': '해외진출지원',
            'oda': '국제협력사업',
            'readonly': '조회전용',
            'pending': '승인대기'
        };
        const roleText = scopeMap[user.permissionScope] || (isAdmin ? '관리자' : '사용자');

        // 헤더 업데이트
        const userNameEl = document.getElementById('userName');
        const userAvatarEl = document.getElementById('userAvatar');
        if (userNameEl) userNameEl.textContent = user.name || '사용자';
        if (userAvatarEl) userAvatarEl.textContent = initial;

        // 드롭다운 업데이트
        const dropdownName = document.getElementById('dropdownName');
        const dropdownAvatar = document.getElementById('dropdownAvatar');
        const dropdownRole = document.getElementById('dropdownRole');
        const dropdownDept = document.getElementById('dropdownDept');
        const dropdownEmail = document.getElementById('dropdownEmail');

        if (dropdownName) dropdownName.textContent = user.name || '사용자';
        if (dropdownAvatar) dropdownAvatar.textContent = initial;
        if (dropdownRole) dropdownRole.textContent = roleText;
        const deptMap = {
            'gad': '글로벌농업개발부',
            'gb': '글로벌사업부',
            'aidc': '농식품국제개발협력센터'
        };
        if (dropdownDept) dropdownDept.textContent = deptMap[user.department] || user.department || '글로벌사업처';
        if (dropdownEmail) dropdownEmail.textContent = user.email || '';

        // admin 사이드바 메뉴 표시
        const adminMenu = document.getElementById('adminMenuUser');
        if (adminMenu) {
            adminMenu.style.display = isAdmin ? 'block' : 'none';
        }

        // 드롭다운 사용자관리 링크: admin만 표시
        const adminDropdownLink = document.getElementById('adminDropdownLink');
        if (adminDropdownLink) {
            adminDropdownLink.style.display = isAdmin ? 'flex' : 'none';
        }
    } catch (e) {
        console.error('사용자 정보 파싱 오류:', e);
    }
}

/**
 * 메뉴 권한 제어
 */
function filterMenuByPermission() {
    // 메뉴는 모두 표시 (모든 사용자가 읽기 가능)
    // 수정/삭제/등록 버튼만 hasWritePermission()으로 제어
    // 이 함수는 더 이상 메뉴를 숨기지 않음

    const userInfo = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');
    if (!userInfo) return;

    try {
        const user = JSON.parse(userInfo);
        const permissionScope = user.permissionScope || user.permission_scope || 'readonly';

        // 관리자는 모든 메뉴 접근 가능
        if (user.role === 'admin' || permissionScope === 'all') {
            return;
        }

        const sidebar = document.getElementById('sidebar') || document.querySelector('.app-sidebar');
        if (!sidebar) return;

        // **변경사항**: 메뉴 숨김 로직 제거
        // 모든 메뉴는 표시되고, 페이지 내에서 수정 버튼만 hasWritePermission()으로 제어

        // **변경사항**: 모든 메뉴를 표시
        // 권한에 관계없이 모든 사용자가 모든 메뉴를 볼 수 있음
        // 각 페이지 내에서 수정/삭제/등록 버튼만 hasWritePermission()으로 제어

    } catch (e) {
        console.error('메뉴 권한 제어 오류:', e);
    }
}

/**
 * 서브메뉴 토글 함수
 */
function toggleSubmenu(event) {
    event.preventDefault();
    event.stopPropagation();

    const toggleLink = event.currentTarget;
    const parentLi = toggleLink.closest('li.has-submenu');
    if (!parentLi) return;

    const submenu = parentLi.querySelector(':scope > .submenu-nested, :scope > .submenu-nested-level4');
    if (!submenu) return;

    // 서브메뉴 토글
    const isVisible = submenu.style.display === 'block';
    submenu.style.display = isVisible ? 'none' : 'block';

    // 화살표 업데이트
    if (toggleLink.textContent.includes('▸')) {
        toggleLink.textContent = toggleLink.textContent.replace('▸', '▾');
    } else if (toggleLink.textContent.includes('▾')) {
        toggleLink.textContent = toggleLink.textContent.replace('▾', '▸');
    }

    // aria-expanded 속성 업데이트
    toggleLink.setAttribute('aria-expanded', !isVisible);
}

/**
 * 현재 페이지에 해당하는 메뉴 자동 확장 및 활성화
 */
function initMenuForCurrentPage() {
    const currentPath = window.location.pathname;
    const sidebar = document.getElementById('sidebar') || document.querySelector('.app-sidebar');
    if (!sidebar) return;

    // 현재 파일명 추출
    const fileName = currentPath.split('/').pop().replace('.html', '');

    // URL 패턴 매핑 - 파일명을 직접 검색하여 매칭
    const menuMap = {
        // 확장 페이지 (해외진출지원사업)
        'company-management': ['해외진출지원사업', '기업관리'],
        'loan-management': ['해외진출지원사업', '융자관리'],
        'loan-performance': ['해외진출지원사업', '정보표출', '융자사업 추진실적'],
        'loan-repayment': ['해외진출지원사업', '정보표출', '융자사업 연도별 상환내역'],
        'loan-projects': ['해외진출지원사업', '정보표출', '융자사업 관리'],
        'company-collateral': ['해외진출지원사업', '정보표출', '기업별 담보 현황'],
        'post-management': ['해외진출지원사업', '정보표출', '사후관리대장'],
        'mortgage-contract': ['해외진출지원사업', '정보표출', '근저당권 설정계약서'],
        // 해외기술용역
        'overseas-tech': ['사업관리', '해외기술용역', '사업현황'],
        'overseas-tech-bidding': ['사업관리', '해외기술용역', 'TOR/RFP·제안서'],
        'overseas-tech-contracts': ['사업관리', '해외기술용역', '계약서/최종보고서'],
        'overseas-tech-performance': ['사업관리', '해외기술용역', '실적관리'],
        'overseas-tech-board': ['사업관리', '해외기술용역', '기타'],
        // 국제협력사업
        'international-cooperation': ['사업관리', '국제협력사업', '사업현황'],
        'oda-reports': ['사업관리', '국제협력사업', '보고서관리'],
        'intl-coop-pcp': ['사업관리', '국제협력사업', 'PCP'],
        'intl-coop-grant-plan': ['사업관리', '국제협력사업', '무상원조시행계획서'],
        'intl-coop-feasibility': ['사업관리', '국제협력사업', '타당성조사보고서'],
        'intl-coop-mou': ['사업관리', '국제협력사업', '협의의사록'],
        'intl-coop-vendor-proposal': ['사업관리', '국제협력사업', '업체제안서 및 발표자료'],
        'intl-coop-pmc': ['사업관리', '국제협력사업', 'PMC보고서'],
        'intl-coop-performance': ['사업관리', '국제협력사업', '성과관리보고서'],
        'intl-coop-board': ['사업관리', '국제협력사업', '기타'],
        'expansion-board': ['해외진출지원사업', '기타'],
        // 해외사무소 등
        'offices': ['사업관리', '해외사무소 등'],
        // 관리자 페이지
        'users': ['사용자 관리'],
        // 예산/정산
        'profitability': ['예산/정산'],
        // GIS
        'gis': ['글로벌맵'],
        // 편의기능
        'utilities': ['편의기능'],
        // 분석 도구
        'cn-global': ['편의기능'],
    };

    const targetMenuPath = menuMap[fileName];

    // 1단계: 모든 메뉴의 기본 상태 설정 (초기화)
    const allSubmenus = sidebar.querySelectorAll('.submenu-nested, .submenu-nested-level4, .submenu');
    allSubmenus.forEach(submenu => {
        submenu.style.display = 'none';
    });

    const allToggles = sidebar.querySelectorAll('.submenu-toggle');
    allToggles.forEach(toggle => {
        if (toggle.textContent.includes('▾')) {
            toggle.textContent = toggle.textContent.replace('▾', '▸');
        }
        toggle.setAttribute('aria-expanded', 'false');
    });

    const allLinks = sidebar.querySelectorAll('a');
    allLinks.forEach(link => {
        link.classList.remove('active');
    });

    // 매핑이 없는 경우 (예: 대시보드) 종료
    if (!targetMenuPath || targetMenuPath.length === 0) return;

    // 2단계: URL 기반으로 현재 페이지 링크 찾기
    let targetLink = null;
    allLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (href && (href.endsWith(`${fileName}.html`) || href === fileName)) {
            targetLink = link;
        }
    });

    // 링크를 못 찾은 경우 경로 기반으로 다시 시도
    if (!targetLink) {
        allLinks.forEach(link => {
            const linkText = link.textContent.trim().replace(/[▸▾]/g, '').trim();
            // 마지막 메뉴 항목 이름과 일치하는지 확인
            if (linkText === targetMenuPath[targetMenuPath.length - 1]) {
                targetLink = link;
            }
        });
    }

    if (!targetLink) return;

    // 3단계: 현재 페이지 링크에 active 클래스 추가
    targetLink.classList.add('active');

    // 4단계: 모든 부모 메뉴 찾기 및 확장
    let currentElement = targetLink.closest('li');
    const parentsToExpand = [];

    while (currentElement) {
        parentsToExpand.unshift(currentElement);
        const parentUl = currentElement.parentElement;
        if (parentUl && (parentUl.classList.contains('submenu-nested') ||
                         parentUl.classList.contains('submenu-nested-level4') ||
                         parentUl.classList.contains('submenu'))) {
            currentElement = parentUl.closest('li');
        } else {
            currentElement = null;
        }
    }

    // 5단계: 수집된 모든 부모 메뉴 확장
    parentsToExpand.forEach(element => {
        // 최상위 사업관리 버튼 처리
        const topButton = element.querySelector(':scope > button.nav-link');
        if (topButton) {
            const submenu = element.querySelector(':scope > .submenu');
            if (submenu) {
                submenu.style.display = 'block';
                topButton.setAttribute('aria-expanded', 'true');
                const arrow = topButton.querySelector('.nav-arrow');
                if (arrow) {
                    arrow.style.transform = 'rotate(90deg)';
                }
            }
        }

        // 서브메뉴 토글 처리
        const toggleBtn = element.querySelector(':scope > a.submenu-toggle');
        if (toggleBtn) {
            toggleBtn.classList.add('active');

            const submenu = element.querySelector(':scope > .submenu-nested, :scope > .submenu-nested-level4');
            if (submenu) {
                submenu.style.display = 'block';

                // 화살표 업데이트
                const currentText = toggleBtn.textContent;
                if (currentText.includes('▸')) {
                    toggleBtn.textContent = currentText.replace('▸', '▾');
                } else if (!currentText.includes('▾')) {
                    // 화살표가 없으면 추가
                    toggleBtn.textContent = currentText.trim() + ' ▾';
                }
                toggleBtn.setAttribute('aria-expanded', 'true');
            }
        }
    });
}

/**
 * 사이드바 토글 초기화 (햄버거 메뉴)
 */
function initSidebarToggle() {
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar') || document.querySelector('.app-sidebar');

    if (sidebarToggle && sidebar) {
        // 백드롭 생성 (모바일에서 사이드바 외부 탭으로 닫기)
        let backdrop = document.querySelector('.sidebar-backdrop');
        if (!backdrop) {
            backdrop = document.createElement('div');
            backdrop.className = 'sidebar-backdrop';
            document.body.appendChild(backdrop);
        }

        function closeSidebar() {
            sidebar.classList.remove('open');
            backdrop.classList.remove('active');
            sidebarToggle.setAttribute('aria-expanded', 'false');
        }

        // 모바일 닫기 버튼 추가 (사이드바 상단)
        if (!sidebar.querySelector('.sidebar-close-btn')) {
            const closeDiv = document.createElement('div');
            closeDiv.className = 'sidebar-close-btn';
            closeDiv.innerHTML = '<button aria-label="메뉴 닫기">✕</button>';
            closeDiv.querySelector('button').addEventListener('click', closeSidebar);
            sidebar.insertBefore(closeDiv, sidebar.firstChild);
        }

        sidebarToggle.addEventListener('click', function () {
            sidebar.classList.toggle('open');
            const isOpen = sidebar.classList.contains('open');
            backdrop.classList.toggle('active', isOpen);
            sidebarToggle.setAttribute('aria-expanded', isOpen);
        });

        // 백드롭 클릭 → 사이드바 닫기
        backdrop.addEventListener('click', closeSidebar);

        // ESC 키 → 사이드바 닫기
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && sidebar.classList.contains('open')) {
                closeSidebar();
            }
        });
    }
}

/**
 * 메뉴 상태 초기화 - 페이지 로드 시 호출
 */
function initSidebar() {
    initMenuForCurrentPage();

    // 최상위 메뉴 버튼(사업관리 등)에 클릭 이벤트 추가
    const sidebar = document.getElementById('sidebar') || document.querySelector('.app-sidebar');
    if (!sidebar) return;

    const topLevelButtons = sidebar.querySelectorAll('.nav-item.has-submenu > button.nav-link');
    topLevelButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            const parentLi = this.closest('.nav-item.has-submenu');
            const submenu = parentLi.querySelector(':scope > .submenu');
            const arrow = this.querySelector('.nav-arrow');

            if (submenu) {
                const isOpen = submenu.style.display === 'block';
                submenu.style.display = isOpen ? 'none' : 'block';
                this.setAttribute('aria-expanded', !isOpen);

                // 화살표 회전
                if (arrow) {
                    arrow.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
                }
            }
        });
    });
}

/**
 * 비밀번호 변경 모달 생성 및 초기화
 */
function initPasswordChangeModal() {
    // 모달이 이미 존재하면 생성하지 않음
    if (document.getElementById('passwordChangeModal')) return;

    // 모달 HTML 생성
    const modalHTML = `
        <div class="modal-backdrop" id="passwordChangeModal" style="display: none;">
            <div class="modal-container" style="max-width: 420px;">
                <div class="modal-header">
                    <h3 class="modal-title">🔐 비밀번호 변경</h3>
                    <button type="button" class="modal-close" onclick="closePasswordChangeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="passwordChangeForm">
                        <div class="form-group">
                            <label class="form-label" for="currentPassword">현재 비밀번호 <span class="required">*</span></label>
                            <input type="password" class="form-control" id="currentPassword" name="currentPassword" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label" for="newPassword">새 비밀번호 <span class="required">*</span></label>
                            <input type="password" class="form-control" id="newPassword" name="newPassword" required>
                            <small class="form-text text-muted">
                                10자 이상, 대문자·소문자·숫자·특수문자 각 1개 이상 포함
                            </small>
                        </div>
                        <div class="form-group">
                            <label class="form-label" for="confirmPassword">새 비밀번호 확인 <span class="required">*</span></label>
                            <input type="password" class="form-control" id="confirmPassword" name="confirmPassword" required>
                        </div>
                        <div id="passwordError" class="alert alert-danger" style="display: none;"></div>
                        <div id="passwordSuccess" class="alert alert-success" style="display: none;"></div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" onclick="closePasswordChangeModal()">취소</button>
                    <button type="button" class="btn btn-primary" onclick="submitPasswordChange()">변경</button>
                </div>
            </div>
        </div>
    `;

    // 모달 스타일 추가
    const styleHTML = `
        <style id="passwordModalStyles">
            #passwordChangeModal .modal-backdrop {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                z-index: 9999;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            #passwordChangeModal.modal-backdrop {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                z-index: 9999;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            #passwordChangeModal .modal-container {
                background: var(--color-neutral-0, #fff);
                border-radius: 12px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
                width: 100%;
                max-width: 420px;
                margin: 20px;
            }
            #passwordChangeModal .modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                border-bottom: 1px solid var(--color-neutral-200, #e5e7eb);
            }
            #passwordChangeModal .modal-title {
                margin: 0;
                font-size: 18px;
                font-weight: 600;
                color: var(--color-neutral-900, #111827);
            }
            #passwordChangeModal .modal-close {
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                color: var(--color-neutral-500, #6b7280);
                line-height: 1;
            }
            #passwordChangeModal .modal-close:hover {
                color: var(--color-neutral-700, #374151);
            }
            #passwordChangeModal .modal-body {
                padding: 20px;
            }
            #passwordChangeModal .modal-footer {
                display: flex;
                justify-content: flex-end;
                gap: 8px;
                padding: 16px 20px;
                border-top: 1px solid var(--color-neutral-200, #e5e7eb);
            }
            #passwordChangeModal .form-group {
                margin-bottom: 16px;
            }
            #passwordChangeModal .form-label {
                display: block;
                margin-bottom: 6px;
                font-weight: 500;
                color: var(--color-neutral-700, #374151);
            }
            #passwordChangeModal .required {
                color: #ef4444;
            }
            #passwordChangeModal .form-control {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid var(--color-neutral-300, #d1d5db);
                border-radius: 6px;
                font-size: 14px;
                box-sizing: border-box;
            }
            #passwordChangeModal .form-control:focus {
                outline: none;
                border-color: var(--color-primary-500, #1A4B7C);
                box-shadow: 0 0 0 3px rgba(26, 75, 124, 0.1);
            }
            #passwordChangeModal .form-text {
                display: block;
                margin-top: 6px;
                font-size: 12px;
                color: var(--color-neutral-500, #6b7280);
            }
            #passwordChangeModal .alert {
                padding: 12px;
                border-radius: 6px;
                margin-top: 16px;
                font-size: 14px;
            }
            #passwordChangeModal .alert-danger {
                background: #fef2f2;
                color: #dc2626;
                border: 1px solid #fecaca;
            }
            #passwordChangeModal .alert-success {
                background: #f0fdf4;
                color: #16a34a;
                border: 1px solid #bbf7d0;
            }
            #passwordChangeModal .btn {
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                border: none;
                transition: background 0.2s;
            }
            #passwordChangeModal .btn-primary {
                background: var(--color-primary-500, #1A4B7C);
                color: #fff;
            }
            #passwordChangeModal .btn-primary:hover {
                background: var(--color-primary-600, #153d64);
            }
            #passwordChangeModal .btn-secondary {
                background: var(--color-neutral-200, #e5e7eb);
                color: var(--color-neutral-700, #374151);
            }
            #passwordChangeModal .btn-secondary:hover {
                background: var(--color-neutral-300, #d1d5db);
            }
        </style>
    `;

    // DOM에 추가
    document.body.insertAdjacentHTML('beforeend', modalHTML);
    if (!document.getElementById('passwordModalStyles')) {
        document.head.insertAdjacentHTML('beforeend', styleHTML);
    }
}

/**
 * 비밀번호 변경 모달 열기
 */
function openPasswordChangeModal() {
    initPasswordChangeModal();
    const modal = document.getElementById('passwordChangeModal');
    if (modal) {
        modal.style.display = 'flex';
        // 폼 초기화
        const form = document.getElementById('passwordChangeForm');
        if (form) form.reset();
        // 메시지 초기화
        const errorEl = document.getElementById('passwordError');
        const successEl = document.getElementById('passwordSuccess');
        if (errorEl) errorEl.style.display = 'none';
        if (successEl) successEl.style.display = 'none';
        // 드롭다운 닫기
        const userDropdown = document.getElementById('userDropdown');
        if (userDropdown) userDropdown.classList.remove('show');
    }
}

/**
 * 비밀번호 변경 모달 닫기
 */
function closePasswordChangeModal() {
    const modal = document.getElementById('passwordChangeModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 비밀번호 변경 제출
 */
async function submitPasswordChange() {
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    const errorEl = document.getElementById('passwordError');
    const successEl = document.getElementById('passwordSuccess');

    // 유효성 검사
    if (!currentPassword || !newPassword || !confirmPassword) {
        errorEl.textContent = '모든 필드를 입력해주세요.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    if (newPassword !== confirmPassword) {
        errorEl.textContent = '새 비밀번호가 일치하지 않습니다.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    // 비밀번호 정책 검증 (프론트엔드)
    if (newPassword.length < 10) {
        errorEl.textContent = '비밀번호는 10자 이상이어야 합니다.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    if (!/[A-Z]/.test(newPassword)) {
        errorEl.textContent = '대문자를 1개 이상 포함해야 합니다.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    if (!/[a-z]/.test(newPassword)) {
        errorEl.textContent = '소문자를 1개 이상 포함해야 합니다.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    if (!/\d/.test(newPassword)) {
        errorEl.textContent = '숫자를 1개 이상 포함해야 합니다.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    if (!/[!@#$%^&*(),.?":{}|<>]/.test(newPassword)) {
        errorEl.textContent = '특수문자(!@#$%^&*(),.?":{}|<>)를 1개 이상 포함해야 합니다.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
        return;
    }

    try {
        // API 호출
        const response = await apiCall('/auth/change-password', 'POST', {
            currentPassword,
            newPassword
        });

        if (response.success) {
            successEl.textContent = '비밀번호가 성공적으로 변경되었습니다.';
            successEl.style.display = 'block';
            errorEl.style.display = 'none';

            // 2초 후 모달 닫기
            setTimeout(() => {
                closePasswordChangeModal();
            }, 2000);
        } else {
            errorEl.textContent = response.message || '비밀번호 변경에 실패했습니다.';
            errorEl.style.display = 'block';
            successEl.style.display = 'none';
        }
    } catch (error) {
        console.error('비밀번호 변경 오류:', error);
        errorEl.textContent = '서버 오류가 발생했습니다. 다시 시도해주세요.';
        errorEl.style.display = 'block';
        successEl.style.display = 'none';
    }
}

/**
 * 비밀번호 변경 메뉴 (Google OAuth 사용으로 비활성화)
 */
function addPasswordChangeMenu() {
    // Google OAuth 로그인 사용 — 비밀번호 변경 불필요
}

/**
 * 공통 UI 초기화 (테마, 드롭다운, 사용자 정보, 햄버거 메뉴, 메뉴 권한)
 */
function initCommonUI() {
    requireAuth();
    initUserDropdown();
    displayUserInfo();
    filterMenuByPermission();
    initSidebarToggle();
    initSidebar();
    addPasswordChangeMenu();
    applyReadonlyMode();
}

/**
 * 조회전용(readonly) 권한 시 쓰기 액션 요소 숨김
 * - body.readonly-mode 클래스 추가 → CSS 규칙으로 동적 생성 버튼 포함 숨김
 * - btn-primary/btn-success 중 쓰기 키워드 포함 버튼 직접 숨김
 */
function applyReadonlyMode() {
    const userInfo = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');
    if (!userInfo) return;
    try {
        const user = JSON.parse(userInfo);
        const scope = user.permissionScope || user.permission_scope;
        if (scope !== 'readonly') return;

        // CSS 기반 숨김 활성화 (동적 생성 요소 포함)
        document.body.classList.add('readonly-mode');

        // 쓰기 액션 텍스트가 포함된 btn-primary/btn-success 버튼 직접 숨김
        // (CSS 클래스로 구분되지 않는 페이지 전용 버튼 처리)
        const WRITE_KEYWORDS = ['등록', '신규', '추가', '수정', '삭제', '저장', '업로드', '작성', '편집 모드'];
        document.querySelectorAll('button.btn-primary, button.btn-success, a.btn-primary').forEach(function(el) {
            const text = el.textContent.trim();
            if (WRITE_KEYWORDS.some(function(kw) { return text.includes(kw); })) {
                el.style.setProperty('display', 'none', 'important');
            }
        });
    } catch (e) {}
}

// 페이지 로드 시 자동 초기화
document.addEventListener('DOMContentLoaded', function () {
    // initCommonUI()를 호출하지 않는 페이지를 위해 readonly 모드 적용
    applyReadonlyMode();
});

// 전역으로 사용할 수 있도록 window 객체에 할당
window.toggleSubmenu = toggleSubmenu;
window.openPasswordChangeModal = openPasswordChangeModal;
window.closePasswordChangeModal = closePasswordChangeModal;
window.submitPasswordChange = submitPasswordChange;

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        formatDate,
        formatNumber,
        formatCurrency,
        formatFileSize,
        debounce,
        getQueryParams,
        storage,
        checkAuth,
        checkAdminRole,
        logout,
        toggleAnalysisMenu,
        initUserDropdown,
        displayUserInfo,
        initCommonUI,
        openPasswordChangeModal,
        closePasswordChangeModal,
        submitPasswordChange
    };
}
