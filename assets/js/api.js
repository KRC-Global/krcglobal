// ═══════════════════════════════════════════════════════
// KRC GLOBAL API 통신 모듈
// ═══════════════════════════════════════════════════════

// 동적으로 서버 주소 감지 (내부망 지원)
// 현재 접속한 호스트와 포트를 그대로 사용
const API_BASE_URL = `${window.location.protocol}//${window.location.host}/api`;

/**
 * API 요청 헬퍼 (인증 토큰 포함)
 * @param {string} endpoint - API 엔드포인트
 * @param {Object} options - fetch 옵션 또는 레거시 파라미터
 * @returns {Promise} API 응답
 */
async function apiCall(endpoint, options = {}) {
    const token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');

    console.log('🌐 API Call:', endpoint, 'Token:', token ? '있음' : '없음');

    // 레거시 호환: 두 번째 인자가 문자열(method)인 경우
    if (typeof options === 'string') {
        const method = options;
        const data = arguments[2] || null;
        console.log('📝 레거시 모드:', { method, data });
        options = {
            method: method,
            body: data ? JSON.stringify(data) : null
        };
    }

    const defaultOptions = {
        method: options.method || 'GET',
        headers: {
            ...options.headers
        }
    };

    // FormData가 아닌 경우에만 Content-Type 헤더 추가
    if (!options.skipContentType && !(options.body instanceof FormData)) {
        defaultOptions.headers['Content-Type'] = 'application/json';
    }

    // Add authorization token if available
    if (token) {
        defaultOptions.headers['Authorization'] = `Bearer ${token}`;
        console.log('🔑 토큰 헤더 추가 완료');
    } else {
        console.warn('⚠️ 토큰 없음!');
    }

    // Add body
    if (options.body) {
        defaultOptions.body = options.body;
        console.log('📦 Body 추가:', typeof options.body === 'string' ? options.body.substring(0, 100) : options.body);
    }

    try {
        console.log('📡 Fetch 요청:', `${API_BASE_URL}${endpoint}`, defaultOptions);
        const response = await fetch(`${API_BASE_URL}${endpoint}`, defaultOptions);
        console.log('📡 응답 상태:', response.status, response.statusText);

        const result = await response.json();
        console.log('📡 응답 데이터:', result);

        // Check if unauthorized and redirect to login
        if (response.status === 401) {
            console.error('❌ 401 Unauthorized - 로그인 페이지로 리다이렉트');
            localStorage.removeItem('gbms_token');
            localStorage.removeItem('gbms_user');
            sessionStorage.removeItem('gbms_token');
            sessionStorage.removeItem('gbms_user');
            // 상대 경로 사용 (페이지 위치에 관계없이 작동)
            const depth = (window.location.pathname.match(/\//g) || []).length - 1;
            const prefix = depth > 1 ? '../'.repeat(depth - 1) : '';
            window.location.href = `${prefix}index.html`;
            throw new Error('Unauthorized');
        }

        if (!response.ok) {
            throw new Error(result.message || `HTTP error! status: ${response.status}`);
        }

        return result;
    } catch (error) {
        console.error('API request error:', error);
        throw error;
    }
}

/**
 * FormData용 API 요청 (파일 업로드)
 * @param {string} endpoint - API 엔드포인트
 * @param {string} method - HTTP 메서드 (POST, PUT 등)
 * @param {FormData} formData - 업로드할 FormData
 * @returns {Promise} API 응답
 */
async function apiCallFormData(endpoint, method = 'POST', formData) {
    const token = localStorage.getItem('gbms_token') || sessionStorage.getItem('gbms_token');

    const options = {
        method: method,
        headers: {}
    };

    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    options.body = formData;

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        const result = await response.json();

        if (response.status === 401) {
            localStorage.removeItem('gbms_token');
            localStorage.removeItem('gbms_user');
            sessionStorage.removeItem('gbms_token');
            sessionStorage.removeItem('gbms_user');
            window.location.href = '../../index.html';
            throw new Error('Unauthorized');
        }

        return result;
    } catch (error) {
        console.error('API FormData request error:', error);
        throw error;
    }
}

/**
 * API 요청 헬퍼 (레거시 지원)
 * @param {string} endpoint - API 엔드포인트
 * @param {Object} options - fetch 옵션
 * @returns {Promise} API 응답
 */
async function apiRequest(endpoint, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    const config = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...options.headers,
        },
    };

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, config);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API request error:', error);
        throw error;
    }
}

/**
 * GET 요청 (레거시)
 */
const api = {
    get(endpoint) {
        return apiRequest(endpoint, { method: 'GET' });
    },

    post(endpoint, data) {
        return apiRequest(endpoint, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    put(endpoint, data) {
        return apiRequest(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },

    delete(endpoint) {
        return apiRequest(endpoint, { method: 'DELETE' });
    },
};

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { api, apiRequest, apiCall };
}

/**
 * 현재 로그인한 사용자 정보 가져오기
 * @returns {Object|null} 사용자 정보
 */
function getCurrentUser() {
    const userJson = localStorage.getItem('gbms_user') || sessionStorage.getItem('gbms_user');
    if (!userJson) return null;
    try {
        return JSON.parse(userJson);
    } catch (e) {
        return null;
    }
}

/**
 * 사용자가 특정 권한을 가지고 있는지 확인
 * @param {string} scope - 필요한 권한 ('overseas_tech', 'expansion', 'oda', 'all')
 * @returns {boolean} 권한 여부
 */
function hasPermission(scope) {
    const user = getCurrentUser();
    if (!user) return false;

    // admin 역할이면 모든 권한 허용
    if (user.role === 'admin') return true;

    // permissionScope가 'all'이면 모든 권한 허용
    const userScope = user.permissionScope || 'readonly';
    if (userScope === 'all') return true;

    // 요청된 권한과 사용자 권한 비교
    return userScope === scope;
}

/**
 * 관리자인지 확인
 * @returns {boolean} 관리자 여부
 */
function isAdmin() {
    const user = getCurrentUser();
    return user && user.role === 'admin';
}

/**
 * 권한에 따라 요소 표시/숨김
 * @param {string} elementId - 요소 ID
 * @param {string} scope - 필요한 권한
 */
function toggleElementByPermission(elementId, scope) {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.display = hasPermission(scope) ? '' : 'none';
    }
}
