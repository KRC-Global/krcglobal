/**
 * 해외진출지원사업 페이지 공통 사이드바 컴포넌트
 * 모든 expansion 페이지에서 동일한 메뉴를 표시합니다.
 */

// 상대 경로 계산 (info 하위 페이지인 경우)
function getBasePath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '../../../';  // pages/expansion/info/ -> root
    }
    return '../../';  // pages/expansion/ -> root
}

function getExpansionPath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '../';  // pages/expansion/info/ -> pages/expansion/
    }
    return '';  // pages/expansion/ -> pages/expansion/
}

function getProjectsPath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '../../projects/';
    }
    return '../projects/';
}

function getAdminPath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '../../admin/';
    }
    return '../admin/';
}

function getGisPath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '../../gis.html';
    }
    return '../gis.html';
}

function getBudgetPath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '../../budget/profitability.html';
    }
    return '../budget/profitability.html';
}

function getInfoPath() {
    const path = window.location.pathname;
    if (path.includes('/expansion/info/')) {
        return '';  // 같은 폴더
    }
    return 'info/';
}

// 현재 페이지 감지
function getCurrentPage() {
    const path = window.location.pathname;
    if (path.includes('company-management')) return 'company';
    if (path.includes('loan-management')) return 'loan';
    if (path.includes('loan-performance')) return 'loan-performance';
    if (path.includes('loan-repayment')) return 'loan-repayment';
    if (path.includes('loan-projects')) return 'loan-projects';
    if (path.includes('company-collateral')) return 'company-collateral';
    if (path.includes('post-management')) return 'post-management';
    if (path.includes('mortgage-contract')) return 'mortgage-contract';
    return '';
}

// 사이드바 HTML 생성
function generateSidebarHTML() {
    const base = getBasePath();
    const expansion = getExpansionPath();
    const projects = getProjectsPath();
    const admin = getAdminPath();
    const gis = getGisPath();
    const budget = getBudgetPath();
    const info = getInfoPath();
    const current = getCurrentPage();

    return `
    <nav class="sidebar-nav" aria-label="주메뉴">
        <ul class="nav-list">
            <li class="nav-item">
                <a href="${base}dashboard.html" class="nav-link">
                    <svg class="nav-icon" width="20" height="20" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2">
                        <rect x="3" y="3" width="7" height="7" />
                        <rect x="14" y="3" width="7" height="7" />
                        <rect x="14" y="14" width="7" height="7" />
                        <rect x="3" y="14" width="7" height="7" />
                    </svg>
                    <span class="nav-text">대시보드</span>
                </a>
            </li>

            <li class="nav-item has-submenu open">
                <button class="nav-link" aria-expanded="true">
                    <svg class="nav-icon" width="20" height="20" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2">
                        <path d="M9 11l3 3L22 4" />
                        <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
                    </svg>
                    <span class="nav-text">사업관리</span>
                    <svg class="nav-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2">
                        <path d="M9 18l6-6-6-6" />
                    </svg>
                </button>
                <ul class="submenu" style="display: block;">
                    <li><a href="${projects}overseas-tech.html">해외기술용역</a></li>
                    <li><a href="${projects}international-cooperation.html">국제협력사업</a></li>
                    <li><a href="${projects}methane.html">메탄감축사업</a></li>
                    <li><a href="${admin}offices.html">해외사무소</a></li>
                    <li class="has-submenu open">
                        <a href="#" class="submenu-toggle" onclick="toggleExpansionSubmenu(event)">해외진출지원사업 ▾</a>
                        <ul class="submenu-nested" style="display: block;">
                            <li><a href="${expansion}company-management.html" class="${current === 'company' ? 'active' : ''}">기업관리</a></li>
                            <li><a href="${expansion}loan-management.html" class="${current === 'loan' ? 'active' : ''}">융자관리</a></li>
                            <li class="has-submenu open">
                                <a href="#" class="submenu-toggle" onclick="toggleExpansionSubmenu(event)">정보표출 ▾</a>
                                <ul class="submenu-nested-level4" style="display: block;">
                                    <li><a href="${info}loan-performance.html" class="${current === 'loan-performance' ? 'active' : ''}">융자사업 추진실적</a></li>
                                    <li><a href="${info}loan-repayment.html" class="${current === 'loan-repayment' ? 'active' : ''}">융자사업 연도별 상환내역</a></li>
                                    <li><a href="${info}loan-projects.html" class="${current === 'loan-projects' ? 'active' : ''}">융자사업 관리</a></li>
                                    <li><a href="${info}company-collateral.html" class="${current === 'company-collateral' ? 'active' : ''}">기업별 담보 현황</a></li>
                                    <li><a href="${info}post-management.html" class="${current === 'post-management' ? 'active' : ''}">사후관리대장</a></li>
                                    <li><a href="${info}mortgage-contract.html" class="${current === 'mortgage-contract' ? 'active' : ''}">근저당권 설정계약서</a></li>
                                </ul>
                            </li>
                        </ul>
                    </li>
                    <li><a href="${gis}">글로벌맵</a></li>
                </ul>
            </li>

            <li class="nav-item">
                <a href="${budget}" class="nav-link">
                    <svg class="nav-icon" width="20" height="20" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10" />
                        <path d="M12 6v6l4 2" />
                    </svg>
                    <span class="nav-text">예산/정산</span>
                </a>
            </li>
        </ul>
    </nav>
    `;
}

// 사이드바 초기화
function initExpansionSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.innerHTML = generateSidebarHTML();
    }
}

// 서브메뉴 토글
function toggleExpansionSubmenu(event) {
    event.preventDefault();
    event.stopPropagation();

    const toggle = event.target;
    const parent = toggle.closest('.has-submenu');

    if (parent) {
        const nested = parent.querySelector(':scope > .submenu-nested, :scope > .submenu-nested-level4');

        if (nested) {
            const isOpen = nested.style.display === 'block';
            nested.style.display = isOpen ? 'none' : 'block';

            const currentText = toggle.textContent;
            toggle.textContent = currentText.replace(/[▾▸]/, isOpen ? '▸' : '▾');
        }
    }
}

// 전역에 노출
window.initExpansionSidebar = initExpansionSidebar;
window.toggleExpansionSubmenu = toggleExpansionSubmenu;
