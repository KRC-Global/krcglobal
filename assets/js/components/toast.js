// ═══════════════════════════════════════════════════════
// Toast 알림 컴포넌트
// ═══════════════════════════════════════════════════════

class Toast {
    /**
     * Toast 알림 표시
     * @param {string} message - 메시지
     * @param {string} type - 타입 (success, error, warning, info)
     * @param {number} duration - 표시 시간 (ms)
     */
    static show(message, type = 'info', duration = 3000) {
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            container.setAttribute('aria-live', 'polite');
            container.setAttribute('aria-atomic', 'true');
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <span class="toast-icon">${this.getIcon(type)}</span>
            <span class="toast-message">${message}</span>
        `;

        container.appendChild(toast);

        // 자동 제거
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease-in forwards';
            setTimeout(() => {
                toast.remove();

                // 컨테이너가 비어있으면 제거
                if (container.children.length === 0) {
                    container.remove();
                }
            }, 300);
        }, duration);
    }

    /**
     * 타입별 아이콘 반환
     * @param {string} type - 타입
     * @returns {string} 아이콘
     */
    static getIcon(type) {
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };
        return icons[type] || icons.info;
    }

    /**
     * 성공 메시지
     */
    static success(message, duration) {
        this.show(message, 'success', duration);
    }

    /**
     * 에러 메시지
     */
    static error(message, duration) {
        this.show(message, 'error', duration);
    }

    /**
     * 경고 메시지
     */
    static warning(message, duration) {
        this.show(message, 'warning', duration);
    }

    /**
     * 정보 메시지
     */
    static info(message, duration) {
        this.show(message, 'info', duration);
    }
}

// 호환성을 위한 전역 함수
function showToast(message, type = 'info', duration = 3000) {
    Toast.show(message, type, duration);
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Toast;
}
