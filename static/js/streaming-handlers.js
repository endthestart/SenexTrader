/**
 * Reusable Streaming Data Handlers
 * For processing WebSocket messages across different pages
 */
class StreamingHandlers {
    constructor(config = {}) {
        // Element ID mappings for different pages
        this.elements = {
            // QQQ Price elements
            qqqPrice: config.qqqPrice || 'qqq-price',
            qqqChange: config.qqqChange || 'qqq-change',

            // Account balance elements
            accountBalance: config.accountBalance || 'account-balance',
            balanceUpdateTime: config.balanceUpdateTime || 'balance-update-time',

            // IV data elements
            ivRank: config.ivRank || null,
            ivPercentile: config.ivPercentile || null,
            currentIv: config.currentIv || null,

            // Streaming status elements
            streamStatus: config.streamStatus || 'stream-status',
            latencyDisplay: config.latencyDisplay || 'latency-display'
        };

        // State
        this.prevDayClose = this.loadPrevDayClose();  // Load from sessionStorage if available
        this.lastQQQPrice = null;

        window.logStreamDebug('StreamingHandlers initialized with prevDayClose:', this.prevDayClose);
    }

    /**
     * Handle quote updates from WebSocket
     */
    handleQuoteUpdate(data) {
        if (data.symbol === 'QQQ') {
            // Extract previous_close from quote if we don't have it yet
            if (data.previous_close && !this.prevDayClose) {
                this.prevDayClose = parseFloat(data.previous_close);
                this.savePrevDayClose(this.prevDayClose);
                window.logStreamDebug('Got prevDayClose from quote:', this.prevDayClose);
            }

            // Calculate mid price as current (accurate during all market conditions)
            const midPrice = (data.bid && data.ask) ?
                            (data.bid + data.ask) / 2 :
                            data.bid || data.ask || data.last || 0;


            if (midPrice > 0) {
                this.updateQQQPrice(midPrice, this.lastQQQPrice);
                this.lastQQQPrice = midPrice;

                // Update additional QQQ data elements
                this.updateQQQDetails(data);

                // Update timestamp
                this.updateTimestamp(this.elements.balanceUpdateTime, data.timestamp);
            }
        }
    }

    /**
     * Handle summary updates (for IV data)
     */
    handleSummaryUpdate(data) {
        if (data.symbol === 'QQQ' && data.prev_day_close !== null && data.prev_day_close !== undefined) {
            const oldPrevDayClose = this.prevDayClose;
            this.prevDayClose = data.prev_day_close;
            this.savePrevDayClose(this.prevDayClose);  // Persist to sessionStorage

            // If we have a current price, update the daily change display
            const priceElement = document.getElementById(this.elements.qqqPrice);
            if (priceElement && priceElement.textContent !== '--') {
                const currentPriceText = priceElement.textContent.replace('$', '');
                const currentPrice = parseFloat(currentPriceText);
                if (!isNaN(currentPrice)) {
                    this.updateQQQPrice(currentPrice, this.lastQQQPrice);
                }
            }
        } else {
            if (data.symbol !== 'QQQ') {
                window.logStreamDebug('Summary update for non-QQQ symbol:', data.symbol);
            } else if (data.prev_day_close === null || data.prev_day_close === undefined) {
                console.warn('QQQ Summary update received but prev_day_close is null/undefined');
            }
        }
    }

    /**
     * Handle error messages
     */
    handleError(data) {
        console.error('Streaming error:', data.message);
        this.updateStreamStatus('Error', 'danger');
    }

    /**
     * Handle heartbeat pong responses
     */
    handlePong(data) {
        // Left intentionally blank; status UI reflects heartbeat separately
    }

    /**
     * Update QQQ price display with change calculation
     */
    updateQQQPrice(price, previousPrice) {
        const priceElement = document.getElementById(this.elements.qqqPrice);
        const changeElement = document.getElementById(this.elements.qqqChange);

        if (priceElement && price !== null && price !== undefined) {
            // Show the data content and hide unavailable message
            this.toggleDataDisplay('qqq', true);

            priceElement.textContent = '$' + Number(price).toFixed(2);

            if (changeElement && this.prevDayClose !== null && this.prevDayClose !== undefined) {
                // Calculate daily change from previous day's close
                const dailyChange = price - this.prevDayClose;
                const dailyChangePercent = (dailyChange / this.prevDayClose) * 100;

                const changeText = (dailyChange >= 0 ? '+' : '') + dailyChange.toFixed(2) +
                                  ' (' + (dailyChangePercent >= 0 ? '+' : '') + dailyChangePercent.toFixed(2) + '%)';

                changeElement.textContent = changeText;
                changeElement.className = dailyChange >= 0 ? 'text-success' : 'text-danger';
            } else if (changeElement) {
                // Fallback to session change if prevDayClose not available yet
                if (previousPrice !== null) {
                    const change = price - previousPrice;
                    const changeText = (change >= 0 ? '+' : '') + change.toFixed(2) + ' (session)';
                    changeElement.textContent = changeText;
                    changeElement.className = change >= 0 ? 'text-success' : 'text-danger';
                } else {
                    changeElement.textContent = '';
                }
            }
        } else {
            // No valid price data, show unavailable message
            this.toggleDataDisplay('qqq', false);
        }
    }

