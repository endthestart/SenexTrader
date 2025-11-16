/**
 * Trading Utilities - Shared helpers for trading interface
 */

const STRATEGY_NAMES = {
    'short_put_vertical': 'Short Put Vertical',
    'short_call_vertical': 'Short Call Vertical',
    'long_put_vertical': 'Long Put Vertical',
    'long_call_vertical': 'Long Call Vertical',
    'long_call_calendar': 'Long Call Calendar',
    'long_put_calendar': 'Long Put Calendar',
    'short_iron_condor': 'Short Iron Condor',
    'long_iron_condor': 'Long Iron Condor',
    'iron_butterfly': 'Iron Butterfly',
    'long_call_ratio_backspread': 'Long Call Ratio Backspread',
    'long_straddle': 'Long Straddle',
    'long_strangle': 'Long Strangle',
    'cash_secured_put': 'Cash-Secured Put',
    'covered_call': 'Covered Call',
    'senex_trident': 'Senex Trident',
};

class TradingUtils {
    static formatValue(value) {
        if (value === null || value === undefined) return '-';
        if (typeof value === 'number' || !isNaN(value)) {
            return parseFloat(value).toFixed(2);
        }
        return value;
    }
    
    static formatMaxProfit(value) {
        if (value === null || value === undefined) return 'Unlimited';
        if (typeof value === 'number' || !isNaN(value)) {
            return `$${parseFloat(value).toFixed(2)}`;
        }
        return value;
    }
    
    static isDebitStrategy(suggestion) {
        return suggestion.price_effect === 'Debit';
    }
    
    static formatExpiration(expStr) {
        const exp = new Date(expStr + 'T00:00:00');
        return exp.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric' 
        });
    }
    
    static getStrategyName(strategyKey) {
        return STRATEGY_NAMES[strategyKey] || strategyKey.replace(/_/g, ' ').toUpperCase();
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { TradingUtils, STRATEGY_NAMES };
}
