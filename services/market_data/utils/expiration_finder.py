"""
Shared utility for finding optimal option expiration dates.

Used by all strategy implementations to select appropriate expiration dates
based on target DTE (Days To Expiration) and available dates from the API.
"""

from datetime import date

from django.utils import timezone

from services.core.logging import get_logger

logger = get_logger(__name__)


def find_target_expiration(
    available_dates: list[date], target_dte: int = 45, min_dte: int = 30, max_dte: int = 45
) -> date | None:
    """
    Find optimal expiration date from available dates.

    Selects the furthest date within min/max DTE range (as far out as possible).

    Args:
        available_dates: List of available expiration dates from API
        target_dte: Target days to expiration (default 45)
        min_dte: Minimum acceptable DTE (default 30)
        max_dte: Maximum acceptable DTE (default 45)

    Returns:
        Optimal expiration date or None if no valid dates found

    Example:
        >>> from datetime import date, timedelta
        >>> today = date.today()
        >>> dates = [today + timedelta(days=d) for d in [30, 45, 60, 90]]
        >>> expiration = find_target_expiration(dates, target_dte=45)
        >>> # Returns date closest to 45 DTE within 30-60 range
    """
    if not available_dates:
        logger.warning("No expiration dates provided")
        return None

    today = timezone.now().date()

    # Filter for dates within the allowed DTE range
    valid_expirations = []
    for exp_date in available_dates:
        dte = (exp_date - today).days
        if min_dte <= dte <= max_dte:
            valid_expirations.append(exp_date)

    if not valid_expirations:
        logger.warning(
            f"No expirations found between {min_dte} and {max_dte} DTE. "
            f"Available dates: {[str(d) for d in available_dates[:5]]}"
        )
        return None

    # From the valid dates, find the one that is furthest out (max DTE)
    best_date = max(valid_expirations)

    actual_dte = (best_date - today).days
    logger.info(
        f"Found furthest expiration {best_date} with DTE of {actual_dte} "
        f"(range: {min_dte}-{max_dte})"
    )
    return best_date


async def a_fetch_and_find_expiration(
    user, symbol: str, target_dte: int = 45, min_dte: int = 30, max_dte: int = 45
) -> date | None:
    """
    Fetch available expirations from API and find optimal date.

    Convenience async function that combines API fetch + expiration finding.

    Args:
        user: Django user for API access
        symbol: Underlying symbol (e.g., 'QQQ', 'SPY')
        target_dte: Target days to expiration (default 45)
        min_dte: Minimum acceptable DTE (default 30)
        max_dte: Maximum acceptable DTE (default 45)

    Returns:
        Optimal expiration date or None if unavailable

    Example:
        >>> expiration = await a_fetch_and_find_expiration(user, 'SPY', target_dte=45)
    """
    from services.market_data.option_chains import OptionChainService

    # Fetch available expirations from API
    option_chain_service = OptionChainService()
    available_expirations = await option_chain_service.a_get_all_expirations(user, symbol)

    if not available_expirations:
        logger.warning(f"Could not retrieve expiration dates for {symbol}")
        return None

    # Find best expiration
    return find_target_expiration(
        available_expirations, target_dte=target_dte, min_dte=min_dte, max_dte=max_dte
    )
