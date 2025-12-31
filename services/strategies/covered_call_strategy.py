"""
Covered Call Strategy - Income generation on stock holdings.

This strategy requires owning 100+ shares of the underlying stock.
It sells OTM calls to generate income while retaining stock ownership.

Strategy Characteristics:
- Stock ownership required: Must own 100+ shares
- Income generation: Collect premium from call sales
- Upside cap: Profits limited if stock rises above strike
- Downside risk: Full stock exposure minus premium collected
- Ideal for: Neutral to slightly bullish outlook

When to Use:
- Own 100+ shares (or willing to buy 100 shares)
- IV rank > 40 (decent premium collection)
- Neutral to slightly bullish outlook
- No strong upside expected near-term
- Price near desired exit point

"""

from decimal import Decimal

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.positions.stock_detector import StockPositionDetector
from services.strategies.base import BaseStrategy
from services.strategies.utils.strike_utils import round_to_even_strike
from trading.models import Position

logger = get_logger(__name__)


class CoveredCallStrategy(BaseStrategy):
    """
    Covered Call - Income generation on stock holdings.

    REQUIREMENTS:
    - User must own 100+ shares OR opt to buy 100 shares
    - If not, return score 0 immediately
    """

    # Strategy constants
    MIN_DTE = 30  # Minimum days to expiration
    MAX_DTE = 60  # Maximum days to expiration
    MIN_IV_RANK = 25  # Minimum IV for decent premium
    OPTIMAL_IV_RANGE = (40, 70)  # Best premium collection range
    CALL_OTM_PCT = Decimal("0.06")  # Sell call 6% OTM (~0.30 delta)
    MIN_PREMIUM_PERCENTAGE = Decimal("0.01")  # Min 1% premium vs stock price

    def __init__(self, user):
        """Initialize covered call strategy."""
        super().__init__(user)  # Get common dependencies from BaseStrategy
        self.stock_detector = StockPositionDetector(user)  # Add strategy-specific dependency

    @property
    def strategy_name(self) -> str:
        """Return strategy name for logging/tracking."""
        return "covered_call"

    async def a_score_market_conditions(self, report: MarketConditionReport) -> tuple[float, str]:
        """
        Score covered call opportunity.

        HARD STOP: Must own 100+ shares (or have option to buy).
        """
        # Check if user owns sufficient shares
        has_stock = await self.stock_detector.has_sufficient_shares(report.symbol, 100)

        if not has_stock:
            # User doesn't own shares - return low score with informational message
            # The UI can offer option to buy 100 shares when presenting this strategy
            return (
                15.0,
                f"No stock position in {report.symbol} - covered call requires 100+ shares. "
                f"Consider buying 100 shares first if bullish on {report.symbol}.",
            )

        # User owns shares - score the covered call opportunity
        score = 50.0
        reasons = []

        # IV rank (premium collection) - Higher is better for selling
        if self.OPTIMAL_IV_RANGE[0] <= report.iv_rank <= self.OPTIMAL_IV_RANGE[1]:
            score += 25
            reasons.append(
                f"IV rank {report.iv_rank:.1f} in optimal range "
                f"({self.OPTIMAL_IV_RANGE[0]}-{self.OPTIMAL_IV_RANGE[1]}) - "
                "excellent premium for covered call"
            )
        elif report.iv_rank > 50:
            score += 20
            reasons.append(f"High IV rank {report.iv_rank:.1f} - good premium available")
        elif report.iv_rank < self.MIN_IV_RANK:
            score -= 15
            reasons.append(
                f"Low IV rank {report.iv_rank:.1f} < {self.MIN_IV_RANK} - minimal premium available"
            )
        else:
            score += 10
            reasons.append(f"IV rank {report.iv_rank:.1f} - acceptable premium")

        # Market trend (prefer neutral to slightly bullish)
        if report.macd_signal == "neutral":
            score += 20
            reasons.append(
                "Neutral market - ideal for covered call (price stable, collect premium, keep stock)"
            )
        elif report.macd_signal == "bearish_exhausted":
            score += 15
            reasons.append(
                "Bearish exhausted - potential bounce, good for covered call (keep stock)"
            )
        elif report.macd_signal == "bullish":
            score += 10
            reasons.append("Bullish trend - acceptable for covered call (collect premium)")
        elif report.macd_signal == "bullish_exhausted":
            score += 5
            reasons.append("Bullish exhausted - might consolidate, marginal for covered call")
        elif report.macd_signal == "strong_bullish":
            score -= 15
            reasons.append(
                "Strong bullish trend - covered call would cap upside gains (stock might get called away)"
            )
        elif report.macd_signal == "bearish":
            score -= 10
            reasons.append("Bearish direction - covered call provides limited downside protection")
        elif report.macd_signal == "strong_bearish":
            score -= 20
            reasons.append("Strong bearish trend - very unfavorable for covered call")

        # ADX (prefer range-bound, not trending)
        if report.adx is not None:
            if report.adx < 20:
                score += 10
                reasons.append(
                    f"Range-bound market (ADX {report.adx:.1f} < 20) - "
                    "favorable for covered call income"
                )
            elif report.adx > 30:
                score -= 10
                reasons.append(
                    f"Strong trend (ADX {report.adx:.1f} > 30) - "
                    "risky for covered call (may move through strike)"
                )
            else:
                reasons.append(
                    f"Moderate trend (ADX {report.adx:.1f}) - "
                    "acceptable but monitor directional risk"
                )

        # Market stress (prefer low to moderate)
        if report.market_stress_level < 40:
            score += 8
            reasons.append(
                f"Low market stress ({report.market_stress_level:.0f}) - "
                "stable environment for income collection"
            )
        elif report.market_stress_level > 60:
            score -= 8
            reasons.append(
                f"High market stress ({report.market_stress_level:.0f}) - "
                "volatile conditions may result in assignment or large stock moves"
            )

        # Build explanation
        explanation = "\n".join(reasons)

        score = max(0, min(100, score))

        logger.info(
            f"Covered call scoring for {report.symbol}: {score:.1f}/100 (owns stock: {has_stock})"
        )

        return (score, explanation)

    async def a_select_call_strike(
        self, report: MarketConditionReport, stock_basis: Decimal | None = None
    ) -> Decimal:
        """
        Select covered call strike.

        Guidelines:
        - 6% OTM (collect premium, ~70% probability of keeping shares)
        - Above cost basis if provided (avoid locking in loss)
        - Delta ~0.30 (30% probability of assignment)

        Args:
            report: Market condition report
            stock_basis: Average cost basis per share (optional)

        Returns:
            Strike price for covered call
        """
        current_price = Decimal(str(report.current_price))

        # If stock basis provided, ensure strike above basis
        if stock_basis:
            min_strike = round_to_even_strike(stock_basis)
        else:
            # Get basis from position detector if available
            basis = await self.stock_detector.get_stock_basis(report.symbol)
            min_strike = round_to_even_strike(basis) if basis else None

        # Target strike: 6% OTM (delta ~0.30)
        target_strike = current_price * (Decimal("1") + self.CALL_OTM_PCT)
        final_strike = round_to_even_strike(target_strike)

        # Ensure strike above cost basis if we have one
        if min_strike and final_strike < min_strike:
            logger.warning(
                f"Target strike ${final_strike} below cost basis ${min_strike}, "
                f"using basis as minimum strike"
            )
            final_strike = min_strike

        logger.info(
            f"Covered call strike: ${final_strike} "
            f"(~6% OTM from ${current_price}, basis: ${min_strike or 'unknown'})"
        )

        return final_strike

    async def build_opening_legs(self, context: dict) -> list:
        """
        Build opening legs for covered call order.

        Args:
            context: Strategy context containing:
                - session: OAuth session for API calls
                - underlying_symbol: Ticker symbol
                - expiration_date: Option expiration
                - strikes: Dict with 'call_strike'
                - quantity: Number of contracts
                - report: MarketConditionReport (optional)
                - include_stock_purchase: If True, include BUY 100 shares leg

        Returns:
            List of SDK Leg objects for order submission
        """
        from decimal import Decimal

        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.sdk.instruments import get_option_instruments_bulk

        symbol = context["underlying_symbol"]
        expiration_date = context["expiration_date"]
        strike = Decimal(str(context["strikes"]["call_strike"]))
        contracts = context.get("quantity", 1)
        include_stock_purchase = context.get("include_stock_purchase", False)
        session = context["session"]

        legs = []

        # Optionally include stock purchase (if user doesn't own shares yet)
        if include_stock_purchase:
            legs.append(
                Leg(
                    instrument_type=InstrumentType.EQUITY,
                    symbol=symbol,
                    action=OrderAction.BUY_TO_OPEN,
                    quantity=Decimal(100 * contracts),
                )
            )
            logger.info(f"Including stock purchase: BUY {100 * contracts} shares of {symbol}")

        # Fetch call instrument
        specs = [
            {
                "underlying": symbol,
                "expiration": expiration_date,
                "strike": strike,
                "option_type": "C",
            }
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        # Sell covered call
        legs.append(
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.SELL_TO_OPEN,
                quantity=Decimal(contracts),
            )
        )

        logger.info(
            f"Built covered call opening legs: "
            f"SELL {contracts} {strike} call "
            f"({'with' if include_stock_purchase else 'without'} stock purchase)"
        )

        return legs

    async def build_closing_legs(self, position: Position) -> list:
        """
        Build closing legs for covered call order (buy back call).

        Note: This does NOT sell the stock - only closes the call position.

        Args:
            position: Position object containing:
                - strategy_id: Strategy identifier
                - underlying_symbol: Ticker symbol
                - expiration_date: Option expiration
                - strikes: Stored strike prices (JSON field with 'call_strike')
                - quantity: Number of contracts
                - user: User object for session access

        Returns:
            List of SDK Leg objects for order submission
        """
        from decimal import Decimal

        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        symbol = position.underlying_symbol
        expiration_date = position.expiration_date.isoformat()
        strike = Decimal(str(position.strikes["call_strike"]))
        contracts = position.quantity

        # Get session for instrument fetching
        account = await get_primary_tastytrade_account(position.user)
        if not account:
            raise ValueError(f"No TastyTrade account found for user {position.user.id}")

        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id=position.user.id, refresh_token=account.refresh_token, is_test=account.is_test
        )

        if not session_result.get("success"):
            raise ValueError(f"Failed to get session: {session_result.get('error')}")

        session = session_result["session"]

        # Fetch call instrument
        specs = [
            {
                "underlying": symbol,
                "expiration": expiration_date,
                "strike": strike,
                "option_type": "C",
            }
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        legs = [
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.BUY_TO_CLOSE,
                quantity=Decimal(contracts),
            )
        ]

        logger.info(f"Built covered call closing legs: BUY {contracts} {strike} call")

        return legs

    # BaseStrategy abstract method implementations
    async def a_get_profit_target_specifications(self, position: Position, *args) -> list:
        """
        Covered calls typically held until expiration or early assignment.

        Profit targets:
        - 50% of premium collected (standard TastyTrade guideline)
        - 75% of premium collected (aggressive)
        """
        # Placeholder - would implement profit target logic
        return []

    def should_place_profit_targets(self, position: Position) -> bool:
        """Covered calls can use profit targets (buy back call early)."""
        return True

    def get_dte_exit_threshold(self, position: Position) -> int:
        """Close covered call at 7 DTE to avoid assignment risk."""
        return 7

    def automation_enabled_by_default(self) -> bool:
        """Covered calls typically managed manually (stock ownership)."""
        return False

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: "MarketConditionReport | None" = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> "dict | None":
        """
        Prepare covered call suggestion context.

        Generates suggestion for selling covered call against existing stock position,
        or optionally suggests buying 100 shares + selling call if no position exists.

        Args:
            symbol: Underlying symbol
            report: Optional pre-computed market report
            suggestion_mode: If True, skip risk validation (for email suggestions)

        Returns:
            Context dict ready for stream manager, or None if unsuitable
        """
        # Covered calls not supported yet - require share position tracking
        logger.warning(
            f"User {self.user.id}: Covered calls not supported yet. "
            f"Requires share position tracking and portfolio integration which is not implemented."
        )
        return None

    async def a_request_suggestion_generation(
        self, report: "MarketConditionReport | None" = None, symbol: str = "QQQ"
    ) -> None:
        """
        Request suggestion generation via channel layer (manual flow).

        This method prepares the context and sends it to the stream manager.
        The actual suggestion will be created after pricing data arrives and
        will be broadcast to the user via WebSocket.

        Args:
            report: Pre-calculated market condition report
            symbol: Underlying symbol (default QQQ)
        """
        # Prepare context using new method
        context = await self.a_prepare_suggestion_context(symbol, report)
        if not context:
            logger.info(f"{self.strategy_name}: Conditions not suitable for {symbol}")
            return

        # Mark as manual (not automated)
        context["is_automated"] = False

        # Dispatch to stream manager
        await self.a_dispatch_to_stream_manager(context)
        logger.info(
            f"User {self.user.id}: Dispatched {self.strategy_name} request to stream manager"
        )

    async def a_calculate_suggestion_from_cached_data(self, context: dict):
        """Calculate suggestion from cached pricing data (single-leg CALL sale)."""
        from datetime import date, timedelta
        from decimal import Decimal

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        occ_bundle = SenexOccBundle.from_dict(context["occ_bundle"])
        pricing_data = self.options_service.read_spread_pricing(occ_bundle)
        if not pricing_data:
            logger.warning(f"Pricing data not found for {self.strategy_name}")
            return None

        config = (
            await StrategyConfiguration.objects.aget(id=context["config_id"])
            if context.get("config_id")
            else None
        )
        symbol = context["symbol"]
        expiration = date.fromisoformat(context["expiration"])
        strikes = context["strikes"]
        market_data = context["market_data"]
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)
        force_generation = context.get("force_generation", False)
        has_stock = context.get("has_stock_position", False)

        # Extract pricing for single call leg
        call_strike = Decimal(str(strikes["call_strike"]))
        call_payload = pricing_data.snapshots.get("call_strike")
        if not call_payload:
            logger.warning(f"Missing pricing data for call strike {call_strike}")
            return None

        # Premium received (credit) - calculate mid from bid/ask
        bid = call_payload.get("bid")
        ask = call_payload.get("ask")
        if bid is None or ask is None:
            logger.warning(f"Missing bid/ask for call strike {call_strike}")
            return None
        premium = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")

        # Max profit = premium received * 100
        max_profit_total = premium * Decimal("100")

        # Max risk = unlimited (if stock falls), but limited upside if called away
        # For risk budget, use stock value as worst case
        current_price = Decimal(str(market_data["current_price"]))
        max_risk_per_contract = current_price * Decimal("100")  # Stock ownership risk

        # Risk budget checking with different behavior for manual vs auto mode
        risk_warning = None
        if not suggestion_mode:
            can_open, reason = await self.risk_manager.a_can_open_position(
                max_risk_per_contract, is_stressed=market_data.get("is_stressed", False)
            )
            if not can_open:
                if force_generation:
                    # Manual mode: Create suggestion with warning
                    logger.warning(
                        f"User {self.user.id}: Generating {self.strategy_name} despite insufficient risk budget "
                        f"(max risk: ${max_risk_per_contract:.2f}) - manual request"
                    )
                    risk_warning = reason
                else:
                    # Auto mode: Block generation entirely
                    logger.info(
                        f"User {self.user.id}: Risk budget insufficient for {self.strategy_name} "
                        f"(max risk: ${max_risk_per_contract:.2f})"
                    )
                    return {
                        "error": True,
                        "error_type": "risk_budget_exceeded",
                        "message": reason,
                        "max_risk": float(max_risk_per_contract),
                        "strategy": self.strategy_name,
                    }
        else:
            logger.info(
                f"User {self.user.id}: Suggestion mode enabled - skipping risk validation "
                f"for {self.strategy_name}"
            )

        # Build market_conditions with risk warning if applicable
        market_conditions_dict = {
            "macd_signal": market_data.get("macd_signal"),
            "adx": market_data.get("adx"),
            "has_stock_position": has_stock,
            "score": market_data["score"],
            "explanation": market_data["explanation"],
        }
        if risk_warning:
            market_conditions_dict["risk_budget_exceeded"] = True
            market_conditions_dict["risk_warning"] = risk_warning

        # Build generation notes if risk warning
        notes = ""
        if risk_warning:
            notes = f"RISK BUDGET EXCEEDED: {risk_warning}"

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=current_price,
            expiration_date=expiration,
            short_call_strike=call_strike,
            call_quantity=1,
            call_spread_credit=premium,
            total_credit=premium,
            total_mid_credit=premium,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.CREDIT.value,
            max_profit=max_profit_total,
            iv_rank=Decimal(str(market_data["iv_rank"])),
            is_range_bound=market_data.get("is_range_bound", False),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions=market_conditions_dict,  # Include risk warning if applicable
            generation_notes=notes,  # Risk warning if applicable
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: Covered Call suggestion - "
            f"Premium: ${premium:.2f}, Strike: ${call_strike}"
        )
        return suggestion
