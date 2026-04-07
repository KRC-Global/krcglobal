/**
 * 해외진출지원사업 페이지 공통 초기화 스크립트
 * 사이드바 메뉴 자동 확장 및 현재 페이지 하이라이트
 */

(function () {
    'use strict';

    // 페이지 로드 시 실행
    document.addEventListener('DOMContentLoaded', function () {
        initExpansionPage();
    });

    function initExpansionPage() {
        // 1. 사업관리 메뉴 펼치기
        expandBusinessMenu();

        // 2. 해외진출지원사업 서브메뉴 펼치기
        expandExpansionSubmenu();

        // 3. 정보표출 서브메뉴 펼치기 (info 페이지인 경우)
        if (isInfoPage()) {
            expandInfoSubmenu();
        }

        // 4. 현재 페이지 하이라이트
        highlightCurrentPage();
    }

    function isInfoPage() {
        return window.location.pathname.includes('/expansion/info/');
    }

    function expandBusinessMenu() {
        // 사업관리 has-submenu 찾아서 열기
        const submenuItems = document.querySelectorAll('.nav-item.has-submenu');
        submenuItems.forEach(item => {
            const navText = item.querySelector('.nav-text');
            if (navText && navText.textContent.includes('사업관리')) {
                const submenu = item.querySelector('.submenu');
                if (submenu) {
                    submenu.style.display = 'block';
                    item.classList.add('open');
                }
            }
        });
    }

    function expandExpansionSubmenu() {
        // 해외진출지원사업 서브메뉴 찾아서 열기
        const submenuToggles = document.querySelectorAll('.submenu-toggle');
        submenuToggles.forEach(toggle => {
            if (toggle.textContent.includes('해외진출지원사업')) {
                const parent = toggle.closest('.has-submenu');
                if (parent) {
                    const nested = parent.querySelector('.submenu-nested');
                    if (nested) {
                        nested.style.display = 'block';
                        toggle.textContent = toggle.textContent.replace('▸', '▾');
                    }
                }
            }
        });
    }

    function expandInfoSubmenu() {
        // 정보표출 서브메뉴 찾아서 열기
        const submenuToggles = document.querySelectorAll('.submenu-toggle');
        submenuToggles.forEach(toggle => {
            if (toggle.textContent.includes('정보표출')) {
                const parent = toggle.closest('.has-submenu');
                if (parent) {
                    const nested = parent.querySelector('.submenu-nested-level4');
                    if (nested) {
                        nested.style.display = 'block';
                        toggle.textContent = toggle.textContent.replace('▸', '▾');
                    }
                }
            }
        });
    }

    function highlightCurrentPage() {
        const path = window.location.pathname;
        const links = document.querySelectorAll('.submenu a, .submenu-nested a, .submenu-nested-level4 a');

        links.forEach(link => {
            const href = link.getAttribute('href');
            if (href && path.endsWith(href.split('/').pop())) {
                link.classList.add('active');
            }
        });
    }

    // 전역 함수: 서브메뉴 토글
    window.toggleSubmenu = function (event) {
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
    };

    // 전역 함수: 로그아웃
    window.logout = function () {
        localStorage.removeItem('gbms_token');
        localStorage.removeItem('gbms_user');
        sessionStorage.removeItem('gbms_token');
        sessionStorage.removeItem('gbms_user');

        // 경로에 따라 index.html로 이동
        const path = window.location.pathname;
        if (path.includes('/expansion/info/')) {
            window.location.href = '../../../index.html';
        } else {
            window.location.href = '../../index.html';
        }
    };

})();
