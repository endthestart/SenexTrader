"""
Intelligent Strategy Selection Orchestrator.

Coordinates market analysis and strategy scoring to select the most appropriate
strategy for current market conditions. Supports both auto-selection mode
(pick best strategy) and forced mode (generate specific strategy with warnings).
"""

import asyncio
from typing import Any

from django.contrib.auth.models import AbstractBaseUser

from services.core.logging import get_logger
from services.core.utils.logging_utils import log_error_with_context
from services.interfaces.streaming_interface import StreamerProtocol
from services.market_data.analysis import MarketAnalyzer, MarketConditionReport
from trading.models import TradingSuggestion

logger = get_logger(__name__)


class StrategySelector:
    """
    Intelligent strategy selection orchestrator for ALL options strategies.

    Dynamically loads all registered strategies from StrategyRegistry.
    Handles auto-selection (score all strategies, pick best) and forced-mode
    (generate specific strategy with confidence warning).

    Execution Modes:
    - Auto Mode: Score all strategies, pick highest scoring
    - Forced Mode: Generate requested strategy with confidence warning

    Note: Senex Trident is handled separately as a trading algorithm.
    See SenexTridentStrategy and trading/views.py (senex_trident_view).

    """

    # Minimum score threshold for auto mode (credit spreads)
    MIN_AUTO_SCORE: int = 30

    def __init__(self, user: AbstractBaseUser, streamer: StreamerProtocol | None = None) -> None:
        """
        Initialize strategy selector with all registered strategies.

        Dynamically loads strategies from StrategyRegistry.
        Senex Trident is excluded (handled separately as an algorithm).

        Args:
            user: Django user for API access
            streamer: Optional streamer instance for dependency injection
        """
        self.user = user
        self.analyzer = MarketAnalyzer(user)
        self._streamer = streamer

        # Dynamic strategy loading from factory
        # All strategies except Senex Trident (handled separately)
        from services.strategies.factory import get_strategy, list_strategies

        self.strategies = {
            name: get_strategy(name, user)
            for name in list_strategies()
            if name != "senex_trident"  # Senex has dedicated page
        }

        # Store last analysis for API access
        self._last_market_report: MarketConditionReport | None = None
        self._last_scores: dict[str, dict[str, Any]] = {}

    @property
    def streamer(self) -> StreamerProtocol | None:
        """Get the injected streamer instance."""
        return self._streamer

    async def a_select_and_generate(
        self, symbol: str, forced_strategy: str | None = None, suggestion_mode: bool = False
    ) -> tuple[str | None, TradingSuggestion | None, dict[str, Any]]:
        """
        Select strategy and generate suggestion.

        Args:
            symbol: Underlying symbol (e.g., 'SPY')
            forced_strategy: If provided, generate this strategy regardless
            suggestion_mode: If True, skip risk validation (for email suggestions)

        Returns:
            (strategy_name, suggestion_data, explanation)

        Examples:
            Auto mode:  a_select_and_generate('SPY')
            Forced mode: a_select_and_generate('SPY', 'senex_trident')
            Suggestion mode: a_select_and_generate('SPY', suggestion_mode=True)
        """
        logger.info(
            f"[TRACE] a_select_and_generate: symbol={symbol}, forced={forced_strategy}, suggestion_mode={suggestion_mode}"
        )

        # Get comprehensive market analysis (single call per request)
        logger.info(f"[TRACE] Getting market analysis for {symbol}")
        report: MarketConditionReport = await self.analyzer.a_analyze_market_conditions(
            self.user,
            symbol,
            {},  # market_snapshot - analyzer will fetch
        )
        logger.info(
            f"[TRACE] Market analysis complete: price={report.current_price}, iv_rank={report.iv_rank}"
        )

        if forced_strategy:
            logger.info(f"[TRACE] Using forced strategy path: {forced_strategy}")
            return await self._generate_forced(forced_strategy, symbol, report, suggestion_mode)
        logger.info("[TRACE] Using auto strategy path")
        return await self._generate_auto(symbol, report, suggestion_mode)

    async def _generate_auto(
        self, symbol: str, report: MarketConditionReport, suggestion_mode: bool = False
    ) -> tuple[str | None, TradingSuggestion | None, dict[str, Any]]:
        """
        Auto mode: Score all strategies, pick best.

        Process:
        1. Check hard stops (return None if no strategy can trade)
        2. Score all strategies
        3. Pick highest scoring
        4. Generate suggestion
        5. Build detailed explanation

        Args:
            symbol: Underlying symbol
            report: Market condition analysis
            suggestion_mode: If True, skip risk validation

        Returns:
            (strategy_name, suggestion_data, explanation)
        """
        # Store market report for API access
        self._last_market_report = report

        # Hard stops (applicable to ALL strategies)
        if not report.can_trade():
            explanation: dict[str, Any] = self._build_no_trade_explanation(report)
            self._last_scores = {}
            return (None, None, explanation)

        # Score all strategies
        scores: dict[str, float] = {}
        explanations: dict[str, str] = {}

        for name, strategy in self.strategies.items():
            try:
                score, explanation = await strategy.a_score_market_conditions(report)
                scores[name] = score
                explanations[name] = explanation
                logger.info(f"{name}: {score:.1f} - {explanation}")
            except Exception as e:
                log_error_with_context("scoring", e, context={"strategy": name})
                scores[name] = 0.0
                explanations[name] = f"Error: {e}"

        # Store scores with explanations for API access
        self._last_scores = {
            name: {"score": scores[name], "explanation": explanations[name]} for name in scores
        }

        # Find highest scoring strategy with deterministic tie-breaking
        # When scores tie, prefer strategies in this priority order (highest to lowest)
        strategy_priority = [
            # Credit Spreads (highest priority - proven track record, defined risk)
            "short_put_vertical",
            "short_call_vertical",
            "cash_secured_put",
            # Debit Spreads (directional plays, defined risk)
            "long_call_vertical",
            "long_put_vertical",
            # Iron Condors (range-bound, defined risk)
            "short_iron_condor",
            "long_iron_condor",
            # Volatility Strategies (limited risk, rare opportunities)
            "long_straddle",
            "long_strangle",
            "iron_butterfly",
            # Advanced Multi-Leg (complex, special requirements)
            "long_call_ratio_backspread",
            "call_calendar",
            "put_calendar",
            "covered_call",
        ]

        # Sort by (score DESC, priority ASC) - ties go to highest priority strategy
        best_strategy_name = max(
            scores.items(),
            key=lambda x: (
                x[1],  # Score (higher is better)
                (
                    -strategy_priority.index(x[0]) if x[0] in strategy_priority else -999
                ),  # Priority (lower index is higher priority)
            ),
        )[0]
        best_score = scores[best_strategy_name]

        # Check if any strategy has reasonable score
        if best_score < self.MIN_AUTO_SCORE:
            explanation = self._build_low_score_explanation(scores, explanations, report)
            return (None, None, explanation)

        # Generate with best strategy
        best_strategy = self.strategies[best_strategy_name]

        try:
            # Prepare context for the selected strategy, passing suggestion_mode flag
            context = await best_strategy.a_prepare_suggestion_context(
                symbol, report, suggestion_mode=suggestion_mode
            )
            if not context:
                return (
                    None,
                    None,
                    {
                        "type": "auto",
                        "title": f"Cannot Generate: {best_strategy_name.replace('_', ' ').title()}",
                        "confidence": {
                            "level": self._score_to_confidence(best_score),
                            "score": round(best_score, 1),
                        },
                        "scores": [],  # Empty since generation failed
                        "warnings": ["Failed to prepare market context for selected strategy"],
                        "market": {
                            "direction": report.macd_signal,
                            "iv_rank": round(report.iv_rank, 1),
                            "volatility": round(
                                report.current_iv, 1
                            ),  # Already in percentage format (22.1 for 22.1%)
                            "range_bound": report.is_range_bound,
                            "stress": round(report.market_stress_level, 0),
                        },
                    },
                )

            # Mark as automated so stream manager returns the suggestion object
            context["is_automated"] = True

            # Get stream manager and process the request directly
            from streaming.services.stream_manager import GlobalStreamManager

            stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)
            suggestion = await stream_manager.a_process_suggestion_request(context)

        except Exception as e:
            # WebSocket close code 1000 = normal closure (user navigated away)
            error_msg = str(e)
            if "1000 (OK)" in error_msg:
                logger.info(f"WebSocket closed normally during {best_strategy_name} generation")
            else:
                log_error_with_context("generation", e, context={"strategy": best_strategy_name})
            return (
                None,
                None,
                {
                    "type": "auto",
                    "title": f"Generation Failed: {best_strategy_name.replace('_', ' ').title()}",
                    "confidence": {
                        "level": self._score_to_confidence(best_score),
                        "score": round(best_score, 1),
                    },
                    "scores": [],  # Empty since generation failed
                    "warnings": [f"Technical error: {e!s}"],
                    "market": {
                        "direction": report.macd_signal,
                        "iv_rank": round(report.iv_rank, 1),
                        "volatility": round(
                            report.current_iv, 1
                        ),  # Already in percentage format (22.1 for 22.1%)
                        "range_bound": report.is_range_bound,
                        "stress": round(report.market_stress_level, 0),
                    },
                },
            )

        # Build detailed explanation
        confidence = self._score_to_confidence(best_score)
        explanation = self._build_auto_explanation(
            best_strategy_name, best_score, confidence, scores, explanations, report
        )

        # Return the generated suggestion directly
        return (best_strategy_name, suggestion, explanation)

    async def _generate_forced(
        self,
        strategy_name: str,
        symbol: str,
        report: MarketConditionReport,
        suggestion_mode: bool = False,
    ) -> tuple[str | None, TradingSuggestion | None, dict[str, Any]]:
        """
        Forced mode: Generate requested strategy with warnings.

        Process:
        1. Validate strategy exists
        2. Score the requested strategy
        3. Generate regardless of score
        4. Build explanation with confidence warning

        Args:
            strategy_name: Requested strategy name
            symbol: Underlying symbol
            report: Market condition analysis
            suggestion_mode: If True, skip risk validation

        Returns:
            (strategy_name, suggestion_data, explanation)
        """
        # Store market report for API access
        self._last_market_report = report

        if strategy_name not in self.strategies:
            self._last_scores = {}
            return (
                None,
                None,
                f"Unknown strategy: {strategy_name}. "
                f"Available: {', '.join(self.strategies.keys())}",
            )

        strategy = self.strategies[strategy_name]

        logger.info(
            f"[TRACE] _generate_forced: strategy_name={strategy_name}, strategy_class={strategy.__class__.__name__}"
        )

        # Score the requested strategy
        try:
            logger.info(f"[TRACE] Scoring {strategy_name}")
            score, score_explanation = await strategy.a_score_market_conditions(report)
            logger.info(f"[TRACE] Score result: {score:.1f} - {score_explanation}")
        except Exception as e:
            log_error_with_context("scoring", e, context={"strategy": strategy_name})
            score = 0.0
            score_explanation = f"Scoring error: {e}"
            logger.error(f"[TRACE] Scoring failed: {e}")

        # Store score for API access
        self._last_scores = {strategy_name: {"score": score, "explanation": score_explanation}}

        # Generate regardless of score (forced mode), with force flag to bypass thresholds
        try:
            # Prepare context for the selected strategy
            # force_generation=True allows generation even with score < threshold
            logger.info(f"[TRACE] Calling a_prepare_suggestion_context for {strategy_name}")
            context = await strategy.a_prepare_suggestion_context(
                symbol, report, suggestion_mode=suggestion_mode, force_generation=True
            )
            logger.info(
                f"[TRACE] a_prepare_suggestion_context returned: context={'present' if context else 'None'}"
            )
            if not context:
                # Parse the detailed explanation to show WHY it failed
                conditions = score_explanation.split(" | ") if score_explanation else []

                # Build clear failure reasons
                failure_reasons = []

                # Check if strike optimizer failed (check logs/explanation for hints)
                # This happens when find_expiration_with_optimal_strikes returns None
                explanation_lower = score_explanation.lower() if score_explanation else ""
                if any(
                    keyword in explanation_lower
                    for keyword in ["no strikes", "quality gate", "deviation", "no expiration"]
                ):
                    failure_reasons.append(
                        "No suitable strikes found - strikes outside quality threshold. "
                        "Try a different symbol or market conditions."
                    )

                # Get strategy's actual threshold (default 35, Iron Butterfly uses 40)
                threshold = getattr(strategy, "MIN_SCORE_THRESHOLD", 35)

                # Detect directional mismatch (strategy requires opposite market direction)
                bullish_strategies = [
                    "short_put_vertical",
                    "long_call_vertical",
                    "long_call_ratio_backspread",
                    "covered_call",
                ]
                bearish_strategies = ["short_call_vertical", "long_put_vertical"]

                if score == 0.0:
                    # Score of 0.0 usually means hard stop condition hit
                    if "bearish" in explanation_lower and strategy_name in bullish_strategies:
                        failure_reasons.append(
                            f"Bearish market conditions unsuitable for {strategy_name.replace('_', ' ').title()} "
                            f"(requires bullish outlook)"
                        )
                    elif "bullish" in explanation_lower and strategy_name in bearish_strategies:
                        failure_reasons.append(
                            f"Bullish market conditions unsuitable for {strategy_name.replace('_', ' ').title()} "
                            f"(requires bearish outlook)"
                        )
                    elif "not bullish" in explanation_lower:
                        failure_reasons.append(
                            f"Market not bullish - {strategy_name.replace('_', ' ').title()} requires bullish conditions"
                        )
                    else:
                        failure_reasons.append(
                            f"Critical condition not met (score: {score:.1f}/100)"
                        )
                elif score < threshold:
                    failure_reasons.append(
                        f"Score too low ({score:.1f}/100) - minimum {threshold} required"
                    )
                if not failure_reasons:
                    failure_reasons.append("Market conditions do not meet strategy requirements")

                return (
                    strategy_name,
                    None,
                    {
                        "type": "forced",
                        "title": f"Cannot Generate: {strategy_name.replace('_', ' ').title()}",
                        "confidence": {
                            "level": self._score_to_confidence(score),
                            "score": round(score, 1),
                        },
                        "conditions": conditions,
                        "warnings": failure_reasons,
                        "market": {
                            "direction": report.macd_signal,
                            "iv_rank": round(report.iv_rank, 1),
                            "volatility": round(
                                report.current_iv, 1
                            ),  # Already in percentage format (22.1 for 22.1%)
                            "range_bound": report.is_range_bound,
                            "stress": round(report.market_stress_level, 0),
                        },
                    },
                )

            # Mark as NOT automated so stream manager broadcasts to WebSocket
            # (stream manager returns suggestion object regardless of this flag)
            context["is_automated"] = False

            # Get stream manager and process the request directly
            from streaming.services.stream_manager import GlobalStreamManager

            stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)

            # CRITICAL FIX: Ensure streaming is active before processing suggestion
            # Forced suggestions require real-time option prices via streaming
            # If streaming isn't active, subscription will silently fail and cause timeout
            if not stream_manager.is_streaming:
                logger.info(
                    f"User {self.user.id}: Starting streaming for forced {strategy_name} generation"
                )
                # Start streaming with the underlying symbol
                # This is idempotent - if already starting, it will skip
                await stream_manager.start_streaming([symbol])

                # Give streaming a moment to establish connection
                # The subscription manager will handle waiting for specific option symbols
                await asyncio.sleep(0.5)

                # Verify streaming actually started (could fail due to no account, session, etc.)
                if (
                    not stream_manager.is_streaming
                    and stream_manager.connection_state != "connecting"
                ):
                    error_msg = (
                        f"Failed to start streaming (state: {stream_manager.connection_state}). "
                        "This may be due to missing account configuration or authentication issues. "
                        "Please ensure your TastyTrade account is properly configured."
                    )
                    logger.error(f"User {self.user.id}: {error_msg}")
                    return (
                        strategy_name,
                        None,
                        {
                            "type": "forced",
                            "title": f"Generation Failed: {strategy_name.replace('_', ' ').title()}",
                            "confidence": {
                                "level": self._score_to_confidence(score),
                                "score": round(score, 1),
                            },
                            "conditions": [error_msg],
                            "warnings": ["Cannot generate suggestion without streaming connection"],
                            "market": {
                                "direction": report.macd_signal,
                                "iv_rank": round(report.iv_rank, 1),
                                "volatility": round(report.current_iv, 1),
                                "range_bound": report.is_range_bound,
                                "stress": round(report.market_stress_level, 0),
                            },
                        },
                    )

            suggestion = await stream_manager.a_process_suggestion_request(context)

            # Log successful force generation with score
            logger.info(
                f"Force generated {strategy_name} for user {self.user.id}: "
                f"score={score:.1f} (below threshold but user requested)"
            )

        except Exception as e:
            # WebSocket close code 1000 = normal closure (user navigated away)
            error_msg = str(e)
            if "1000 (OK)" in error_msg:
                logger.info(f"WebSocket closed normally during {strategy_name} generation")
            else:
                log_error_with_context("generation", e, context={"strategy": strategy_name})
            return (
                strategy_name,
                None,
                {
                    "type": "forced",
                    "title": f"Generation Failed: {strategy_name.replace('_', ' ').title()}",
                    "confidence": {
                        "level": self._score_to_confidence(score),
                        "score": round(score, 1),
                    },
                    "conditions": [f"Technical error: {e!s}"],
                    "warnings": ["An error occurred during strategy generation"],
                    "market": {
                        "direction": report.macd_signal,
                        "iv_rank": round(report.iv_rank, 1),
                        "volatility": round(
                            report.current_iv, 1
                        ),  # Already in percentage format (22.1 for 22.1%)
                        "range_bound": report.is_range_bound,
                        "stress": round(report.market_stress_level, 0),
                    },
                },
            )

        # Build explanation with confidence level
        confidence = self._score_to_confidence(score)
        explanation = self._build_forced_explanation(
            strategy_name, score, confidence, score_explanation, report
        )

        # Return the generated suggestion directly
        return (strategy_name, suggestion, explanation)

    async def a_select_top_suggestions(
        self, symbol: str, count: int = 3, suggestion_mode: bool = True
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

        Example success:
            (
                [
                    ("senex_trident", suggestion_obj, {"score": 78, ...}),
                    ("short_put_vertical", suggestion_obj, {"score": 72, ...}),
                    ("short_call_vertical", suggestion_obj, {"score": 45, ...})
                ],
                {"market_report": {...}, "all_scores": {...}}
            )

        Example no trades:
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
        # 1. Get market analysis (single call)
        report = await self.analyzer.a_analyze_market_conditions(self.user, symbol, {})
        self._last_market_report = report

        # 2. Check hard stops
        if not report.can_trade():
            return (
                [],
                {
                    "type": "hard_stops",
                    "market_report": report,
                    "reasons": report.no_trade_reasons,
                    "all_scores": {},
                },
            )

        # 3. Score ALL strategies
        scores = {}
        explanations = {}

        for name, strategy in self.strategies.items():
            try:
                score, explanation = await strategy.a_score_market_conditions(report)
                scores[name] = score
                explanations[name] = explanation
                logger.info(f"{name}: {score:.1f} - {explanation}")
            except Exception as e:
                logger.error(f"Error scoring {name}: {e}")
                scores[name] = 0.0
                explanations[name] = f"Error: {e}"

        # Store scores for API access
        self._last_scores = {
            name: {"score": scores[name], "explanation": explanations[name]} for name in scores
        }

        # 4. Sort strategies by score (with deterministic tie-breaking)
        strategy_priority = [
            # Credit Spreads (highest priority - proven track record, defined risk)
            "short_put_vertical",
            "short_call_vertical",
            "cash_secured_put",
            # Debit Spreads (directional plays, defined risk)
            "long_call_vertical",
            "long_put_vertical",
            # Iron Condors (range-bound, defined risk)
            "short_iron_condor",
            "long_iron_condor",
            # Volatility Strategies (limited risk, rare opportunities)
            "long_straddle",
            "long_strangle",
            "iron_butterfly",
            # Advanced Multi-Leg (complex, special requirements)
            "long_call_ratio_backspread",
            "call_calendar",
            "put_calendar",
            "covered_call",
        ]
        sorted_strategies = sorted(
            scores.items(),
            key=lambda x: (
                x[1],  # Score (higher first)
                -strategy_priority.index(x[0]) if x[0] in strategy_priority else -999,
            ),
            reverse=True,
        )

        # 5. Filter strategies above threshold
        eligible = [
            (name, score) for name, score in sorted_strategies if score >= self.MIN_AUTO_SCORE
        ]

        # Log scoring summary
        logger.info(
            f"Scoring complete for {symbol}: {len(eligible)}/{len(scores)} strategies "
            f"passed threshold (MIN={self.MIN_AUTO_SCORE})"
        )
        if eligible:
            logger.info(
                f"Eligible strategies: {', '.join([f'{n} ({s:.1f})' for n, s in eligible])}"
            )
        else:
            best_name, best_score = sorted_strategies[0] if sorted_strategies else ("none", 0)
            logger.info(f"No strategies passed threshold. Best: {best_name} ({best_score:.1f})")

        # 6. If none eligible, return low scores explanation
        if not eligible:
            return (
                [],
                {
                    "type": "low_scores",
                    "market_report": report,
                    "all_scores": self._last_scores,
                    "best_score": max(scores.values()) if scores else 0,
                },
            )

        # 7. Generate suggestions for top N eligible strategies
        suggestions = []
        generation_failures = []

        logger.info(
            f"Attempting to generate suggestions for top {min(count, len(eligible))} strategies..."
        )

        for strategy_name, score in eligible[:count]:
            try:
                strategy = self.strategies[strategy_name]
                logger.info(f"  → Generating {strategy_name} (score: {score:.1f})...")

                # Prepare context with suggestion_mode flag
                context = await strategy.a_prepare_suggestion_context(
                    symbol, report, suggestion_mode=suggestion_mode
                )

                if not context:
                    logger.warning(f"  {strategy_name}: Context preparation failed")
                    generation_failures.append((strategy_name, "Context preparation failed"))
                    continue

                logger.info(f"  PASS: {strategy_name}: Context prepared")

                # Mark as automated/suggestion mode
                context["is_automated"] = True
                context["suggestion_mode"] = suggestion_mode

                # Generate via stream manager
                from streaming.services.stream_manager import GlobalStreamManager

                stream_manager = await GlobalStreamManager.get_user_manager(self.user.id)
                suggestion = await stream_manager.a_process_suggestion_request(context)

                if suggestion:
                    explanation = self._build_auto_explanation(
                        strategy_name,
                        score,
                        self._score_to_confidence(score),
                        scores,
                        explanations,
                        report,
                    )
                    suggestions.append((strategy_name, suggestion, explanation))
                    logger.info(f"  {strategy_name}: Suggestion generated successfully")
                else:
                    logger.warning(f"  {strategy_name}: Stream manager returned None")
                    generation_failures.append(
                        (strategy_name, "Suggestion generation returned None")
                    )

            except Exception as e:
                logger.error(f"  {strategy_name}: Exception during generation: {e}")
                generation_failures.append((strategy_name, str(e)))
                continue

        # Log generation summary
        if suggestions:
            logger.info(f"Generated {len(suggestions)} suggestion(s) for {symbol}")
        elif generation_failures:
            logger.warning(
                f"All {len(generation_failures)} eligible strategies failed generation for {symbol}:"
            )
            for name, reason in generation_failures:
                logger.warning(f"  - {name}: {reason}")

        # 8. Return what we successfully generated
        global_context = {
            "type": "suggestions" if suggestions else "generation_failures",
            "market_report": report,
            "all_scores": self._last_scores,
            "generation_failures": generation_failures,
        }

        return (suggestions, global_context)

    def _score_to_confidence(self, score: float) -> str:
        """
        Convert numerical score to confidence level.

        Score ranges:
        - 80-100: HIGH confidence
        - 60-79: MEDIUM confidence
        - 40-59: LOW confidence
        - 0-39: VERY LOW confidence

        Args:
            score: Numerical score (0-100)

        Returns:
            Confidence level string
        """
        if score >= 80:
            return "HIGH"
        if score >= 60:
            return "MEDIUM"
        if score >= 40:
            return "LOW"
        return "VERY LOW"

    def _build_auto_explanation(
        self,
        selected: str,
        selected_score: float,
        confidence: str,
        all_scores: dict[str, float],
        all_explanations: dict[str, str],
        report: MarketConditionReport,
    ) -> dict[str, Any]:
        """
        Build detailed explanation for auto mode selection.

        Args:
            selected: Selected strategy name
            selected_score: Score of selected strategy
            confidence: Confidence level
            all_scores: All strategy scores
            all_explanations: All strategy explanations
            report: Market condition report

        Returns:
            Structured explanation dict for frontend rendering
        """
        # Build strategy scores list (sorted by score, highest first)
        scores: list[dict[str, Any]] = []
        for name, score in sorted(all_scores.items(), key=lambda x: x[1], reverse=True):
            # Split explanation by " | " delimiter to get individual reasons
            reasons = all_explanations[name].split(" | ") if all_explanations[name] else []
            scores.append(
                {
                    "strategy": name.replace("_", " ").title(),
                    "strategy_key": name,
                    "score": round(score, 1),
                    "reasons": reasons,
                    "selected": name == selected,
                }
            )

        return {
            "type": "auto",
            "title": f"Selected: {selected.replace('_', ' ').title()}",
            "confidence": {"level": confidence, "score": round(selected_score, 1)},
            "scores": scores,
            "market": {
                "direction": report.macd_signal,
                "iv_rank": round(report.iv_rank, 1),
                "volatility": round(report.current_iv, 1),
                "range_bound": report.is_range_bound,
                "stress": round(report.market_stress_level, 0),
            },
        }

    def _build_forced_explanation(
        self,
        strategy_name: str,
        score: float,
        confidence: str,
        score_explanation: str,
        report: MarketConditionReport,
    ) -> dict[str, Any]:
        """
        Build explanation for forced mode generation.

        Args:
            strategy_name: Requested strategy name
            score: Strategy score
            confidence: Confidence level
            score_explanation: Detailed scoring explanation
            report: Market condition report

        Returns:
            Structured explanation dict for frontend rendering
        """
        # Split conditions by " | " delimiter to get individual reasons
        conditions: list[str] = score_explanation.split(" | ") if score_explanation else []

        # Build warnings list if confidence is low
        warnings: list[str] = []
        if confidence in ["LOW", "VERY LOW"]:
            warnings.append("Market conditions not ideal for this strategy")

        return {
            "type": "forced",
            "title": f"Requested: {strategy_name.replace('_', ' ').title()}",
            "confidence": {"level": confidence, "score": round(score, 1)},
            "conditions": conditions,
            "market": {
                "direction": report.macd_signal,
                "iv_rank": round(report.iv_rank, 1),
                "volatility": round(report.current_iv, 1),
                "range_bound": report.is_range_bound,
                "stress": round(report.market_stress_level, 0),
            },
            "warnings": warnings,
        }

    def _build_no_trade_explanation(self, report: MarketConditionReport) -> dict[str, Any]:
        """
        Build explanation when no strategy can trade.

        Args:
            report: Market condition report

        Returns:
            Structured explanation dict for frontend rendering
        """
        # Format hard stop reasons
        hard_stops: list[str] = [
            reason.replace("_", " ").title() for reason in report.no_trade_reasons
        ]

        return {
            "type": "no_trade",
            "title": "No Trade Conditions",
            "hard_stops": hard_stops,
            "market_status": {
                "last_update": (
                    report.last_update.strftime("%Y-%m-%d %H:%M:%S")
                    if report.last_update
                    else "Unknown"
                ),
                "data_stale": report.is_data_stale,
            },
        }

    def _build_low_score_explanation(
        self, scores: dict[str, float], explanations: dict[str, str], report: MarketConditionReport
    ) -> dict[str, Any]:
        """
        Build explanation when all strategies score too low.

        Args:
            scores: All strategy scores
            explanations: All strategy explanations
            report: Market condition report

        Returns:
            Structured explanation dict for frontend rendering
        """
        best_name: str = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score: float = scores[best_name]

        # Build strategy scores list (sorted by score, highest first)
        strategy_scores: list[dict[str, Any]] = []
        for name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            # Split explanation by " | " delimiter to get individual reasons
            reasons = explanations[name].split(" | ") if explanations[name] else []
            strategy_scores.append(
                {
                    "strategy": name.replace("_", " ").title(),
                    "strategy_key": name,
                    "score": round(score, 1),
                    "reasons": reasons,
                }
            )

        best_title: str = best_name.replace("_", " ").title()
        return {
            "type": "low_scores",
            "title": f"No Suitable Strategy (best: {best_title}, score: {best_score:.1f})",
            "scores": strategy_scores,
            "market": {
                "direction": report.macd_signal,
                "iv_rank": round(report.iv_rank, 1),
                "range_bound": report.is_range_bound,
                "stress": round(report.market_stress_level, 0),
            },
        }
