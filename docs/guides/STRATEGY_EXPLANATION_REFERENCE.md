# Strategy Explanation Component - Quick Reference

**Component ID**: `strategyExplanation`
**Parser Class**: `StrategyExplanationParser`
**Status**: Reference Documentation
**Location**: `/docs/STRATEGY_EXPLANATION_REFERENCE.md`
**Related**: [TRADING_WORKFLOW_SPECIFICATION.md](TRADING_WORKFLOW_SPECIFICATION.md)

---

## Overview

This document provides a quick reference for the Strategy Explanation Component - a unified UI component that transforms backend strategy selection text into scannable, visually-rich displays with icon-driven sections and clear status indicators.

**Component Features:**
- Adaptive display (success/warning/danger states)
- Icon-driven sections (strategy scores, market conditions, warnings)
- Collapsible details with Bootstrap 5
- Responsive grid layout (mobile-friendly)
- Dark theme compliant

---

## 🚀 Quick Start

### 1. Include in Template
```django
<!-- Add to templates/trading/positions.html -->
<div id="strategyExplanation" class="strategy-explanation-card mb-4" style="display: none;">
  <!-- Component HTML (see full template in implementation guide) -->
</div>
```

### 2. Initialize Parser
```javascript
// In static/js/trading.js
const explanationParser = new StrategyExplanationParser();
```

### 3. Render on API Response
```javascript
fetch('/api/strategy/suggestion/', { /* ... */ })
  .then(response => response.json())
  .then(data => {
    explanationParser.render(
      data.explanation,  // Raw text from backend
      data.mode,         // 'auto' | 'manual' | 'forced'
      data.strategy      // 'bull_put_spread' | etc.
    );
  });
```

---

## 🎨 Component States

| State | Border Color | Icon | Use Case |
|-------|--------------|------|----------|
| **Success** | Green | `bi-check-circle-fill` | Auto mode, HIGH confidence |
| **Warning** | Yellow | `bi-exclamation-triangle-fill` | Forced mode, LOW confidence |
| **Danger** | Red | `bi-shield-fill-x` | No trade, hard stops |
| **Info** | Blue | `bi-info-circle-fill` | Neutral information |

---

## 📊 Expected Backend Format

```
✓ Selected: Bull Put Spread
✓ Confidence: HIGH (score: 72.3)

Strategy Scores:
  → bull_put_spread: 72.3 - Reason text here
  → senex_trident: 35.0 - Reason text here
  → bear_call_spread: 28.0 - Reason text here

Market Conditions:
  • Direction: bullish
  • IV Rank: 45%
  • Volatility: 0.23
  • Range Bound: No
  • Market Stress: 35/100
```

---

## 🔧 Parser API

### Methods

```javascript
// Render component
parser.render(explanationText, mode, selectedStrategy)

// Hide component
parser.clear()

// Parse text (returns object)
const parsed = parser.parseExplanation(text)

// Determine scenario type
const scenario = parser.determineScenario(parsed, mode)
```

### Scenario Determination Logic

```javascript
// No trade: score < 40 or selected = 'none'
if (score < 40 || !selected) return 'no-trade'

// Warning: forced mode OR manual with low confidence
if (mode === 'forced' || (mode === 'manual' && score < 60)) return 'warning'

// Success: everything else
return 'success'
```

---

## 🎯 CSS Classes Reference

### Layout Classes
```css
.strategy-explanation-card      /* Main container */
.explanation-header             /* Header section */
.explanation-body               /* Body content */
.scores-section                 /* Strategy scores */
.market-section                 /* Market metrics */
.warnings-section               /* Warning alerts */
.context-section                /* Additional info */
```

### State Modifiers
```css
.explanation-header.success     /* Green left border */
.explanation-header.warning     /* Yellow left border */
.explanation-header.danger      /* Red left border */
```

### Item Classes
```css
.score-item                     /* Individual strategy */
.score-item.selected            /* Highlighted strategy */
.score-badge                    /* Confidence score */
.score-badge.high               /* 60-100 score */
.score-badge.medium             /* 40-59 score */
.score-badge.low                /* 0-39 score */
.metric-card                    /* Market metric */
```

---

## 🎨 Color Coding

