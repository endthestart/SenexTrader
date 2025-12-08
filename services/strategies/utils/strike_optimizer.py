"""
Strike optimization utilities for flexible strike selection from available strikes.

This module implements the "strikes-from-available" pattern where we:
1. Fetch all available strikes from the option chain
2. Find the optimal strikes from what actually exists
3. Enforce quality thresholds to ensure reasonable trades

This is the correct approach vs. the old "calculate-then-fail" pattern.
"""

from decimal import Decimal
from typing import Literal

from services.core.logging import get_logger

logger = get_logger(__name__)


class StrikeOptimizer:
    """
    Optimizes strike selection from available strikes in option chains.

    Uses theta-first optimization (maximize premium collection) while
    enforcing quality thresholds to prevent trades too far from ideal.
    """

    DEVIATION_THRESHOLD_PCT = 5.0  # Reject if >5% deviation from ideal

    def find_optimal_spread_strikes(
        self,
        available_strikes: list[Decimal],
        current_price: Decimal,
        spread_width: int,
        spread_type: Literal["bull_put", "bear_call", "bear_put", "bull_call"],
        target_otm_pct: float = 0.03,
        support_level: Decimal | None = None,
        resistance_level: Decimal | None = None,
        relaxed_quality: bool = False,
    ) -> dict[str, Decimal] | None:
        """
        Find optimal credit spread strikes from available strikes.

        Algorithm:
        1. Calculate ideal short strike (target % OTM, adjusted for support/resistance)
        2. Find closest available strike to ideal
        3. Validate within deviation threshold (quality gate)
        4. Calculate long strike (spread_width away)
        5. Validate long strike exists in available strikes
        6. Return strikes or None if quality gate fails

        Args:
            available_strikes: List of available strikes from option chain
            current_price: Current underlying price
            spread_width: Width of spread in points
            spread_type: "bull_put" or "bear_call"
            target_otm_pct: Target out-of-the-money percentage (default 3%)
            support_level: Support price level (for bull put adjustment)
            resistance_level: Resistance price level (for bear call adjustment)
            relaxed_quality: If True, use 15% threshold instead of 5% (for force mode)

        Returns:
            Dict with strike keys or None if no suitable strikes found

        Examples:
            >>> optimizer = StrikeOptimizer()
            >>> available = [Decimal('250'), Decimal('252.5'), Decimal('255')]
            >>> result = optimizer.find_optimal_spread_strikes(
            ...     available, Decimal('260'), 5, "bull_put", 0.03
            ... )
            >>> result
            {'short_put': Decimal('252.5'), 'long_put': Decimal('247.5')}
        """
        if not available_strikes:
            logger.warning("No available strikes provided to optimizer")
            return None

        # Sort strikes for easier processing
        available_strikes_sorted = sorted(available_strikes)

        # 1. Calculate ideal short strike
        if spread_type in ["bull_put", "bear_put"]:
            # Put spreads: short strike below current price (3% OTM)
            ideal_short = current_price * Decimal(str(1 - target_otm_pct))

            # Adjust for support level if provided (stay 2% above support)
            if support_level:
                min_short = support_level * Decimal("1.02")  # 2% buffer above support
                ideal_short = max(ideal_short, min_short)
                logger.debug(
                    f"{spread_type}: Adjusted ideal short from support. "
                    f"Support: ${support_level:.2f}, Min short: ${min_short:.2f}"
                )

        else:  # bear_call or bull_call
            # Call spreads: short strike above current price (3% OTM)
            ideal_short = current_price * Decimal(str(1 + target_otm_pct))

            # Adjust for resistance level if provided (stay 2% below resistance)
            if resistance_level:
                max_short = resistance_level * Decimal("0.98")  # 2% buffer below resistance
                ideal_short = min(ideal_short, max_short)
                logger.debug(
                    f"{spread_type}: Adjusted ideal short from resistance. "
                    f"Resistance: ${resistance_level:.2f}, Max short: ${max_short:.2f}"
                )

        logger.info(
            f"{spread_type}: Ideal short strike calculated: ${ideal_short:.2f} "
            f"(current price: ${current_price:.2f}, target {target_otm_pct*100:.0f}% OTM)"
        )

        # 2. Find closest available strike to ideal
        closest_short = self._find_closest_strike(ideal_short, available_strikes_sorted)
        if not closest_short:
            logger.warning(f"Could not find closest strike to ideal ${ideal_short:.2f}")
            return None

        # 3. Validate within deviation threshold (quality gate)
        # Use relaxed 15% threshold if relaxed_quality=True (force mode)
        threshold = 15.0 if relaxed_quality else self.DEVIATION_THRESHOLD_PCT
        if not self.validate_deviation(ideal_short, closest_short, threshold):
            deviation_pct = abs(float((closest_short - ideal_short) / ideal_short)) * 100
            mode_info = " (relaxed mode)" if relaxed_quality else ""
            logger.warning(
                f"Closest strike ${closest_short:.2f} deviates {deviation_pct:.1f}% "
                f"from ideal ${ideal_short:.2f} (threshold: {threshold}%{mode_info}) "
                f"- rejecting to maintain quality"
            )
            return None

        logger.info(f"Selected short strike: ${closest_short:.2f} (closest to ideal)")

        # 4. Calculate long strike (spread_width away)
        if spread_type in ["bull_put", "bear_put"]:
            # Put spreads: long put below short put
            ideal_long = closest_short - Decimal(str(spread_width))
        else:  # bear_call or bull_call
            # Call spreads: long call above short call
            ideal_long = closest_short + Decimal(str(spread_width))

        # 5. Validate long strike exists in available strikes
        # Try exact match first
        if ideal_long in available_strikes_sorted:
            logger.info(f"Found exact long strike: ${ideal_long:.2f}")
            long_strike = ideal_long
        else:
            # Find closest to ideal long strike
            closest_long = self._find_closest_strike(ideal_long, available_strikes_sorted)
            if not closest_long:
                logger.warning(f"No available long strike near ${ideal_long:.2f}")
                return None

            # Be more permissive for long strike (it's just for risk definition)
            # Allow up to 10% deviation for long strike
            if not self.validate_deviation(ideal_long, closest_long, threshold_pct=10.0):
                logger.warning(
                    f"Closest long strike ${closest_long:.2f} too far "
                    f"from ideal ${ideal_long:.2f} (>10% deviation)"
                )
                return None

            logger.info(
                f"Selected long strike: ${closest_long:.2f} "
                f"(closest to ideal ${ideal_long:.2f})"
            )
            long_strike = closest_long

        # Validate directional relationship to prevent invalid spreads
        if spread_type in ["bull_put", "bear_put"]:
            # Put spreads: long put must be BELOW short put
            if long_strike >= closest_short:
                logger.warning(
                    f"Invalid {spread_type} spread: long ${long_strike} >= short ${closest_short}"
                )
                return None
        # Call spreads: long call must be ABOVE short call
        elif long_strike <= closest_short:
            logger.warning(
                f"Invalid {spread_type} spread: long ${long_strike} <= short ${closest_short}"
            )
            return None

        # Log successful validation
        logger.info(
            f"Valid {spread_type} spread: "
            f"short ${closest_short} -> long ${long_strike} "
            f"(width: {abs(long_strike - closest_short)})"
        )

        # 6. Return strikes dict
        if spread_type in ["bull_put", "bear_put"]:
            return {"short_put": closest_short, "long_put": long_strike}
        # bear_call or bull_call
        return {"short_call": closest_short, "long_call": long_strike}

    def detect_strike_interval(self, strikes: list[Decimal]) -> Decimal:
        """
        Detect strike interval from available strikes.

        Analyzes the gaps between consecutive strikes to infer the interval.
        Handles common intervals: $1, $2.50, $5, $10, etc.

        Args:
            strikes: List of available strikes (should be sorted)

        Returns:
            Decimal: Detected interval (e.g., Decimal('1.0'), Decimal('2.5'))

        Examples:
            >>> optimizer = StrikeOptimizer()
            >>> strikes = [Decimal('100'), Decimal('105'), Decimal('110')]
            >>> optimizer.detect_strike_interval(strikes)
            Decimal('5.0')

            >>> strikes = [Decimal('50'), Decimal('52.5'), Decimal('55')]
            >>> optimizer.detect_strike_interval(strikes)
            Decimal('2.5')
        """
        if len(strikes) < 2:
            # Default to $1 if not enough data
            logger.warning("Fewer than 2 strikes provided, defaulting to $1 interval")
            return Decimal("1.0")

        # Calculate gaps between consecutive strikes
        strikes_sorted = sorted(strikes)
        gaps = [strikes_sorted[i + 1] - strikes_sorted[i] for i in range(len(strikes_sorted) - 1)]

        # Find most common gap (mode)
        # Use Counter to find most frequent gap
        from collections import Counter

        gap_counts = Counter(gaps)
        most_common_gap, count = gap_counts.most_common(1)[0]

        logger.debug(
            f"Detected strike interval: ${most_common_gap} " f"(found in {count}/{len(gaps)} gaps)"
        )

        return most_common_gap

    def validate_deviation(
        self, ideal_strike: Decimal, closest_strike: Decimal, threshold_pct: float = 5.0
    ) -> bool:
        """
        Validate that closest strike is within acceptable deviation from ideal.

        Args:
            ideal_strike: Theoretical ideal strike price
            closest_strike: Closest available strike from option chain
            threshold_pct: Maximum acceptable deviation percentage (default 5%)

        Returns:
            bool: True if within threshold, False if exceeds threshold

        Examples:
            >>> optimizer = StrikeOptimizer()
            >>> optimizer.validate_deviation(Decimal('100'), Decimal('101'), 5.0)
            True  # 1% deviation < 5% threshold

            >>> optimizer.validate_deviation(Decimal('100'), Decimal('110'), 5.0)
            False  # 10% deviation > 5% threshold
        """
        if ideal_strike == 0:
            logger.error("Ideal strike is zero - cannot validate deviation")
            return False

        # Calculate absolute percentage deviation
        deviation = abs(float((closest_strike - ideal_strike) / ideal_strike)) * 100

        is_valid = deviation <= threshold_pct

        logger.debug(
            f"Deviation check: ideal=${ideal_strike:.2f}, closest=${closest_strike:.2f}, "
            f"deviation={deviation:.2f}%, threshold={threshold_pct}% → "
            f"{'PASS' if is_valid else 'FAIL'}"
        )

        return is_valid

    def _find_closest_strike(
        self, target: Decimal, available_strikes: list[Decimal]
    ) -> Decimal | None:
        """
        Find the closest available strike to a target price.

        Args:
            target: Target strike price
            available_strikes: Sorted list of available strikes

        Returns:
            Decimal: Closest available strike, or None if no strikes available

        Examples:
            >>> optimizer = StrikeOptimizer()
            >>> strikes = [Decimal('100'), Decimal('105'), Decimal('110')]
            >>> optimizer._find_closest_strike(Decimal('103'), strikes)
            Decimal('105')  # Closer to 105 than 100
        """
        if not available_strikes:
            return None

        # Find strike with minimum absolute distance to target
        return min(available_strikes, key=lambda strike: abs(strike - target))

    async def find_strike_by_delta(
        self,
        user,
        symbol: str,
        expiration,
        option_type: Literal["put", "call"],
        target_delta: float,
        available_strikes: list[Decimal],
        options_service=None,
    ) -> tuple[Decimal | None, float | None]:
        """
        Find the strike with delta closest to target using live Greeks.

        This is the preferred method for strike selection as it adapts to:
        - Current implied volatility
        - Time to expiration
        - Market conditions

        Args:
            user: Django user for API access
            symbol: Underlying symbol (e.g., 'QQQ')
            expiration: Option expiration date
            option_type: "put" or "call"
            target_delta: Target delta (e.g., 0.20 for 20 delta put)
            available_strikes: List of available strikes from option chain
            options_service: Optional StreamingOptionsDataService instance

        Returns:
            (strike, actual_delta) tuple, or (None, None) if no Greeks available

        Example:
            >>> optimizer = StrikeOptimizer()
            >>> strike, delta = await optimizer.find_strike_by_delta(
            ...     user, "QQQ", date(2024, 12, 20), "put", 0.20,
            ...     [Decimal('600'), Decimal('605'), Decimal('610'), ...]
            ... )
            >>> print(f"Found strike ${strike} with delta {delta}")
            Found strike $608 with delta -0.198
        """
        if not available_strikes:
            logger.warning("No available strikes provided for delta search")
            return (None, None)

        # Import here to avoid circular imports
        from services.sdk.instruments import build_occ_symbol
        from services.streaming.options_service import StreamingOptionsDataService

        if options_service is None:
            options_service = StreamingOptionsDataService(user)

        # Pre-filter strikes to a reasonable range around ATM
        # For puts, we want strikes below current price
        # For calls, we want strikes above current price
        # This reduces the number of Greeks lookups needed

        # For puts, target delta is negative (e.g., -0.20)
        # For calls, target delta is positive (e.g., 0.20)
        target_delta_signed = -abs(target_delta) if option_type == "put" else abs(target_delta)

        best_strike = None
        best_delta = None
        best_delta_diff = float("inf")
        strikes_with_greeks = 0

        # Sort strikes for logical processing
        sorted_strikes = sorted(available_strikes)

        # For efficiency, only check strikes in a reasonable range
        # Delta 0.10-0.30 typically falls within 3-12% OTM
        # We'll check all strikes but log how many have Greeks

        for strike in sorted_strikes:
            # Build OCC symbol for this strike
            occ_symbol = build_occ_symbol(
                symbol,
                expiration,
                strike,
                "P" if option_type == "put" else "C",
            )

            # Read Greeks from cache
            greeks = options_service.read_greeks(occ_symbol)

            if greeks and greeks.delta is not None:
                strikes_with_greeks += 1
                actual_delta = float(greeks.delta)

                # Calculate how close this delta is to target
                delta_diff = abs(actual_delta - target_delta_signed)

                if delta_diff < best_delta_diff:
                    best_delta_diff = delta_diff
                    best_strike = strike
                    best_delta = actual_delta

                    # Early exit if we found an exact match (within 0.01)
                    if delta_diff < 0.01:
                        logger.info(
                            f"Found exact delta match: strike ${strike} "
                            f"delta={actual_delta:.3f} (target={target_delta_signed:.3f})"
                        )
                        break

        if best_strike:
            logger.info(
                f"Delta search for {symbol} {option_type}: "
                f"found strike ${best_strike} with delta={best_delta:.3f} "
                f"(target={target_delta_signed:.3f}, diff={best_delta_diff:.3f}, "
                f"checked {strikes_with_greeks}/{len(available_strikes)} strikes with Greeks)"
            )
            return (best_strike, best_delta)

        logger.warning(
            f"No Greeks available for {symbol} {option_type} strikes "
            f"(checked {len(available_strikes)} strikes, none had Greeks in cache)"
        )
        return (None, None)

    async def find_optimal_spread_strikes_by_delta(
        self,
        user,
        symbol: str,
        expiration,
        current_price: Decimal,
        spread_width: int,
        spread_type: Literal["bull_put", "bear_call"],
        target_delta: float = 0.20,
        options_service=None,
        available_strikes: list[Decimal] | None = None,
    ) -> dict[str, Decimal] | None:
        """
        Find optimal spread strikes using delta targeting.

        This combines delta-based short strike selection with spread width
        for the long strike.

        Args:
            user: Django user for API access
            symbol: Underlying symbol
            expiration: Option expiration date
            current_price: Current underlying price
            spread_width: Width of spread in points
            spread_type: "bull_put" or "bear_call"
            target_delta: Target delta for short strike (default 0.20)
            options_service: Optional StreamingOptionsDataService instance
            available_strikes: Pre-fetched available strikes (optional)

        Returns:
            Dict with strike keys or None if no suitable strikes found

        Example:
            >>> strikes = await optimizer.find_optimal_spread_strikes_by_delta(
            ...     user, "QQQ", exp_date, Decimal("622"), 5, "bull_put", 0.20
            ... )
            >>> print(strikes)
            {'short_put': Decimal('608'), 'long_put': Decimal('603')}
        """
        from services.streaming.options_service import StreamingOptionsDataService

        if options_service is None:
            options_service = StreamingOptionsDataService(user)

        # Determine option type based on spread
        option_type: Literal["put", "call"] = (
            "put" if spread_type == "bull_put" else "call"
        )

        # If no strikes provided, we need to fetch them
        if available_strikes is None:
            logger.warning("No available_strikes provided - caller should provide them")
            return None

        # Find short strike by delta
        short_strike, actual_delta = await self.find_strike_by_delta(
            user=user,
            symbol=symbol,
            expiration=expiration,
            option_type=option_type,
            target_delta=target_delta,
            available_strikes=available_strikes,
            options_service=options_service,
        )

        if not short_strike:
            logger.warning(
                f"Could not find {option_type} strike with delta ~{target_delta} for {symbol}"
            )
            return None

        # Calculate long strike based on spread width
        if spread_type == "bull_put":
            long_strike = short_strike - Decimal(str(spread_width))
        else:  # bear_call
            long_strike = short_strike + Decimal(str(spread_width))

        # Validate long strike exists in available strikes
        # Allow some tolerance for finding nearest available
        closest_long = self._find_closest_strike(long_strike, available_strikes)
        if not closest_long:
            logger.warning(f"No available long strike near ${long_strike}")
            return None

        # Check if closest long is within acceptable range (10% of spread width)
        if abs(float(closest_long - long_strike)) > spread_width * 0.5:
            logger.warning(
                f"Closest long strike ${closest_long} too far from ideal ${long_strike}"
            )
            return None

        # Build result
        if spread_type == "bull_put":
            result = {"short_put": short_strike, "long_put": closest_long}
        else:
            result = {"short_call": short_strike, "long_call": closest_long}

        logger.info(
            f"Delta-based {spread_type} for {symbol}: "
            f"short=${short_strike} (delta={actual_delta:.3f}), "
            f"long=${closest_long}, width=${abs(short_strike - closest_long)}"
        )

        return result
