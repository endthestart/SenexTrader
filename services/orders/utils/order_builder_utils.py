"""
Order building utilities for constructing option order legs.

This module consolidates the duplicated order leg building logic
that was spread across OrderExecutionService and SenexTridentStrategy.

Updated to use TastyTrade SDK-aligned symbol building for reliability.
"""

from datetime import date
from decimal import Decimal

from tastytrade.order import Leg

from services.orders.spec import OrderLeg
from services.sdk.instruments import build_occ_symbol


def build_closing_spread_legs(
    underlying_symbol: str,
    expiration_date: date,
    spread_type: str,
    strikes: dict[str, Decimal],
    quantity: int = 1,
) -> list[OrderLeg]:
    """
    Build closing legs for spread positions.

    Args:
        underlying_symbol: The underlying stock symbol
        expiration_date: Option expiration date
        spread_type: Type of spread ('put_spread_1', 'put_spread_2', 'call_spread', 'iron_condor', 'short_iron_condor')
        strikes: Dictionary with strike prices (short_put, long_put, short_call, long_call)
        quantity: Number of contracts (default: 1)

    Returns:
        List of OrderLeg objects for closing the spread

    Examples:
        >>> build_closing_spread_legs('SPY', date(2025, 11, 7), 'put_spread_1',
        ...     {'short_put': Decimal('590'), 'long_put': Decimal('585')})
        [OrderLeg(action='buy_to_close', ...), OrderLeg(action='sell_to_close', ...)]
    """
    legs = []

    if spread_type in ["put_spread_1", "put_spread_2"]:
        # Close put spread: Buy to close short put, Sell to close long put
        if strikes.get("short_put") and strikes.get("long_put"):
            # Buy to close the short put (we sold it originally)
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["short_put"], "P"
                    ),
                    action="buy_to_close",
                    quantity=quantity,
                )
            )

            # Sell to close the long put (we bought it originally)
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["long_put"], "P"
                    ),
                    action="sell_to_close",
                    quantity=quantity,
                )
            )

    elif spread_type == "call_spread":
        # Close call spread: Buy to close short call, Sell to close long call
        if strikes.get("short_call") and strikes.get("long_call"):
            # Buy to close the short call (we sold it originally)
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["short_call"], "C"
                    ),
                    action="buy_to_close",
                    quantity=quantity,
                )
            )

            # Sell to close the long call (we bought it originally)
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["long_call"], "C"
                    ),
                    action="sell_to_close",
                    quantity=quantity,
                )
            )

    elif spread_type in ["iron_condor", "short_iron_condor"]:
        # Close iron condor: Close both put spread and call spread
        # Close put spread
        if strikes.get("short_put") and strikes.get("long_put"):
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["short_put"], "P"
                    ),
                    action="buy_to_close",
                    quantity=quantity,
                )
            )
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["long_put"], "P"
                    ),
                    action="sell_to_close",
                    quantity=quantity,
                )
            )

        # Close call spread
        if strikes.get("short_call") and strikes.get("long_call"):
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["short_call"], "C"
                    ),
                    action="buy_to_close",
                    quantity=quantity,
                )
            )
            legs.append(
                OrderLeg(
                    instrument_type="equity_option",
                    symbol=build_occ_symbol(
                        underlying_symbol, expiration_date, strikes["long_call"], "C"
                    ),
                    action="sell_to_close",
                    quantity=quantity,
                )
            )

    return legs


