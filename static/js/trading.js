/**
 * Trading Interface - Handles trade execution and real-time updates
 * Phase 6: Trading Execution Implementation
 */

class TradingInterface {
    constructor() {
        this.config = null;
        this.socket = null;
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second
        this.handlerId = null;  // Track our handler ID for cleanup
    }

    /**
     * Initialize the trading interface
     * @param {Object} config - Configuration object
     */
    init(config) {
        this.config = config;
        this.bindEvents();
        this.useGlobalWebSocket();
        this.updateStatusBadges();
        this.loadRiskBudget(); // Load risk budget on init

        // Register this instance's message handler with the global system
        if (window.addMessageHandler) {
            this.handlerId = window.addMessageHandler((data) => this.handleTradingMessage(data), 'trading');
        }

        window.logStreamInfo('Trading Interface initialized', config);
    }

    /**
     * Clean up resources when page is unloaded
     */
    destroy() {
        if (this.handlerId && window.removeMessageHandler) {
            window.removeMessageHandler(this.handlerId);
            this.handlerId = null;
        }
    }

    /**
     * Show loading state on UI elements
     * @param {string} strategy - The strategy being generated
     */
    showLoadingState(strategy) {
        const statusPanel = document.getElementById('generationStatusPanel');
        const buttons = document.querySelectorAll('.strategy-btn');

        if (statusPanel) {
            const safeStrategy = escapeHtml(strategy.replace(/_/g, ' ').toUpperCase());
            statusPanel.innerHTML = `<div class="text-center text-info"><i class="bi bi-hourglass-split"></i> Generating ${safeStrategy}...</div>`;
        }

        buttons.forEach(btn => btn.disabled = true);
    }

    /**
     * Hide loading state and restore UI elements
     * @param {boolean} isError - If true, show an error state
     */
    hideLoadingState(isError = false) {
        const statusPanel = document.getElementById('generationStatusPanel');
        const buttons = document.querySelectorAll('.strategy-btn');

        if (statusPanel) {
            if (isError) {
                statusPanel.innerHTML = '<div class="text-center text-danger">Generation Failed</div>';
            } else {
                statusPanel.innerHTML = '<div class="text-center text-muted">Ready to generate suggestions</div>';
            }
        }

        buttons.forEach(btn => btn.disabled = false);
    }

    /**
     * Bind event handlers to UI elements
     */
    bindEvents() {
        // Execution buttons
        const approveBtn = document.getElementById('approveBtn');
        const executeBtn = document.getElementById('executeBtn');
        const rejectBtn = document.getElementById('rejectBtn');
        const refreshBtn = document.getElementById('refreshBtn');

        if (approveBtn) {
            approveBtn.addEventListener('click', (e) => this.approveSuggestion(e));
        }

        if (executeBtn) {
            executeBtn.addEventListener('click', (e) => this.executeTrade(e));
        }

        if (rejectBtn) {
            rejectBtn.addEventListener('click', (e) => this.rejectSuggestion(e));
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refreshData());
        }

