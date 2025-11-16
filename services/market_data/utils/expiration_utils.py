"""
Expiration selection utilities with strike validation support.

Extends the basic expiration_finder.py logic to validate that selected
expirations actually have the required strikes available in the option chain.

This solves the edge case where the longest DTE expiration (e.g., 45 DTE)
might only have even strikes, preventing strategies that need odd strikes
(e.g., width=3 spreads needing strikes like 441, 444, 447).
"""

from datetime import date
from decimal import Decimal

from django.utils import timezone

from services.core.logging import get_logger
from services.market_data.option_chains import extract_call_strikes, extract_put_strikes

logger = get_logger(__name__)


async def find_expiration_with_exact_strikes(
    user,
    symbol: str,
    strikes: dict[str, Decimal],
    min_dte: int = 30,
    max_dte: int = 45,
) -> tuple[date, dict] | None:
    """
    Find longest DTE expiration that has all required strikes available.

    Strike matching algorithm (flexible):
    1. First try: Exact strike match (preferred)
    2. Fallback: Nearest available strike (no distance limit)
    3. Log when using nearest vs exact for debugging

    This function implements a cascade validation pattern:
    1. Get all expirations in the DTE range
    2. Sort by DTE (longest first)
    3. For each expiration, fetch the chain and find best matching strikes
    4. Return first expiration with all required strikes (exact or nearest)

    Reuses existing infrastructure:
    - OptionChainService for chain fetching + caching
    - expiration_finder date filtering logic
    - StreamingOptionsDataService for chain access
    - find_nearest_available_strike for flexible matching

    Args:
        user: Django user for API access
        symbol: Underlying symbol (e.g., 'QQQ', 'SPY')
        strikes: Dict with required strikes (e.g., {short_put: 444, long_put: 441})
        min_dte: Minimum acceptable DTE (default 30)
        max_dte: Maximum acceptable DTE (default 45)

    Returns:
        (expiration_date, matched_strikes_dict, option_chain_dict) or None if no valid chain found
        The matched_strikes_dict contains actual strikes used (may differ from input if nearest was used)

    Example:
        >>> strikes = {"short_put": Decimal("444"), "long_put": Decimal("441")}
        >>> result = await find_expiration_with_exact_strikes(
        ...     user, "QQQ", strikes, min_dte=30, max_dte=45
        ... )
        >>> if result:
        ...     expiration, matched_strikes, chain = result
        ...     print(f"Found valid chain at {expiration} with strikes {matched_strikes}")
    """
    from services.market_data.option_chains import OptionChainService
    from services.streaming.options_service import StreamingOptionsDataService

    # 1. Get all expirations for symbol
    chain_service = OptionChainService()
    all_expirations = await chain_service.a_get_all_expirations(user, symbol)

    if not all_expirations:
        logger.warning(f"No expirations available for {symbol}")
        return None

    # 2. Filter to DTE range
    today = timezone.now().date()
    valid_expirations = []

    for exp_date in all_expirations:
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            valid_expirations.append((dte, exp_date))

    if not valid_expirations:
        logger.warning(
            f"No expirations found between {min_dte} and {max_dte} DTE for {symbol}. "
            f"Available: {[str(d) for d in all_expirations[:5]]}"
        )
        return None

    # Sort by DTE descending (longest first)
    valid_expirations.sort(reverse=True)
    logger.info(
        f"Checking {len(valid_expirations)} expirations for {symbol} "
        f"(DTE range: {min_dte}-{max_dte})"
    )

    # 3. Try each expiration (longest DTE first)
    options_service = StreamingOptionsDataService(user)
    from services.strategies.utils.strike_utils import find_nearest_available_strike

    for dte, expiration in valid_expirations:
        logger.info(f"Checking expiration {expiration} (DTE: {dte}) for valid strikes")

        # Fetch option chain for this expiration
        chain = await options_service._get_option_chain(symbol, expiration)
        if not chain:
            logger.warning(f"Could not fetch chain for {symbol} {expiration}")
            continue

        # Get available strikes as lists (sorted)
        strikes_list = chain.get("strikes", [])
        put_strikes_set = extract_put_strikes(strikes_list)
        call_strikes_set = extract_call_strikes(strikes_list)
        put_strikes_list = sorted(put_strikes_set)
        call_strikes_list = sorted(call_strikes_set)

        # Try to match all required strikes (exact or nearest)
        matched_strikes = {}
        all_matched = True
        adjustments_made = []

        for leg, target_strike in strikes.items():
            is_put = "put" in leg
            available = put_strikes_list if is_put else call_strikes_list
            available_set = put_strikes_set if is_put else call_strikes_set

            # First try: Exact match (preferred)
            if target_strike in available_set:
                matched_strikes[leg] = target_strike
                continue

            # Fallback: Find nearest available strike
            nearest = find_nearest_available_strike(target_strike, available)
            if nearest is None:
                logger.warning(
                    f"No {'put' if is_put else 'call'} strikes available at {expiration}"
                )
                all_matched = False
                break

            matched_strikes[leg] = nearest
            deviation = abs(float(nearest - target_strike))
            adjustments_made.append(
                f"{leg}: {target_strike} → {nearest} (deviation: ${deviation:.2f})"
            )

        if not all_matched:
            continue

        # Validate spread widths for multi-leg strategies (iron condor, spreads)
        # Ensure short/long strikes are different to avoid zero-width spreads
        needs_width_validation = any(
            k in matched_strikes for k in ["short_put", "long_put", "short_call", "long_call"]
        )

        if needs_width_validation:
            # Validate put spread width
            if "short_put" in matched_strikes and "long_put" in matched_strikes:
                if matched_strikes["short_put"] == matched_strikes["long_put"]:
                    # Find next lower strike for long_put
                    short_put = matched_strikes["short_put"]
                    lower_strikes = [s for s in put_strikes_list if s < short_put]
                    if not lower_strikes:
                        logger.warning(
                            f"Cannot create put spread at {expiration} - no lower strike available"
                        )
                        all_matched = False
                        continue
                    matched_strikes["long_put"] = max(lower_strikes)
                    adjustments_made.append(
                        f"long_put: {matched_strikes['short_put']} → {matched_strikes['long_put']} (adjusted for non-zero width)"
                    )

            # Validate call spread width
            if "short_call" in matched_strikes and "long_call" in matched_strikes:
                if matched_strikes["short_call"] == matched_strikes["long_call"]:
                    # Find next higher strike for long_call
                    short_call = matched_strikes["short_call"]
                    higher_strikes = [s for s in call_strikes_list if s > short_call]
                    if not higher_strikes:
                        logger.warning(
                            f"Cannot create call spread at {expiration} - no higher strike available"
                        )
                        all_matched = False
                        continue
                    matched_strikes["long_call"] = min(higher_strikes)
                    adjustments_made.append(
                        f"long_call: {matched_strikes['short_call']} → {matched_strikes['long_call']} (adjusted for non-zero width)"
                    )

        if not all_matched:
            continue

        # Log adjustments if any were made
        if adjustments_made:
            logger.info(
                f"⚙️ Expiration {expiration} (DTE: {dte}) - Using nearest strikes:\n"
                + "\n".join(f"  {adj}" for adj in adjustments_made)
            )
        else:
            logger.info(f"✅ Expiration {expiration} (DTE: {dte}) - All exact strikes matched")

        return (expiration, matched_strikes, chain)

    # No valid expiration found
    logger.warning(
        f"No expiration in {min_dte}-{max_dte} DTE range has all required strikes "
        f"for {symbol}. Strikes needed: {strikes}"
    )
    return None


