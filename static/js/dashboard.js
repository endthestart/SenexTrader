/**
 * Trading Dashboard - Risk Management Integration
 * Fetches and displays buying power, risk budget, and account metrics
 */

class TradingDashboard {
    constructor() {
        this.riskBudgetCache = null;
        this.refreshInterval = null;
        this.refreshIntervalMs = 30000; // 30 seconds
    }

    /**
     * Initialize dashboard with risk budget loading
     */
    init() {
        this.loadRiskBudget();
        this.startPeriodicRefresh();
        this.bindEvents();
    }

    /**
     * Bind event handlers
     */
    bindEvents() {
        // Add manual refresh button if it exists
        const refreshBtn = document.getElementById('refreshRiskBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadRiskBudget(true));
        }

        // Refresh when window becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.loadRiskBudget();
            }
        });
    }

    /**
     * Fetch risk budget data from API
     * @param {boolean} forceRefresh - Force refresh bypassing cache
     */
    async loadRiskBudget(forceRefresh = false) {
        try {
            // Use cache if available and not forcing refresh
            if (!forceRefresh && this.riskBudgetCache) {
                this.updateRiskDisplay(this.riskBudgetCache);
                return;
            }

            const response = await fetch('/trading/api/risk-budget/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.success && data.data_available) {
                this.riskBudgetCache = data;
                this.updateRiskDisplay(data);
                this.updateLastUpdateTime();
            } else {
                // Handle expected cases: no account configured or data unavailable
                this.handleDataUnavailable(data.error || 'Risk data unavailable');
            }

        } catch (error) {
            console.error('Error loading risk budget:', error);
            this.handleLoadError(error.message);
        }
    }

    /**
     * Update dashboard display with risk budget data
     * @param {Object} data - Risk budget data from API
     */
    updateRiskDisplay(data) {
        // Update buying power
        const buyingPowerEl = document.getElementById('buyingPower');
        if (buyingPowerEl) {
            buyingPowerEl.textContent = `${window.formatCurrency(data.tradeable_capital)}`;
            buyingPowerEl.className = 'text-success mb-1';
        }

        // Update other metrics if elements exist
        window.updateElement('todaysPnl', '$0.00', 'text-muted mb-1'); // Placeholder for now
        window.updateElement('activeSuggestionsCount', '0'); // Updated by other code
        window.updateElement('pendingTradesCount', '0'); // Updated by other code

        // Add risk utilization display if element exists
        const utilizationEl = document.getElementById('riskUtilization');
        if (utilizationEl) {
            const utilization = data.utilization_percent || 0;
            utilizationEl.textContent = `${utilization.toFixed(1)}%`;

            // Color code based on utilization
            if (utilization < 50) {
                utilizationEl.className = 'text-success mb-1';
            } else if (utilization < 75) {
                utilizationEl.className = 'text-warning mb-1';
            } else {
                utilizationEl.className = 'text-danger mb-1';
            }
        }

        // Update strategy power if element exists
        const strategyPowerEl = document.getElementById('strategyPower');
        if (strategyPowerEl) {
            strategyPowerEl.textContent = `${window.formatCurrency(data.strategy_power)}`;
            strategyPowerEl.className = 'text-info mb-1';
        }
    }

    /**
     * Handle when account data is unavailable
     * @param {string} message - Error message to display
     */
    handleDataUnavailable(message = 'Account data unavailable') {
        window.updateElement('buyingPower', 'Unavailable', 'text-warning mb-1');
        window.updateElement('riskUtilization', 'N/A', 'text-muted mb-1');
        window.updateElement('strategyPower', 'N/A', 'text-muted mb-1');

        console.warn('Account data unavailable:', message);
    }

    /**
     * Handle load errors
     * @param {string} error - Error message
     */
    handleLoadError(error) {
        window.updateElement('buyingPower', 'Error', 'text-danger mb-1');
        console.error('Risk budget load error:', error);
    }

    /**
     * Start periodic refresh of risk data
     */
    startPeriodicRefresh() {
        this.refreshInterval = setInterval(() => {
            this.loadRiskBudget();
        }, this.refreshIntervalMs);
    }

    /**
     * Stop periodic refresh
     */
    stopPeriodicRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    /**
     * Update the last update timestamp
     */
    updateLastUpdateTime() {
        const now = new Date();
        const timeString = now.toLocaleTimeString();
        window.updateElement('lastRiskUpdate', timeString);
    }

    /**
     * Cleanup when page unloads
     */
    destroy() {
        this.stopPeriodicRefresh();
    }
}

// Global instance
window.tradingDashboard = new TradingDashboard();

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (window.tradingDashboard && typeof window.tradingDashboard.init === 'function') {
        window.tradingDashboard.init();
    }
});

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (window.tradingDashboard && typeof window.tradingDashboard.destroy === 'function') {
        window.tradingDashboard.destroy();
    }
});
