/**
 * Base class for real-time WebSocket updates.
 * Provides common functionality for updating UI elements with live data.
 */
class RealtimeUpdaterBase {
    constructor(config = {}) {
        this.websocket = config.websocket || window.streamerWebSocket;
        this.handlers = new Map();
        this.formatters = {
            currency: this.formatCurrency.bind(this),
            decimal: this.formatDecimal.bind(this),
            percentage: this.formatPercentage.bind(this)
        };
        this.handlerId = null;  // Track handler ID for cleanup
        this.context = config.context || 'realtime-updater';
    }

    /**
     * Register a message handler for a specific type.
     */
    registerHandler(messageType, callback) {
        this.handlers.set(messageType, callback);
    }

    /**
     * Initialize - register with global WebSocket
     */
    init() {
        if (window.addMessageHandler) {
            this.handlerId = window.addMessageHandler((data) => {
                const handler = this.handlers.get(data.type);
                if (handler) {
                    handler.call(this, data);
                }
            }, this.context);
        }
    }

    /**
     * Clean up resources
     */
    destroy() {
        if (this.handlerId && window.removeMessageHandler) {
            window.removeMessageHandler(this.handlerId);
            this.handlerId = null;
        }
    }

    /**
     * Update an element with optional formatting and flash animation
     */
    updateElement(elementId, value, options = {}) {
        const element = document.getElementById(elementId);
        if (!element) return;

        const formatter = options.formatter || ((v) => v);
        const formattedValue = formatter(value);
        const currentValue = element.textContent;

        // Only update if value changed
        if (currentValue !== formattedValue) {
            element.textContent = formattedValue;

            // Apply color class if provided
            if (options.colorClass) {
                element.className = options.colorClass;
            }

            // Flash animation
            if (options.flash !== false) {
                this.flashElement(element, options.duration || 500);
            }
        }
    }

    /**
     * Add flash animation to element
     * Uses 'pnl-updated' class for compatibility with existing animations
     */
    flashElement(element, duration = 500) {
        element.classList.add('pnl-updated');
        setTimeout(() => {
            element.classList.remove('pnl-updated');
        }, duration);
    }

    /**
     * Get color class based on value and thresholds
     */
    getColorClass(value, thresholds = {positive: 0, negative: 0}) {
        if (value > thresholds.positive) return 'text-success';
        if (value < thresholds.negative) return 'text-danger';
        return 'text-muted';
    }

    /**
     * Format as currency
     */
    formatCurrency(value) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(value);
    }

    /**
     * Format as decimal
     */
    formatDecimal(value, decimals = 2) {
        return parseFloat(value).toFixed(decimals);
    }

    /**
     * Format as percentage
     */
    formatPercentage(value, decimals = 2) {
        return `${(parseFloat(value) * 100).toFixed(decimals)}%`;
    }
}

// Export globally
window.RealtimeUpdaterBase = RealtimeUpdaterBase;
