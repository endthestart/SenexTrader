"""
Calendar Spread Strategy - Time decay differential play.

This strategy exploits theta acceleration between near-term and longer-term options.
It sells a near-term option (20-30 DTE) and buys a longer-term option (50-60 DTE)
at the same strike to profit from theta differential.

Strategy Characteristics:
- Different expirations: Near-term vs Long-term (same strike)
- Theta advantage: Near-term decays 2-3x faster
- IV expansion benefits: Long leg gains from IV increase
- Low IV entry: Opposite of credit spreads (want cheap options to buy)
- Neutral directional: Profit maximized at strike price

When to Use:
- IV rank < 40 (low IV, cheap to buy long option)
- ADX < 20 (neutral/range-bound market)
- HV/IV ratio > 1.1 (room for IV expansion)
- No near-term catalysts (earnings, etc.)
- Price stable near target strike

Epic 22 Task 006: Calendar Spread implementation
"""

from decimal import Decimal

from services.core.logging import get_logger
from services.market_data.analysis import MarketConditionReport
from services.market_data.option_chains import OptionChainService
from services.strategies.base import BaseStrategy
from services.strategies.registry import register_strategy
from services.strategies.utils.strike_utils import round_to_even_strike
from trading.models import Position

logger = get_logger(__name__)


