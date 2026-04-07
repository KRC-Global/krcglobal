// ═══════════════════════════════════════════════════════
// Modal 컴포넌트
// ═══════════════════════════════════════════════════════

class Modal {
    constructor(options = {}) {
        this.onClose = options.onClose || (() => { });
        this.overlay = null;
        this.focusableElements = [];
        this.previousFocus = null;
    }

    /**
     * 모달 열기
     * @param {string} content - 모달 내용 (HTML)
     * @param {string} title - 모달 제목
     * @param {Object} options - 추가 옵션
     */
    open(content, title = '', options = {}) {
        this.previousFocus = document.activeElement;

        this.overlay = document.createElement('div');
        this.overlay.className = 'modal-overlay';
        this.overlay.innerHTML = `
            <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
                <div class="modal-header">
                    <h3 id="modal-title">${title}</h3>
                    <button class="modal-close" aria-label="닫기">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
                ${options.footer ? `<div class="modal-footer">${options.footer}</div>` : ''}
            </div>
        `;

        document.body.appendChild(this.overlay);
        document.body.style.overflow = 'hidden';

        // 이벤트 리스너
        this.overlay.querySelector('.modal-close').addEventListener('click', () => this.close());
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) this.close();
        });

        // ESC 키로 닫기
        this.handleEscape = (e) => {
            if (e.key === 'Escape') this.close();
        };
        document.addEventListener('keydown', this.handleEscape);

        // 포커스 트랩
        this.trapFocus();

        // 첫 번째 포커스 가능한 요소에 포커스
        const firstFocusable = this.overlay.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (firstFocusable) {
            firstFocusable.focus();
        }
    }

    /**
     * 모달 닫기
     */
    close() {
        if (this.overlay) {
            this.overlay.remove();
            document.body.style.overflow = '';
            document.removeEventListener('keydown', this.handleEscape);

            // 이전 포커스 복원
            if (this.previousFocus) {
                this.previousFocus.focus();
            }

            this.onClose();
        }
    }

    /**
     * 포커스 트랩 (접근성)
     */
    trapFocus() {
        const modal = this.overlay.querySelector('.modal');
        const focusableElements = modal.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );

        this.focusableElements = Array.from(focusableElements);

        if (this.focusableElements.length === 0) return;

        const firstElement = this.focusableElements[0];
        const lastElement = this.focusableElements[this.focusableElements.length - 1];

        modal.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;

            if (e.shiftKey) {
                if (document.activeElement === firstElement) {
                    lastElement.focus();
                    e.preventDefault();
                }
            } else {
                if (document.activeElement === lastElement) {
                    firstElement.focus();
                    e.preventDefault();
                }
            }
        });
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Modal;
}
