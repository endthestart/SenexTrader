"""
Symbol conversion utilities with workarounds for TastyTrade SDK bugs.

This module provides corrected versions of SDK symbol conversion functions
that work around known bugs in the TastyTrade SDK.
"""

from tastytrade.instruments import Option


def streamer_to_occ_fixed(streamer_symbol: str) -> str:
    """
    Convert DXFeed/streamer format symbol to OCC format with SDK bug workaround.

    Workaround for TastyTrade SDK bug in Option.streamer_symbol_to_occ().
    The SDK function produces 22-character symbols for certain strikes (like 599.78)
    instead of the correct 21-character OCC format. It multiplies the strike by
    10000 instead of 1000, adding an extra trailing zero.

    Example of SDK bug:
        Input:  .QQQ251219P599.78
        SDK:    QQQ   251219P005997800 (22 chars, strike=5997800) 
        Fixed:  QQQ   251219P00599780  (21 chars, strike=599780)  [OK]

    Args:
        streamer_symbol: DXFeed/streamer format symbol (e.g., '.QQQ251219P599.78')

    Returns:
        OCC format symbol in correct 21-character format

    Raises:
        ValueError: If symbol format is invalid or cannot be corrected

    References:
        - TastyTrade SDK bug affects certain decimal strikes
        - OCC format: SYMBOL(6) + YYMMDD(6) + C/P(1) + STRIKE(8) = 21 chars
        - See: streaming/services/stream_manager.py for usage
    """
    # Try SDK conversion first
    try:
        occ_symbol = Option.streamer_symbol_to_occ(streamer_symbol)
    except Exception as e:
        raise ValueError(f"SDK conversion failed for '{streamer_symbol}': {e}")

    # Check if result is the correct 21 characters
    if len(occ_symbol) == 21:
        return occ_symbol

    # SDK bug: strike portion is 9 digits instead of 8 (extra trailing zero)
    if len(occ_symbol) == 22:
        # Format: SYMBOL(6) + YYMMDD(6) + C/P(1) + STRIKE(9 -> should be 8)
        root = occ_symbol[:6]  # 6 chars: "QQQ   "
        exp = occ_symbol[6:12]  # 6 chars: "251219"
        opt_type = occ_symbol[12]  # 1 char:  "P"
        strike_bad = occ_symbol[13:22]  # 9 chars: "005997800" (BUG)

        # Remove trailing zero and reformat to 8 digits
        # The SDK multiplied by 10000 instead of 1000, so divide by 10
        strike_value = int(strike_bad) // 10  # 005997800 -> 599780
        strike_fixed = f"{strike_value:08d}"  # Format as 8 digits: "00599780"

        corrected = f"{root}{exp}{opt_type}{strike_fixed}"

        # Verify correction produced valid 21-char symbol
        if len(corrected) != 21:
            raise ValueError(
                f"Workaround failed: corrected symbol '{corrected}' is {len(corrected)} chars, expected 21"
            )

        return corrected

    # Unknown format length
    raise ValueError(
        f"Invalid OCC symbol format: '{occ_symbol}' is {len(occ_symbol)} chars, expected 21. "
        f"Original streamer symbol: '{streamer_symbol}'"
    )
