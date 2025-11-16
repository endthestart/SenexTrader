# Daily Trade Suggestions - Technical Implementation Specification

## Code Changes Required

### 1. services/strategy_selector.py

#### Add New Method
```python
async def a_select_top_suggestions(
    self, 
    symbol: str, 
    count: int = 3,
    suggestion_mode: bool = True
) -> tuple[list[tuple[str, TradingSuggestion, dict]], dict]:
    """
    Generate top N strategy suggestions for email recommendations.
    
    Args:
        symbol: Underlying symbol (default "SPY")
        count: Number of suggestions to generate (default 3)
        suggestion_mode: If True, skip risk validation
        
    Returns:
        (
            [(strategy_name, suggestion, explanation), ...],  # List of suggestions
            global_context_dict  # Market report, scores, etc.
        )
        
    Example return when successful:
        (
            [
                ("senex_trident", suggestion_obj, {"score": 78, ...}),
                ("bull_put_spread", suggestion_obj, {"score": 72, ...}),
                ("bear_call_spread", suggestion_obj, {"score": 45, ...})
            ],
            {"market_report": {...}, "all_scores": {...}}
        )
        
    Example return when no trades:
        (
            [],  # Empty suggestions list
            {
                "type": "no_trade" | "low_scores" | "hard_stops",
                "market_report": {...},
                "all_scores": {...},
                "reasons": [...]
            }
        )
    """
    # Get market analysis (single call)
    report = await self.validator.a_analyze_market_conditions(
        self.user, symbol, {}
    )
    
    # Store for API access
    self._last_market_report = report
    
    # Check hard stops
    if not report.can_trade():
        return (
            [],
            {
                "type": "hard_stops",
                "market_report": report,
                "reasons": report.no_trade_reasons,
                "all_scores": {}
            }
        )
    
    # Score all strategies
    scores = {}
    explanations = {}
    
    for name, strategy in self.strategies.items():
        try:
            score, explanation = await strategy.a_score_market_conditions(report)
            scores[name] = score
            explanations[name] = explanation
        except Exception as e:
            logger.error(f"Error scoring {name}: {e}")
            scores[name] = 0.0
            explanations[name] = f"Error: {e}"
    
    # Store scores for API
    self._last_scores = {
        name: {"score": scores[name], "explanation": explanations[name]}
        for name in scores
    }
    
    # Sort strategies by score (with deterministic tie-breaking)
    strategy_priority = ["senex_trident", "bull_put_spread", "bear_call_spread"]
    sorted_strategies = sorted(
        scores.items(),
        key=lambda x: (
            x[1],  # Score (higher first)
            -strategy_priority.index(x[0]) if x[0] in strategy_priority else -999
        ),
        reverse=True
    )
    
    # Filter strategies above threshold
    eligible = [
        (name, score) 
        for name, score in sorted_strategies 
        if score >= self.MIN_AUTO_SCORE
    ]
    
    # If none eligible, return low scores explanation
    if not eligible:
        return (
            [],
            {
                "type": "low_scores",
                "market_report": report,
                "all_scores": self._last_scores,
                "best_score": max(scores.values()) if scores else 0
            }
        )
    
    # Generate suggestions for top N eligible strategies
    suggestions = []
    generation_failures = []
    
    for strategy_name, score in eligible[:count]:
        try:
            strategy = self.strategies[strategy_name]
            
            # Prepare context with suggestion_mode flag
            context = await strategy.a_prepare_suggestion_context(
                symbol, report, suggestion_mode=suggestion_mode
            )
            
            if not context:
                generation_failures.append(
                    (strategy_name, "Context preparation failed")
                )
                continue
            
            # Mark as automated/suggestion mode
            context["is_automated"] = True
            context["suggestion_mode"] = suggestion_mode
            
            # Generate via stream manager
            from streaming.services.stream_manager import GlobalStreamManager
            stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)
            suggestion = await stream_manager.a_process_suggestion_request(context)
            
            if suggestion:
                explanation = self._build_auto_explanation(
                    strategy_name, score, 
                    self._score_to_confidence(score),
                    scores, explanations, report
                )
                suggestions.append((strategy_name, suggestion, explanation))
                logger.info(f"Generated suggestion for {strategy_name} (score: {score})")
            else:
                generation_failures.append(
                    (strategy_name, "Suggestion generation returned None")
                )
                
        except Exception as e:
            logger.error(f"Error generating {strategy_name}: {e}")
            generation_failures.append((strategy_name, str(e)))
            continue
    
    # Return what we successfully generated
    global_context = {
        "type": "suggestions" if suggestions else "generation_failures",
        "market_report": report,
        "all_scores": self._last_scores,
        "generation_failures": generation_failures
    }
    
    return (suggestions, global_context)
```