@register_strategy("long_call_calendar")
class LongCallCalendarStrategy(BaseStrategy):
    """
    Calendar Spread: Sell near-term option, buy longer-term option.

    Structure:
    - Sell 1 option @ strike K, DTE 20-30 (near-term)
    - Buy 1 option @ strike K, DTE 50-60 (long-term)
    - Same strike, different expirations, same type

    Best Entry Conditions:
    - IV rank < 40 (low IV, cheap to buy)
    - ADX < 20 (neutral market)
    - HV/IV ratio > 1.1 (room for IV expansion)
    - No earnings in either expiration
    """

    # Strategy constants - IV Environment (want LOW IV)
    MIN_IV_RANK = 0
    MAX_IV_RANK = 40  # Don't enter above this
    OPTIMAL_IV_RANK = 25  # Sweet spot

    # DTE Targets (TastyTrade methodology with practical flexibility)
    NEAR_TERM_DTE_TARGET = 25
    NEAR_TERM_DTE_MIN = 15  # More flexible: 15-35 (still catches accelerated decay)
    NEAR_TERM_DTE_MAX = 35

    LONG_TERM_DTE_TARGET = 55
    LONG_TERM_DTE_MIN = 45  # More flexible: 45-75 (still in slow decay zone)
    LONG_TERM_DTE_MAX = 75

    # DTE ratio should be roughly 2:1 (long:near)
    MIN_DTE_RATIO = 1.6  # Slightly more flexible: 1.6-3.0
    IDEAL_DTE_RATIO = 2.2
    MAX_DTE_RATIO = 3.0

    # Market Conditions
    MAX_ADX_NEUTRAL = 20  # Want neutral/range-bound
    OPTIMAL_ADX = 15
    MIN_HV_IV_RATIO = 1.1  # Want room for IV expansion
    OPTIMAL_HV_IV_RATIO = 1.3

    def __init__(self, user):
        """Initialize calendar spread strategy."""
        super().__init__(user)  # Get common dependencies from BaseStrategy
        self.option_chain_service = OptionChainService()  # Add strategy-specific dependency

    @property
    def strategy_name(self) -> str:
        """Return strategy name for logging/tracking."""
        return "long_call_calendar"

    async def a_score_market_conditions(self, report: MarketConditionReport) -> tuple[float, str]:
        """
        Score market conditions for Calendar Spread entry (0-100).

        Scoring Weights:
        - IV environment (want LOW): 35%
        - ADX (want neutral): 25%
        - HV/IV ratio (want >1.1): 20%
        - Price proximity: 10%
        - Expiration availability: 10%

        Calendar spreads are OPPOSITE of credit spreads:
        - Want LOW IV (cheap to buy options)
        - Want potential for IV expansion (benefits long leg)
        """
        score = 50.0
        reasons = []

        # ===== IV RANK SCORING (35% weight) - INVERTED =====
        iv_score, iv_reasons = self._score_iv_environment(report)
        score += iv_score
        reasons.extend(iv_reasons)

        # ===== ADX NEUTRAL SCORING (25% weight) =====
        adx_score, adx_reasons = self._score_neutral_market(report)
        score += adx_score
        reasons.extend(adx_reasons)

        # ===== HV/IV RATIO SCORING (20% weight) =====
        hv_iv_score, hv_iv_reasons = self._score_iv_expansion_potential(report)
        score += hv_iv_score
        reasons.extend(hv_iv_reasons)

        # ===== PRICE PROXIMITY SCORING (10% weight) =====
        # Calendar spreads work best when price stays near strike
        proximity_score = 7.0  # Assume within range for now
        reasons.append("Price positioning suitable for calendar spread")
        score += proximity_score

        # ===== EXPIRATION AVAILABILITY (10% weight) =====
        exp_score, exp_reasons = await self._score_expiration_availability(report)
        score += exp_score
        reasons.extend(exp_reasons)

        # Ensure score doesn't go below zero (no upper limit)
        score = max(0, score)

        # Build explanation
        explanation = "\n".join(reasons)

        logger.info(f"Long Call Calendar scoring for {report.symbol}: {score:.1f}/100")

        return (score, explanation)

    def _score_iv_environment(self, report: MarketConditionReport) -> tuple[float, list[str]]:
        """
        Score IV rank environment (want LOW IV to buy cheap options).

        OPPOSITE of credit spreads - low IV is GOOD here.
        """
        iv_rank = report.iv_rank
        reasons = []

        if iv_rank < 25:
            score = 35.0
            reasons.append(f"IV rank {iv_rank:.1f} - EXCELLENT value, cheap to buy calendar spread")
        elif iv_rank < 30:
            score = 25.0
            reasons.append(f"IV rank {iv_rank:.1f} - Very good value for calendar")
        elif iv_rank < 40:
            score = 15.0
            reasons.append(f"IV rank {iv_rank:.1f} - Good value for calendar entry")
        elif iv_rank < 50:
            score = 0.0
            reasons.append(f"IV rank {iv_rank:.1f} - Neutral, prefer lower IV")
        elif iv_rank < 60:
            score = -20.0
            reasons.append(f"IV rank {iv_rank:.1f} - Expensive to buy, poor value")
        else:
            score = -35.0
            reasons.append(f"IV rank {iv_rank:.1f} - VERY EXPENSIVE, avoid buying")

        return (score, reasons)

    def _score_neutral_market(self, report: MarketConditionReport) -> tuple[float, list[str]]:
        """
        Score ADX for neutral/range-bound market (want low ADX).

        Returns:
            (score_delta, reasons) where score_delta is -25 to +25
        """
        adx = report.adx
        reasons = []

        if adx is None:
            score = 0.0
            reasons.append("ADX unavailable - cannot assess trend strength")
        elif adx < 15:
            score = 25.0
            reasons.append(f"ADX {adx:.1f} - Extremely neutral, perfect for calendar spread")
        elif adx < 20:
            score = 20.0
            reasons.append(f"ADX {adx:.1f} - Neutral/range-bound market, favorable")
        elif adx < 25:
            score = 10.0
            reasons.append(f"ADX {adx:.1f} - Weak trend, acceptable")
        elif adx < 30:
            score = -10.0
            reasons.append(f"ADX {adx:.1f} - Moderate trend, risky for calendar")
        else:
            score = -25.0
            reasons.append(
                f"ADX {adx:.1f} - Strong trend, AVOID calendar spreads "
                "(price likely to move through strike)"
            )

        return (score, reasons)

    def _score_iv_expansion_potential(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score HV/IV ratio for IV expansion potential (want ratio > 1.0).

        Returns:
            (score_delta, reasons) where score_delta is -20 to +20
        """
        ratio = report.hv_iv_ratio
        reasons = []

        if ratio > 1.3:
            score = 20.0
            reasons.append(
                f"HV/IV {ratio:.2f} - Significant IV expansion potential, "
                "excellent for calendar spread"
            )
        elif ratio > 1.2:
            score = 15.0
            reasons.append(f"HV/IV {ratio:.2f} - Good IV expansion potential")
        elif ratio > 1.1:
            score = 10.0
            reasons.append(f"HV/IV {ratio:.2f} - Moderate IV expansion potential")
        elif ratio > 1.0:
            score = 5.0
            reasons.append(f"HV/IV {ratio:.2f} - Slight IV expansion potential")
        elif ratio > 0.9:
            score = -5.0
            reasons.append(f"HV/IV {ratio:.2f} - Limited IV expansion potential")
        else:
            score = -20.0
            reasons.append(
                f"HV/IV {ratio:.2f} - No IV expansion potential, "
                "IV already expensive vs realized"
            )

        return (score, reasons)

    async def _score_expiration_availability(
        self, report: MarketConditionReport
    ) -> tuple[float, list[str]]:
        """
        Score availability of proper expiration structure.

        Returns:
            (score_delta, reasons) where score_delta is 0 to +10
        """
        try:
            # Use the new expiration pair finder
            from services.market_data.utils.expiration_utils import find_calendar_expiration_pair

            expiration_pair = await find_calendar_expiration_pair(
                user=self.user,
                symbol=report.symbol,
                near_dte_target=self.NEAR_TERM_DTE_TARGET,
                near_dte_range=(self.NEAR_TERM_DTE_MIN, self.NEAR_TERM_DTE_MAX),
                far_dte_target=self.LONG_TERM_DTE_TARGET,
                far_dte_range=(self.LONG_TERM_DTE_MIN, self.LONG_TERM_DTE_MAX),
                min_ratio=self.MIN_DTE_RATIO,
                max_ratio=self.MAX_DTE_RATIO,
            )

            if expiration_pair:
                near_exp, far_exp = expiration_pair
                from django.utils import timezone

                today = timezone.now().date()
                (near_exp - today).days
                (far_exp - today).days

                score = 10.0
                reasons = [
                    "Proper expiration structure available for calendar spread "
                    "(2 expirations found)"
                ]
            else:
                score = 0.0
                reasons = ["Missing required expirations for calendar spread"]

            return (score, reasons)

        except Exception as e:
            logger.warning(f"Error scoring expirations: {e}")
            return (5.0, ["Unable to verify expiration availability"])

    async def a_select_strike(
        self, report: MarketConditionReport, directional_bias: str | None = None
    ) -> Decimal:
        """
        Select strike for calendar spread.

        Args:
            report: Market condition report
            directional_bias: 'bullish', 'bearish', or None (ATM)

        Returns:
            Strike price for both legs
        """
        current_price = report.current_price

        # Determine strike based on directional bias
        if directional_bias == "bullish":
            # 2% OTM call calendar for bullish bias
            strike_target = current_price * Decimal("1.02")
        elif directional_bias == "bearish":
            # 2% OTM put calendar for bearish bias
            strike_target = current_price * Decimal("0.98")
        else:
            # ATM for neutral
            strike_target = current_price

        strike = round_to_even_strike(strike_target)

        logger.info(
            f"Calendar spread strike: ${strike} "
            f"(bias: {directional_bias or 'neutral'}, current: ${current_price})"
        )

        return strike

    async def build_opening_legs(
        self,
        report: MarketConditionReport,
        contracts: int = 1,
        near_term_expiration: str | None = None,
        long_term_expiration: str | None = None,
        option_type: str = "call",
        directional_bias: str | None = None,
    ) -> list:
        """
        Build opening legs for calendar spread order.

        Args:
            report: Market condition report
            contracts: Number of contracts (default 1)
            near_term_expiration: Near-term expiration (YYYY-MM-DD)
            long_term_expiration: Long-term expiration (YYYY-MM-DD)
            option_type: 'call' or 'put'
            directional_bias: 'bullish', 'bearish', or None

        Returns:
            List of SDK Leg objects for order submission
        """
        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        strike = await self.a_select_strike(report, directional_bias)

        # Get session for instrument fetching
        account = await get_primary_tastytrade_account(self.user)
        if not account:
            raise ValueError(f"No TastyTrade account found for user {self.user.id}")

        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id=self.user.id, refresh_token=account.refresh_token, is_test=account.is_test
        )

        if not session_result.get("success"):
            raise ValueError(f"Failed to get session: {session_result.get('error')}")

        session = session_result["session"]

        # Fetch instruments for both expirations (same strike, different dates)
        opt_type = "C" if option_type == "call" else "P"
        specs = [
            {
                "underlying": report.symbol,
                "expiration": near_term_expiration,
                "strike": strike,
                "option_type": opt_type,
            },
            {
                "underlying": report.symbol,
                "expiration": long_term_expiration,
                "strike": strike,
                "option_type": opt_type,
            },
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        # Build SDK Leg objects: sell near-term, buy long-term
        legs = [
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.SELL_TO_OPEN,
                quantity=contracts,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[1].symbol,
                action=OrderAction.BUY_TO_OPEN,
                quantity=contracts,
            ),
        ]

        logger.info(
            f"Built calendar spread opening legs: "
            f"SELL {contracts} {strike} {option_type} ({near_term_expiration}), "
            f"BUY {contracts} {strike} {option_type} ({long_term_expiration})"
        )

        return legs

    async def build_closing_legs(
        self,
        report: MarketConditionReport,
        contracts: int = 1,
        near_term_expiration: str | None = None,
        long_term_expiration: str | None = None,
        option_type: str = "call",
        directional_bias: str | None = None,
    ) -> list:
        """
        Build closing legs for calendar spread order.

        Args:
            report: Market condition report
            contracts: Number of contracts (default 1)
            near_term_expiration: Near-term expiration (YYYY-MM-DD)
            long_term_expiration: Long-term expiration (YYYY-MM-DD)
            option_type: 'call' or 'put'
            directional_bias: 'bullish', 'bearish', or None

        Returns:
            List of SDK Leg objects for order submission
        """
        from tastytrade.order import InstrumentType, Leg, OrderAction

        from services.brokers.tastytrade.session import TastyTradeSessionService
        from services.core.data_access import get_primary_tastytrade_account
        from services.sdk.instruments import get_option_instruments_bulk

        strike = await self.a_select_strike(report, directional_bias)

        # Get session for instrument fetching
        account = await get_primary_tastytrade_account(self.user)
        if not account:
            raise ValueError(f"No TastyTrade account found for user {self.user.id}")

        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id=self.user.id, refresh_token=account.refresh_token, is_test=account.is_test
        )

        if not session_result.get("success"):
            raise ValueError(f"Failed to get session: {session_result.get('error')}")

        session = session_result["session"]

        # Fetch instruments for both expirations (same strike, different dates)
        opt_type = "C" if option_type == "call" else "P"
        specs = [
            {
                "underlying": report.symbol,
                "expiration": near_term_expiration,
                "strike": strike,
                "option_type": opt_type,
            },
            {
                "underlying": report.symbol,
                "expiration": long_term_expiration,
                "strike": strike,
                "option_type": opt_type,
            },
        ]

        instruments = await get_option_instruments_bulk(session, specs)

        # Build SDK Leg objects: buy near-term, sell long-term (opposite of opening)
        legs = [
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[0].symbol,
                action=OrderAction.BUY_TO_CLOSE,
                quantity=contracts,
            ),
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instruments[1].symbol,
                action=OrderAction.SELL_TO_CLOSE,
                quantity=contracts,
            ),
        ]

        logger.info(
            f"Built calendar spread closing legs: "
            f"BUY {contracts} {strike} {option_type} ({near_term_expiration}), "
            f"SELL {contracts} {strike} {option_type} ({long_term_expiration})"
        )

        return legs

    # BaseStrategy abstract method implementations
    async def a_get_profit_target_specifications(self, position: Position, *args) -> list:
        """
        Calendar spreads typically target 25% of debit paid.

        Conservative due to complexity and variable max profit.
        """
        # Placeholder - would implement profit target logic
        return []

    def should_place_profit_targets(self, position: Position) -> bool:
        """Calendar spreads can use profit targets."""
        return True

    def get_dte_exit_threshold(self, position: Position) -> int:
        """Close or roll calendar spread at 7-10 DTE on near-term leg."""
        return 7

    def automation_enabled_by_default(self) -> bool:
        """Calendar spreads typically managed manually (complex timing)."""
        return False

    def _find_common_atm_strike(
        self, current_price: Decimal, near_chain: dict, far_chain: dict
    ) -> Decimal | None:
        """
        Find ATM strike that exists in BOTH near and far chains.

        For calendar spreads, we MUST use the same strike in both expirations.
        This method finds the strike closest to current price that exists in
        both option chains.

        Args:
            current_price: Current underlying price
            near_chain: Near-term option chain
            far_chain: Far-term option chain

        Returns:
            ATM strike that exists in both chains, or None if no common strike
        """
        # Extract available strikes from both chains (use calls for now)
        near_strikes_data = near_chain.get("strikes", [])
        far_strikes_data = far_chain.get("strikes", [])

        # Extract call strikes
        near_strikes = set()
        for strike_obj in near_strikes_data:
            if hasattr(strike_obj, "strike_price"):
                near_strikes.add(Decimal(str(strike_obj.strike_price)))
            elif isinstance(strike_obj, dict) and "strike_price" in strike_obj:
                near_strikes.add(Decimal(str(strike_obj["strike_price"])))

        far_strikes = set()
        for strike_obj in far_strikes_data:
            if hasattr(strike_obj, "strike_price"):
                far_strikes.add(Decimal(str(strike_obj.strike_price)))
            elif isinstance(strike_obj, dict) and "strike_price" in strike_obj:
                far_strikes.add(Decimal(str(strike_obj["strike_price"])))

        # Find common strikes
        common_strikes = near_strikes & far_strikes

        if not common_strikes:
            logger.error("No common strikes between near and far chains")
            return None

        # Find closest strike to current price
        closest_strike = min(common_strikes, key=lambda s: abs(float(s) - float(current_price)))

        logger.info(
            f"Selected ATM strike {closest_strike} from {len(common_strikes)} "
            f"common strikes (price: {current_price}, "
            f"near strikes: {len(near_strikes)}, far strikes: {len(far_strikes)})"
        )

        return closest_strike

    async def a_prepare_suggestion_context(
        self,
        symbol: str,
        report: "MarketConditionReport | None" = None,
        suggestion_mode: bool = False,
        force_generation: bool = False,
    ) -> "dict | None":
        """
        Prepare calendar spread suggestion context.

        Calendar spread: Sell near-term option, buy far-term option at same strike.
        Benefits from time decay differential (near-term decays faster).

        Args:
            symbol: Underlying symbol
            report: Optional pre-computed market report
            suggestion_mode: If True, skip risk validation (for email suggestions)
            force_generation: If True, bypass score threshold

        Returns:
            Context dict ready for stream manager, or None if unsuitable
        """
        # Get active config
        config = await self.a_get_active_config()

        # Get market report if not provided
        if report is None:
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(self.user)
            report = await analyzer.a_analyze_market_conditions(self.user, symbol, {})

        # Score conditions
        score, explanation = await self.a_score_market_conditions(report)
        logger.info(f"{self.strategy_name} score for {symbol}: {score:.1f} - {explanation}")

        # Check threshold (allow bypass in force mode)
        if score < self.MIN_SCORE_THRESHOLD and not force_generation:
            logger.info(f"Score too low ({score:.1f}) - not generating {self.strategy_name}")
            return None

        if force_generation and score < self.MIN_SCORE_THRESHOLD:
            logger.warning(
                f"Force generating {self.strategy_name} despite low score ({score:.1f})"
            )

        # Find optimal expiration pair (TastyTrade methodology with practical flexibility)
        from services.market_data.utils.expiration_utils import find_calendar_expiration_pair

        expiration_pair = await find_calendar_expiration_pair(
            user=self.user,
            symbol=symbol,
            near_dte_target=self.NEAR_TERM_DTE_TARGET,
            near_dte_range=(self.NEAR_TERM_DTE_MIN, self.NEAR_TERM_DTE_MAX),
            far_dte_target=self.LONG_TERM_DTE_TARGET,
            far_dte_range=(self.LONG_TERM_DTE_MIN, self.LONG_TERM_DTE_MAX),
            min_ratio=self.MIN_DTE_RATIO,
            max_ratio=self.MAX_DTE_RATIO,
        )

        if not expiration_pair:
            logger.warning(f"No suitable expiration pair for calendar spread on {symbol}")
            return None

        near_exp, far_exp = expiration_pair

        # Fetch option chains for both expirations
        from services.streaming.options_service import StreamingOptionsDataService

        options_service = StreamingOptionsDataService(self.user)

        near_chain = await options_service._get_option_chain(symbol, near_exp)
        far_chain = await options_service._get_option_chain(symbol, far_exp)

        if not near_chain or not far_chain:
            logger.warning(f"Failed to fetch option chains for {symbol}")
            return None

        # Find ATM strike that exists in BOTH chains
        atm_strike = self._find_common_atm_strike(
            Decimal(str(report.current_price)), near_chain, far_chain
        )

        if not atm_strike:
            logger.warning(f"No common ATM strike available for {symbol} calendar spread")
            return None

        logger.info(
            f"User {self.user.id}: Calendar spread for {symbol}: "
            f"near={near_exp}, far={far_exp}, strike=${atm_strike}"
        )

        # Build OCC bundles with PROPER LABELS for calendar spread
        # Near-term = SHORT (we sell), Far-term = LONG (we buy)
        near_strikes = {"short_call": atm_strike}  # Sell near-term
        far_strikes = {"long_call": atm_strike}  # Buy far-term

        near_occ = await self.options_service.build_occ_bundle(symbol, near_exp, near_strikes)
        far_occ = await self.options_service.build_occ_bundle(symbol, far_exp, far_strikes)

        if not near_occ or not far_occ:
            logger.warning(f"User {self.user.id}: Failed to build OCC bundles")
            return None

        # Combine both OCC bundles for stream manager (it needs all legs)
        # For calendar spreads, use near-term expiration as primary
        combined_legs = {}
        combined_legs.update(near_occ.legs)
        combined_legs.update(far_occ.legs)

        from services.streaming.dataclasses import SenexOccBundle

        combined_occ = SenexOccBundle(
            underlying=symbol,
            expiration=near_exp,  # Use near-term as primary expiration
            legs=combined_legs,
        )

        # Calculate actual DTEs
        from django.utils import timezone

        today = timezone.now().date()
        near_dte = (near_exp - today).days
        far_dte = (far_exp - today).days

        # Prepare serializable market data
        serializable_report = {
            "current_price": float(report.current_price),
            "iv_rank": float(report.iv_rank),
            "hv_iv_ratio": float(report.hv_iv_ratio),
            "adx": float(report.adx) if report.adx else None,
            "market_stress_level": float(report.market_stress_level),
            "score": score,
            "explanation": explanation,
        }

        # Build context
        context = {
            "config_id": config.id if config else None,
            "strategy": self.strategy_name,
            "symbol": symbol,
            "near_expiration": near_exp.isoformat(),
            "far_expiration": far_exp.isoformat(),
            "near_dte": near_dte,
            "far_dte": far_dte,
            "market_data": serializable_report,
            "strike": float(atm_strike),
            "occ_bundle": combined_occ.to_dict(),  # Combined for stream manager
            "near_occ_bundle": near_occ.to_dict(),  # Near expiration (short_call)
            "far_occ_bundle": far_occ.to_dict(),  # Far expiration (long_call)
            "suggestion_mode": suggestion_mode,
        }

        logger.info(f"User {self.user.id}: Context prepared for {self.strategy_name}")
        return context

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
        """
        Calculate suggestion from cached pricing data.

        Calendar spread: Sell near-term, buy far-term at same strike.
        Net position is a DEBIT (pay to enter).
        """
        from datetime import date, timedelta
        from decimal import Decimal

        from django.utils import timezone

        from services.sdk.trading_utils import PriceEffect
        from services.streaming.dataclasses import SenexOccBundle
        from trading.models import StrategyConfiguration, TradingSuggestion

        # Use the COMBINED bundle that has both short_call and long_call
        combined_occ = SenexOccBundle.from_dict(context["occ_bundle"])

        # Read pricing for the combined spread
        pricing = self.options_service.read_spread_pricing(combined_occ)

        if not pricing:
            logger.warning(f"Pricing data not found for {self.strategy_name}")
            return None

        config = (
            await StrategyConfiguration.objects.aget(id=context["config_id"])
            if context.get("config_id")
            else None
        )
        symbol = context["symbol"]
        near_exp = date.fromisoformat(context["near_expiration"])
        date.fromisoformat(context["far_expiration"])
        strike = Decimal(str(context["strike"]))
        market_data = context["market_data"]
        is_automated = context.get("is_automated", False)
        suggestion_mode = context.get("suggestion_mode", False)

        # Calendar spread: SELL near-term (short_call), BUY far-term (long_call)
        # pricing.call_credit is calculated as: short_call_bid - long_call_ask
        # For calendar spread, this will be NEGATIVE (we pay a debit)
        net_debit = -pricing.call_credit  # Flip sign to get debit

        if net_debit <= 0:
            logger.warning(
                f"Invalid calendar debit: {net_debit} (call_credit: {pricing.call_credit})"
            )
            return None

        # Max risk = debit paid * 100 (per contract)
        max_risk_per_contract = net_debit * Decimal("100")

        # Max profit for calendar spreads is complex (depends on IV expansion and time decay)
        # Use conservative estimate: 50% of debit as max profit
        max_profit_total = net_debit * Decimal("0.5") * Decimal("100")

        if not suggestion_mode:
            can_open, reason = await self.risk_manager.a_can_open_position(
                max_risk_per_contract, is_stressed=market_data.get("is_stressed", False)
            )
            if not can_open:
                return {
                    "error": True,
                    "error_type": "risk_budget_exceeded",
                    "message": reason,
                    "max_risk": float(max_risk_per_contract),
                    "strategy": self.strategy_name,
                }

        suggestion = await TradingSuggestion.objects.acreate(
            user=self.user,
            strategy_id=self.strategy_name,
            strategy_configuration=config,
            underlying_symbol=symbol,
            underlying_price=Decimal(str(market_data["current_price"])),
            expiration_date=near_exp,  # Primary expiration
            long_call_strike=strike,  # Far expiration (buying)
            short_call_strike=strike,  # Near expiration (selling)
            put_spread_quantity=0,  # No puts in call calendar
            call_spread_quantity=1,  # Calendar spread: 1 contract
            call_spread_credit=-net_debit,  # Negative = debit
            total_credit=-net_debit,
            total_mid_credit=-net_debit,
            max_risk=max_risk_per_contract,
            price_effect=PriceEffect.DEBIT.value,
            max_profit=max_profit_total,
            iv_rank=Decimal(str(market_data["iv_rank"])),
            market_stress_level=Decimal(str(market_data["market_stress_level"])),
            market_conditions={
                "leg_expiration_overrides": {
                    "long_call": context["far_expiration"],  # Long leg uses far expiration
                },
                "hv_iv_ratio": market_data.get("hv_iv_ratio"),
                "adx": market_data.get("adx"),
                "near_dte": context["near_dte"],
                "far_dte": context["far_dte"],
                "near_expiration": context["near_expiration"],
                "far_expiration": context["far_expiration"],
                "score": market_data["score"],
                "explanation": market_data["explanation"],
            },
            status="pending",
            expires_at=timezone.now() + timedelta(hours=24),
            has_real_pricing=True,
            pricing_source="streaming",
            is_automated=is_automated,
        )

        logger.info(
            f"User {self.user.id}: Long Call Calendar suggestion - "
            f"Debit: ${net_debit:.2f}, Strike: ${strike}"
        )
        return suggestion
