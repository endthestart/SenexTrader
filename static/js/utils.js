/**
 * Utility functions for the Senex Trader application
 * Provides consistent formatting across all pages
 */

/**
 * Format a number as a localized currency string (e.g., $1,234.56).
 * Uses the Intl.NumberFormat API for proper localization and formatting.
 * @param {number|string} value - The value to format
 * @returns {string} Formatted currency string
 */
function formatCurrency(value) {
    const number = parseFloat(value);
    if (value === undefined || value === null || isNaN(number)) {
        return '$0.00';
    }
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(number);
}

/**
 * Format a number with exactly 2 decimal places (no currency symbol)
 * @param {number|string} value - The value to format
 * @returns {string} Formatted number string
 */
function formatDecimal(value, decimals = 2) {
    if (value === undefined || value === null || isNaN(value)) {
        return '0.00';
    }
    return parseFloat(value).toFixed(decimals);
}

/**
 * Format a number as percentage
 * @param {number} value - The value to format (0.1 = 10%)
 * @param {number} decimals - Number of decimal places
 * @returns {string} Formatted percentage string
 */
function formatPercentage(value, decimals = 2) {
    if (value === undefined || value === null || isNaN(value)) {
        return '0%';
    }
    return (parseFloat(value) * 100).toFixed(decimals) + '%';
}

/**
 * Get CSRF token from cookies
 * @returns {string} CSRF token
 */
function getCsrfToken() {
    const name = 'csrftoken';
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [key, value] = cookie.trim().split('=');
        if (key === name) {
            return decodeURIComponent(value);
        }
    }
    return '';
}

/**
 * Update element with text and class
 * @param {string} id - Element ID
 * @param {string} text - Text to display
 * @param {string} className - CSS class to apply
 */
function updateElement(id, text, className = '') {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = text;
        if (className) {
            el.className = className;
        }
    }
}

/**
 * Show reusable confirmation modal with custom title, message, and callback
 * Provides better UX than browser confirm() which can be disabled by users
 * @param {string} title - Modal title
 * @param {string} message - Modal body message (supports HTML)
 * @param {Function} onConfirm - Callback when user confirms
 * @param {string} confirmBtnText - Text for confirm button (default: "Confirm")
 * @param {string} confirmBtnClass - CSS class for confirm button (default: "btn-primary")
 */
function showConfirmModal(title, message, onConfirm, confirmBtnText = 'Confirm', confirmBtnClass = 'btn-primary') {
    const modal = document.getElementById('confirmModal');
    const titleEl = document.getElementById('confirmModalTitle');
    const bodyEl = document.getElementById('confirmModalBody');
    const confirmBtn = document.getElementById('confirmModalConfirmBtn');

    // Set content
    titleEl.textContent = title;
    bodyEl.innerHTML = message;
    confirmBtn.textContent = confirmBtnText;
    confirmBtn.className = `btn ${confirmBtnClass}`;

    // Remove old click handlers by cloning
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

    // Add new click handler
    newConfirmBtn.addEventListener('click', function() {
        bootstrap.Modal.getInstance(modal).hide();
        if (typeof onConfirm === 'function') {
            onConfirm();
        }
    });

    // Show modal
    new bootstrap.Modal(modal).show();
}

/**
 * Show prompt modal for user input (replaces browser prompt())
 * Provides consistent UX and better styling than browser prompt
 * @param {string} title - Modal title
 * @param {string} label - Input label text
 * @param {string} placeholder - Input placeholder text
 * @param {string} defaultValue - Default input value
 * @param {Function} onConfirm - Callback when user confirms, receives input value
 * @param {Function} onCancel - Optional callback when user cancels
 * @returns {Promise<string|null>} Promise that resolves to input value or null if cancelled
 */
function showPromptModal(title, label, placeholder = '', defaultValue = '', onConfirm = null, onCancel = null) {
    return new Promise((resolve) => {
        const modal = document.getElementById('promptModal');
        const titleEl = document.getElementById('promptModalTitle');
        const labelEl = document.getElementById('promptModalLabel');
        const inputEl = document.getElementById('promptModalInput');
        const confirmBtn = document.getElementById('promptModalConfirmBtn');

        // Set content
        titleEl.textContent = title;
        labelEl.textContent = label;
        inputEl.placeholder = placeholder;
        inputEl.value = defaultValue;

        // Remove old click handlers by cloning
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

        // Handle confirm
        newConfirmBtn.addEventListener('click', function() {
            const value = inputEl.value;
            bootstrap.Modal.getInstance(modal).hide();
            if (typeof onConfirm === 'function') {
                onConfirm(value);
            }
            resolve(value);
        });

        // Handle cancel
        const handleCancel = () => {
            if (typeof onCancel === 'function') {
                onCancel();
            }
            resolve(null);
        };

        modal.addEventListener('hidden.bs.modal', handleCancel, { once: true });

        // Focus input and select text
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
        modal.addEventListener('shown.bs.modal', () => {
            inputEl.focus();
            inputEl.select();
            // Handle Enter key
            inputEl.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    newConfirmBtn.click();
                }
            }, { once: true });
        }, { once: true });
    });
}

