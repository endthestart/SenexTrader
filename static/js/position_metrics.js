/**
 * Real-time Position Metrics Updates via WebSocket
 *
 * Unified handler for position Greeks, P&L, and account balance updates.
 * Receives position_metrics_update messages from StreamManager every 30 seconds.
 *
 * Data Flow Pattern (site-wide standard):
 * 1. Initial page load: Data from database
 * 2. WebSocket connects: Subscribe to position_metrics_update
 * 3. Updates received: Apply to DOM every 30 seconds
 * 4. No polling: Pure WebSocket-driven updates
 *
 * Integrates with existing WebSocket connection on positions.html.
 * Extends RealtimeUpdaterBase for common real-time update functionality.
 */

class PositionMetricsUpdater extends RealtimeUpdaterBase {
    constructor(websocket) {
        super({ websocket });

        this.lastUpdate = null;
        this.updateCount = 0;

        // Register handler for unified metrics updates
        this.registerHandler('position_metrics_update', this.handleMetricsUpdate);

        // Keep legacy handler for backward compatibility during transition
        this.registerHandler('position_pnl_update', this.handleLegacyPnLUpdate);

        // Initialize and register with global WebSocket
        this.init();

        window.logStreamInfo('[PositionMetrics] Initialized - listening for unified metrics updates');
    }

    handleMetricsUpdate(data) {
        const positions = data.positions || [];
        const balance = data.balance;
        const portfolioGreeks = data.portfolio_greeks;
        const timestamp = data.timestamp;

        if (positions.length === 0 && !balance && !portfolioGreeks) {
            return;
        }

        // Update each position row with Greeks + P&L
        positions.forEach(pos => {
            this.updatePositionRow(pos.position_id, pos.pnl, pos.greeks);
        });

        // Update portfolio Greeks display (server-provided, single source of truth)
        if (portfolioGreeks) {
            this.updatePortfolioGreeks(portfolioGreeks);
        }

        // Update balance display if present
        if (balance) {
            this.updateBalanceDisplay(balance);
        }

        // After updating individual rows, recalculate total from DOM
        this.updatePnLTotalFromDOM();

        // Track update stats
        this.lastUpdate = timestamp;
        this.updateCount++;
    }

    updatePortfolioGreeks(portfolioGreeks) {
        // Portfolio Greeks provided by backend (single source of truth)
        // No client-side aggregation - backend calculates via GreeksService

        // Update portfolio Greeks display if the global greeks updater exists
        if (window.greeksDisplay && typeof window.greeksDisplay.updatePortfolioGreeksDisplay === 'function') {
            window.greeksDisplay.updatePortfolioGreeksDisplay(portfolioGreeks);
        }
    }

    updatePnLTotalFromDOM() {
        // Simple: just sum unrealized P&L cells in tbody rows (exclude footer)
        let total = 0;

        // Find the table that has the totals footer
        const totalCell = document.getElementById('total-unrealized-pnl');
        if (!totalCell) return;

        const table = totalCell.closest('table');
        if (!table) return;

        // Only sum tbody rows (not tfoot)
        table.querySelectorAll('tbody .unrealized-pnl').forEach(cell => {
            // Extract the actual span content
            const span = cell.querySelector('span');
            if (!span) return;

            const text = span.textContent.trim();
            if (text === '-' || text === '$0.00') return;

            // Parse: +$123.45 or -$123.45 or $123.45
            const match = text.match(/([+-]?)\$?([\d,]+\.?\d*)/);
            if (match) {
                let value = parseFloat(match[2].replace(/,/g, ''));
                if (text.includes('-') || match[1] === '-') {
                    value = -value;
                }
                total += value;
            }
        });

        // Update total display (reuse totalCell from above)
        if (totalCell) {
            const formatted = this.formatPnL(total);
            if (totalCell.innerHTML !== formatted) {
                totalCell.innerHTML = formatted;
                this.flashElement(totalCell);
            }
        }
    }

    formatPnL(value) {
        if (value > 0) {
            return `<span class="text-success">+$${value.toFixed(2)}</span>`;
        } else if (value < 0) {
            return `<span class="text-danger">$${value.toFixed(2)}</span>`;
        } else {
            return `<span class="text-muted">$0.00</span>`;
        }
    }

