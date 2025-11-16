"""
TastyTrade SDK instrument utilities.

This module provides wrappers around the TastyTrade SDK's instrument functionality,
replacing custom OCC symbol generation with battle-tested SDK patterns.

Key Benefits:
- Uses SDK's native Option.a_get() for accurate symbol formatting
- Type-safe Pydantic models for all instruments
- Built-in validation and error handling
- Automatic updates when SDK improves

Reference: tastytrade SDK v10.3.0
See tastytrade-cli examples: https://github.com/tastyware/tastytrade
"""

from datetime import date
from decimal import Decimal

from django.utils import timezone as dj_timezone

from tastytrade import Session
from tastytrade.instruments import Option as TastytradeOption

from services.core.exceptions import InvalidOptionTypeError, InvalidSymbolFormatError
from services.core.logging import get_logger

logger = get_logger(__name__)


async def get_option_instrument(
    session: Session,
    underlying: str,
    expiration: date,
    strike: Decimal,
    option_type: str,  # 'C' or 'P'
) -> TastytradeOption:
    """
    Fetch option instrument from TastyTrade SDK.

    Args:
        session: OAuth session for API access
        underlying: Underlying symbol (e.g., 'SPY', 'QQQ')
        expiration: Option expiration date
        strike: Strike price as Decimal
        option_type: 'C' for Call, 'P' for Put

    Returns:
        TastytradeOption: SDK Option object with OCC-formatted symbol

    Raises:
        ValueError: If option_type is invalid or instrument not found

    Example:
        >>> from datetime import date
        >>> from decimal import Decimal
        >>> option = await get_option_instrument(
        ...     session, 'SPY', date(2025, 11, 7), Decimal('591.00'), 'P'
        ... )
        >>> option.symbol  # 'SPY   251107P00591000'
        >>> option.strike_price  # Decimal('591.00')
    """
    if option_type not in ("C", "P"):
        raise InvalidOptionTypeError(option_type=option_type)

    # Build OCC symbol using same format as custom code for compatibility
    # Format: SYMBOL(6)YYMMDD(6)C/P(1)STRIKE(8)
    symbol = underlying.upper()[:6].ljust(6)
    exp_str = expiration.strftime("%y%m%d")
    strike_int = int(strike * Decimal("1000"))
    occ_symbol = f"{symbol}{exp_str}{option_type}{strike_int:08d}"

    logger.debug(f"Fetching instrument: {occ_symbol}")

    # Use SDK to fetch instrument (validates symbol and enriches with data)
    return await TastytradeOption.a_get(session, occ_symbol)


async def get_option_instruments_bulk(
    session: Session, option_specs: list[dict]
) -> list[TastytradeOption]:
    """
    Fetch multiple option instruments in efficient batch.

    Args:
        session: OAuth session for API access
        option_specs: List of dicts with keys:
            - underlying: str
            - expiration: date
            - strike: Decimal
            - option_type: str ('C' or 'P')

    Returns:
        List[TastytradeOption]: List of SDK Option objects

    Example:
        >>> specs = [
        ...     {'underlying': 'SPY', 'expiration': date(2025, 11, 7),
        ...      'strike': Decimal('591.00'), 'option_type': 'P'},
        ...     {'underlying': 'SPY', 'expiration': date(2025, 11, 7),
        ...      'strike': Decimal('586.00'), 'option_type': 'P'},
        ... ]
        >>> options = await get_option_instruments_bulk(session, specs)
        >>> len(options)  # 2
    """
    # Build OCC symbols for all specs
    occ_symbols = []
    for spec in option_specs:
        underlying = spec["underlying"]
        expiration = spec["expiration"]
        strike = spec["strike"]
        option_type = spec["option_type"]

        if option_type not in ("C", "P"):
            raise InvalidOptionTypeError(option_type=option_type)

        symbol = underlying.upper()[:6].ljust(6)
        exp_str = expiration.strftime("%y%m%d")
        strike_int = int(strike * Decimal("1000"))
        occ_symbol = f"{symbol}{exp_str}{option_type}{strike_int:08d}"
        occ_symbols.append(occ_symbol)

    logger.debug(f"Fetching {len(occ_symbols)} instruments in bulk")

    # Fetch all instruments (SDK handles batching efficiently)
    options = []
    for occ_symbol in occ_symbols:
        option = await TastytradeOption.a_get(session, occ_symbol)
        options.append(option)

    return options


def build_occ_symbol(
    underlying: str,
    expiration: date,
    strike: Decimal,
    option_type: str,
) -> str:
    """
    Build OCC-compliant option symbol.

    Use this function when you need just the OCC symbol string (e.g., for order
    construction, cache keys). Use get_option_instrument() when you need the full
    instrument object with enriched data from the API.

    Args:
        underlying: Underlying symbol
        expiration: Expiration date
        strike: Strike price as Decimal
        option_type: 'C' or 'P'

    Returns:
        str: OCC-formatted symbol

    Example:
        >>> build_occ_symbol('SPY', date(2025, 11, 7), Decimal('591.00'), 'P')
        'SPY   251107P00591000'
    """
    if option_type not in ("C", "P"):
        raise InvalidOptionTypeError(option_type=option_type)

    symbol = underlying.upper()[:6].ljust(6)
    exp_str = expiration.strftime("%y%m%d")
    strike_int = int(strike * Decimal("1000"))
    return f"{symbol}{exp_str}{option_type}{strike_int:08d}"


def parse_occ_symbol(occ_symbol: str) -> dict:
    """
    Parse an OCC symbol into its components (compatibility function).

    Args:
        occ_symbol: The OCC-formatted option symbol

    Returns:
        dict: Parsed components with keys:
            - underlying: The underlying symbol
            - expiration: The expiration date
            - option_type: 'C' or 'P'
            - strike: The strike price as Decimal

    Raises:
        ValueError: If the symbol format is invalid

    Example:
        >>> parse_occ_symbol('SPY   251107P00591000')
        {
            'underlying': 'SPY',
            'expiration': date(2025, 11, 7),
            'option_type': 'P',
            'strike': Decimal('591.00')
        }
    """
    if len(occ_symbol) != 21:
        raise InvalidSymbolFormatError(symbol=occ_symbol, expected_length=21)

    # Extract components
    underlying = occ_symbol[:6].strip()
    exp_str = occ_symbol[6:12]
    option_type = occ_symbol[12]
    strike_str = occ_symbol[13:21]

    # Parse expiration date - create timezone-aware datetime, then extract date
    from datetime import datetime as dt

    year = int("20" + exp_str[0:2])
    month = int(exp_str[2:4])
    day = int(exp_str[4:6])
    expiration = dt(year, month, day, tzinfo=dj_timezone.get_current_timezone()).date()

    # Parse strike price (divide by 1000)
    strike = Decimal(strike_str) / Decimal("1000")

    return {
        "underlying": underlying,
        "expiration": expiration,
        "option_type": option_type,
        "strike": strike,
    }


def validate_occ_symbol(occ_symbol: str) -> bool:
    """
    Validate if a string is a properly formatted OCC symbol.

    Args:
        occ_symbol: The string to validate

    Returns:
        bool: True if valid OCC symbol, False otherwise
    """
    try:
        parse_occ_symbol(occ_symbol)
        return True
    except (ValueError, AttributeError, InvalidSymbolFormatError, InvalidOptionTypeError):
        return False