    /**
     * Update QQQ additional details (bid, ask, volume, source)
     */
    updateQQQDetails(data) {
        // Update bid
        const bidElement = document.getElementById('qqq-bid');
        if (bidElement && data.bid !== null && data.bid !== undefined) {
            bidElement.textContent = '$' + Number(data.bid).toFixed(2);
        }

        // Update ask
        const askElement = document.getElementById('qqq-ask');
        if (askElement && data.ask !== null && data.ask !== undefined) {
            askElement.textContent = '$' + Number(data.ask).toFixed(2);
        }

        // Update volume
        const volumeElement = document.getElementById('qqq-volume');
        if (volumeElement && data.volume !== null && data.volume !== undefined) {
            volumeElement.textContent = Number(data.volume).toLocaleString();
        }

        // Update source
        const sourceElement = document.getElementById('qqq-source');
        if (sourceElement) {
            sourceElement.textContent = 'streaming';
        }
    }

    /**
     * Update account balance display
     */
    updateAccountBalance(balance) {
        const balanceElement = document.getElementById(this.elements.accountBalance);
        if (balanceElement && balance !== null && balance !== undefined) {
            // Check privacy mode
            if (window.PRIVACY_MODE) {
                balanceElement.innerHTML = '<span class="text-muted">••••••</span>';
            } else {
                balanceElement.textContent = '$' + Number(balance).toLocaleString('en-US', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                });
            }
        }
    }

    /**
     * Update timestamp display
     */
    updateTimestamp(elementId, timestamp) {
        if (!elementId) return;

        const timeElement = document.getElementById(elementId);
        if (timeElement && timestamp) {
            const date = new Date(timestamp);
            // Check if date is valid before displaying
            if (!isNaN(date.getTime())) {
                const timestampStr = date.toLocaleTimeString();
                timeElement.textContent = `(${timestampStr})`;
            } else {
                timeElement.textContent = '';  // Clear invalid date display
            }
        }
    }

    /**
     * Update stream status display
     */
    updateStreamStatus(status, type) {
        const statusElement = document.getElementById(this.elements.streamStatus);
        if (statusElement) {
            statusElement.textContent = status;
            statusElement.className = `badge bg-${type} ms-2`;
        }
    }

    /**
     * Toggle data display between content and unavailable states
     * Standardized method for all dashboard cards
     */
    toggleDataDisplay(dataPrefix, hasData) {
        const contentElement = document.getElementById(`${dataPrefix}-data-content`);
        const unavailableElement = document.getElementById(`${dataPrefix}-data-unavailable`);

        if (contentElement && unavailableElement) {
            if (hasData) {
                contentElement.style.display = 'block';
                unavailableElement.style.display = 'none';
            } else {
                contentElement.style.display = 'none';
                unavailableElement.style.display = 'block';
            }
        } else {
            console.warn(`toggleDataDisplay: Missing elements for ${dataPrefix}`);
        }
    }

    /**
     * Main message router - call this from WebSocket onmessage
     */
    handleMessage(data) {
        switch (data.type) {
            case 'quote_update':
                this.handleQuoteUpdate(data);
                break;
            case 'summary_update':
                this.handleSummaryUpdate(data);
                break;
            case 'error':
                this.handleError(data);
                break;
            case 'pong':
                this.handlePong(data);
                break;
            default:
                window.logStreamDebug('Unhandled message type:', data.type);
        }
    }

    /**
     * Load previous day close from sessionStorage
     * Only returns value if it's from today (same calendar day)
     */
    loadPrevDayClose() {
        try {
            const stored = sessionStorage.getItem('qqq_prev_day_close');
            const storedDate = sessionStorage.getItem('qqq_prev_day_close_date');

            if (stored !== null && storedDate !== null) {
                const value = parseFloat(stored);
                const today = new Date().toDateString();

                // Check if stored date matches today
                if (!isNaN(value) && storedDate === today) {
                    window.logStreamDebug('Loaded prevDayClose from sessionStorage:', value, 'date:', storedDate);
                    return value;
                } else if (storedDate !== today) {
                    window.logStreamDebug('🗓️ Cached prevDayClose is stale (from', storedDate, '), waiting for fresh Summary data');
                    // Clear stale data
                    sessionStorage.removeItem('qqq_prev_day_close');
                    sessionStorage.removeItem('qqq_prev_day_close_date');
                }
            }
        } catch (error) {
            console.error('Error loading prevDayClose from sessionStorage:', error);
        }
        return null;
    }

    /**
     * Save previous day close to sessionStorage with today's date
     */
    savePrevDayClose(value) {
        try {
            if (value !== null && value !== undefined && !isNaN(value)) {
                const today = new Date().toDateString();
                sessionStorage.setItem('qqq_prev_day_close', value.toString());
                sessionStorage.setItem('qqq_prev_day_close_date', today);
                window.logStreamDebug('Saved prevDayClose to sessionStorage:', value, 'date:', today);
            }
        } catch (error) {
            console.error('Error saving prevDayClose to sessionStorage:', error);
        }
    }
}

// Export for use in modules
window.StreamingHandlers = StreamingHandlers;