async def build_opening_spread_legs(
    session,
    underlying_symbol: str,
    expiration_date: date,
    spread_type: str,
    strikes: dict[str, Decimal],
    quantity: int = 1,
) -> list[Leg]:
    """
    Build opening legs for spread positions using SDK instruments.

    Args:
        session: The OAuth session for API calls.
        underlying_symbol: The underlying stock symbol
        expiration_date: Option expiration date
        spread_type: Type of spread
        strikes: Dictionary with strike prices
        quantity: Number of contracts

    Supported spread_type values:
        - 'put_spread': Sell short_put, buy long_put
        - 'call_spread': Sell short_call, buy long_call
        - 'iron_condor': SHORT iron condor - Sell put spread + sell call spread (CREDIT)
        - 'long_iron_condor': LONG iron condor - Buy inner strikes, sell outer strikes (DEBIT)
        - 'iron_butterfly': Sell ATM straddle + buy OTM wings (4 legs, same ATM strike)
        - 'straddle': Buy ATM call + buy ATM put (2 legs, same strike)
        - 'strangle': Buy OTM call + buy OTM put (2 legs, different strikes)
        - 'call_backspread': Sell 1 ATM call, buy 2 OTM calls (ratio spread)

    Returns:
        List of tastytrade.order.Leg objects for opening the spread
    """
    from tastytrade.order import InstrumentType, OrderAction

    from services.sdk.instruments import get_option_instruments_bulk

    specs = []
    actions = []

    if spread_type == "put_spread":
        if strikes.get("short_put") and strikes.get("long_put"):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    elif spread_type == "call_spread":
        if strikes.get("short_call") and strikes.get("long_call"):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    elif spread_type == "iron_condor":
        if all(k in strikes for k in ["short_put", "long_put", "short_call", "long_call"]):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    elif spread_type == "long_iron_condor":
        # LONG Iron Condor: BUY inner strikes (higher premium), SELL outer strikes (lower premium)
        # This is the OPPOSITE of a regular (short) iron condor
        if all(k in strikes for k in ["short_put", "long_put", "short_call", "long_call"]):
            # Put side: BUY short_put (higher/inner), SELL long_put (lower/outer)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            # Call side: BUY short_call (lower/inner), SELL long_call (higher/outer)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)

    elif spread_type == "iron_butterfly":
        if all(k in strikes for k in ["long_put", "short_put", "short_call", "long_call"]):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_put"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    elif spread_type == "straddle":
        if strikes.get("strike"):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["strike"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["strike"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    elif spread_type == "strangle":
        if strikes.get("call_strike") and strikes.get("put_strike"):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["call_strike"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["put_strike"],
                    "option_type": "P",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    elif spread_type == "call_backspread":
        if strikes.get("short_call") and strikes.get("long_call"):
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["short_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.SELL_TO_OPEN)
            specs.append(
                {
                    "underlying": underlying_symbol,
                    "expiration": expiration_date,
                    "strike": strikes["long_call"],
                    "option_type": "C",
                }
            )
            actions.append(OrderAction.BUY_TO_OPEN)

    if not specs:
        return []

    instruments = await get_option_instruments_bulk(session, specs)

    legs = []
    for i, instrument in enumerate(instruments):
        qty = quantity
        if spread_type == "call_backspread" and i == 1:
            qty = quantity * 2
        legs.append(
            Leg(
                instrument_type=InstrumentType.EQUITY_OPTION,
                symbol=instrument.symbol,
                action=actions[i],
                quantity=Decimal(str(qty)),
            )
        )

    return legs


async def build_senex_trident_legs(
    session,
    underlying_symbol: str,
    expiration_date: date,
    put_strikes: dict[str, Decimal],
    call_strikes: dict[str, Decimal] | None = None,
    put_quantity: int = 2,
    call_quantity: int = 1,
) -> list[Leg]:
    """
    Build the complete Senex Trident structure using SDK Leg objects.

    Args:
        session: The OAuth session for API calls.
        underlying_symbol: The underlying stock symbol
        expiration_date: Option expiration date
        put_strikes: Dict with 'short_put' and 'long_put' strikes
        call_strikes: Optional dict with 'short_call' and 'long_call' strikes
        put_quantity: Number of put spread contracts (default: 2)
        call_quantity: Number of call spread contracts (default: 1)

    Returns:
        List of all order legs for the Senex Trident structure
    """
    legs = []

    # Add put spread legs
    if put_strikes:
        put_legs = await build_opening_spread_legs(
            session, underlying_symbol, expiration_date, "put_spread", put_strikes, put_quantity
        )
        legs.extend(put_legs)

    # Add call spread legs if present
    if call_strikes:
        call_legs = await build_opening_spread_legs(
            session, underlying_symbol, expiration_date, "call_spread", call_strikes, call_quantity
        )
        legs.extend(call_legs)

    return legs
