"""
Utility module for building option legs and managing instrument fetching.
Eliminates code duplication across strategy implementations.

This module provides centralized utilities for:
- Fetching option instruments with proper spec formatting
- Mapping strikes to instruments
- Building leg objects for orders
- Session management helpers

Following DRY principle per CLAUDE.md and Epic 22 refactoring.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from tastytrade import Option as TastytradeOption
from tastytrade.order import Leg

from services.core.logging import get_logger
from services.sdk.instruments import get_option_instruments_bulk

logger = get_logger(__name__)


async def fetch_spread_instruments(
    session: Any,
    underlying: str,
    expiration: date,
    put_strikes: list[Decimal] | None = None,
    call_strikes: list[Decimal] | None = None,
) -> tuple[list[TastytradeOption], list[TastytradeOption]]:
    """
    Fetch put and call instruments for spread strategies.

    Centralizes the pattern used by Iron Condor, Iron Butterfly, and other
    multi-leg strategies to reduce code duplication.

    Args:
        session: TastyTrade OAuth session
        underlying: Underlying symbol
        expiration: Expiration date
        put_strikes: List of put strike prices (optional)
        call_strikes: List of call strike prices (optional)

    Returns:
        Tuple of (put_instruments, call_instruments)

    Raises:
        ValueError: If instrument fetching fails
    """
    put_instruments = []
    call_instruments = []

    # Fetch put instruments if strikes provided
    if put_strikes:
        put_specs = [
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strike,
                "option_type": "P",
            }
            for strike in put_strikes
        ]
        put_instruments = await get_option_instruments_bulk(session, put_specs)

        # Validate we got all expected instruments
        if len(put_instruments) != len(put_strikes):
            raise ValueError(
                f"Expected {len(put_strikes)} put instruments, got {len(put_instruments)}"
            )

    # Fetch call instruments if strikes provided
    if call_strikes:
        call_specs = [
            {
                "underlying": underlying,
                "expiration": expiration,
                "strike": strike,
                "option_type": "C",
            }
            for strike in call_strikes
        ]
        call_instruments = await get_option_instruments_bulk(session, call_specs)

        # Validate we got all expected instruments
        if len(call_instruments) != len(call_strikes):
            raise ValueError(
                f"Expected {len(call_strikes)} call instruments, got {len(call_instruments)}"
            )

    return put_instruments, call_instruments


def map_strikes_to_instruments(
    instruments: list[TastytradeOption], strikes: dict[str, Decimal]
) -> dict[str, TastytradeOption]:
    """
    Map strike prices to their corresponding instrument objects.

    Replaces the repeated pattern of using next() with string matching
    across all strategy implementations.

    Args:
        instruments: List of TastyTrade Option objects
        strikes: Dictionary mapping strike names to prices
                 e.g., {"short_strike": Decimal("100"), "long_strike": Decimal("95")}

    Returns:
        Dictionary mapping strike names to instrument objects

    Raises:
        ValueError: If a strike cannot be found in instruments
    """
    result = {}

    for name, strike_price in strikes.items():
        # Convert strike to string for symbol matching
        strike_str = str(strike_price)

        # Find instrument with matching strike in symbol
        matching_instrument = None
        for instrument in instruments:
            if strike_str in instrument.symbol:
                matching_instrument = instrument
                break

        if not matching_instrument:
            raise ValueError(f"Could not find instrument for {name} at strike {strike_price}")

        result[name] = matching_instrument

    return result


def build_spread_legs(
    put_instruments: dict[str, TastytradeOption],
    call_instruments: dict[str, TastytradeOption],
    quantity: int,
    strategy_type: str,
) -> list[Leg]:
    """
    Build leg objects for common spread strategies.

    Args:
        put_instruments: Dict mapping put position names to instruments
                        e.g., {"short": Option1, "long": Option2}
        call_instruments: Dict mapping call position names to instruments
        quantity: Number of contracts per leg
        strategy_type: Type of spread (e.g., "iron_condor", "iron_butterfly")

    Returns:
        List of Leg objects for order submission
    """
    legs = []

    if strategy_type == "short_iron_condor":
        # Bull put spread (lower side)
        if "short" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["short"].instrument_type,
                    symbol=put_instruments["short"].symbol,
                    quantity=quantity,
                    action="Sell to Open",
                )
            )
        if "long" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["long"].instrument_type,
                    symbol=put_instruments["long"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )

        # Bear call spread (upper side)
        if "short" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["short"].instrument_type,
                    symbol=call_instruments["short"].symbol,
                    quantity=quantity,
                    action="Sell to Open",
                )
            )
        if "long" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["long"].instrument_type,
                    symbol=call_instruments["long"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )

    elif strategy_type == "long_iron_condor":
        # Bear put spread (lower side) - debit spread
        if "outer" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["outer"].instrument_type,
                    symbol=put_instruments["outer"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )
        if "inner" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["inner"].instrument_type,
                    symbol=put_instruments["inner"].symbol,
                    quantity=quantity,
                    action="Sell to Open",
                )
            )

        # Bull call spread (upper side) - debit spread
        if "inner" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["inner"].instrument_type,
                    symbol=call_instruments["inner"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )
        if "outer" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["outer"].instrument_type,
                    symbol=call_instruments["outer"].symbol,
                    quantity=quantity,
                    action="Sell to Open",
                )
            )

    elif strategy_type == "iron_butterfly":
        # Sell ATM straddle
        if "atm" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["atm"].instrument_type,
                    symbol=put_instruments["atm"].symbol,
                    quantity=quantity,
                    action="Sell to Open",
                )
            )
        if "atm" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["atm"].instrument_type,
                    symbol=call_instruments["atm"].symbol,
                    quantity=quantity,
                    action="Sell to Open",
                )
            )

        # Buy wings for protection
        if "wing" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["wing"].instrument_type,
                    symbol=put_instruments["wing"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )
        if "wing" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["wing"].instrument_type,
                    symbol=call_instruments["wing"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )

    elif strategy_type == "long_straddle":
        # Buy both ATM options
        if "atm" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["atm"].instrument_type,
                    symbol=put_instruments["atm"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )
        if "atm" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["atm"].instrument_type,
                    symbol=call_instruments["atm"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )

    elif strategy_type == "long_strangle":
        # Buy OTM options
        if "otm" in put_instruments:
            legs.append(
                Leg(
                    instrument_type=put_instruments["otm"].instrument_type,
                    symbol=put_instruments["otm"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )
        if "otm" in call_instruments:
            legs.append(
                Leg(
                    instrument_type=call_instruments["otm"].instrument_type,
                    symbol=call_instruments["otm"].symbol,
                    quantity=quantity,
                    action="Buy to Open",
                )
            )

    return legs


def build_closing_legs(opening_legs: list[Leg]) -> list[Leg]:
    """
    Build closing legs that are the opposite of opening legs.

    Args:
        opening_legs: List of opening Leg objects

    Returns:
        List of closing Leg objects
    """
    closing_legs = []

    for leg in opening_legs:
        # Determine closing action based on opening action
        if leg.action == "Buy to Open":
            closing_action = "Sell to Close"
        elif leg.action == "Sell to Open":
            closing_action = "Buy to Close"
        else:
            # Handle any other action types
            closing_action = leg.action.replace("Open", "Close")

        closing_legs.append(
            Leg(
                instrument_type=leg.instrument_type,
                symbol=leg.symbol,
                quantity=leg.quantity,
                action=closing_action,
            )
        )

    return closing_legs


async def get_session_for_position(position: Any) -> Any:
    """
    Get TastyTrade session for a position's user.

    Centralizes the session management pattern used in build_closing_legs
    across all strategies.

    Args:
        position: Position object with user attribute

    Returns:
        OAuth session object

    Raises:
        ValueError: If session cannot be obtained
    """
    from services.brokers.tastytrade.session import TastyTradeSessionService
    from services.core.data_access import get_primary_tastytrade_account

    # Get the user's TastyTrade account
    account = await get_primary_tastytrade_account(position.user)
    if not account:
        raise ValueError(f"No TastyTrade account found for user {position.user.id}")

    # Get session using the service
    session_result = await TastyTradeSessionService.get_session_for_user(
        user_id=position.user.id, refresh_token=account.refresh_token, is_test=account.is_test
    )

    if not session_result.get("success"):
        raise ValueError(f"Failed to get session: {session_result.get('error')}")

    return session_result["session"]