#### Modify Existing Method
```python
async def a_select_and_generate(
    self, 
    symbol: str, 
    forced_strategy: str | None = None,
    suggestion_mode: bool = False  # ⭐ NEW PARAMETER
) -> tuple[str | None, TradingSuggestion | None, dict[str, Any]]:
    """
    Select strategy and generate suggestion.
    
    Args:
        symbol: Underlying symbol (e.g., 'SPY')
        forced_strategy: If provided, generate this strategy regardless
        suggestion_mode: If True, skip risk validation ⭐ NEW
        
    Returns:
        (strategy_name, suggestion_data, explanation)
    """
    # ... existing code ...
    
    # Pass suggestion_mode to context preparation
    context = await best_strategy.a_prepare_suggestion_context(
        symbol, report, suggestion_mode=suggestion_mode  # ⭐ PASS FLAG
    )
    
    # ... rest of existing code ...
```

### 2. services/strategies/credit_spread_base.py

#### Modify Method Signature
```python
async def a_prepare_suggestion_context(
    self, 
    symbol: str, 
    report: MarketConditionReport | None = None,
    suggestion_mode: bool = False  # ⭐ NEW PARAMETER
) -> dict | None:
    """
    Prepare suggestion context WITHOUT creating TradingSuggestion.
    
    Args:
        symbol: Underlying symbol
        report: Optional pre-computed market report
        suggestion_mode: If True, skip risk validation ⭐ NEW
        
    Returns:
        Optional[dict]: Context dict ready for stream manager, or None if unsuitable
    """
    # ... existing market report and scoring logic ...
    
    # Score conditions
    score, explanation = await self.a_score_market_conditions(report)
    
    logger.info(
        f"{self.strategy_name} score for {symbol}: {score:.1f} - {explanation}"
    )
    
    # Check score threshold
    if score < self.MIN_SCORE_THRESHOLD:
        logger.info(
            f"{self.strategy_name}: Score {score:.1f} below threshold "
            f"{self.MIN_SCORE_THRESHOLD}"
        )
        return None
    
    # ⭐ CONDITIONAL RISK CHECK
    if not suggestion_mode:
        # Original behavior: check risk for execution
        can_trade, risk_message = await self.a_validate_risk_budget(
            max_risk=spread_width * 100, 
            is_stressed=False
        )
        if not can_trade:
            logger.warning(
                f"{self.strategy_name}: Risk validation failed - {risk_message}"
            )
            return None
    else:
        # Suggestion mode: skip risk check, always allow generation
        logger.info(
            f"{self.strategy_name}: Suggestion mode - skipping risk validation"
        )
    
    # ... rest of existing code ...
```

### 3. services/senex_trident_strategy.py

#### Similar Change
```python
async def a_prepare_suggestion_context(
    self, 
    symbol: str = "SPY",
    suggestion_mode: bool = False  # ⭐ NEW PARAMETER
) -> dict | None:
    """
    Prepare suggestion context for Senex Trident strategy.
    
    Args:
        symbol: Underlying symbol (default "SPY")
        suggestion_mode: If True, skip risk validation ⭐ NEW
    """
    # ... existing code ...
    
    # ⭐ CONDITIONAL RISK CHECK
    if not suggestion_mode:
        # Check risk budget (original behavior)
        max_risk_dollars = total_spreads_risk * 100
        can_trade, risk_message = await self.a_validate_risk_budget(
            max_risk_dollars, is_stressed
        )
        if not can_trade:
            return None
    else:
        logger.info("Senex Trident: Suggestion mode - skipping risk validation")
    
    # ... rest of existing code ...
```

### 4. services/utils/explanation_builder.py (NEW FILE)

