"""
Email builder for trade suggestion emails.

Handles formatting of single-symbol and multi-symbol trade suggestion emails
with consistent styling, scoring, and layout.
"""


class SuggestionEmailBuilder:
    """
    Builder for trade suggestion emails.

    Provides methods to build formatted text emails for:
    - Single-symbol suggestions (original flow)
    - Multi-symbol watchlist suggestions (Epic 22)
    - No-trade-today notifications

    Example:
        builder = SuggestionEmailBuilder(base_url="https://app.example.com")
        subject, body = builder.build_multi_symbol_email(
            user=user,
            candidates=sorted_candidates
        )
    """

    # Confidence level thresholds
    CONFIDENCE_THRESHOLDS = {"HIGH": 70, "MEDIUM": 50, "LOW": 0}

    # Medal emojis for top 3
    MEDALS = ["🥇", "🥈", "🥉"]

    def __init__(self, base_url: str):
        """
        Initialize email builder.

        Args:
            base_url: Application base URL (e.g., "https://app.example.com")
        """
        self.base_url = base_url

    def get_confidence(self, score: float) -> str:
        """
        Convert numeric score to confidence level.

        Args:
            score: Strategy score (0-100)

        Returns:
            "HIGH", "MEDIUM", or "LOW"
        """
        if score >= self.CONFIDENCE_THRESHOLDS["HIGH"]:
            return "HIGH"
        if score >= self.CONFIDENCE_THRESHOLDS["MEDIUM"]:
            return "MEDIUM"
        return "LOW"

    def format_strategy_name(self, strategy_id: str) -> str:
        """
        Convert strategy_id to display name.

        Args:
            strategy_id: Internal strategy ID (e.g., "bull_put_spread")

        Returns:
            Display name (e.g., "Bull Put Spread")
        """
        return strategy_id.replace("_", " ").title()

    def build_multi_symbol_email(
        self,
        user,
        candidates: list[dict],
        failed_symbols: list[dict] = None,
        watchlist: list[str] = None,
    ) -> tuple[str, str]:
        """
        Build consolidated multi-symbol email with global top-3 ranking.

        Displays:
        - Top 3 opportunities (detailed)
        - Other opportunities (summary table)
        - No suitable trades section (if applicable) with diagnostics

        Args:
            user: Django user object
            candidates: List of dicts from _process_symbols_parallel() (sorted by score)
                Each dict contains: symbol, strategy_name, suggestion, explanation, score, market_report
            failed_symbols: List of dicts with diagnostic info for symbols with no trades
                Each dict contains: symbol, reason, best_score, best_strategy, all_scores
            watchlist: List of symbols in user's watchlist

        Returns:
            (subject, body) tuple
        """
        failed_symbols = failed_symbols or []
        watchlist = watchlist or []
        from django.utils import timezone

        today = timezone.now().strftime("%B %d, %Y")

        # Split candidates into categories
        top_3 = candidates[:3]
        others = candidates[3:8]  # Show max 5 more

        # Build subject
        if not top_3:
            subject = f"No Suitable Trades Today - {today}"
        else:
            top_symbol = top_3[0]["symbol"]
            top_score = top_3[0]["score"]
            confidence = self.get_confidence(top_score)
            subject = f"Daily Suggestions: {len(candidates)} Opportunities ({top_symbol} Top Pick - {confidence}) - {today}"

        # Build body
        body = f"Daily Trade Suggestions - {today}\n"
        body += "=" * 70 + "\n\n"

        # Case: No suitable trades
        if not candidates:
            body += "NO SUITABLE TRADES TODAY\n"
            body += "=" * 70 + "\n\n"
            body += f"Analyzed {len(watchlist)} symbols from your watchlist.\n"
            body += "Market conditions did not meet criteria for generating suggestions.\n\n"

            # Add diagnostic breakdown
            if failed_symbols:
                body += "ANALYSIS BREAKDOWN\n"
                body += "-" * 70 + "\n\n"

                # Categorize failures
                low_scores = [s for s in failed_symbols if s.get("reason") == "low_scores"]
                gen_failures = [
                    s for s in failed_symbols if s.get("reason") == "generation_failures"
                ]
                errors = [s for s in failed_symbols if s.get("reason") == "exception"]

                if low_scores:
                    body += f"Scores Below Threshold ({len(low_scores)} symbols):\n"
                    body += "  Strategy scores did not meet minimum requirements (need 30+)\n\n"

                    # Show top near-misses (within 10 points of threshold)
                    near_misses = [
                        (s["symbol"], s.get("best_strategy"), s.get("best_score"))
                        for s in low_scores
                        if s.get("best_score", 0) >= 20
                    ]
                    near_misses.sort(key=lambda x: x[2], reverse=True)

                    if near_misses:
                        body += "  Closest Opportunities:\n"
                        for symbol, strategy, score in near_misses[:5]:
                            strategy_display = self.format_strategy_name(strategy or "unknown")
                            body += f"    • {symbol} - {strategy_display}: {score:.1f} (need 30+)\n"
                        body += "\n"

                if gen_failures:
                    body += f"Generation Issues ({len(gen_failures)} symbols):\n"
                    body += "  Strategies scored high enough but failed to generate suggestions.\n"
                    body += "  This may indicate data availability or configuration issues.\n\n"

                if errors:
                    body += f"Technical Errors ({len(errors)} symbols):\n"
                    body += "  Some symbols encountered technical issues during analysis.\n\n"

                # Common issues summary
                body += "Common Issues Detected:\n"
                # Count strategies that failed with "insufficient historical data"
                insufficient_data_count = sum(
                    1
                    for s in failed_symbols
                    if s.get("all_scores")
                    and any(
                        "Insufficient historical data" in str(score_data.get("explanation", ""))
                        for score_data in s.get("all_scores", {}).values()
                    )
                )
                if insufficient_data_count > 0:
                    body += f"  • Insufficient historical data: {insufficient_data_count} symbols\n"
                    body += (
                        "    Solution: Data collection ongoing, availability improves over time\n"
                    )

            body += "\n"
            body += f"View dashboard: {self.base_url}/trading/\n"
            body += f"Manage watchlist: {self.base_url}/trading/watchlist/\n\n"
            body += "Conditions will be re-evaluated in the next daily cycle.\n"
            body += "Markets change—what's unsuitable today may be perfect tomorrow."
            return (subject, body)

        # Top 3 opportunities
        body += f"TOP OPPORTUNITIES ({len(top_3)})\n"
        body += "=" * 70 + "\n\n"

        for idx, candidate in enumerate(top_3):
            medal = self.MEDALS[idx]
            symbol = candidate["symbol"]
            strategy_name = candidate["strategy_name"]
            strategy_display = self.format_strategy_name(strategy_name)
            score = candidate["score"]
            suggestion = candidate["suggestion"]
            report = candidate.get("market_report")
            conf = self.get_confidence(score)

            body += f"{medal} {symbol} - {strategy_display} (Score: {score:.1f}/100 - {conf} CONFIDENCE)\n"
            body += "-" * 70 + "\n\n"

            # Trade Structure
            body += "   📋 TRADE STRUCTURE\n"
            body += f"   • Underlying Price: ${suggestion.underlying_price}\n"
            body += f"   • Expiration: {suggestion.expiration_date.strftime('%b %d, %Y')}\n"
            body += f"   • Strategy Type: {suggestion.price_effect}\n"
            body += "\n"

            # Leg Details
            body += "   📊 POSITION LEGS\n"

            # Check if this is a spread strategy or single option strategy
            has_put_spread = suggestion.short_put_strike and suggestion.long_put_strike
            has_call_spread = suggestion.short_call_strike and suggestion.long_call_strike
            has_single_put = suggestion.long_put_strike and not suggestion.short_put_strike
            has_single_call = suggestion.long_call_strike and not suggestion.short_call_strike

            if has_put_spread:
                body += f"   Put Spread (x{suggestion.put_spread_quantity}):\n"
                body += f"      • Sell ${suggestion.short_put_strike} Put"
                if suggestion.put_spread_credit:
                    body += f" → ${abs(suggestion.put_spread_credit):.2f} credit per spread"
                body += "\n"
                body += f"      • Buy ${suggestion.long_put_strike} Put\n"
                if suggestion.put_spread_mid_credit:
                    body += f"      • Net Credit (mid): ${abs(suggestion.put_spread_mid_credit):.2f} per spread\n"
                body += "\n"
            elif has_single_put:
                body += "   Long Put:\n"
                body += f"      • Buy ${suggestion.long_put_strike} Put"
                if suggestion.put_spread_credit:
                    body += f" → ${abs(suggestion.put_spread_credit):.2f} cost"
                body += "\n\n"

            if has_call_spread:
                body += f"   Call Spread (x{suggestion.call_spread_quantity}):\n"
                body += f"      • Sell ${suggestion.short_call_strike} Call"
                if suggestion.call_spread_credit:
                    body += f" → ${abs(suggestion.call_spread_credit):.2f} credit per spread"
                body += "\n"
                body += f"      • Buy ${suggestion.long_call_strike} Call\n"
                if suggestion.call_spread_mid_credit:
                    body += f"      • Net Credit (mid): ${abs(suggestion.call_spread_mid_credit):.2f} per spread\n"
                body += "\n"
            elif has_single_call:
                body += "   Long Call:\n"
                body += f"      • Buy ${suggestion.long_call_strike} Call"
                if suggestion.call_spread_credit:
                    body += f" → ${abs(suggestion.call_spread_credit):.2f} cost"
                body += "\n\n"

            # Financial Summary
            body += "   💰 FINANCIAL SUMMARY\n"
            credit = suggestion.total_mid_credit or suggestion.total_credit
            if suggestion.price_effect == "Credit":
                body += f"   • Total Credit: ${abs(credit):.2f}\n"
            else:
                body += f"   • Total Debit: ${abs(credit):.2f}\n"

            if suggestion.max_profit:
                body += f"   • Max Profit: ${suggestion.max_profit:.2f}\n"

            body += f"   • Max Risk: ${suggestion.max_risk:.2f}\n"

            # Risk/Reward Ratio
            if suggestion.max_profit and suggestion.max_risk and suggestion.max_risk > 0:
                risk_reward = float(suggestion.max_profit) / float(suggestion.max_risk)
                body += f"   • Risk/Reward: 1:{risk_reward:.2f}\n"
            body += "\n"

            # Market snapshot for this symbol
            if report:
                body += "   📈 MARKET CONDITIONS\n"
                iv_rank = getattr(report, "iv_rank", None)
                market_stress = getattr(report, "market_stress_level", None)
                if iv_rank is not None:
                    body += f"   • IV Rank: {iv_rank:.1f}%\n"
                if market_stress is not None:
                    body += f"   • Market Stress: {market_stress:.1f}\n"
                body += "\n"

            body += f"   👉 Execute: {self.base_url}/trading/?suggestion={suggestion.id}\n\n"

            if idx < len(top_3) - 1:
                body += "---\n\n"

        # Other opportunities (detailed list)
        if others:
            body += "\n" + "=" * 70 + "\n"
            body += f"OTHER OPPORTUNITIES ({len(others)})\n"
            body += "=" * 70 + "\n\n"

            for idx, candidate in enumerate(others, start=4):
                symbol = candidate["symbol"]
                strategy_display = self.format_strategy_name(candidate["strategy_name"])
                score = candidate["score"]
                suggestion = candidate["suggestion"]
                conf = self.get_confidence(score)

                body += f"{idx}. {symbol} - {strategy_display} (Score: {score:.1f} - {conf})\n"
                body += f"   • Expiration: {suggestion.expiration_date.strftime('%b %d, %Y')}\n"

                # Strikes summary
                if suggestion.short_put_strike and suggestion.short_call_strike:
                    body += f"   • Strikes: Put ${suggestion.short_put_strike}/${suggestion.long_put_strike}"
                    body += (
                        f" | Call ${suggestion.short_call_strike}/${suggestion.long_call_strike}\n"
                    )
                elif suggestion.short_put_strike:
                    body += f"   • Put Strikes: ${suggestion.short_put_strike}/${suggestion.long_put_strike}\n"
                elif suggestion.short_call_strike:
                    body += f"   • Call Strikes: ${suggestion.short_call_strike}/${suggestion.long_call_strike}\n"

                # Financial summary
                credit = suggestion.total_mid_credit or suggestion.total_credit
                if suggestion.price_effect == "Credit":
                    body += f"   • Credit: ${abs(credit):.2f}"
                else:
                    body += f"   • Debit: ${abs(credit):.2f}"

                if suggestion.max_profit:
                    body += f" | Max Profit: ${suggestion.max_profit:.2f}"
                body += f" | Max Risk: ${suggestion.max_risk:.2f}\n"

                body += f"   • Execute: {self.base_url}/trading/?suggestion={suggestion.id}\n"

                if idx - 3 < len(others):  # Don't add separator after last one
                    body += "\n"

            body += "\n"

        # Footer
        body += "=" * 70 + "\n\n"
        body += "This is a suggestion-only email. Trades are NOT automatically executed.\n"
        body += "Review suggestions and execute through your dashboard when ready.\n\n"
        body += f"View full dashboard: {self.base_url}/trading/\n"
        body += f"Manage watchlist: {self.base_url}/trading/watchlist/\n\n"
        body += "---\n"
        body += f"Manage email preferences: {self.base_url}/settings/\n"

        return (subject, body)

    def build_single_symbol_email(
        self, user, suggestions_list: list, global_context: dict
    ) -> tuple[str, str]:
        """
        Build comprehensive email with market analysis and top strategy suggestions.

        Args:
            user: Django user
            suggestions_list: List of (strategy_name, suggestion, explanation) tuples
            global_context: Dict with market_report, all_scores, type, etc.

        Returns:
            (subject, body) tuple
        """
        from django.utils import timezone

        from services.strategies.utils.explanation_builder import ExplanationBuilder

        today = timezone.now().strftime("%B %d, %Y")
        report = global_context.get("market_report")
        context_type = global_context.get("type", "unknown")

        # Case 1: No suitable trades
        if not suggestions_list:
            subject = f"No Suitable Trade Today - {today}"
            body = f"Daily Trade Suggestion - {today}\n\n"
            body += "NO TRADE RECOMMENDED TODAY\n"
            body += "=" * 50 + "\n\n"

            if context_type == "hard_stops":
                body += "Market conditions triggered hard stops:\n"
                for stop in global_context.get("reasons", []):
                    body += f"  • {stop}\n"
            elif context_type == "low_scores":
                body += f"All strategies scored below threshold (best: {global_context.get('best_score', 0):.1f})\n\n"
                body += "Strategy Scores:\n"
                all_scores = global_context.get("all_scores", {})
                for name, data in sorted(
                    all_scores.items(), key=lambda x: x[1]["score"], reverse=True
                ):
                    body += f"  • {self.format_strategy_name(name)}: {data['score']:.1f}\n"

            body += f"\n\nView dashboard: {self.base_url}/trading/\n"
            body += "\nThis is an automated suggestion email. Market conditions will be evaluated again tomorrow."
            return (subject, body)

        # Case 2: Suggestions available
        num_suggestions = len(suggestions_list)

        # Get top strategy for subject
        top_strategy_name = self.format_strategy_name(suggestions_list[0][0])
        all_scores = global_context.get("all_scores", {})
        top_score = all_scores.get(suggestions_list[0][0], {}).get("score", 0)
        confidence = self.get_confidence(top_score)

        subject = (
            f"Daily Suggestions: {num_suggestions} Trades ({top_strategy_name} Top Pick) - {today}"
        )

        body = f"Daily Trade Suggestions - {today}\n"
        body += "=" * 60 + "\n\n"

        # Market snapshot
        if report:
            snapshot = ExplanationBuilder.explain_market_snapshot(report)
            body += "MARKET SNAPSHOT (as of 10:00 AM ET)\n"
            body += f"• SPY: {snapshot['price']} ({snapshot['change']} today)\n"
            body += f"• IV Rank: {snapshot['iv_rank']}\n"
            body += f"• Trend: {snapshot['trend']}\n"
            body += f"• Market Stress: {snapshot['stress']}\n"
            body += f"• Range-Bound: {snapshot['range_bound']}\n\n"

        body += "=" * 60 + "\n"
        body += f"RECOMMENDED TRADES (Top {num_suggestions})\n"
        body += "=" * 60 + "\n\n"

        # Build each suggestion
        for idx, (strategy_name, suggestion, explanation) in enumerate(suggestions_list):
            medal = self.MEDALS[idx] if idx < 3 else f"#{idx+1}"
            score = all_scores.get(strategy_name, {}).get("score", 0)
            strategy_display = self.format_strategy_name(strategy_name)
            conf_level = self.get_confidence(score)

            body += f"{medal} STRATEGY #{idx+1}: {strategy_display.upper()} "
            body += f"(Score: {score:.1f}/100 - {conf_level} CONFIDENCE)\n\n"

            # Trade details
            body += "   Trade Details:\n"
            body += f"   • Symbol: {suggestion.underlying_symbol}\n"
            body += f"   • Expiration: {suggestion.expiration_date}\n"

            if suggestion.short_put_strike:
                body += (
                    f"   • Put Spread: {suggestion.short_put_strike}/{suggestion.long_put_strike}"
                )
                if suggestion.put_spread_quantity > 1:
                    body += f" (x{suggestion.put_spread_quantity})"
                body += "\n"
            if suggestion.short_call_strike:
                body += f"   • Call Spread: {suggestion.short_call_strike}/{suggestion.long_call_strike}\n"

            credit = suggestion.total_mid_credit or suggestion.total_credit
            body += f"   • Expected Credit: ${credit}\n"
            body += f"   • Max Risk: ${suggestion.max_risk}\n\n"

            # Execute link
            body += f"   👉 Execute: {self.base_url}/trading/?suggestion={suggestion.id}\n\n"

            if idx < len(suggestions_list) - 1:
                body += "---\n\n"

        # Footer
        body += "=" * 60 + "\n\n"
        body += "This is a suggestion-only email. Trades are NOT automatically executed.\n"
        body += "Review suggestions and execute through your dashboard when ready.\n\n"
        body += f"View full dashboard: {self.base_url}/trading/\n\n"
        body += "---\n"
        body += f"Manage email preferences: {self.base_url}/settings/\n"

        return (subject, body)
