"""
Explanation Builder - Translate technical data to human-readable text.

This utility converts technical market indicators and strategy scoring data
into plain English explanations suitable for email content and user communication.
"""

from services.market_data.analysis import MarketConditionReport


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
            "range_bound": "Yes" if report.is_range_bound else "No",
        }

    @staticmethod
    def _format_price_change(current: float, open_price: float) -> str:
        """Format price change as '+0.3%' or '-1.2%'"""
        if open_price > 0:
            change_pct = ((current - open_price) / open_price) * 100
            sign = "+" if change_pct >= 0 else ""
            return f"{sign}{change_pct:.1f}%"
        return "N/A"

    @staticmethod
    def _explain_iv_rank(iv_rank: float) -> str:
        """Convert IV rank to human description"""
        if iv_rank >= 75:
            return f"{iv_rank:.0f}% (Very High - Excellent premium)"
        if iv_rank >= 50:
            return f"{iv_rank:.0f}% (High - Good premium)"
        if iv_rank >= 25:
            return f"{iv_rank:.0f}% (Moderate - Fair premium)"
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
        if stress >= 60:
            return f"{stress:.0f}/100 (High)"
        if stress >= 40:
            return f"{stress:.0f}/100 (Moderate)"
        return f"{stress:.0f}/100 (Normal)"

    @staticmethod
    def build_trade_reasoning(
        strategy_name: str,
        score: float,
        score_reasons: list[str],
        report: MarketConditionReport,
    ) -> list[str]:
        """
        Build bullet-point list of reasons why this trade is recommended.

        Args:
            strategy_name: Name of strategy
            score: Strategy score (0-100)
            score_reasons: List of scoring reason strings
            report: Market condition report

        Returns:
            List of human-readable reason strings (max 5)
        """
        reasons = []

        # Parse score reasons and translate
        for reason in score_reasons:
            # IV rank reasons
            if "Good premium" in reason or "IV rank" in reason:
                reasons.append(f"Good options premium available (IV rank {report.iv_rank:.0f}%)")

            # MACD trend reasons
            elif "Bullish" in reason and "MACD" in reason:
                reasons.append("Strong bullish momentum (MACD indicator positive)")
            elif "Bearish" in reason and "MACD" in reason:
                reasons.append("Bearish momentum detected (MACD indicator negative)")

            # Support/resistance reasons
            elif "Support" in reason and report.support_level:
                reasons.append(f"Strong support level at ${report.support_level:.2f}")
            elif "Resistance" in reason and report.resistance_level:
                reasons.append(
                    f"Resistance level at ${report.resistance_level:.2f} provides target"
                )

            # RSI reasons
            elif "RSI" in reason:
                if report.rsi > 60:
                    reasons.append(f"Market strength confirmed (RSI {report.rsi:.0f}/100)")
                elif report.rsi < 40:
                    reasons.append(f"Market weakness confirmed (RSI {report.rsi:.0f}/100)")

            # Stress reasons
            elif "Low stress" in reason or "stress" in reason.lower():
                reasons.append(
                    f"Market conditions stable (stress {report.market_stress_level:.0f}/100)"
                )

        # Add strategy-specific context
        if "trident" in strategy_name.lower():
            if report.is_range_bound:
                reasons.append("Price consolidating in range - ideal for multi-leg strategy")

        # Deduplicate and return top 5 most important
        return list(dict.fromkeys(reasons))[:5]

    @staticmethod
    def explain_strategy_type(strategy_name: str, report: MarketConditionReport) -> str:
        """Generate brief explanation of why this strategy type works now."""

        if "credit" in strategy_name or "spread" in strategy_name:
            explanation = "Why credit spreads in this environment?\n"

            if report.iv_rank >= 50:
                explanation += (
                    f"• IV rank at {report.iv_rank:.0f}% means options premiums are elevated\n"
                )
            else:
                explanation += f"• IV rank at {report.iv_rank:.0f}% provides moderate but acceptable premiums\n"

            explanation += "• Selling spreads collects premium that decays over time\n"
            explanation += "• Defined risk on both sides protects against surprises\n"

            return explanation

        return ""

    @staticmethod
    def generate_watchlist(report: MarketConditionReport) -> list[str]:
        """Generate list of key levels and events to watch."""
        watchlist = []

        if report.support_level:
            watchlist.append(f"Support at ${report.support_level:.2f} - if broken, bias may shift")

        if report.resistance_level:
            watchlist.append(
                f"Resistance at ${report.resistance_level:.2f} - breakout could signal continuation"
            )

        if report.iv_rank < 30:
            watchlist.append(f"IV rank at {report.iv_rank:.0f}% - watch for increase above 30%")

        watchlist.append("Economic calendar events - FOMC, jobs reports may increase volatility")
        watchlist.append("Price action at key moving averages")

        return watchlist