```python
"""
Explanation Builder - Translate technical data to human-readable text.
"""

from services.market_condition_validator import MarketConditionReport
from typing import Any


class ExplanationBuilder:
    """Convert technical indicators to plain English explanations."""
    
    @staticmethod
    def explain_market_snapshot(report: MarketConditionReport) -> dict[str, str]:
        """
        Build human-readable market snapshot.
        
        Returns:
            Dict with formatted strings for each metric
        """
        return {
            "price": f"${report.current_price:.2f}",
            "change": ExplanationBuilder._format_price_change(
                report.current_price, report.open_price
            ),
            "iv_rank": ExplanationBuilder._explain_iv_rank(report.iv_rank),
            "trend": ExplanationBuilder._explain_trend(
                report.macd_signal, report.rsi, report.trend_strength
            ),
            "stress": ExplanationBuilder._explain_stress(report.market_stress_level),
            "range_bound": "Yes" if report.is_range_bound else "No"
        }
    
    @staticmethod
    def _format_price_change(current: float, open: float) -> str:
        """Format price change as '+0.3%' or '-1.2%'"""
        if open > 0:
            change_pct = ((current - open) / open) * 100
            sign = "+" if change_pct >= 0 else ""
            return f"{sign}{change_pct:.1f}%"
        return "N/A"
    
    @staticmethod
    def _explain_iv_rank(iv_rank: float) -> str:
        """Convert IV rank to human description"""
        if iv_rank >= 75:
            return f"{iv_rank:.0f}% (Very High - Excellent premium)"
        elif iv_rank >= 50:
            return f"{iv_rank:.0f}% (High - Good premium)"
        elif iv_rank >= 25:
            return f"{iv_rank:.0f}% (Moderate - Fair premium)"
        else:
            return f"{iv_rank:.0f}% (Low - Poor premium)"
    
    @staticmethod
    def _explain_trend(macd: str, rsi: float, strength: str) -> str:
        """Explain trend direction and strength"""
        direction = macd.capitalize()
        
        if rsi > 70:
            rsi_note = ", overbought"
        elif rsi < 30:
            rsi_note = ", oversold"
        else:
            rsi_note = ""
        
        return f"{direction} ({strength} trend{rsi_note})"
    
    @staticmethod
    def _explain_stress(stress: float) -> str:
        """Explain market stress level"""
        if stress >= 80:
            return f"{stress:.0f}/100 (Extreme)"
        elif stress >= 60:
            return f"{stress:.0f}/100 (High)"
        elif stress >= 40:
            return f"{stress:.0f}/100 (Moderate)"
        else:
            return f"{stress:.0f}/100 (Normal)"
    
    @staticmethod
    def build_trade_reasoning(
        strategy_name: str, 
        score: float, 
        score_reasons: list[str],
        report: MarketConditionReport
    ) -> list[str]:
        """
        Build bullet-point list of reasons why this trade is recommended.
        
        Args:
            strategy_name: Name of strategy
            score: Strategy score (0-100)
            score_reasons: List of scoring reason strings
            report: Market condition report
            
        Returns:
            List of human-readable reason strings
        """
        reasons = []
        
        # Parse score reasons and translate
        for reason in score_reasons:
            if "Good premium" in reason or "IV rank" in reason:
                reasons.append(
                    f"Good options premium available (IV rank {report.iv_rank:.0f}%)"
                )
            elif "Bullish" in reason and "MACD" in reason:
                reasons.append(
                    "Strong bullish momentum (MACD indicator positive)"
                )
            elif "Bearish" in reason and "MACD" in reason:
                reasons.append(
                    "Bearish momentum detected (MACD indicator negative)"
                )
            elif "Support" in reason:
                reasons.append(
                    f"Strong support level at ${report.support_level:.2f}"
                )
            elif "Resistance" in reason:
                reasons.append(
                    f"Resistance level at ${report.resistance_level:.2f} provides target"
                )
            elif "RSI" in reason:
                if report.rsi > 60:
                    reasons.append(
                        f"Market strength confirmed (RSI {report.rsi:.0f}/100)"
                    )
                elif report.rsi < 40:
                    reasons.append(
                        f"Market weakness confirmed (RSI {report.rsi:.0f}/100)"
                    )
            elif "Low stress" in reason or "stress" in reason.lower():
                reasons.append(
                    f"Market conditions stable (stress {report.market_stress_level:.0f}/100)"
                )
        
        # Add strategy-specific context
        if "trident" in strategy_name.lower():
            if report.is_range_bound:
                reasons.append(
                    "Price consolidating in range - ideal for multi-leg strategy"
                )
        
        # Deduplicate and return top 5 most important
        return list(dict.fromkeys(reasons))[:5]
```

