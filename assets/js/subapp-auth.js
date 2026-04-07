/**
 * subapp-auth.js
 * 해외기술정보 하위 앱(CN산정, 침수흔적, 만능뷰어)용 독립형 인증/UI 스크립트
 * common.js/api.js에 의존하지 않음
 */

// ── 즉시 실행: 로그인 세션 체크 ──
(function () {
    var token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');
    var userInfo = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');
    if (!token || !userInfo) {
        window.location.href = '/index.html';
    }
})();

// ── DOMContentLoaded: UI 주입 ──
document.addEventListener('DOMContentLoaded', function () {
    var API_BASE = location.protocol + '//' + location.host + '/api';

    // 사용자 정보 파싱
    var user = null;
    try {
        var raw = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');
        if (raw) user = JSON.parse(raw);
    } catch (e) { /* ignore */ }

    // ── 1. 뒤로가기 수정 ──
    var backLink = document.querySelector('a[href="/dashboard.html"]');
    if (backLink) {
        backLink.removeAttribute('href');
        backLink.style.cursor = 'pointer';
        backLink.title = '이전 페이지로 돌아가기';
        backLink.onclick = function (e) {
            e.preventDefault();
            if (window.history.length > 1) {
                window.history.back();
            } else {
                window.location.href = '/dashboard.html';
            }
        };
    }

    // ── 2. 사용자 드롭다운 주입 ──
    var initial = (user && user.name) ? user.name.charAt(0) : '?';
    var userName = (user && user.name) ? user.name : '사용자';
    var userRole = (user && user.role === 'admin') ? '관리자' : '사용자';
    var userDept = (user && user.department) ? user.department : '';

    // 드롭다운 HTML
    var menuHTML =
        '<div class="gbms-sa-user-menu">' +
        '  <button class="gbms-sa-menu-btn" id="gbmsSaMenuBtn">' +
        '    <span class="gbms-sa-avatar">' + initial + '</span>' +
        '    <span class="gbms-sa-name">' + userName + '</span>' +
        '    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>' +
        '  </button>' +
        '  <div class="gbms-sa-dropdown" id="gbmsSaDropdown">' +
        '    <div class="gbms-sa-dd-header">' +
        '      <span class="gbms-sa-dd-avatar">' + initial + '</span>' +
        '      <div>' +
        '        <div class="gbms-sa-dd-name">' + userName + '</div>' +
        '        <div class="gbms-sa-dd-role">' + userRole + '</div>' +
        (userDept ? '        <div class="gbms-sa-dd-dept">' + userDept + '</div>' : '') +
        '      </div>' +
        '    </div>' +
        '    <div class="gbms-sa-dd-divider"></div>' +
        '    <a href="#" class="gbms-sa-dd-item" id="gbmsSaPwChange"><span>🔐</span> 비밀번호 변경</a>' +
        '    <a href="#" class="gbms-sa-dd-item" id="gbmsSaLogout"><span>🚪</span> 로그아웃</a>' +
        '  </div>' +
        '</div>';

    // 삽입 위치 결정
    var headerRight = document.querySelector('.header-right');
    var headerInner = document.querySelector('.header-inner');
    var target = headerRight || headerInner || (document.querySelector('header'));

    if (target) {
        var wrapper = document.createElement('div');
        wrapper.innerHTML = menuHTML;
        var menuEl = wrapper.firstElementChild;
        if (headerRight) {
            headerRight.appendChild(menuEl);
        } else if (headerInner) {
            headerInner.appendChild(menuEl);
        } else {
            target.appendChild(menuEl);
        }
    }

    // ── 3. 스타일 주입 ──
    var styleEl = document.createElement('style');
    styleEl.textContent =
        '.gbms-sa-user-menu { position: relative; margin-left: auto; }' +
        '.gbms-sa-menu-btn {' +
        '  display: flex; align-items: center; gap: 8px;' +
        '  background: none; border: 1px solid rgba(255,255,255,0.3); border-radius: 8px;' +
        '  padding: 6px 12px; cursor: pointer; color: inherit; font-size: 14px; transition: background 0.2s;' +
        '}' +
        '.gbms-sa-menu-btn:hover { background: rgba(255,255,255,0.15); }' +
        '.gbms-sa-avatar {' +
        '  width: 30px; height: 30px; border-radius: 50%;' +
        '  background: #1A4B7C; color: #fff; display: flex; align-items: center; justify-content: center;' +
        '  font-size: 13px; font-weight: 700; flex-shrink: 0;' +
        '}' +
        '.gbms-sa-name { font-weight: 500; }' +
        '.gbms-sa-dropdown {' +
        '  display: none; position: absolute; right: 0; top: calc(100% + 6px);' +
        '  background: #fff; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.15);' +
        '  min-width: 220px; z-index: 9000; overflow: hidden; color: #1e2124;' +
        '}' +
        '.gbms-sa-dropdown.show { display: block; }' +
        '.gbms-sa-dd-header {' +
        '  display: flex; align-items: center; gap: 10px; padding: 14px 16px;' +
        '}' +
        '.gbms-sa-dd-avatar {' +
        '  width: 36px; height: 36px; border-radius: 50%;' +
        '  background: #1A4B7C; color: #fff; display: flex; align-items: center; justify-content: center;' +
        '  font-size: 15px; font-weight: 700; flex-shrink: 0;' +
        '}' +
        '.gbms-sa-dd-name { font-weight: 600; font-size: 14px; color: #1e2124; }' +
        '.gbms-sa-dd-role { font-size: 12px; color: #6b7280; }' +
        '.gbms-sa-dd-dept { font-size: 12px; color: #6b7280; }' +
        '.gbms-sa-dd-divider { height: 1px; background: #e5e7eb; margin: 0; }' +
        '.gbms-sa-dd-item {' +
        '  display: flex; align-items: center; gap: 8px; padding: 10px 16px;' +
        '  text-decoration: none; color: #374151; font-size: 14px; transition: background 0.15s;' +
        '}' +
        '.gbms-sa-dd-item:hover { background: #f3f4f6; }' +
        /* 밝은 배경 헤더 대응 */
        '.header .gbms-sa-menu-btn { border-color: rgba(0,0,0,0.15); color: #1e2124; }' +
        '.header .gbms-sa-menu-btn:hover { background: rgba(0,0,0,0.05); }' +
        '.viewer-header .gbms-sa-menu-btn { border-color: rgba(0,0,0,0.15); color: #1e2124; }' +
        '.viewer-header .gbms-sa-menu-btn:hover { background: rgba(0,0,0,0.05); }' +
        /* 비밀번호 변경 모달 */
        '#gbmsSaPwModal {' +
        '  display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;' +
        '  background: rgba(0,0,0,0.5); z-index: 10000; align-items: center; justify-content: center;' +
        '}' +
        '#gbmsSaPwModal.show { display: flex; }' +
        '#gbmsSaPwModal .pw-container {' +
        '  background: #fff; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.2);' +
        '  width: 100%; max-width: 420px; margin: 20px; color: #1e2124;' +
        '}' +
        '#gbmsSaPwModal .pw-header {' +
        '  display: flex; justify-content: space-between; align-items: center;' +
        '  padding: 16px 20px; border-bottom: 1px solid #e5e7eb;' +
        '}' +
        '#gbmsSaPwModal .pw-title { margin: 0; font-size: 18px; font-weight: 600; }' +
        '#gbmsSaPwModal .pw-close { background: none; border: none; font-size: 24px; cursor: pointer; color: #6b7280; }' +
        '#gbmsSaPwModal .pw-close:hover { color: #374151; }' +
        '#gbmsSaPwModal .pw-body { padding: 20px; }' +
        '#gbmsSaPwModal .pw-footer {' +
        '  display: flex; justify-content: flex-end; gap: 8px;' +
        '  padding: 16px 20px; border-top: 1px solid #e5e7eb;' +
        '}' +
        '#gbmsSaPwModal .pw-group { margin-bottom: 16px; }' +
        '#gbmsSaPwModal .pw-label { display: block; margin-bottom: 6px; font-weight: 500; font-size: 14px; color: #374151; }' +
        '#gbmsSaPwModal .pw-label .req { color: #ef4444; }' +
        '#gbmsSaPwModal .pw-input {' +
        '  width: 100%; padding: 10px 12px; border: 1px solid #d1d5db; border-radius: 6px;' +
        '  font-size: 14px; box-sizing: border-box;' +
        '}' +
        '#gbmsSaPwModal .pw-input:focus { outline: none; border-color: #1A4B7C; box-shadow: 0 0 0 3px rgba(26,75,124,0.1); }' +
        '#gbmsSaPwModal .pw-hint { display: block; margin-top: 6px; font-size: 12px; color: #6b7280; }' +
        '#gbmsSaPwModal .pw-msg { padding: 12px; border-radius: 6px; margin-top: 16px; font-size: 14px; display: none; }' +
        '#gbmsSaPwModal .pw-error { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }' +
        '#gbmsSaPwModal .pw-success { background: #f0fdf4; color: #16a34a; border: 1px solid #bbf7d0; }' +
        '#gbmsSaPwModal .pw-btn {' +
        '  padding: 10px 20px; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; border: none;' +
        '}' +
        '#gbmsSaPwModal .pw-btn-primary { background: #1A4B7C; color: #fff; }' +
        '#gbmsSaPwModal .pw-btn-primary:hover { background: #153d64; }' +
        '#gbmsSaPwModal .pw-btn-secondary { background: #e5e7eb; color: #374151; }' +
        '#gbmsSaPwModal .pw-btn-secondary:hover { background: #d1d5db; }';
    document.head.appendChild(styleEl);

    // ── 4. 드롭다운 토글 ──
    var menuBtn = document.getElementById('gbmsSaMenuBtn');
    var dropdown = document.getElementById('gbmsSaDropdown');
    if (menuBtn && dropdown) {
        menuBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });
        document.addEventListener('click', function (e) {
            if (!dropdown.contains(e.target) && !menuBtn.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });
    }

    // ── 5. 로그아웃 ──
    var logoutBtn = document.getElementById('gbmsSaLogout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function (e) {
            e.preventDefault();
            localStorage.removeItem('gbms_token');
            localStorage.removeItem('gbms_user');
            sessionStorage.removeItem('gbms_token');
            sessionStorage.removeItem('gbms_user');
            sessionStorage.removeItem('userInfo');
            window.location.href = '/index.html';
        });
    }

    // ── 6. 비밀번호 변경 ──
    var pwChangeBtn = document.getElementById('gbmsSaPwChange');
    if (pwChangeBtn) {
        pwChangeBtn.addEventListener('click', function (e) {
            e.preventDefault();
            dropdown.classList.remove('show');
            openPwModal();
        });
    }

    function openPwModal() {
        var modal = document.getElementById('gbmsSaPwModal');
        if (!modal) {
            var html =
                '<div id="gbmsSaPwModal">' +
                '  <div class="pw-container">' +
                '    <div class="pw-header">' +
                '      <h3 class="pw-title">🔐 비밀번호 변경</h3>' +
                '      <button class="pw-close" id="gbmsSaPwClose">&times;</button>' +
                '    </div>' +
                '    <div class="pw-body">' +
                '      <div class="pw-group">' +
                '        <label class="pw-label">현재 비밀번호 <span class="req">*</span></label>' +
                '        <input type="password" class="pw-input" id="gbmsSaCurPw">' +
                '      </div>' +
                '      <div class="pw-group">' +
                '        <label class="pw-label">새 비밀번호 <span class="req">*</span></label>' +
                '        <input type="password" class="pw-input" id="gbmsSaNewPw">' +
                '        <small class="pw-hint">10자 이상, 대문자·소문자·숫자·특수문자 각 1개 이상 포함</small>' +
                '      </div>' +
                '      <div class="pw-group">' +
                '        <label class="pw-label">새 비밀번호 확인 <span class="req">*</span></label>' +
                '        <input type="password" class="pw-input" id="gbmsSaConfPw">' +
                '      </div>' +
                '      <div class="pw-msg pw-error" id="gbmsSaPwError"></div>' +
                '      <div class="pw-msg pw-success" id="gbmsSaPwSuccess"></div>' +
                '    </div>' +
                '    <div class="pw-footer">' +
                '      <button class="pw-btn pw-btn-secondary" id="gbmsSaPwCancel">취소</button>' +
                '      <button class="pw-btn pw-btn-primary" id="gbmsSaPwSubmit">변경</button>' +
                '    </div>' +
                '  </div>' +
                '</div>';
            document.body.insertAdjacentHTML('beforeend', html);
            modal = document.getElementById('gbmsSaPwModal');

            document.getElementById('gbmsSaPwClose').addEventListener('click', closePwModal);
            document.getElementById('gbmsSaPwCancel').addEventListener('click', closePwModal);
            document.getElementById('gbmsSaPwSubmit').addEventListener('click', submitPwChange);
            modal.addEventListener('click', function (e) {
                if (e.target === modal) closePwModal();
            });
        }
        // 초기화
        document.getElementById('gbmsSaCurPw').value = '';
        document.getElementById('gbmsSaNewPw').value = '';
        document.getElementById('gbmsSaConfPw').value = '';
        document.getElementById('gbmsSaPwError').style.display = 'none';
        document.getElementById('gbmsSaPwSuccess').style.display = 'none';
        modal.classList.add('show');
    }

    function closePwModal() {
        var modal = document.getElementById('gbmsSaPwModal');
        if (modal) modal.classList.remove('show');
    }

    function showPwError(msg) {
        var el = document.getElementById('gbmsSaPwError');
        el.textContent = msg;
        el.style.display = 'block';
        document.getElementById('gbmsSaPwSuccess').style.display = 'none';
    }

    async function submitPwChange() {
        var curPw = document.getElementById('gbmsSaCurPw').value;
        var newPw = document.getElementById('gbmsSaNewPw').value;
        var confPw = document.getElementById('gbmsSaConfPw').value;

        if (!curPw || !newPw || !confPw) { showPwError('모든 필드를 입력해주세요.'); return; }
        if (newPw !== confPw) { showPwError('새 비밀번호가 일치하지 않습니다.'); return; }
        if (newPw.length < 10) { showPwError('비밀번호는 10자 이상이어야 합니다.'); return; }
        if (!/[A-Z]/.test(newPw)) { showPwError('대문자를 1개 이상 포함해야 합니다.'); return; }
        if (!/[a-z]/.test(newPw)) { showPwError('소문자를 1개 이상 포함해야 합니다.'); return; }
        if (!/\d/.test(newPw)) { showPwError('숫자를 1개 이상 포함해야 합니다.'); return; }
        if (!/[!@#$%^&*(),.?":{}|<>]/.test(newPw)) { showPwError('특수문자를 1개 이상 포함해야 합니다.'); return; }

        var token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');
        try {
            var res = await fetch(API_BASE + '/auth/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token
                },
                body: JSON.stringify({ currentPassword: curPw, newPassword: newPw })
            });
            var data = await res.json();
            if (data.success) {
                var suc = document.getElementById('gbmsSaPwSuccess');
                suc.textContent = '비밀번호가 성공적으로 변경되었습니다.';
                suc.style.display = 'block';
                document.getElementById('gbmsSaPwError').style.display = 'none';
                setTimeout(closePwModal, 2000);
            } else {
                showPwError(data.message || '비밀번호 변경에 실패했습니다.');
            }
        } catch (err) {
            showPwError('서버 오류가 발생했습니다. 다시 시도해주세요.');
        }
    }
});