async def find_expiration_with_optimal_strikes(
    user,
    symbol: str,
    target_criteria: dict,
    min_dte: int = 30,
    max_dte: int = 45,
    relaxed_quality: bool = False,
) -> tuple[date, dict[str, Decimal], dict] | None:
    """
    Find longest DTE expiration with optimal strikes from available strikes.

    This function implements the "strikes-from-available" pattern:
    1. Get all expirations in the DTE range
    2. Sort by DTE (longest first)
    3. For each expiration:
        a. Fetch ALL available strikes from option chain
        b. Run optimizer to find best strikes from available
        c. If quality gate passes (5% or 15% threshold), return
    4. Return None if no expiration passes quality gate

    This is the CORRECT pattern for credit spreads - we adapt to what
    strikes actually exist rather than failing if theoretical strikes
    don't exist.

    Args:
        user: Django user for API access
        symbol: Underlying symbol (e.g., 'QQQ', 'SPY')
        target_criteria: Dict with optimization criteria:
            - spread_type: "bull_put" | "bear_call"
            - otm_pct: Target out-of-the-money percentage (e.g., 0.03 for 3%)
            - spread_width: Width of spread in points
            - current_price: Current underlying price
            - support_level: Support level (bull put only, optional)
            - resistance_level: Resistance level (bear call only, optional)
        min_dte: Minimum acceptable DTE (default 30)
        max_dte: Maximum acceptable DTE (default 45)
        relaxed_quality: If True, use 15% threshold instead of 5% (for force mode)

    Returns:
        (expiration_date, selected_strikes_dict, option_chain_dict) or None

    Example:
        >>> target_criteria = {
        ...     "spread_type": "bull_put",
        ...     "otm_pct": 0.03,
        ...     "spread_width": 5,
        ...     "current_price": Decimal("450"),
        ...     "support_level": Decimal("440"),
        ...     "resistance_level": None,
        ... }
        >>> result = await find_expiration_with_optimal_strikes(
        ...     user, "SPY", target_criteria, min_dte=30, max_dte=45
        ... )
        >>> if result:
        ...     expiration, strikes, chain = result
        ...     print(f"Selected strikes: {strikes} at {expiration}")
    """
    from services.market_data.option_chains import OptionChainService
    from services.strategies.utils.strike_optimizer import StrikeOptimizer
    from services.streaming.options_service import StreamingOptionsDataService

    # Extract criteria
    spread_type = target_criteria["spread_type"]
    otm_pct = target_criteria["otm_pct"]
    spread_width = target_criteria["spread_width"]
    current_price = target_criteria["current_price"]
    support_level = target_criteria.get("support_level")
    resistance_level = target_criteria.get("resistance_level")

    logger.info(
        f"Finding optimal {spread_type} strikes for {symbol} "
        f"(price: ${current_price:.2f}, width: {spread_width}, "
        f"target: {otm_pct*100:.0f}% OTM)"
    )

    # 1. Get all expirations for symbol
    chain_service = OptionChainService()
    all_expirations = await chain_service.a_get_all_expirations(user, symbol)

    if not all_expirations:
        logger.warning(f"No expirations available for {symbol}")
        return None

    # 2. Filter to DTE range
    today = timezone.now().date()
    valid_expirations = []

    for exp_date in all_expirations:
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            valid_expirations.append((dte, exp_date))

    if not valid_expirations:
        logger.warning(
            f"No expirations found between {min_dte} and {max_dte} DTE for {symbol}. "
            f"Available: {[str(d) for d in all_expirations[:5]]}"
        )
        return None

    # Sort by DTE descending (longest first)
    valid_expirations.sort(reverse=True)
    logger.info(
        f"Checking {len(valid_expirations)} expirations for {symbol} "
        f"(DTE range: {min_dte}-{max_dte})"
    )

    # 3. Try each expiration (longest DTE first)
    options_service = StreamingOptionsDataService(user)
    optimizer = StrikeOptimizer()

    for dte, expiration in valid_expirations:
        logger.info(f"Checking expiration {expiration} (DTE: {dte}) for optimal strikes")

        # Fetch option chain for this expiration
        chain = await options_service._get_option_chain(symbol, expiration)
        if not chain:
            logger.warning(f"Could not fetch chain for {symbol} {expiration}")
            continue

        # Get available strikes (put or call based on spread type)
        strikes_list = chain.get("strikes", [])
        if spread_type in ["bull_put", "bear_put"]:
            available_strikes = sorted(extract_put_strikes(strikes_list))
        else:  # bear_call or bull_call
            available_strikes = sorted(extract_call_strikes(strikes_list))

        if not available_strikes:
            logger.warning(f"No available strikes found in chain for {symbol} {expiration}")
            continue

        logger.debug(
            f"Found {len(available_strikes)} available strikes "
            f"(range: ${min(available_strikes):.2f} - ${max(available_strikes):.2f})"
        )

        # Run optimizer to find best strikes from available
        selected_strikes = optimizer.find_optimal_spread_strikes(
            available_strikes=available_strikes,
            current_price=current_price,
            spread_width=spread_width,
            spread_type=spread_type,
            target_otm_pct=otm_pct,
            support_level=support_level,
            resistance_level=resistance_level,
            relaxed_quality=relaxed_quality,
        )

        if selected_strikes:
            mode_info = " (relaxed mode)" if relaxed_quality else ""
            logger.info(
                f"✅ Found optimal strikes for {symbol} at {expiration} "
                f"(DTE: {dte}){mode_info}: {selected_strikes}"
            )
            return (expiration, selected_strikes, chain)

        # Optimizer returned None - strikes failed quality gate
        threshold = "15%" if relaxed_quality else "5%"
        logger.info(
            f"❌ Expiration {expiration} (DTE: {dte}) failed quality gate "
            f"(no strikes within {threshold} deviation threshold)"
        )

    # No valid expiration found
    threshold = "15%" if relaxed_quality else "5%"
    logger.warning(
        f"No expiration in {min_dte}-{max_dte} DTE range passed quality gate "
        f"for {symbol} (threshold: {threshold}). Try widening DTE range or lowering quality threshold."
    )
    return None