### Score Badges
- **HIGH** (60-100): Green background, success color
- **MEDIUM** (40-59): Yellow background, warning color
- **LOW** (0-39): Red background, danger color

### Strategy Icons
- **Bull strategies**: `bi-arrow-up-circle-fill` (green)
- **Bear strategies**: `bi-arrow-down-circle` (red)
- **Neutral strategies**: `bi-dash-circle` (blue)

### Market Metrics
- **Bullish direction**: Green arrow up
- **Bearish direction**: Red arrow down
- **High IV/volatility**: Red/yellow icons
- **Normal values**: Default teal color

---

## 📱 Responsive Breakpoints

```css
/* Desktop (default) */
.metric-value { font-size: 1.25rem; }

/* Mobile (< 768px) */
@media (max-width: 768px) {
  .explanation-title { font-size: 1rem; }
  .metric-value { font-size: 1rem; }
  .score-item { padding: 0.5rem; }
}
```

---

## 🐛 Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Component not showing | `display: none` not removed | Check `parser.render()` called |
| Styles not applying | CSS not loaded | Hard refresh (Ctrl+Shift+R) |
| Collapse broken | Wrong Bootstrap version | Ensure Bootstrap 5+ |
| Parser errors | Wrong text format | Check backend response |
| Icons missing | Bootstrap Icons not loaded | Add CDN link |

---

## ✅ Implementation Checklist

### Frontend
- [ ] Add CSS to `static/css/style.css`
- [ ] Include Bootstrap Icons CDN
- [ ] Add HTML template to page
- [ ] Copy parser JS to `static/js/strategy_explanation.js`
- [ ] Initialize parser in main JS file
- [ ] Update API response handlers
- [ ] Remove old explanation UI elements

### Backend (if needed)
- [ ] Verify explanation text format
- [ ] Add confidence level to response
- [ ] Include mode in response data
- [ ] Test with all strategy types

### Testing
- [ ] Test auto mode success
- [ ] Test forced mode warning
- [ ] Test no-trade scenario
- [ ] Test mobile responsive
- [ ] Test collapse/expand
- [ ] Test all strategy types
- [ ] Cross-browser testing

---

## 📚 File Locations

- **This Reference**: `/docs/STRATEGY_EXPLANATION_REFERENCE.md`
- **Mockups**: `/docs/planning/2025-10-01-strategy-explanation-component.html`
- **Parser JS**: `/docs/planning/2025-10-01-strategy-explanation-parser.js`
- **Implementation Guide**: `/docs/planning/2025-10-01-strategy-explanation-implementation-guide.md`

---

## 🔗 Integration Example

```javascript
// Complete example in static/js/trading.js

// Initialize once
const explanationParser = new StrategyExplanationParser();

// Use in API call
async function getStrategySuggestion() {
  const symbol = document.getElementById('symbolInput').value;
  const mode = document.getElementById('modeSelect').value;

  try {
    showLoading(); // Your loading indicator

    const response = await fetch('/api/strategy/suggestion/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken')
      },
      body: JSON.stringify({ symbol, mode })
    });

    const data = await response.json();
    hideLoading();

    if (data.error) {
      showError(data.error);
      explanationParser.clear();
      return;
    }

    // Render unified explanation
    explanationParser.render(
      data.explanation,
      data.mode || mode,
      data.strategy || null
    );

    // Update other UI elements
    if (data.strategy) {
      updateStrategyForm(data.strategy);
    }

  } catch (error) {
    hideLoading();
    console.error('Error:', error);
    showError('Failed to fetch strategy suggestion');
    explanationParser.clear();
  }
}
```

---

## 🎯 Performance Targets

- **Load Time**: < 200ms additional
- **Render Time**: < 500ms after API response
- **Parse Time**: < 10ms for typical text
- **Error Rate**: < 0.1%

---

## 🚦 Browser Support

- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ iOS Safari 14+
- ✅ Chrome Android 90+

---

## 📞 Support

**Issues**: Check console for parser errors with debug mode:
```javascript
const parser = new StrategyExplanationParser(true); // Debug enabled
```

**Documentation**: See implementation guide for detailed troubleshooting

---

**Last Updated**: 2025-10-01
**Version**: 1.0