### 5. trading/tasks.py

#### Rewrite Email Generation
```python
async def _async_generate_and_email_daily_suggestions():
    """Async implementation of daily trade suggestion email task."""
    from django.conf import settings
    from django.core.mail import send_mail
    from services.strategy_selector import StrategySelector
    from services.risk_validation import RiskValidationService
    from services.utils.explanation_builder import ExplanationBuilder
    
    logger.info("🤖 Starting daily trade suggestion email generation...")
    
    # Query users who want daily suggestions
    eligible_users = await sync_to_async(list)(
        User.objects.filter(
            is_active=True, 
            email_daily_trade_suggestion=True
        ).exclude(email_preference="none")
    )
    
    logger.info(f"Found {len(eligible_users)} users opted-in for daily trade suggestions")
    
    results = {"emails_sent": 0, "failed": 0, "skipped": 0}
    
    for user in eligible_users:
        logger.info(f"📧 Generating suggestions for: {user.email}")
        
        try:
            # ⭐ NEW: Generate top 3 suggestions
            selector = StrategySelector(user)
            suggestions_list, global_context = await selector.a_select_top_suggestions(
                symbol="SPY",
                count=3,
                suggestion_mode=True  # ⭐ Skip risk validation
            )
            
            # ⭐ NEW: Build comprehensive email (NO RISK CHECKING)
            subject, body = _build_comprehensive_email(
                user=user,
                suggestions_list=suggestions_list,
                global_context=global_context,
                base_url=settings.APP_BASE_URL
            )
            
            # Send email
            await sync_to_async(send_mail)(
                subject=subject,
                message=body,
                from_email="noreply@your-domain.com",
                recipient_list=[user.email],
                fail_silently=True,
            )
            
            results["emails_sent"] += 1
            logger.info(f"✅ Sent daily suggestion email to {user.email}")
            
        except Exception as exc:
            logger.error(
                f"❌ Failed to send suggestion to {user.email}: {exc}", 
                exc_info=True
            )
            results["failed"] += 1
            continue
    
    logger.info(
        f"📧 Daily suggestions complete. Sent: {results['emails_sent']}, "
        f"Failed: {results['failed']}, Skipped: {results['skipped']}"
    )
    
    return results


def _build_comprehensive_email(
    user, 
    suggestions_list: list,
    global_context: dict,
    base_url: str
) -> tuple[str, str]:
    """
    Build comprehensive email with top 3 suggestions.
    
    Focus: Education and market analysis, NOT risk management.
    
    Args:
        user: Django user
        suggestions_list: List of (strategy_name, suggestion, explanation) tuples
        global_context: Dict with market report and scores
        base_url: Application base URL
        
    Returns:
        (subject, body) tuple
    """
    from django.utils import timezone
    from services.utils.explanation_builder import ExplanationBuilder
    
    today = timezone.now().strftime("%B %d, %Y")
    report = global_context.get("market_report")
    
    # Case 1: No suggestions (hard stops or low scores)
    if not suggestions_list:
        context_type = global_context.get("type")
        
        if context_type == "hard_stops":
            subject = f"Market Conditions Not Suitable - {today}"
            body = _build_no_trade_email_hard_stops(
                today, global_context, base_url
            )
        elif context_type == "low_scores":
            subject = f"No High-Confidence Trades Today - {today}"
            body = _build_no_trade_email_low_scores(
                today, global_context, base_url
            )
        else:
            subject = f"Trade Suggestions Unavailable - {today}"
            body = _build_error_email(today, global_context, base_url)
        
        return (subject, body)
    
    # Case 2: Suggestions available
    num_suggestions = len(suggestions_list)
    best_strategy = suggestions_list[0][0].replace("_", " ").title()
    
    subject = f"Daily Suggestions: {num_suggestions} Trades ({best_strategy} Top Pick) - {today}"
    
    # Build email body
    body = f"Daily Trade Suggestions - {today}\n"
    body += "=" * 60 + "\n\n"
    
    # Market snapshot
    body += "MARKET SNAPSHOT (as of 10:00 AM ET)\n"
    if report:
        snapshot = ExplanationBuilder.explain_market_snapshot(report)
        body += f"• SPY: {snapshot['price']} ({snapshot['change']} today)\n"
        body += f"• IV Rank: {snapshot['iv_rank']}\n"
        body += f"• Trend: {snapshot['trend']}\n"
        body += f"• Market Stress: {snapshot['stress']}\n"
        body += f"• Range-Bound: {snapshot['range_bound']}\n"
    body += "\n"
    body += "=" * 60 + "\n"
    body += f"RECOMMENDED TRADES (Top {num_suggestions})\n"
    body += "=" * 60 + "\n\n"
    
    # Build each suggestion section
    medals = ["🥇", "🥈", "🥉"]
    for idx, (strategy_name, suggestion, explanation) in enumerate(suggestions_list):
        medal = medals[idx] if idx < 3 else f"#{idx+1}"
        body += _build_suggestion_section(
            medal, idx + 1, strategy_name, suggestion, 
            explanation, base_url
        )
        body += "\n---\n\n"
    
    # Strategy comparison section
    body += "=" * 60 + "\n"
    body += "📊 STRATEGY COMPARISON\n\n"
    body += _build_strategy_comparison(suggestions_list, global_context)
    body += "\n"
    
    # Learning corner section
    body += "=" * 60 + "\n"
    body += "📚 LEARNING CORNER\n\n"
    body += _build_learning_section(report, suggestions_list)
    body += "\n"
    
    # Footer
    body += "=" * 60 + "\n\n"
    body += "This is a suggestion-only email. Trades are NOT automatically executed.\n"
    body += "Review each trade carefully before executing.\n\n"
    body += f"View full dashboard: {base_url}/trading/\n\n"
    body += "---\n"
    body += f"Prefer different email frequency? Update preferences: {base_url}/settings/\n\n"
    body += "As we add more strategies and indicators, these suggestions will become even smarter.\n"
    
    return (subject, body)


def _build_suggestion_section(
    medal: str,
    rank: int,
    strategy_name: str,
    suggestion,
    explanation: dict,
    base_url: str
) -> str:
    """Build detailed section for one suggestion - EDUCATION FOCUSED."""
    from services.utils.explanation_builder import ExplanationBuilder
    
    strategy_display = strategy_name.replace("_", " ").title()
    score = explanation.get("confidence", {}).get("score", 0)
    confidence = explanation.get("confidence", {}).get("level", "UNKNOWN")
    
    section = f"{medal} STRATEGY #{rank}: {strategy_display.upper()} "
    section += f"(Score: {score}/100 - {confidence} CONFIDENCE)\n\n"
    
    # Why this trade - FOCUS ON MARKET REASONING
    section += "   Why This Trade:\n"
    score_data = explanation.get("scores", [])
    if score_data:
        reasons_list = score_data[0].get("reasons", [])
        market_report = explanation.get("market", {})
        
        # Build human-readable reasons
        reasoning = ExplanationBuilder.build_trade_reasoning(
            strategy_name, score, reasons_list, market_report
        )
        for reason in reasoning:
            section += f"   • {reason}\n"
    section += "\n"
    
    # Trade details
    section += "   Trade Details:\n"
    section += f"   • Symbol: {suggestion.underlying_symbol}\n"
    section += f"   • Expiration: {suggestion.expiration_date}\n"
    
    if suggestion.short_put_strike:
        section += f"   • Put Spread: {suggestion.short_put_strike}/{suggestion.long_put_strike}"
        if suggestion.put_spread_quantity > 1:
            section += f" (x{suggestion.put_spread_quantity})"
        section += "\n"
    if suggestion.short_call_strike:
        section += f"   • Call Spread: {suggestion.short_call_strike}/{suggestion.long_call_strike}\n"
    
    credit = suggestion.total_mid_credit or suggestion.total_credit
    section += f"   • Expected Credit: ${credit} per contract\n"
    section += f"   • Max Risk: ${suggestion.max_risk} per contract\n"
    
    # Profit targets (strategy-specific)
    if "trident" in strategy_name.lower():
        section += f"   • Profit Targets: 40%, 60%, 50%\n"
    else:
        section += f"   • Profit Target: 50% of credit\n"
    section += "\n"
    
    # Execute link - NO RISK CHECKING HERE
    section += f"   👉 Execute this trade: {base_url}/trading/?suggestion={suggestion.id}\n"
    
    return section


def _build_strategy_comparison(suggestions_list: list, global_context: dict) -> str:
    """Build comparison section showing how strategies complement each other."""
    section = "Today's market conditions analysis:\n\n"
    
    report = global_context.get("market_report")
    if report:
        if report.macd_signal == "bullish":
            section += "Bullish bias detected - strategies ranked accordingly:\n\n"
        elif report.macd_signal == "bearish":
            section += "Bearish bias detected - strategies ranked accordingly:\n\n"
        else:
            section += "Neutral market - balanced approach recommended:\n\n"
    
    # Describe each strategy's role
    for idx, (strategy_name, suggestion, explanation) in enumerate(suggestions_list):
        rank = idx + 1
        strategy_display = strategy_name.replace("_", " ").title()
        score = explanation.get("confidence", {}).get("score", 0)
        
        section += f"{rank}. {strategy_display} ({score}/100)"
        
        if score >= 70:
            section += " ⭐ STRONG PICK\n"
        elif score >= 50:
            section += " ⚙️ MODERATE PICK\n"
        else:
            section += " ⚠️ HEDGE OPTION\n"
        
        # Strategy-specific description
        if "trident" in strategy_name.lower():
            section += "   Best for: Neutral to bullish bias with range expectations\n"
            section += "   Strengths: Multiple profit targets, flexible management\n"
        elif "bull_put" in strategy_name.lower():
            section += "   Best for: Directional bullish plays\n"
            section += "   Strengths: Simple structure, defined risk, good premium\n"
        elif "bear_call" in strategy_name.lower():
            section += "   Best for: Portfolio hedging or bearish bias\n"
            section += "   Strengths: Caps upside risk, complements bullish positions\n"
        section += "\n"
    
    section += "These strategies can work together as a balanced portfolio approach.\n"
    return section


def _build_learning_section(report, suggestions_list: list) -> str:
    """Build educational content section."""
    section = ""
    
    # Explain current strategy type
    if suggestions_list and len(suggestions_list) > 0:
        primary_strategy = suggestions_list[0][0]
        
        if "credit" in primary_strategy.lower() or "spread" in primary_strategy.lower():
            section += "Why credit spreads in this environment?\n"
            if report:
                section += f"• IV rank at {report.iv_rank:.0f}% means options premiums are "
                if report.iv_rank >= 50:
                    section += "elevated\n"
                else:
                    section += "moderate but acceptable\n"
            section += "• Selling spreads collects premium that decays over time\n"
            section += "• Defined risk on both sides protects against surprises\n"
            section += f"• {suggestions_list[0][1].expiration_date} expiration gives time for thesis to play out\n"
            section += "\n"
    
    # What to watch
    section += "What to watch this week:\n"
    if report:
        if report.support_level:
            section += f"• Support at ${report.support_level:.2f} - if broken, bias may shift\n"
        if report.resistance_level:
            section += f"• Resistance at ${report.resistance_level:.2f} - breakout could signal continuation\n"
        if report.iv_rank < 30:
            section += f"• IV rank at {report.iv_rank:.0f}% - watch for increase above 30%\n"
    section += "• Economic calendar events - FOMC, jobs reports may increase volatility\n"
    section += "• Price action at key moving averages\n"
    
    return section


# Additional helper functions...
# (implement _build_no_trade_email_hard_stops, _build_no_trade_email_low_scores, etc.)
```