async def find_calendar_expiration_pair(
    user,
    symbol: str,
    near_dte_target: int = 25,
    near_dte_range: tuple[int, int] = (20, 30),
    far_dte_target: int = 55,
    far_dte_range: tuple[int, int] = (50, 60),
    min_ratio: float = 1.8,
    max_ratio: float = 2.5,
) -> tuple[date, date] | None:
    """
    Find optimal near/far expiration pair for calendar spread.

    Calendar spreads require TWO expirations with specific DTE ranges:
    - Near-term: 20-30 DTE (sell, fast theta decay)
    - Far-term: 50-60 DTE (buy, slow theta decay)
    - DTE ratio: 1.8:1 to 2.5:1 (ideally 2.2:1)

    Args:
        user: Django user for API access
        symbol: Underlying symbol (e.g., 'QQQ', 'SPY')
        near_dte_target: Target near-term DTE (default 25)
        near_dte_range: (min, max) acceptable near-term DTE (default 20-30)
        far_dte_target: Target far-term DTE (default 55)
        far_dte_range: (min, max) acceptable far-term DTE (default 50-60)
        min_ratio: Minimum far/near DTE ratio (default 1.8)
        max_ratio: Maximum far/near DTE ratio (default 2.5)

    Returns:
        (near_expiration, far_expiration) or None if no suitable pair found

    Example:
        >>> pair = await find_calendar_expiration_pair(user, "QQQ")
        >>> if pair:
        ...     near_exp, far_exp = pair
        ...     # near_exp: 2025-12-07 (25 DTE)
        ...     # far_exp: 2026-01-16 (56 DTE, ratio 2.24)
    """
    from services.market_data.option_chains import OptionChainService

    # Get all expirations
    chain_service = OptionChainService()
    all_exps = await chain_service.a_get_all_expirations(user, symbol)

    if not all_exps:
        logger.warning(f"No expirations available for {symbol}")
        return None

    today = timezone.now().date()

    # Find near-term expiration (closest to target within range)
    near_candidates = []
    for exp in all_exps:
        dte = (exp - today).days
        if near_dte_range[0] <= dte <= near_dte_range[1]:
            # Store (distance_from_target, expiration)
            near_candidates.append((abs(dte - near_dte_target), exp))

    if not near_candidates:
        logger.warning(
            f"No near-term expiration found for {symbol} in range "
            f"{near_dte_range[0]}-{near_dte_range[1]} DTE"
        )
        return None

    # Select closest to target
    near_exp = sorted(near_candidates)[0][1]

    # Find far-term expiration (closest to target within range)
    far_candidates = []
    for exp in all_exps:
        dte = (exp - today).days
        if far_dte_range[0] <= dte <= far_dte_range[1]:
            far_candidates.append((abs(dte - far_dte_target), exp))

    if not far_candidates:
        logger.warning(
            f"No far-term expiration found for {symbol} in range "
            f"{far_dte_range[0]}-{far_dte_range[1]} DTE"
        )
        return None

    far_exp = sorted(far_candidates)[0][1]

    # Validate DTE ratio
    near_dte = (near_exp - today).days
    far_dte = (far_exp - today).days
    ratio = far_dte / near_dte if near_dte > 0 else 0

    if not (min_ratio <= ratio <= max_ratio):
        logger.warning(
            f"DTE ratio {ratio:.2f} outside acceptable range "
            f"({min_ratio}-{max_ratio}) for {symbol}. "
            f"Near: {near_exp} ({near_dte} DTE), Far: {far_exp} ({far_dte} DTE)"
        )
        return None

    logger.info(
        f"Calendar pair for {symbol}: {near_exp} ({near_dte} DTE) / "
        f"{far_exp} ({far_dte} DTE), ratio {ratio:.2f}"
    )

    return (near_exp, far_exp)