    handleLegacyPnLUpdate(data) {
        // Legacy handler for old position_pnl_update format (during transition)
        const positions = data.positions || [];
        const timestamp = data.timestamp;

        if (positions.length === 0) {
            return;
        }

        window.logStreamInfo(`[PositionMetrics] Legacy P&L update: ${positions.length} positions`);

        positions.forEach(pos => {
            this.updatePositionRow(pos.position_id, pos.unrealized_pnl, null);
        });

        this.lastUpdate = timestamp;
    }

    updatePositionRow(positionId, pnl, greeks) {
        // Find the table row for this position
        const row = document.querySelector(`tr[data-position-id="${positionId}"]`);

        if (!row) {
            console.warn(`[PositionMetrics] Row not found for position ${positionId}`);
            return;
        }

        // Update P&L if provided
        if (pnl !== null && pnl !== undefined) {
            const pnlCell = row.querySelector('.unrealized-pnl');
            if (pnlCell) {
                const formattedValue = this.formatCurrency(pnl);

                // Only update if value changed
                if (pnlCell.textContent !== formattedValue) {
                    pnlCell.textContent = formattedValue;
                    this.updateColorClass(pnlCell, pnl);
                    this.flashElement(pnlCell);
                }
            }
        }

        // Update Greeks if provided
        if (greeks) {
            this.updateGreeksInRow(row, greeks);
        }
    }

    updateGreeksInRow(row, greeks) {
        // Update Delta
        const deltaCell = row.querySelector('.position-delta');
        if (deltaCell && greeks.delta !== null && greeks.delta !== undefined) {
            const formattedDelta = greeks.delta.toFixed(2);
            if (deltaCell.textContent !== formattedDelta) {
                deltaCell.textContent = formattedDelta;
                // Color code delta: positive = green (bullish), negative = red (bearish)
                deltaCell.classList.remove('text-success', 'text-danger', 'text-warning', 'text-muted');
                if (greeks.delta > 0.1) {
                    deltaCell.classList.add('text-success');
                } else if (greeks.delta < -0.1) {
                    deltaCell.classList.add('text-danger');
                } else {
                    deltaCell.classList.add('text-warning');
                }
                this.flashElement(deltaCell);
            }
        }

        // Update Theta
        const thetaCell = row.querySelector('.position-theta');
        if (thetaCell && greeks.theta !== null && greeks.theta !== undefined) {
            const formattedTheta = greeks.theta.toFixed(2);
            if (thetaCell.textContent !== formattedTheta) {
                thetaCell.textContent = formattedTheta;
                // Color code theta: positive = green (decay working for you), negative = red
                thetaCell.classList.remove('text-success', 'text-danger', 'text-warning', 'text-muted');
                if (greeks.theta > 0) {
                    thetaCell.classList.add('text-success');
                } else if (greeks.theta < -1.0) {
                    thetaCell.classList.add('text-danger');
                } else {
                    thetaCell.classList.add('text-warning');
                }
                this.flashElement(thetaCell);
            }
        }

        // Could add gamma, vega, rho if desired
    }

    updateBalanceDisplay(balance) {
        // Update account balance if element exists
        const balanceElement = document.getElementById('accountBalance');
        if (balanceElement && balance.balance !== null && balance.balance !== undefined) {
            balanceElement.textContent = this.formatCurrency(balance.balance);
        }

        // Update buying power if element exists
        const buyingPowerElement = document.getElementById('buyingPower');
        if (buyingPowerElement && balance.buying_power !== null && balance.buying_power !== undefined) {
            buyingPowerElement.textContent = this.formatCurrency(balance.buying_power);
        }
    }

    updateColorClass(element, value) {
        // Remove existing color classes
        element.classList.remove('text-success', 'text-danger', 'text-muted');

        // Get appropriate color class using base class method
        const colorClass = this.getColorClass(value);
        element.classList.add(colorClass);
    }

    getStats() {
        return {
            lastUpdate: this.lastUpdate ? new Date(this.lastUpdate).toLocaleString() : 'Never',
            updateCount: this.updateCount
        };
    }
}

// Export for use in templates
window.PositionMetricsUpdater = PositionMetricsUpdater;