## Testing Plan

### Unit Tests

#### test_strategy_selector.py
```python
@pytest.mark.asyncio
async def test_select_top_suggestions_returns_three():
    """Test that top 3 suggestions are returned when all score above threshold."""
    # Arrange: Mock market conditions favorable for all strategies
    # Act: Call a_select_top_suggestions()
    # Assert: Returns 3 suggestions
    pass


@pytest.mark.asyncio
async def test_select_top_suggestions_with_suggestion_mode():
    """Test that suggestion_mode bypasses risk validation."""
    # Arrange: User at 100% risk budget
    # Act: Call a_select_top_suggestions(suggestion_mode=True)
    # Assert: Suggestions still generated
    pass


@pytest.mark.asyncio
async def test_select_top_suggestions_hard_stops():
    """Test handling of hard stops (market closed, stale data)."""
    # Arrange: Mock stale market data
    # Act: Call a_select_top_suggestions()
    # Assert: Returns empty list with hard_stops explanation
    pass
```

#### test_explanation_builder.py
```python
def test_explain_iv_rank_very_high():
    """Test IV rank explanation for very high values."""
    result = ExplanationBuilder._explain_iv_rank(85.0)
    assert "Very High" in result
    assert "Excellent premium" in result


def test_explain_trend_bullish_overbought():
    """Test trend explanation for bullish + overbought conditions."""
    result = ExplanationBuilder._explain_trend("bullish", 75.0, "strong")
    assert "Bullish" in result
    assert "overbought" in result
```

