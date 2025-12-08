/**
 * Greeks Display Component
 * Shows real-time Greeks for positions and portfolio
 *
 * Features:
 * - Portfolio-level Greeks aggregation
 * - Auto-refresh every 5 seconds
 * - Color-coded display (delta/theta)
 * - Handles missing data gracefully
 */

class GreeksDisplay {
    constructor() {
        // No polling - WebSocket updates only (30s from StreamManager)
        window.logStreamInfo('[Greeks] Using WebSocket-only updates (no polling)');
    }

    /**
     * Initialize Greeks display
     */
    init() {
        window.logStreamInfo('Greeks display initialized');

        // Load initial portfolio Greeks (if portfolio card exists)
        // After this, WebSocket updates take over (via position_metrics_update)
        if (document.getElementById('portfolioDelta')) {
            this.loadPortfolioGreeks();
        }

        // Load initial position-level Greeks (if on positions page)
        // After this, WebSocket updates take over (via position_metrics_update)
        if (document.querySelector('tr[data-position-id]')) {
            this.loadAllPositionGreeks();
        }

        // WebSocket updates handled by PositionMetricsUpdater - no polling needed
    }

    /**
     * Load portfolio-level Greeks
     */
    async loadPortfolioGreeks() {
        try {
            const response = await fetch('/trading/api/portfolio/greeks/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (data.success) {
                this.updatePortfolioGreeksDisplay(data.greeks);
            } else {
                this.handleGreeksUnavailable();
            }

        } catch (error) {
            console.error('Error loading portfolio Greeks:', error);
            this.handleLoadError(error.message);
        }
    }

    /**
     * Update portfolio Greeks display
     */
    updatePortfolioGreeksDisplay(greeks) {
        // Delta
        window.updateElement('portfolioDelta', this.formatGreek(greeks.delta, 2),
            this.getGreekColorClass('delta', greeks.delta));

        // Gamma
        window.updateElement('portfolioGamma', this.formatGreek(greeks.gamma, 3),
            'text-info mb-1');

        // Theta
        window.updateElement('portfolioTheta', this.formatGreek(greeks.theta, 2),
            this.getGreekColorClass('theta', greeks.theta));

        // Vega
        window.updateElement('portfolioVega', this.formatGreek(greeks.vega, 2),
            'text-info mb-1');

        // Rho (optional - not always displayed)
        if (document.getElementById('portfolioRho')) {
            window.updateElement('portfolioRho', this.formatGreek(greeks.rho, 2),
                'text-muted mb-1');
        }

        // Position count
        if (document.getElementById('portfolioPositionCount')) {
            window.updateElement('portfolioPositionCount', greeks.position_count);
        }
    }

    /**
     * Format Greek value for display
     */
    formatGreek(value, decimals = 2) {
        if (value === null || value === undefined) {
            return 'N/A';
        }
        return value.toFixed(decimals);
    }

    /**
     * Get color class based on Greek value
     */
    getGreekColorClass(greek, value) {
        if (greek === 'delta') {
            // Positive delta = bullish (green), negative = bearish (red)
            if (value > 0.1) return 'text-success mb-1';
            if (value < -0.1) return 'text-danger mb-1';
            return 'text-warning mb-1'; // Near neutral
        }

        if (greek === 'theta') {
            // Negative theta = time decay working against you (yellow/red)
            // Positive theta = time decay working for you (green)
            if (value > 0) return 'text-success mb-1';
            if (value < -1.0) return 'text-danger mb-1';
            return 'text-warning mb-1';
        }

        return 'text-muted mb-1';
    }

    /**
     * Handle Greeks data unavailable
     */
    handleGreeksUnavailable() {
        window.updateElement('portfolioDelta', 'N/A', 'text-muted mb-1');
        window.updateElement('portfolioGamma', 'N/A', 'text-muted mb-1');
        window.updateElement('portfolioTheta', 'N/A', 'text-muted mb-1');
        window.updateElement('portfolioVega', 'N/A', 'text-muted mb-1');
        if (document.getElementById('portfolioRho')) {
            window.updateElement('portfolioRho', 'N/A', 'text-muted mb-1');
        }
    }

    /**
     * Handle load errors
     */
    handleLoadError(error) {
        console.error('Greeks load error:', error);
        // Don't show N/A on error - keep previous values
    }

    /**
     * Update Greeks in position table row
     */
    updatePositionGreeksDisplay(positionId, greeks) {
        const row = document.querySelector(`tr[data-position-id="${positionId}"]`);
        if (!row) return;

        // Delta cell
        const deltaCell = row.querySelector('.position-delta');
        if (deltaCell) {
            deltaCell.textContent = this.formatGreek(greeks.delta, 2);
            deltaCell.className = `position-delta ${this.getGreekColorClass('delta', greeks.delta)}`;
        }

        // Theta cell
        const thetaCell = row.querySelector('.position-theta');
        if (thetaCell) {
            thetaCell.textContent = this.formatGreek(greeks.theta, 2);
            thetaCell.className = `position-theta ${this.getGreekColorClass('theta', greeks.theta)}`;
        }
    }

    /**
     * Load Greeks for all visible positions (batch endpoint)
     */
    async loadAllPositionGreeks() {
        try {
            const response = await fetch('/trading/api/positions/greeks/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            if (data.success && data.positions) {
                // Update each position's display
                for (const [positionId, greeks] of Object.entries(data.positions)) {
                    this.updatePositionGreeksDisplay(positionId, greeks);
                }
            }
        } catch (error) {
            console.error('Error loading position Greeks:', error);
        }
    }

    /**
     * Cleanup - no periodic refresh to stop
     */
    destroy() {
        // No polling intervals to clean up
        window.logStreamInfo('[Greeks] Cleanup complete');
    }
}

// Global instance
window.greeksDisplay = new GreeksDisplay();

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (window.greeksDisplay && typeof window.greeksDisplay.init === 'function') {
        window.greeksDisplay.init();
    }
});

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (window.greeksDisplay && typeof window.greeksDisplay.destroy === 'function') {
        window.greeksDisplay.destroy();
    }
});