/**
 * Show generic result modal for success, error, info, or warning messages
 * Provides consistent UX for execution results and critical feedback
 * @param {string} type - Modal type: 'success' | 'error' | 'info' | 'warning'
 * @param {string} title - Modal title text
 * @param {string} message - Modal body message (supports HTML)
 * @param {Array} actions - Array of action button configs: [{text, class, callback}, ...]
 */
function showResultModal(type, title, message, actions = []) {
    const modal = document.getElementById('resultModal');
    const modalContent = document.getElementById('resultModalContent');
    const modalHeader = document.getElementById('resultModalHeader');
    const icon = document.getElementById('resultModalIcon');
    const titleText = document.getElementById('resultModalTitleText');
    const body = document.getElementById('resultModalBody');
    const footer = document.getElementById('resultModalFooter');

    // Configure modal styling based on type
    const config = {
        success: {
            headerClass: 'bg-success text-white',
            contentClass: 'bg-dark text-white',
            icon: 'bi-check-circle-fill text-success'
        },
        error: {
            headerClass: 'bg-danger text-white',
            contentClass: 'bg-dark text-white',
            icon: 'bi-x-circle-fill text-danger'
        },
        info: {
            headerClass: 'bg-info text-white',
            contentClass: 'bg-dark text-white',
            icon: 'bi-info-circle-fill text-info'
        },
        warning: {
            headerClass: 'bg-warning text-dark',
            contentClass: 'bg-dark text-white',
            icon: 'bi-exclamation-triangle-fill text-warning'
        }
    };

    const typeConfig = config[type] || config.info;

    // Apply styling
    modalHeader.className = `modal-header ${typeConfig.headerClass}`;
    modalContent.className = `modal-content ${typeConfig.contentClass}`;
    icon.className = `${typeConfig.icon} me-2`;

    // Set content
    titleText.textContent = title;
    body.innerHTML = message;

    // Clear and rebuild footer
    footer.innerHTML = '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>';

    // Add action buttons
    actions.forEach(action => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `btn ${action.class || 'btn-primary'}`;
        btn.textContent = action.text;

        // Add click handler
        btn.addEventListener('click', function() {
            bootstrap.Modal.getInstance(modal).hide();
            if (typeof action.callback === 'function') {
                action.callback();
            }
        });

        footer.appendChild(btn);
    });

    // Show modal
    new bootstrap.Modal(modal).show();
}

/**
 * Update streaming status badge (navbar indicator)
 * @param {string} status - 'connecting' | 'connected' | 'offline'
 * @param {string} message - Tooltip message
 */
function updateStreamingBadge(status, message) {
    const badge = document.getElementById('streaming-status-badge');
    if (!badge) return;

    const textSpan = document.getElementById('badge-text');
    const icon = badge.querySelector('i');

    // Show badge
    badge.style.display = 'inline-block';

    // Update based on status
    const config = {
        connecting: { color: 'text-warning', icon: 'bi-wifi', text: 'Connecting...' },
        connected: { color: 'text-success', icon: 'bi-wifi', text: 'Live' },
        offline: { color: 'text-danger', icon: 'bi-wifi-off', text: 'Offline' }
    };

    const cfg = config[status] || config.offline;
    badge.className = `nav-link ${cfg.color}`;
    icon.className = cfg.icon;
    textSpan.textContent = cfg.text;
    badge.title = message || cfg.text;
}


// Export functions for use in templates
window.formatCurrency = formatCurrency;
window.formatDecimal = formatDecimal;
window.formatPercentage = formatPercentage;
window.getCsrfToken = getCsrfToken;
window.updateElement = updateElement;
window.showConfirmModal = showConfirmModal;
window.showPromptModal = showPromptModal;
window.showResultModal = showResultModal;
window.updateStreamingBadge = updateStreamingBadge;