### Integration Tests

#### test_daily_suggestions_task.py
```python
@pytest.mark.asyncio
async def test_task_generates_multiple_suggestions():
    """Test full task execution generates 3 suggestions per user."""
    # Arrange: Create test user with email enabled
    # Act: Run _async_generate_and_email_daily_suggestions()
    # Assert: 3 TradingSuggestion objects created for user
    pass


@pytest.mark.asyncio
async def test_task_at_full_risk_budget():
    """Critical test: Suggestions generated even at 100% risk utilization."""
    # Arrange: User with 100% risk budget used
    # Act: Run task
    # Assert: 
    #   - Suggestions generated ✓
    #   - Email sent ✓
    #   - Email shows "CANNOT EXECUTE" status ✓
    pass


@pytest.mark.asyncio
async def test_risk_check_still_blocks_execution():
    """Verify risk checks still work for actual execution."""
    # Arrange: 
    #   - Generate suggestion at 100% risk budget
    #   - Try to execute via OrderExecutionService
    # Assert: Execution blocked with risk error
    pass
```

### Manual Testing Checklist

- [ ] Run task manually in dev environment
- [ ] Verify 3 suggestions generated per user
- [ ] Check email formatting (plain text readable)
- [ ] Verify links work correctly
- [ ] Test at various risk utilization levels (0%, 50%, 100%)
- [ ] Verify execution still checks risk
- [ ] Test automated trading flow unchanged

