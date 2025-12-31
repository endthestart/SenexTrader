"""
Vertical Spread Builder for unified strategy architecture.

Builds all four vertical spread types from VerticalSpreadParams:
- Bull Put Spread (credit): BULLISH + PUT
- Bear Call Spread (credit): BEARISH + CALL
- Bull Call Spread (debit): BULLISH + CALL
- Bear Put Spread (debit): BEARISH + PUT

The builder handles:
1. Strike selection from available option chains (via StrikeOptimizer or DeltaStrikeSelector)
2. Expiration selection with DTE targeting
3. Leg composition with proper sides (SHORT/LONG)
4. Quality scoring for trade assessment
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from services.core.logging import get_logger
from services.strategies.core import (
    Direction,
    OptionContract,
    OptionType,
    Side,
    StrategyComposition,
    StrategyLeg,
    StrikeSelection,
    VerticalSpreadParams,
)
from services.strategies.quality import QualityScore

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = get_logger(__name__)


@dataclass
class BuildResult:
    """
    Result of a strategy build operation.

    Contains either a successful composition or error information.
    This allows callers to handle failures gracefully and provide
    meaningful feedback to users.

    Attributes:
        composition: The built strategy composition (None on failure)
        expiration: Selected expiration date
        strikes: Dict of selected strikes
        success: Whether the build succeeded
        error_message: Error description on failure
        quality: Full quality assessment (replaces quality_score)
    """

    composition: StrategyComposition | None
    expiration: date | None
    strikes: dict[str, Decimal] | None
    success: bool
    error_message: str | None = None
    quality: QualityScore | None = None

    @classmethod
    def success_result(
        cls,
        composition: StrategyComposition,
        expiration: date,
        strikes: dict[str, Decimal],
        quality: QualityScore | None = None,
    ) -> "BuildResult":
        """Create a successful build result."""
        return cls(
            composition=composition,
            expiration=expiration,
            strikes=strikes,
            success=True,
            error_message=None,
            quality=quality,
        )

    @classmethod
    def failure_result(cls, error_message: str) -> "BuildResult":
        """Create a failed build result."""
        return cls(
            composition=None,
            expiration=None,
            strikes=None,
            success=False,
            error_message=error_message,
        )


class VerticalSpreadBuilder:
    """
    Builds vertical spread strategies from parameters.

    This builder transforms VerticalSpreadParams into executable
    StrategyComposition objects by:
    1. Finding optimal expiration within DTE range
    2. Selecting strikes from available option chains
    3. Composing legs with correct sides based on direction

    The builder uses the StrikeOptimizer for quality-gated strike
    selection, ensuring trades are within acceptable deviation
    from theoretical targets.

    Attributes:
        user: Django user for API access

    Example:
        >>> builder = VerticalSpreadBuilder(user)
        >>> params = VerticalSpreadParams.bull_put_defaults(width_min=5, width_max=5)
        >>> result = await builder.build("QQQ", params)
        >>> if result.success:
        ...     composition = result.composition
        ...     print(f"Built {len(composition.legs)} leg spread")
    """

    def __init__(self, user: "User"):
        self.user = user

    async def build(
        self,
        symbol: str,
        params: VerticalSpreadParams,
        current_price: Decimal | None = None,
        support_level: Decimal | None = None,
        resistance_level: Decimal | None = None,
        market_context: dict | None = None,
    ) -> BuildResult:
        """
        Build a vertical spread composition from parameters.

        Supports two selection methods:
        - DELTA: Use DeltaStrikeSelector for delta-based targeting
        - OTM_PERCENT: Use StrikeOptimizer for OTM percentage targeting

        Args:
            symbol: Underlying symbol (e.g., "QQQ", "SPY")
            params: VerticalSpreadParams with strategy configuration
            current_price: Current underlying price (fetched if not provided)
            support_level: Support level for put spread adjustment
            resistance_level: Resistance level for call spread adjustment
            market_context: Optional market context (IV, stress level)

        Returns:
            BuildResult with composition and quality on success
        """
        from services.streaming.options_service import StreamingOptionsDataService

        logger.info(
            f"Building {params.spread_type_name} for {symbol} "
            f"(DTE: {params.dte_min}-{params.dte_max}, width: {params.effective_width_target}, "
            f"selection: {params.selection_method.value})"
        )

        # Get current price if not provided
        if current_price is None:
            options_service = StreamingOptionsDataService(self.user)
            current_price = await self._get_current_price(symbol, options_service)
            if current_price is None:
                return BuildResult.failure_result(
                    f"Could not fetch current price for {symbol}"
                )

        # Route to appropriate selection method
        if params.selection_method == StrikeSelection.DELTA and params.delta_target:
            return await self._build_with_delta_selection(
                symbol=symbol,
                params=params,
                current_price=current_price,
                market_context=market_context,
            )

        # Default: OTM percentage selection
        return await self._build_with_otm_selection(
            symbol=symbol,
            params=params,
            current_price=current_price,
            support_level=support_level,
            resistance_level=resistance_level,
        )

    async def _build_with_delta_selection(
        self,
        symbol: str,
        params: VerticalSpreadParams,
        current_price: Decimal,
        market_context: dict | None = None,
    ) -> BuildResult:
        """Build using delta-based strike selection."""
        from datetime import timedelta

        from django.utils import timezone

        from services.market_data.option_chains import OptionChainService
        from services.strategies.strike_selection import DeltaStrikeSelector

        chain_service = OptionChainService()

        # Get all expirations
        all_expirations = await chain_service.a_get_all_expirations(self.user, symbol)
        if not all_expirations:
            return BuildResult.failure_result(
                f"Could not fetch expirations for {symbol}"
            )

        # Filter to DTE range
        today = timezone.now().date()
        min_exp = today + timedelta(days=params.dte_min)
        max_exp = today + timedelta(days=params.dte_max)

        valid_expirations = [
            exp for exp in all_expirations
            if min_exp <= exp <= max_exp
        ]

        if not valid_expirations:
            return BuildResult.failure_result(
                f"No expirations found for {symbol} in DTE range {params.dte_min}-{params.dte_max}"
            )

        # Use first valid expiration (closest to min DTE)
        expiration = sorted(valid_expirations)[0]

        # Get option chain for this expiration
        chain = await chain_service.a_get_chain_for_expiration(
            self.user, symbol, expiration
        )

        if not chain:
            return BuildResult.failure_result(
                f"Could not fetch option chain for {symbol} exp {expiration}"
            )

        # Build chain_strikes list for selector
        chain_strikes = self._build_chain_strikes(chain)

        if not chain_strikes:
            return BuildResult.failure_result(
                f"Option chain empty for {symbol} exp {expiration}"
            )

        # Use DeltaStrikeSelector
        selector = DeltaStrikeSelector(self.user)
        spread_type = self._get_spread_type(params)

        result = await selector.select_strikes(
            symbol=symbol,
            expiration=expiration,
            chain_strikes=chain_strikes,
            spread_type=spread_type,
            spread_width=params.effective_width_target,
            target_delta=params.delta_target,
            current_price=current_price,
            market_context=market_context,
        )

        if not result:
            return BuildResult.failure_result(
                f"Delta selection failed for {symbol} (target delta: {params.delta_target})"
            )

        # Convert StrikeQualityResult to QualityScore
        quality = QualityScore(
            score=result.quality.score,
            level=result.quality.level,
            warnings=result.quality.warnings,
            component_scores=result.quality.component_scores,
        )

        # Build composition
        composition = self._build_composition(
            symbol=symbol,
            expiration=expiration,
            strikes=result.strikes,
            params=params,
        )

        logger.info(
            f"Built {params.spread_type_name} for {symbol} via delta selection: "
            f"expiration={expiration}, strikes={result.strikes}, "
            f"delta={result.delta:.3f} ({result.delta_source}), quality={quality.score:.1f}"
        )

        return BuildResult.success_result(
            composition=composition,
            expiration=expiration,
            strikes=result.strikes,
            quality=quality,
        )

    async def _build_with_otm_selection(
        self,
        symbol: str,
        params: VerticalSpreadParams,
        current_price: Decimal,
        support_level: Decimal | None = None,
        resistance_level: Decimal | None = None,
    ) -> BuildResult:
        """Build using OTM percentage selection (original method)."""
        from services.market_data.utils.expiration_utils import (
            find_expiration_with_optimal_strikes,
        )
        from services.strategies.core.parameters import GenerationMode

        spread_type = self._get_spread_type(params)

        target_criteria = {
            "spread_type": spread_type,
            "otm_pct": params.otm_percent,
            "spread_width": params.effective_width_target,
            "current_price": current_price,
            "support_level": support_level,
            "resistance_level": resistance_level,
        }

        relaxed_quality = params.generation_mode in [
            GenerationMode.RELAXED,
            GenerationMode.FORCE,
        ]

        result = await find_expiration_with_optimal_strikes(
            user=self.user,
            symbol=symbol,
            target_criteria=target_criteria,
            min_dte=params.dte_min,
            max_dte=params.dte_max,
            relaxed_quality=relaxed_quality,
        )

        if not result:
            threshold = "15%" if relaxed_quality else "5%"
            return BuildResult.failure_result(
                f"No expiration found with strikes within {threshold} quality threshold "
                f"for {symbol} (DTE: {params.dte_min}-{params.dte_max})"
            )

        expiration, strikes, _chain = result

        composition = self._build_composition(
            symbol=symbol,
            expiration=expiration,
            strikes=strikes,
            params=params,
        )

        logger.info(
            f"Built {params.spread_type_name} for {symbol} via OTM selection: "
            f"expiration={expiration}, strikes={strikes}"
        )

        return BuildResult.success_result(
            composition=composition,
            expiration=expiration,
            strikes=strikes,
        )

    def _build_chain_strikes(self, chain: list) -> list[dict]:
        """Convert option chain to chain_strikes format for DeltaStrikeSelector."""
        chain_strikes = []
        for item in chain:
            strike_dict = {"strike_price": item.get("strike_price")}
            if "put" in item:
                strike_dict["put"] = item["put"]
            if "call" in item:
                strike_dict["call"] = item["call"]
            if "put_symbol" in item:
                strike_dict["put"] = item["put_symbol"]
            if "call_symbol" in item:
                strike_dict["call"] = item["call_symbol"]
            chain_strikes.append(strike_dict)
        return chain_strikes

    async def build_from_strikes(
        self,
        symbol: str,
        expiration: date,
        short_strike: Decimal,
        long_strike: Decimal,
        params: VerticalSpreadParams,
        quality: QualityScore | None = None,
    ) -> BuildResult:
        """
        Build a vertical spread from explicit strikes.

        Use this when strikes are already known (e.g., from manual selection
        or a previous calculation). Skips the strike optimization step.

        Args:
            symbol: Underlying symbol
            expiration: Option expiration date
            short_strike: Strike to sell
            long_strike: Strike to buy
            params: VerticalSpreadParams (for direction/option_type)
            quality: Optional quality score (passed through if provided)

        Returns:
            BuildResult with composition
        """
        # Determine strike keys based on option type
        if params.option_type == OptionType.PUT:
            strikes = {"short_put": short_strike, "long_put": long_strike}
        else:
            strikes = {"short_call": short_strike, "long_call": long_strike}

        composition = self._build_composition(
            symbol=symbol,
            expiration=expiration,
            strikes=strikes,
            params=params,
        )

        return BuildResult.success_result(
            composition=composition,
            expiration=expiration,
            strikes=strikes,
            quality=quality,
        )

    def _get_spread_type(self, params: VerticalSpreadParams) -> str:
        """Map params to spread type string for optimizer."""
        if params.direction == Direction.BULLISH:
            if params.option_type == OptionType.PUT:
                return "bull_put"
            return "bull_call"
        # BEARISH
        if params.option_type == OptionType.CALL:
            return "bear_call"
        return "bear_put"

    def _build_composition(
        self,
        symbol: str,
        expiration: date,
        strikes: dict[str, Decimal],
        params: VerticalSpreadParams,
    ) -> StrategyComposition:
        """
        Build StrategyComposition from strikes and parameters.

        Determines leg sides based on direction and option type:
        - Credit spreads (bull put, bear call): SHORT near ATM, LONG further OTM
        - Debit spreads (bull call, bear put): LONG near ATM, SHORT further OTM
        """
        legs = []

        if params.option_type == OptionType.PUT:
            short_strike = strikes["short_put"]
            long_strike = strikes["long_put"]

            # For put spreads: short_put > long_put (short is closer to ATM)
            if params.is_credit_spread:
                # Bull Put (credit): SELL higher strike, BUY lower strike
                short_leg = self._create_leg(
                    symbol, expiration, short_strike, OptionType.PUT, Side.SHORT, params.quantity
                )
                long_leg = self._create_leg(
                    symbol, expiration, long_strike, OptionType.PUT, Side.LONG, params.quantity
                )
            else:
                # Bear Put (debit): BUY higher strike, SELL lower strike
                short_leg = self._create_leg(
                    symbol, expiration, short_strike, OptionType.PUT, Side.LONG, params.quantity
                )
                long_leg = self._create_leg(
                    symbol, expiration, long_strike, OptionType.PUT, Side.SHORT, params.quantity
                )

            legs = [short_leg, long_leg]

        else:  # CALL
            short_strike = strikes["short_call"]
            long_strike = strikes["long_call"]

            # For call spreads: long_call > short_call (long is further OTM)
            if params.is_credit_spread:
                # Bear Call (credit): SELL lower strike, BUY higher strike
                short_leg = self._create_leg(
                    symbol, expiration, short_strike, OptionType.CALL, Side.SHORT, params.quantity
                )
                long_leg = self._create_leg(
                    symbol, expiration, long_strike, OptionType.CALL, Side.LONG, params.quantity
                )
            else:
                # Bull Call (debit): BUY lower strike, SELL higher strike
                short_leg = self._create_leg(
                    symbol, expiration, short_strike, OptionType.CALL, Side.LONG, params.quantity
                )
                long_leg = self._create_leg(
                    symbol, expiration, long_strike, OptionType.CALL, Side.SHORT, params.quantity
                )

            legs = [short_leg, long_leg]

        return StrategyComposition(legs=legs)

    def _create_leg(
        self,
        symbol: str,
        expiration: date,
        strike: Decimal,
        option_type: OptionType,
        side: Side,
        quantity: int,
    ) -> StrategyLeg:
        """Create a single strategy leg."""
        contract = OptionContract(
            symbol=symbol,
            option_type=option_type,
            strike=strike,
            expiration=expiration,
        )
        return StrategyLeg(contract=contract, side=side, quantity=quantity)

    async def _get_current_price(
        self, symbol: str, options_service
    ) -> Decimal | None:
        """Fetch current price for symbol from streaming cache or market data."""
        from services.market_data.service import MarketDataService

        # Try streaming cache first
        quote = options_service.read_underlying_quote(symbol)
        if quote and quote.last_price:
            return Decimal(str(quote.last_price))

        # Fall back to market data service
        market_service = MarketDataService()
        price = await market_service.a_get_current_price(self.user, symbol)
        if price:
            return Decimal(str(price))

        return None