        // Risk budget refresh button
        const refreshRiskBtn = document.getElementById('refreshRiskBtn');
        if (refreshRiskBtn) {
            refreshRiskBtn.addEventListener('click', () => this.loadRiskBudget(true));
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'Enter' && executeBtn && !executeBtn.disabled) {
                this.executeTrade(e);
            }
        });
    }

    /**
     * Load risk budget data and update displays
     * @param {boolean} forceRefresh - Force refresh bypassing cache
     */
    async loadRiskBudget(forceRefresh = false) {
        try {
            window.logStreamInfo('Loading risk budget...');

            const response = await fetch('/trading/api/risk-budget/', {
                method: 'GET',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                if (response.status === 503) {
                    this.handleRiskDataUnavailable();
                    return;
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.success && data.data_available) {
                this.updateRiskDisplay(data);
            } else {
                this.handleRiskDataUnavailable(data.error || 'Risk data unavailable');
            }

        } catch (error) {
            console.error('Error loading risk budget:', error);
            this.handleRiskLoadError(error.message);
        }
    }

    /**
     * Update risk budget display elements
     * @param {Object} data - Risk budget data
     */
    updateRiskDisplay(data) {
        // Update buying power
        window.updateElement('riskBuyingPower', `${window.formatCurrency(data.tradeable_capital)}`, 'text-success mb-0');

        // Update strategy power
        window.updateElement('riskStrategyPower', `${window.formatCurrency(data.strategy_power)}`, 'text-info mb-0');

        // Update available budget (remaining)
        window.updateElement('riskAvailableBudget', `${window.formatCurrency(data.remaining_budget)}`, 'text-warning mb-0');

        // Update risk utilization
        const utilization = data.utilization_percent || 0;
        window.updateElement('riskUtilization', `${utilization.toFixed(1)}%`, this.getRiskUtilizationClass(utilization));

        // Update progress bar
        const progressBar = document.getElementById('riskProgressBar');
        if (progressBar) {
            progressBar.style.width = `${Math.min(100, Math.max(0, utilization))}%`;
            progressBar.className = `progress-bar ${this.getProgressBarClass(utilization)}`;
        }

        // Update risk status alert
        this.updateRiskStatusAlert(data);

        window.logStreamInfo('Risk budget updated:', data);
    }

    /**
     * Handle when risk data is unavailable
     * @param {string} message - Error message
     */
    handleRiskDataUnavailable(message = 'Account data unavailable') {
        window.updateElement('riskBuyingPower', 'Unavailable', 'text-warning mb-0');
        window.updateElement('riskStrategyPower', 'N/A', 'text-muted mb-0');
        window.updateElement('riskAvailableBudget', 'N/A', 'text-muted mb-0');
        window.updateElement('riskUtilization', 'N/A', 'text-muted mb-0');

        this.showRiskAlert('warning', message);
        console.warn('Risk data unavailable:', message);
    }

    /**
     * Handle risk load errors
     * @param {string} error - Error message
     */
    handleRiskLoadError(error) {
        window.updateElement('riskBuyingPower', 'Error', 'text-danger mb-0');
        window.updateElement('riskStrategyPower', 'Error', 'text-danger mb-0');
        window.updateElement('riskAvailableBudget', 'Error', 'text-danger mb-0');
        window.updateElement('riskUtilization', 'Error', 'text-danger mb-0');

        this.showRiskAlert('danger', `Failed to load risk data: ${error}`);
        console.error('Risk budget load error:', error);
    }

    /**
     * Update risk status alert based on current data
     * @param {Object} data - Risk budget data
     */
    updateRiskStatusAlert(data) {
        const utilization = data.utilization_percent || 0;

        if (utilization > 90) {
            this.showRiskAlert('danger', 'Risk budget nearly exhausted! Consider reducing position sizes.');
        } else if (utilization > 75) {
            this.showRiskAlert('warning', 'High risk utilization. Monitor position sizes carefully.');
        } else if (utilization > 50) {
            this.showRiskAlert('info', 'Moderate risk utilization. Room for additional positions.');
        } else {
            this.hideRiskAlert();
        }
    }

    /**
     * Show risk status alert
     * @param {string} type - Alert type (success, info, warning, danger)
     * @param {string} message - Alert message
     */
    showRiskAlert(type, message) {
        const alert = document.getElementById('riskStatusAlert');
        if (alert) {
            alert.className = `alert alert-${type}`;
            alert.textContent = message;
            alert.classList.remove('d-none');
        }
    }

    /**
     * Hide risk status alert
     */
    hideRiskAlert() {
        const alert = document.getElementById('riskStatusAlert');
        if (alert) {
            alert.classList.add('d-none');
        }
    }

    /**
     * Get CSS class for risk utilization based on percentage
     * @param {number} utilization - Utilization percentage
     * @returns {string} CSS class
     */
    getRiskUtilizationClass(utilization) {
        if (utilization < 50) return 'text-success mb-0';
        if (utilization < 75) return 'text-warning mb-0';
        return 'text-danger mb-0';
    }

    /**
     * Get progress bar CSS class based on utilization
     * @param {number} utilization - Utilization percentage
     * @returns {string} CSS class
     */
    getProgressBarClass(utilization) {
        if (utilization < 50) return 'bg-success';
        if (utilization < 75) return 'bg-warning';
        return 'bg-danger';
    }

    /**
     * Use global WebSocket connection (no separate WebSocket needed)
     */
    useGlobalWebSocket() {
        // WebSocket management is now handled globally in base.html
        // This class just registers handlers with the global system
        if (window.streamerWebSocket) {
            this.socket = window.streamerWebSocket;
            this.isConnected = this.socket.readyState === WebSocket.OPEN;
        }
    }

    /**
     * Handle WebSocket messages (called by global message handler)
     */
    handleTradingMessage(data) {
        switch (data.type) {
            case 'suggestion_update':
                this.displaySuggestion(data.suggestion);
                this.showAlert('success', 'Pricing data received, suggestion ready!');
                break;
            case 'error':
                this.handleSuggestionError(data);
                break;
            case 'order.status':
                this.handleOrderStatusUpdate(data);
                break;
            case 'order.fill':
                this.handleOrderFill(data);
                break;
            case 'account_state.update':
                this.handleAccountStateUpdate(data);
                break;
            case 'stream.status':
                this.handleStreamStatus(data);
                break;
        }
    }

    /**
     * Handle suggestion generation errors
     */
    handleSuggestionError(data) {
        const { error_type, message, max_risk, strategy } = data;

        this.hideLoadingState(true);

        // Hide suggestion container and buttons
        const container = document.getElementById('suggestionContainer');
        if (container) {
            container.classList.add('d-none');
        }

        // Handle specific error types
        if (error_type === 'risk_budget_exceeded') {
            // Show clear risk budget error with details
            const riskMessage = `
                <div class="alert alert-danger">
                    <h5 class="alert-heading">
                        <i class="bi bi-exclamation-triangle-fill me-2"></i>
                        Risk Budget Exceeded
                    </h5>
                    <hr>
                    <p class="mb-2"><strong>Cannot generate ${strategy ? strategy.replace(/_/g, ' ') : 'strategy'}:</strong></p>
                    <p class="mb-2">${message}</p>
                    ${max_risk ? `<p class="mb-2">Position risk: <strong>$${max_risk.toFixed(2)}</strong></p>` : ''}
                    <hr>
                    <p class="mb-0">
                        <strong>Solutions:</strong><br>
                        • Close some existing positions to free up risk budget<br>
                        • Increase your risk tolerance in settings<br>
                        • Wait for current positions to close naturally
                    </p>
                </div>
            `;

            // Display in the suggestion content area
            const content = document.getElementById('suggestionContent');
            if (content) {
                content.innerHTML = riskMessage;
                const suggestionContainer = document.getElementById('suggestionContainer');
                if (suggestionContainer) {
                    suggestionContainer.classList.remove('d-none');
                }
            }

            // Also update risk budget display to reflect the issue
            this.loadRiskBudget(true);
        } else {
            // Generic error handling
            this.showAlert('warning', message || 'Unable to generate suggestion under current conditions.');
        }
    }

    /**
     * Render option legs dynamically based on strategy and available strikes
     */
    renderLegs(suggestion) {
        if (!suggestion.legs || suggestion.legs.length === 0) {
            return '<div class="text-muted">No legs data available</div>';
        }

        const formatLeg = (leg, index) => {
            const sign = leg.action === 'sell' ? '-' : '+';
            const qty = leg.quantity || 1;
            const exp = TradingUtils.formatExpiration(leg.expiration);
            const dte = leg.dte ? `${leg.dte}d` : '';
            const strike = TradingUtils.formatValue(leg.strike);
            const type = leg.option_type === 'call' ? 'C' : 'P';
            const action = leg.action === 'sell' ? 'STO' : 'BTO';

            const rowBg = index % 2 === 0 ? 'rgba(255, 255, 255, 0.05)' : 'transparent';
            const actionColor = leg.action === 'sell' ? '#ff6b6b' : '#51cf66';
            const qtyColor = leg.action === 'sell' ? '#ff8787' : '#69db7c';

            return `
                <div class="mb-1 font-monospace small" style="background: ${rowBg}; padding: 4px 8px; border-radius: 3px;">
                    <span style="display: inline-block; width: 30px; text-align: right; color: ${qtyColor}; font-weight: 600;">${sign}${qty}</span>
                    <span style="display: inline-block; width: 75px; margin-left: 8px; color: #a0a0a0;">${exp}</span>
                    <span style="display: inline-block; width: 40px; color: #808080;">${dte}</span>
                    <span style="display: inline-block; width: 65px; color: #e0e0e0; font-weight: 500;">$${strike}</span>
                    <span style="display: inline-block; width: 20px; color: ${type === 'C' ? '#74c0fc' : '#ffa94d'};">${type}</span>
                    <span style="display: inline-block; width: 40px; color: ${actionColor}; font-weight: 600;">${action}</span>
                </div>
            `;
        };

        return `<div class="row"><div class="col-12">${suggestion.legs.map((leg, i) => formatLeg(leg, i)).join('')}</div></div>`;
    }

    /**
     * Display trading suggestion in the UI
     */
    displaySuggestion(suggestion) {
        if (!suggestion) {
            this.showAlert('warning', 'No suggestion generated under current market conditions.');
            return;
        }

        const container = document.getElementById('suggestionContainer');
        const content = document.getElementById('suggestionContent');
        const timestamp = document.getElementById('suggestionTimestamp');

        if (!container || !content || !timestamp) {
            console.error('Suggestion display elements not found');
            return;
        }

        const getOrderDescription = (suggestion) => {
            const baseName = TradingUtils.getStrategyName(suggestion.strategy_id);

            if (suggestion.strategy_id === 'senex_trident') {
                return `${suggestion.put_spread_quantity || 0} Put Spreads + ${suggestion.call_spread_quantity || 0} Call Spread`;
            } else if (suggestion.strategy_id === 'short_iron_condor' || suggestion.strategy_id === 'short_iron_butterfly') {
                return `${suggestion.put_spread_quantity || 1} Put Spread + ${suggestion.call_spread_quantity || 1} Call Spread`;
            }

            const totalQty = (suggestion.put_spread_quantity || 0) + (suggestion.call_spread_quantity || 0);
            if (totalQty > 1) {
                return `${totalQty} ${baseName}${totalQty > 1 ? 's' : ''}`;
            }

            return baseName;
        };

        // Update timestamp
        timestamp.textContent = new Date().toLocaleTimeString();

        // Build suggestion HTML (reusing pattern from strategy_view)
        content.innerHTML = `
            <div class="row">
                <div class="col-md-6">
                    <div class="card bg-secondary border-secondary mb-3">
                        <div class="card-header">
                            <h6 class="mb-0">Order Entry</h6>
                        </div>
                        <div class="card-body">
                            <table class="table table-dark table-sm mb-2">
                                <tr>
                                    <td>${TradingUtils.isDebitStrategy(suggestion) ? 'Entry Debit' : 'Entry Credit'} (per contract):</td>
                                    <td>
                                        <input type="number"
                                               class="form-control form-control-sm"
                                               id="entryCreditInput"
                                               value="${Math.abs(suggestion.total_mid_credit || suggestion.total_credit).toFixed(2)}"
                                               step="0.01"
                                               min="0.01"
                                               style="width: 80px; display: inline-block;">
                                    </td>
                                </tr>
                                <tr>
                                    <td>Bid | Mid | Ask:</td>
                                    <td id="bidAskSpread" class="text-info">Loading...</td>
                                </tr>
                            </table>
                        </div>
                    </div>
                    <div class="card bg-secondary border-secondary mb-3">
                        <div class="card-header">
                            <h6 class="mb-0">💰 P&L Metrics</h6>
                        </div>
                        <div class="card-body">
                            <table class="table table-dark table-sm mb-0">
                                <tr><td>Max Profit:</td><td id="maxProfitValue" class="text-success fw-bold">${TradingUtils.formatMaxProfit(suggestion.max_profit)}</td></tr>
                                <tr><td>Max Loss:</td><td id="maxLossValue" class="text-warning">$${TradingUtils.formatValue(suggestion.max_risk)}</td></tr>
                                ${suggestion.put_spread_quantity > 0 ? `
                                    <tr>
                                        <td>${TradingUtils.isDebitStrategy(suggestion) ? 'Put Debit:' : 'Put Credit:'}</td>
                                        <td>
                                            $${TradingUtils.formatValue(Math.abs(suggestion.put_spread_mid_credit || suggestion.put_spread_credit || 0) * 100)}
                                            × ${suggestion.put_spread_quantity}
                                            = $${TradingUtils.formatValue(Math.abs(suggestion.put_spread_mid_credit || suggestion.put_spread_credit || 0) * 100 * suggestion.put_spread_quantity)}
                                        </td>
                                    </tr>
                                ` : ''}
                                ${suggestion.call_spread_quantity > 0 ? `
                                    <tr>
                                        <td>${TradingUtils.isDebitStrategy(suggestion) ? 'Call Debit:' : 'Call Credit:'}</td>
                                        <td>
                                            $${TradingUtils.formatValue(Math.abs(suggestion.call_spread_mid_credit || suggestion.call_spread_credit || 0) * 100)}
                                            × ${suggestion.call_spread_quantity}
                                            = $${TradingUtils.formatValue(Math.abs(suggestion.call_spread_mid_credit || suggestion.call_spread_credit || 0) * 100 * suggestion.call_spread_quantity)}
                                        </td>
                                    </tr>
                                ` : ''}
                            </table>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card bg-secondary border-secondary mb-3">
                        <div class="card-header">
                            <h6 class="mb-0">Trade Details</h6>
                        </div>
                        <div class="card-body">
                            <table class="table table-dark table-sm mb-0">
                                <tr><td>Strategy:</td><td class="text-info fw-bold">${TradingUtils.getStrategyName(suggestion.strategy_id)}</td></tr>
                                <tr><td>Symbol:</td><td class="text-info fw-bold">${suggestion.underlying_symbol || '-'}</td></tr>
                                <tr><td>Current Price:</td><td>$${TradingUtils.formatValue(suggestion.underlying_price)}</td></tr>
                                <tr><td>IV Rank:</td><td>${TradingUtils.formatValue(suggestion.iv_rank)}%</td></tr>
                                <tr>
                                    <td>Total ${TradingUtils.isDebitStrategy(suggestion) ? 'Debit' : 'Credit'}:</td>
                                    <td class="${TradingUtils.isDebitStrategy(suggestion) ? 'text-warning' : 'text-success'} fw-bold">
                                        $${TradingUtils.formatValue(Math.abs(suggestion.total_mid_credit || suggestion.total_credit) * 100)}
                                    </td>
                                </tr>
                            </table>
                        </div>
                    </div>
                    <div class="card bg-secondary border-secondary mb-3">
                        <div class="card-header">
                            <h6 class="mb-0">Option Legs</h6>
                        </div>
                        <div class="card-body">
                            ${this.renderLegs(suggestion)}
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Update button data attributes
        const executeBtn = document.getElementById('executeBtn');
        const rejectBtn = document.getElementById('rejectBtn');
        if (executeBtn) executeBtn.dataset.suggestionId = suggestion.id;
        if (rejectBtn) rejectBtn.dataset.suggestionId = suggestion.id;

        // Add event listener for credit input changes
        const creditInput = document.getElementById('entryCreditInput');
        const totalValueSpan = document.getElementById('totalOrderValue');
        if (creditInput && totalValueSpan) {
            creditInput.addEventListener('input', function() {
                const newCredit = parseFloat(this.value) || 0;

                // Derive max_side from backend-calculated values (don't recalculate from strikes!)
                const oldCredit = Math.abs(parseFloat(suggestion.total_mid_credit || suggestion.total_credit));
                const oldTotalCredit = oldCredit * 100;
                const maxSide = parseFloat(suggestion.max_risk) + oldTotalCredit;

                // Calculate new totals
                const newTotalCredit = newCredit * 100;
                totalValueSpan.textContent = formatValue(newTotalCredit);

                // Update Max Profit (= total credit for credit spreads only)
                // For strategies with unlimited profit (null max_profit), don't update
                const maxProfitElem = document.getElementById('maxProfitValue');
                if (maxProfitElem && suggestion.max_profit !== null) {
                    maxProfitElem.textContent = `$${formatValue(newTotalCredit)}`;
                }

                // Update Max Loss (= max_side - new_total_credit)
                const maxLossElem = document.getElementById('maxLossValue');
                if (maxLossElem) {
                    const newMaxLoss = maxSide - newTotalCredit;
                    maxLossElem.textContent = `$${formatValue(newMaxLoss)}`;
                }
            });

            // Preserve trailing zeros on blur
            creditInput.addEventListener('blur', function() {
                if (this.value) {
                    this.value = parseFloat(this.value).toFixed(2);
                }
            });
        }

        // Use existing spread data from suggestion (already calculated by streaming services)
        this.displayBidAskFromSuggestion(suggestion);

        // Show container
        container.classList.remove('d-none');

        // Ensure action buttons are visible for valid suggestions (reuse existing references from line 461)
        if (executeBtn) executeBtn.style.display = '';
        if (rejectBtn) rejectBtn.style.display = '';

        this.showAlert('success', 'Trading suggestion generated successfully!');
    }

    /**
     * Handle order status updates from WebSocket
     */
    handleOrderStatusUpdate(data) {
        const { trade_id, status, filled_at, fill_price } = data;

        // Update trade row in table
        this.updateTradeRow(trade_id, { status, filled_at, fill_price });

        // Show notification
        this.showToast(`Trade ${trade_id} status: ${status}`,
                      status === 'filled' ? 'success' : 'info');

        // If current suggestion was executed, refresh page data
        if (this.config.suggestionId && data.suggestion_id === this.config.suggestionId) {
            this.refreshData();
        }
    }

    /**
     * Handle order fill notifications
     */
    handleOrderFill(data) {
        const { trade_id, fill_price, quantity } = data;

        this.showToast(
            `Order filled! Trade ${trade_id} - ${quantity} @ $${fill_price}`,
            'success'
        );

        // Refresh trades table and risk budget (positions changed)
        this.refreshTradesTable();
        this.loadRiskBudget(true); // Force refresh risk budget
    }

    /**
     * Handle account state updates from WebSocket
     */
    handleAccountStateUpdate(data) {
        window.logStreamInfo('Account state updated:', data);

        // Refresh risk budget with the new account data
        this.loadRiskBudget(true);

        // Show toast notification for significant changes
        if (data.data && data.data.buying_power !== undefined) {
            this.showToast('Account balance updated', 'info');
        }
    }

    /**
     * Handle stream status updates
     */
    handleStreamStatus(data) {
        window.logStreamInfo('Stream status update:', data);

        const { status, scope, id } = data.data || {};

        // Update status for account streams
        if (scope === 'account') {
            if (status === 'connected') {
                // Refresh risk budget when stream comes back online
                this.loadRiskBudget(true);
            } else if (status === 'disconnected' || status === 'degraded') {
                // Show stale data warning
                this.showRiskAlert('warning', 'Real-time data stream interrupted. Risk data may be stale.');
            }
        }
    }

    /**
     * Validate risk budget before trade execution using server-side API
     * @param {string} suggestionId - Suggestion ID to validate
     * @returns {Object} Validation result with valid flag and message
     */
    async validateRiskBudget(suggestionId) {
        try {
            const response = await fetch('/trading/api/validate-trade-risk/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    suggestion_id: suggestionId
                })
            });

            const result = await response.json();

            if (response.ok) {
                return result;
            } else {
                return {
                    valid: false,
                    message: result.message || 'Risk validation failed'
                };
            }

        } catch (error) {
            console.error('Risk validation error:', error);
            return {
                valid: false,
                message: `Risk validation failed: ${error.message}. Trade execution blocked for safety.`
            };
        }
    }

    /**
     * Trading action handlers
     */
    async approveSuggestion(event) {
        const suggestionId = event.target.dataset.suggestionId;
        if (!suggestionId) return;

        try {
            this.setButtonLoading(event.target, true);

            const response = await this.makeRequest('POST', `/api/trading/approve/${suggestionId}/`);

            if (response.success) {
                this.showAlert('success', 'Suggestion approved for execution');
                // Refresh page to show execute button
                setTimeout(() => window.location.reload(), 1000);
            } else {
                this.showAlert('danger', response.message || 'Failed to approve suggestion');
            }
        } catch (error) {
            this.showAlert('danger', `Error approving suggestion: ${error.message}`);
        } finally {
            this.setButtonLoading(event.target, false);
        }
    }

    async executeTrade(event) {
        const suggestionId = event.target.dataset.suggestionId;
        if (!suggestionId) return;

        // Validate risk budget before execution
        const riskValidation = await this.validateRiskBudget(suggestionId);
        if (!riskValidation.valid) {
            this.showAlert('danger', riskValidation.message);
            return;
        }

        // Build confirmation message with risk warning if present
        let confirmMessage = '<p>This will place <strong>real orders</strong> with your broker.</p>';
        if (riskValidation.warning) {
            confirmMessage = `
                <div class="alert alert-warning mb-3">
                    <strong>Risk Warning:</strong><br>
                    ${riskValidation.warning}
                </div>
                ${confirmMessage}
            `;
        }

        // Show modal confirmation
        window.showConfirmModal(
            'Execute Trade?',
            confirmMessage,
            async () => {
                // Execute trade after confirmation
                try {
                    this.setButtonLoading(event.target, true);
                    this.showProgress(0, 'Submitting order to broker...');

                    // Get the custom credit value from the input field
                    const creditInput = document.getElementById('entryCreditInput');
                    const customCredit = creditInput ? parseFloat(creditInput.value) : null;

                    const requestBody = {};
                    if (customCredit && customCredit > 0) {
                        requestBody.custom_credit = customCredit;
                    }

                    const response = await this.makeRequest('POST', `/trading/api/suggestions/${suggestionId}/execute/`, requestBody);

                    if (response.success) {
                        // Success - show result modal with trade details
                        this.hideProgress();
                        window.showResultModal('success',
                            'Trade Executed Successfully',
                            `<p>Your order has been submitted to the broker.</p>
                             <p class="mb-1"><strong>Trade ID:</strong> ${response.trade_id || 'Pending'}</p>
                             <p class="mb-0"><strong>Position ID:</strong> ${response.position_id}</p>
                             <p class="mb-0 text-muted mt-2"><small>Monitoring for fills...</small></p>`,
                            [{
                                text: 'View Positions',
                                class: 'btn-primary',
                                callback: () => window.location.href = '/trading/positions/'
                            }]
                        );

                        // Start monitoring this trade
                        if (response.trade_id) {
                            this.monitorTradeStatus(response.trade_id);
                        }
                    } else {
                        // Error - show error modal with specific guidance
                        this.hideProgress();
                        const errorConfig = this.getErrorModalConfig(response, suggestionId);
                        window.showResultModal('error',
                            errorConfig.title,
                            errorConfig.message,
                            errorConfig.actions
                        );
                    }
                } catch (error) {
                    // HTTP error - show generic error modal
                    this.hideProgress();
                    window.showResultModal('error',
                        'Execution Failed',
                        `<p>An error occurred while executing the trade:</p>
                         <p class="text-danger mb-0">${error.message}</p>
                         <p class="text-muted mt-2"><small>Please check your connection and try again.</small></p>`,
                        [{
                            text: 'Retry',
                            class: 'btn-warning',
                            callback: () => this.executeTrade(event)
                        }]
                    );
                } finally {
                    this.setButtonLoading(event.target, false);
                }
            },
            'Execute Trade',
            'btn-success'
        );
    }

    async rejectSuggestion(event) {
        const suggestionId = event.target.dataset.suggestionId;
        if (!suggestionId) return;

        const reason = await window.showPromptModal(
            'Reject Suggestion',
            'Reason for rejection (optional):',
            'Enter reason...',
            ''
        );
        if (reason === null) return; // User cancelled

        try {
            this.setButtonLoading(event.target, true);

            const response = await this.makeRequest('POST', `/trading/api/suggestions/${suggestionId}/reject/`, {
                reason: reason || 'User rejected'
            });

            if (response.success) {
                this.showAlert('info', 'Suggestion rejected');
                setTimeout(() => window.location.reload(), 1000);
            } else {
                this.showAlert('danger', response.message || 'Failed to reject suggestion');
            }
        } catch (error) {
            this.showAlert('danger', `Error rejecting suggestion: ${error.message}`);
        } finally {
            this.setButtonLoading(event.target, false);
        }
    }

    /**
     * Get error modal configuration based on error type
     * Maps backend error types to user-friendly modal content and actions
     * @param {Object} response - Error response from backend
     * @param {string} suggestionId - Suggestion ID for context
     * @returns {Object} Modal configuration {title, message, actions}
     */
    getErrorModalConfig(response, suggestionId) {
        const errorType = response.error_type || 'unknown';
        const errorMessage = response.error || 'An unknown error occurred';

        const configs = {
            stale_pricing: {
                title: '⏱️ Pricing Data Stale',
                message: `<p class="mb-3">${errorMessage}</p>
                         <p class="text-warning mb-0"><small><i class="bi bi-exclamation-triangle me-1"></i>
                         Market prices have moved since this suggestion was generated.
                         Fresh pricing is required for safe execution.</small></p>`,
                actions: [{
                    text: 'Generate Fresh Suggestion',
                    class: 'btn-primary',
                    callback: () => window.location.reload()  // Reload to generate new suggestion
                }]
            },
            no_account: {
                title: '🔗 No Trading Account',
                message: `<p class="mb-3">${errorMessage}</p>
                         <p class="text-info mb-0"><small><i class="bi bi-info-circle me-1"></i>
                         Connect your brokerage account to start trading.</small></p>`,
                actions: [{
                    text: 'Go to Settings',
                    class: 'btn-primary',
                    callback: () => window.location.href = '/accounts/settings/'
                }]
            },
            oauth_failed: {
                title: 'Authentication Failed',
                message: `<p class="mb-3">${errorMessage}</p>
                         <p class="text-warning mb-0"><small><i class="bi bi-exclamation-triangle me-1"></i>
                         Your broker connection may have expired. Reconnect to continue trading.</small></p>`,
                actions: [{
                    text: 'Reconnect Account',
                    class: 'btn-warning',
                    callback: () => window.location.href = '/accounts/settings/'
                }]
            },
            order_build_failed: {
                title: 'Order Construction Failed',
                message: `<p class="mb-3">${errorMessage}</p>
                         <p class="text-danger mb-0"><small><i class="bi bi-bug me-1"></i>
                         This is a system error. Please report this issue.</small></p>`,
                actions: [{
                    text: 'Contact Support',
                    class: 'btn-danger',
                    callback: () => window.location.href = 'mailto:support@example.com'
                }]
            },
            invalid_pricing: {
                title: '💰 Invalid Pricing',
                message: `<p class="mb-3">${errorMessage}</p>
                         <p class="text-warning mb-0"><small><i class="bi bi-exclamation-triangle me-1"></i>
                         The pricing data appears incorrect. Generate a new suggestion.</small></p>`,
                actions: [{
                    text: 'Generate New Suggestion',
                    class: 'btn-primary',
                    callback: () => window.location.reload()
                }]
            },
            order_placement_failed: {
                title: 'Order Placement Failed',
                message: `<p class="mb-3">${errorMessage}</p>
                         <p class="text-info mb-0"><small><i class="bi bi-arrow-clockwise me-1"></i>
                         This is usually temporary. Try again in a moment.</small></p>`,
                actions: [{
                    text: 'Retry Execution',
                    class: 'btn-warning',
                    callback: () => window.location.reload()
                }]
            }
        };

        // Return specific config or generic fallback
        return configs[errorType] || {
            title: 'Execution Error',
            message: `<p class="mb-3">${errorMessage}</p>
                     <p class="text-muted mb-0"><small>Please try again or contact support if the problem persists.</small></p>`,
            actions: [{
                text: 'Retry',
                class: 'btn-warning',
                callback: () => window.location.reload()
            }]
        };
    }

    /**
     * Monitor trade status for a specific trade
     */
    async monitorTradeStatus(tradeId) {
        let attempts = 0;
        const maxAttempts = 60; // Monitor for 5 minutes (5s intervals)

        const checkStatus = async () => {
            try {
                const response = await this.makeRequest('GET', `/trading/api/orders/${tradeId}/status/`);

                if (response.status === 'filled') {
                    this.showProgress(100, 'Trade filled successfully!');
                    setTimeout(() => this.hideProgress(), 3000);
                    return; // Stop monitoring
                }

                if (response.status === 'rejected' || response.status === 'cancelled') {
                    this.showAlert('warning', `Trade ${response.status}`);
                    this.hideProgress();
                    return; // Stop monitoring
                }

                // Continue monitoring
                attempts++;
                if (attempts < maxAttempts) {
                    const progress = Math.min(50 + (attempts / maxAttempts) * 40, 90);
                    this.showProgress(progress, `Monitoring order status... (${attempts}s)`);
                    setTimeout(checkStatus, 5000); // Check every 5 seconds
                } else {
                    this.hideProgress();
                    this.showAlert('info', 'Order monitoring timeout. Check trades table for updates.');
                }

            } catch (error) {
                console.error('Error checking trade status:', error);
                this.hideProgress();
            }
        };

        setTimeout(checkStatus, 5000); // Start checking after 5 seconds
    }

    /**
     * Utility functions
     */
    async makeRequest(method, url, data = null) {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.getCsrfToken()
            }
        };

        if (data) {
            options.body = JSON.stringify(data);
        }

        const response = await fetch(url, options);

        // Do not throw on non-2xx responses. Instead, parse the JSON body,
        // as the backend provides structured error details. This allows the
        // caller to inspect the error payload (e.g., for `error_type`).
        // If JSON parsing fails, return a structured error.
        try {
            return await response.json();
        } catch (e) {
            return {
                success: false,
                error: `Failed to parse server response (HTTP ${response.status}).`,
                error_type: 'network_error'
            };
        }
    }

    setButtonLoading(button, loading) {
        if (loading) {
            button.disabled = true;
            button.dataset.originalText = button.innerHTML;
            button.innerHTML = '<i class="bi bi-hourglass-split"></i> Processing...';
        } else {
            button.disabled = false;
            if (button.dataset.originalText) {
                button.innerHTML = button.dataset.originalText;
            }
        }
    }

    showAlert(type, message) {
        const alertDiv = document.getElementById('statusAlert');
        if (alertDiv) {
            alertDiv.className = `alert alert-${escapeHtml(type)} fade show`;
            alertDiv.textContent = message;
            alertDiv.classList.remove('d-none');

            // Auto-hide after 5 seconds for non-error messages
            if (type !== 'danger') {
                setTimeout(() => alertDiv.classList.add('d-none'), 5000);
            }
        }
    }

    showProgress(percent, text) {
        const container = document.getElementById('progressContainer');
        const bar = document.getElementById('progressBar');
        const textEl = document.getElementById('progressText');

        if (container && bar && textEl) {
            container.classList.remove('d-none');
            bar.style.width = `${percent}%`;
            textEl.textContent = text;
        }
    }

    hideProgress() {
        const container = document.getElementById('progressContainer');
        if (container) {
            container.classList.add('d-none');
        }
    }

    showToast(message, type = 'info') {
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${type} border-0 position-fixed bottom-0 start-0 m-3`;
        toast.style.zIndex = '1055';
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        document.body.appendChild(toast);

        // Initialize and show toast
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();

        // Remove from DOM after hiding
        toast.addEventListener('hidden.bs.toast', () => {
            document.body.removeChild(toast);
        });
    }


    updateStatusBadges() {
        // Update status badges based on trade status
        const badges = document.querySelectorAll('.status-badge');
        badges.forEach(badge => {
            const status = badge.dataset.status;
            badge.className = `badge status-badge ${this.getStatusClass(status)}`;
        });
    }

    getStatusClass(status) {
        const statusClasses = {
            'pending': 'bg-warning',
            'approved': 'bg-info',
            'submitted': 'bg-primary',
            'filled': 'bg-success',
            'rejected': 'bg-danger',
            'cancelled': 'bg-secondary',
            'partial': 'bg-warning'
        };
        return statusClasses[status] || 'bg-secondary';
    }

    updateTradeRow(tradeId, data) {
        const row = document.querySelector(`tr[data-trade-id="${tradeId}"]`);
        if (!row) return;

        // Update status badge
        const statusBadge = row.querySelector('.status-badge');
        if (statusBadge && data.status) {
            statusBadge.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);
            statusBadge.className = `badge status-badge ${this.getStatusClass(data.status)}`;
        }

        // Update other fields as needed
        if (data.filled_at) {
            // Could update a filled_at column if it exists
        }
    }

    refreshData() {
        window.location.reload();
    }

    async refreshTradesTable() {
        // This could be implemented to refresh just the trades table via AJAX
        // For now, we'll use a full page refresh
        this.refreshData();
    }

    /**
     * Display bid/ask spread using real pricing data from streaming services
     */
    displayBidAskFromSuggestion(suggestion) {
        const bidAskElement = document.getElementById('bidAskSpread');
        if (!bidAskElement) return;

        // Use real mid-price credit if available (use absolute values for debit spreads)
        const naturalCredit = suggestion.total_credit ? Math.abs(parseFloat(suggestion.total_credit)) : null;
        const midCredit = suggestion.total_mid_credit ? Math.abs(parseFloat(suggestion.total_mid_credit)) : null;

        if (midCredit && naturalCredit) {
            // Calculate spread width from the difference between natural and mid prices
            const spreadWidth = Math.abs(midCredit - naturalCredit) * 2; // Natural is ~half spread below mid
            const bid = midCredit - (spreadWidth / 2);
            const ask = midCredit + (spreadWidth / 2);

            bidAskElement.innerHTML = `
                <span class="text-warning">$${bid.toFixed(2)}</span> |
                <span class="text-info fw-bold">$${midCredit.toFixed(2)}</span> |
                <span class="text-success">$${ask.toFixed(2)}</span>
                <small class="text-muted ms-2">(Bid-Ask Spread: $${spreadWidth.toFixed(2)})</small>
            `;
        } else if (naturalCredit) {
            // Fallback to conservative estimate for backward compatibility
            bidAskElement.innerHTML = `
                <span class="text-warning">$${naturalCredit.toFixed(2)}</span> |
                <span class="text-info fw-bold">$${(naturalCredit + 0.025).toFixed(2)}</span> |
                <span class="text-success">$${(naturalCredit + 0.05).toFixed(2)}</span>
                <small class="text-muted ms-2">(Conservative est.)</small>
            `;
        } else {
            bidAskElement.innerHTML = '<span class="text-info">Loading pricing data...</span>';
        }
    }

    /**
     * Generate suggestion using Auto Mode (system picks best strategy)
     * @param {string} symbol - Underlying symbol
     */
    async generateAutoSuggestion(symbol) {
        this.showLoadingState('Auto');
        try {
            const response = await fetch('/trading/api/suggestions/auto/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ symbol })
            });

            const data = await response.json();

            if (data.success && data.strategy) {
                this.hideLoadingState();
                window.logStreamInfo('Auto suggestion response:', {
                    strategy: data.strategy,
                    has_suggestion: !!data.suggestion,
                    suggestion_data: data.suggestion,
                    explanation: data.explanation
                });

                // Display market conditions and strategy scores
                this.displayMarketConditions(data.market_conditions);
                this.displayStrategyScores(data.strategy_scores);

                // ALWAYS display analysis (score + confidence + reasoning)
                this.displayAnalysis(data);

                // Show confidence badge
                this.displayConfidenceBadge(data.confidence);

                // Show the suggestion using existing method
                if (data.suggestion) {
                    window.logStreamInfo('Displaying suggestion with data:', data.suggestion);
                    this.displaySuggestion(data.suggestion);
                } else {
                    console.warn('No suggestion data in response - analysis shows why');

                    // Hide suggestion container and action buttons when there's no suggestion to execute
                    const suggestionContainer = document.getElementById('suggestionContainer');
                    if (suggestionContainer) suggestionContainer.classList.add('d-none');

                    const executeBtn = document.getElementById('executeBtn');
                    const rejectBtn = document.getElementById('rejectBtn');
                    if (executeBtn) executeBtn.style.display = 'none';
                    if (rejectBtn) rejectBtn.style.display = 'none';
                }
            } else {
                console.warn('Auto suggestion failed or no strategy selected:', data);
                this.hideLoadingState(true);
                // No suitable strategy or hard stop - analysis panel shows why
                this.displayMarketConditions(data.market_conditions);
                this.displayAnalysis(data);
            }
        } catch (error) {
            console.error('Error generating auto suggestion:', error);
            this.showAlert('danger', 'Failed to generate suggestion: ' + error.message);
            this.hideLoadingState(true);
        }
    }

    /**
     * Generate suggestion using Forced Mode (manual strategy selection)
     * @param {string} symbol - Underlying symbol
     * @param {string} strategy - Strategy to force
     */
    async generateForcedSuggestion(symbol, strategy) {
        this.showLoadingState(strategy);
        try {
            const response = await fetch('/trading/api/suggestions/forced/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': window.getCsrfToken(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ symbol, strategy })
            });

            const data = await response.json();

            if (data.success) {
                this.hideLoadingState();
                window.logStreamInfo('Forced suggestion response:', {
                    strategy: strategy,
                    has_suggestion: !!data.suggestion,
                    suggestion_data: data.suggestion,
                    explanation: data.explanation
                });

                // Display market conditions
                this.displayMarketConditions(data.market_conditions);

                // ALWAYS display analysis (score + confidence + reasoning)
                this.displayAnalysis(data);

                // Show confidence badge
                this.displayConfidenceBadge(data.confidence);

                // Show the suggestion
                if (data.suggestion) {
                    window.logStreamInfo('Displaying forced suggestion with data:', data.suggestion);
                    this.displaySuggestion(data.suggestion);
                } else {
                    console.warn('No suggestion data in forced response - analysis shows why');

                    // Hide suggestion container and action buttons when there's no suggestion to execute
                    const suggestionContainer = document.getElementById('suggestionContainer');
                    if (suggestionContainer) suggestionContainer.classList.add('d-none');

                    const executeBtn = document.getElementById('executeBtn');
                    const rejectBtn = document.getElementById('rejectBtn');
                    if (executeBtn) executeBtn.style.display = 'none';
                    if (rejectBtn) rejectBtn.style.display = 'none';
                }
            } else {
                console.error('Forced suggestion error:', data);
                this.showAlert('danger', data.error || 'Failed to generate suggestion');
                this.hideLoadingState(true); // Hide with error state
            }
        } catch (error) {
            console.error('Error generating forced suggestion:', error);
            this.showAlert('danger', 'Failed to generate suggestion: ' + error.message);
            this.hideLoadingState(true); // Hide with error state
        }
    }

    /**
     * Display market conditions panel (compact inline badges)
     * @param {Object} conditions - Market conditions data
     */
    displayMarketConditions(conditions) {
        const panel = document.getElementById('marketConditionsPanel');
        const card = document.getElementById('marketConditionsCard');

        if (!panel || !conditions) return;

        // Compact inline badge display (single line)
        const html = `
            <div class="d-flex flex-wrap gap-2 align-items-center">
                <span class="badge ${this.getDirectionBadgeClass(conditions.direction)} px-3 py-2">
                    Direction: ${conditions.direction || 'N/A'}
                </span>
                <span class="badge ${this.getIVRankColorClass(conditions.iv_rank)} px-3 py-2">
                    IV Rank: ${(conditions.iv_rank || 0).toFixed(1)}%
                </span>
                <span class="badge ${this.getVolatilityColorClass(conditions.volatility)} px-3 py-2">
                    Vol: ${conditions.volatility ? conditions.volatility.toFixed(1) + '%' : 'N/A'}
                </span>
                <span class="badge ${conditions.range_bound ? 'bg-warning text-dark' : 'bg-success'} px-3 py-2">
                    Range: ${conditions.range_bound ? 'Yes' : 'No'}
                </span>
                <span class="badge ${this.getStressColorClass(conditions.stress_level)} px-3 py-2">
                    Stress: ${(conditions.stress_level || 0).toFixed(0)}/100
                </span>
            </div>
        `;

        panel.innerHTML = html;
        if (card) card.style.display = 'block';  // Show the card
    }

    /**
     * Display strategy scores comparison (Auto mode only)
     * @param {Object} scores - Strategy scores object
     */
    displayStrategyScores(scores) {
        const panel = document.getElementById('strategyScoresPanel');
        const section = document.getElementById('strategyComparisonSection');

        if (!panel || !scores) {
            if (section) section.style.display = 'none';
            return;
        }

        // Show the section when scores are available
        if (section) section.style.display = '';

        // Convert scores object to sorted array
        const sortedScores = Object.entries(scores).sort((a, b) => b[1].score - a[1].score);

        const html = `
            <table class="table table-dark table-sm mb-0">
                <thead>
                    <tr>
                        <th>Strategy</th>
                        <th style="width: 200px;">Score</th>
                        <th>Confidence</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${sortedScores.map(([name, data], index) => {
                        const isSelected = index === 0;
                        const displayName = name.replace(/_/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                        const confidence = this.scoreToConfidence(data.score);

                        return `
                            <tr class="${isSelected ? 'table-success' : ''}">
                                <td>${displayName}</td>
                                <td>
                                    <div class="position-relative">
                                        <div class="progress" style="height: 25px;">
                                            <div class="progress-bar ${this.getScoreColorClass(data.score)}"
                                                 style="width: ${data.score}%"></div>
                                        </div>
                                        <div class="position-absolute top-50 start-50 translate-middle fw-bold ${this.getScoreTextColorClass(data.score)}"
                                             style="text-shadow: 1px 1px 2px rgba(0,0,0,0.8), -1px -1px 2px rgba(0,0,0,0.8);">
                                            ${data.score.toFixed(1)}
                                        </div>
                                    </div>
                                </td>
                                <td><span class="badge ${this.getConfidenceBadgeClass(confidence)}">${confidence}</span></td>
                                <td>${isSelected ? '[OK] Selected' : ''}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        `;

        panel.innerHTML = html;
    }

    /**
     * Display suggestion analysis in separate box
     * @param {Object} data - Response data with explanation, confidence, strategy_scores
     */
    displayAnalysis(data) {
        const analysisContainer = document.getElementById('suggestionAnalysisContainer');
        const analysisContent = document.getElementById('suggestionAnalysisContent');
        const analysisBadge = document.getElementById('analysisConfidenceBadge');

        if (!analysisContainer || !analysisContent) return;

        // Get strategy score and explanation
        const strategyName = data.strategy || 'Unknown';
        const explanation = data.explanation || {};
        const confidence = data.confidence || 'N/A';

        // Get score from strategy_scores (auto mode) or explanation.confidence (forced mode)
        let score = 0;
        if (data.strategy_scores && data.strategy_scores[strategyName]) {
            score = data.strategy_scores[strategyName].score || 0;
        } else if (explanation && explanation.confidence && explanation.confidence.score !== undefined) {
            score = explanation.confidence.score;
        }

        // Update confidence badge
        if (analysisBadge) {
            analysisBadge.textContent = confidence;
            analysisBadge.className = `badge ${this.getConfidenceBadgeClass(confidence)}`;
        }

        // Build analysis HTML
        let html = `
            <div class="row g-3">
                <div class="col-md-4">
                    <div class="text-center">
                        <div class="text-muted small mb-1">Strategy Score</div>
                        <div class="fs-4 fw-bold ${this.getScoreColorClass(score)}">${score.toFixed(1)}</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="text-center">
                        <div class="text-muted small mb-1">Confidence</div>
                        <div class="fs-5">
                            <span class="badge ${this.getConfidenceBadgeClass(confidence)} px-3 py-2">${confidence}</span>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="text-center">
                        <div class="text-muted small mb-1">Strategy</div>
                        <div class="fs-6 fw-bold">${strategyName.replace(/_/g, ' ').toUpperCase()}</div>
                    </div>
                </div>
            </div>
        `;

        // Add detailed explanation/reasoning if available
        if (explanation && typeof explanation === 'object' && !Array.isArray(explanation)) {
            const explanationHTML = this.renderExplanationHTML(explanation);
            html += `<hr class="my-3">${explanationHTML}`;
        }

        analysisContent.innerHTML = html;
        analysisContainer.classList.remove('d-none');
    }


    /**
     * Render explanation HTML from structured data
     * @param {Object} data - Structured explanation data
     * @returns {string} HTML content
     */
    renderExplanationHTML(data) {
        const confidenceLevel = data.confidence ? data.confidence.level : null;
        const scenarioClass = this.getScenarioClass(data.type, confidenceLevel);
        const scenarioIcon = this.getScenarioIcon(data.type, confidenceLevel);

        let html = `
            <div class="alert ${scenarioClass} mb-0">
                <div class="d-flex align-items-center justify-content-between mb-3">
                    <div class="d-flex align-items-center">
                        <i class="bi ${scenarioIcon} fs-5 me-2"></i>
                        <h6 class="mb-0">${data.title}</h6>
                    </div>
                    ${data.confidence ? `
                        <span class="badge ${this.getConfidenceBadgeClass(data.confidence.level)}">
                            ${data.confidence.level} (${data.confidence.score})
                        </span>
                    ` : ''}
                </div>
        `;

        // Add consolidated warnings/conditions alert for failed or unfavorable strategies
        if (data.warnings && data.warnings.length > 0) {
            // Check title to distinguish true failures from generated-but-not-recommended
            const isTrueFailure = data.title && data.title.includes('Cannot Generate');
            const warningClass = isTrueFailure ? 'alert-danger' : 'alert-warning';
            const iconClass = isTrueFailure ? 'bi-x-circle-fill' : 'bi-exclamation-triangle';
            const headingText = isTrueFailure ? 'Strategy Cannot Be Generated' : 'Not Recommended - Low Confidence';

            html += `
                <div class="alert ${warningClass} alert-sm mb-3">
                    <div class="d-flex align-items-start">
                        <i class="bi ${iconClass} me-2 flex-shrink-0"></i>
                        <div class="flex-grow-1">
                            <h6 class="alert-heading mb-1">${headingText}</h6>
                            <div class="small">
                                <strong>Reasons:</strong>
                                <ul class="mb-1 ps-3">
                                    ${data.warnings.map(w => `<li>${w}</li>`).join('')}
                                </ul>
            `;

            // Include conditions if present
            if (data.conditions && data.conditions.length > 0) {
                html += `
                                <strong>Market Conditions:</strong>
                                <ul class="mb-0 ps-3">
                                    ${data.conditions.map(c => `<li class="text-muted">${c}</li>`).join('')}
                                </ul>
                `;
            }

            html += `
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        // Render based on type
        if (data.type === 'auto' && data.scores) {
            html += this.renderAutoModeScores(data.scores);
        } else if (data.type === 'forced' && data.conditions) {
            // Skip conditions if already shown in consolidated alert
            if (!data.warnings || data.warnings.length === 0) {
                html += this.renderForcedModeConditions(data.conditions);
            }
        } else if (data.type === 'no_trade' && data.hard_stops) {
            html += this.renderNoTradeStops(data.hard_stops, data.market_status);
        } else if (data.type === 'low_scores' && data.scores) {
            html += this.renderLowScores(data.scores);
        }

        // Add market conditions
        if (data.market) {
            html += this.renderMarketConditions(data.market);
        }

        html += `</div>`;
        return html;
    }

    /**
     * Render auto mode strategy scores table
     */
    renderAutoModeScores(scores) {
        return `
            <div class="mb-3">
                <h6 class="text-muted mb-2">Strategy Comparison:</h6>
                <div class="table-responsive">
                    <table class="table table-dark table-sm table-hover mb-0">
                        <thead>
                            <tr>
                                <th>Strategy</th>
                                <th>Score</th>
                                <th>Analysis</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${scores.map(s => `
                                <tr class="${s.selected ? 'table-success' : ''}">
                                    <td>
                                        ${s.selected ? '<i class="bi bi-check-circle-fill text-success me-1"></i>' : ''}
                                        <strong>${s.strategy}</strong>
                                    </td>
                                    <td><span class="badge bg-secondary">${s.score}</span></td>
                                    <td><small>${s.reasons.join(' • ')}</small></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    /**
     * Render forced mode conditions
     */
    renderForcedModeConditions(conditions) {
        if (!conditions || conditions.length === 0) return '';

        return `
            <div class="mb-3">
                <h6 class="text-muted mb-2">Conditions:</h6>
                <ul class="mb-0">
                    ${conditions.map(c => `<li>${c}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    /**
     * Render no-trade hard stops
     */
    renderNoTradeStops(hardStops, marketStatus) {
        let html = `
            <div class="mb-3">
                <h6 class="text-danger mb-2">Hard Stops Active:</h6>
                <ul class="mb-0">
                    ${hardStops.map(s => `<li>${s}</li>`).join('')}
                </ul>
            </div>
        `;

        if (marketStatus) {
            html += `
                <div class="mb-3">
                    <h6 class="text-muted mb-2">Market Status:</h6>
                    <div class="small">
                        <div>Last Update: ${marketStatus.last_update}</div>
                        <div>Data Stale: ${marketStatus.data_stale ? 'Yes' : 'No'}</div>
                    </div>
                </div>
            `;
        }

        return html;
    }

    /**
     * Render low scores explanation
     */
    renderLowScores(scores) {
        return `
            <div class="mb-3">
                <h6 class="text-warning mb-2">All Strategies Below Threshold:</h6>
                <div class="table-responsive">
                    <table class="table table-dark table-sm mb-0">
                        <tbody>
                            ${scores.map(s => `
                                <tr>
                                    <td><strong>${s.strategy}</strong></td>
                                    <td><span class="badge bg-secondary">${s.score}</span></td>
                                    <td><small>${s.reasons.join(' • ')}</small></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    /**
     * Render market conditions grid
     */
    renderMarketConditions(market) {
        return `
            <div class="mt-3 pt-3 border-top border-secondary">
                <h6 class="text-muted mb-2">Market Snapshot:</h6>
                <div class="row g-2 small">
                    <div class="col-6 col-md-3">
                        <div><span class="text-muted">Direction:</span></div>
                        <div><strong>${market.direction}</strong></div>
                    </div>
                    <div class="col-6 col-md-3">
                        <div><span class="text-muted">IV Rank:</span></div>
                        <div><strong>${market.iv_rank}%</strong></div>
                    </div>
                    ${market.volatility !== undefined ? `
                        <div class="col-6 col-md-3">
                            <div><span class="text-muted">Volatility:</span></div>
                            <div><strong>${market.volatility}%</strong></div>
                        </div>
                    ` : ''}
                    ${market.range_bound !== undefined ? `
                        <div class="col-6 col-md-3">
                            <div><span class="text-muted">Range Bound:</span></div>
                            <div><strong>${market.range_bound ? 'Yes' : 'No'}</strong></div>
                        </div>
                    ` : ''}
                    ${market.stress !== undefined ? `
                        <div class="col-6 col-md-3">
                            <div><span class="text-muted">Market Stress:</span></div>
                            <div><strong>${market.stress}/100</strong></div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    /**
     * Get alert class based on scenario type and confidence
     * @param {string} type - Scenario type (auto, forced, no_trade, low_scores)
     * @param {string} confidence - Confidence level (HIGH, MEDIUM, LOW, VERY LOW)
     */
    getScenarioClass(type, confidence) {
        // For forced mode, use confidence to determine color instead of always warning
        if (type === 'forced') {
            if (confidence === 'HIGH') return 'alert-success';      // Green for high confidence
            if (confidence === 'MEDIUM') return 'alert-info';       // Blue for medium confidence
            return 'alert-warning';  // Yellow only for LOW/VERY LOW confidence
        }

        // Original logic for other types
        const classes = {
            'auto': 'alert-success',
            'no_trade': 'alert-danger',
            'low_scores': 'alert-warning'
        };
        return classes[type] || 'alert-info';
    }

    /**
     * Get icon based on scenario type and confidence
     * @param {string} type - Scenario type (auto, forced, no_trade, low_scores)
     * @param {string} confidence - Confidence level (HIGH, MEDIUM, LOW, VERY LOW)
     */
    getScenarioIcon(type, confidence) {
        // For forced mode, use confidence to determine icon instead of always warning
        if (type === 'forced') {
            if (confidence === 'HIGH') return 'bi-check-circle-fill';           // Check for high confidence
            if (confidence === 'MEDIUM') return 'bi-info-circle-fill';          // ℹ Info for medium confidence
            return 'bi-exclamation-triangle-fill';  // Triangle only for LOW/VERY LOW confidence
        }

        // Original logic for other types
        const icons = {
            'auto': 'bi-check-circle-fill',
            'no_trade': 'bi-x-circle-fill',
            'low_scores': 'bi-exclamation-triangle-fill'
        };
        return icons[type] || 'bi-info-circle-fill';
    }

    /**
     * Display confidence badge in suggestion header
     * @param {string} confidence - HIGH, MEDIUM, LOW, VERY LOW
     */
    displayConfidenceBadge(confidence) {
        const badge = document.getElementById('confidenceBadge');

        if (!badge || !confidence) return;

        badge.textContent = confidence + ' Confidence';
        badge.className = `badge ${this.getConfidenceBadgeClass(confidence)}`;
        badge.style.display = '';
    }


    // Helper methods for styling
    scoreToConfidence(score) {
        if (score >= 80) return 'HIGH';
        if (score >= 60) return 'MEDIUM';
        if (score >= 40) return 'LOW';
        return 'VERY LOW';
    }

    getConfidenceBadgeClass(confidence) {
        const classes = {
            'HIGH': 'bg-success',
            'MEDIUM': 'bg-info',
            'LOW': 'bg-warning',
            'VERY LOW': 'bg-danger'
        };
        return classes[confidence] || 'bg-secondary';
    }

    getScoreColorClass(score) {
        if (score >= 70) return 'bg-success';
        if (score >= 50) return 'bg-info';
        if (score >= 30) return 'bg-warning';
        return 'bg-danger';
    }

    getScoreTextColorClass(score) {
        // Use dark text on warning (yellow) background for contrast
        // This ensures WCAG AA compliance for scores in 30-49 range
        if (score >= 30 && score < 50) return 'text-dark';
        // Use white text on all other backgrounds (green, blue, red)
        return 'text-white';
    }

    getDirectionBadgeClass(direction) {
        const classes = {
            'bullish': 'bg-success',
            'bearish': 'bg-danger',
            'neutral': 'bg-info'
        };
        return classes[direction?.toLowerCase()] || 'bg-secondary';
    }

    getIVRankColorClass(ivRank) {
        if (ivRank >= 70) return 'bg-success';
        if (ivRank >= 40) return 'bg-info';
        return 'bg-warning';
    }

    getVolatilityColorClass(volatility) {
        if (volatility >= 40) return 'bg-success';
        if (volatility >= 20) return 'bg-info';
        return 'bg-warning';
    }

    getStressColorClass(stress) {
        if (stress >= 70) return 'bg-danger';
        if (stress >= 40) return 'bg-warning';
        return 'bg-success';
    }
}

// Global trade details function for modal
window.showTradeDetails = async function(tradeId) {
    const modal = new bootstrap.Modal(document.getElementById('tradeDetailsModal'));
    const body = document.getElementById('tradeDetailsBody');

    body.innerHTML = '<div class="text-center"><i class="bi bi-hourglass-split"></i> Loading...</div>';
    modal.show();

    try {
        // This would fetch detailed trade info
        // For now, show placeholder
        const safeTradeId = escapeHtml(String(tradeId));
        body.innerHTML = `
            <p><strong>Trade ID:</strong> ${safeTradeId}</p>
            <p><em>Detailed trade information will be implemented in future updates.</em></p>
        `;
    } catch (error) {
        const safeError = escapeHtml(error.message);
        body.innerHTML = `<div class="alert alert-danger">Error loading trade details: ${safeError}</div>`;
    }
};

// Create global instance
window.TradingInterface = new TradingInterface();

// Add cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (window.TradingInterface && window.TradingInterface.destroy) {
        window.TradingInterface.destroy();
    }
});