## Deployment Checklist

### Pre-Deployment
- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] Code review completed
- [ ] Documentation updated
- [ ] Staging deployment successful

### Deployment
- [ ] Deploy during low-activity window
- [ ] Monitor Celery task execution
- [ ] Check email delivery metrics
- [ ] Verify no errors in logs

### Post-Deployment
- [ ] Monitor first production run
- [ ] Check email open rates
- [ ] Verify no user complaints
- [ ] Collect feedback

## Configuration

### No New Settings Required

The implementation uses existing configuration:
- `User.email_daily_trade_suggestion` - Already exists
- `User.email_preference` - Already exists
- `CELERY_BEAT_SCHEDULE` - Already configured
- `MIN_AUTO_SCORE` - Already in StrategySelector

### Optional Future Settings

```python
# settings/base.py

# Daily suggestions configuration (future enhancement)
DAILY_SUGGESTIONS_CONFIG = {
    "max_suggestions": 3,  # Top N to generate
    "min_score_threshold": 30,  # Minimum score to include
    "include_risk_status": True,  # Show risk check in email
    "email_format": "text",  # "text" or "html"
}
```

## Performance Considerations

### API Call Budget
- Current: 1 market analysis + 1 pricing fetch per user
- Proposed: 1 market analysis + 3 pricing fetches per user
- Impact: +2 TastyTrade API calls per user per day
- With 100 users: 300 API calls/day (well within limits)

### Task Duration
- Current: ~5 seconds per user
- Proposed: ~10-15 seconds per user
- With 100 users: 10-15 minute total task time
- Acceptable for daily task

### Database Impact
- Current: 1 TradingSuggestion per user per day
- Proposed: 3 TradingSuggestions per user per day
- Impact: 3x records, but still minimal
- Cleanup task handles expiration automatically

## Rollback Plan

If issues arise:
1. Revert code to previous version
2. No database migrations, so safe rollback
3. Previous email format still works
4. Monitor logs for any stragglers

Emergency rollback command:
```bash
git revert <commit-hash>
git push
# Redeploy via normal process
```

## Future Enhancements

### HTML Email Version
- Rich formatting with colors
- Collapsible sections
- Charts and graphs
- Mobile-responsive design

### Personalization
- User-specific strategy preferences
- Historical performance tracking
- Favorite symbols
- Time zone adjustments

### Multi-Symbol Support
- SPY, QQQ, IWM suggestions
- Sector-specific strategies
- Correlation analysis

## Documentation Updates

Files to update:
- [ ] `AI.md` - Add section on daily suggestions
- [ ] `CLAUDE.md` - Note risk validation flow
- [ ] User guide - Explain email format
- [ ] Troubleshooting guide - Common issues
