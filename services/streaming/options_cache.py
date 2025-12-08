"""Utilities for reading streaming-derived data from the cache layer."""

from __future__ import annotations

from decimal import Decimal

from django.core.cache import cache

from services.core.cache import CacheManager
from services.core.logging import get_logger
from services.streaming.dataclasses import (
    DEFAULT_MAX_AGE,
    OptionGreeks,
    SenexOccBundle,
    SenexPricing,
    UnderlyingSnapshot,
)

logger = get_logger(__name__)


class OptionsCache:
    """Thin wrapper around Redis cache keys populated by the streaming layer."""

    def __init__(self, max_age: int = DEFAULT_MAX_AGE) -> None:
        self.max_age = max_age

    def get_underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        payload = cache.get(CacheManager.dxfeed_underlying(symbol))
        if not payload:
            return None
        snapshot = UnderlyingSnapshot.from_cache(symbol, payload)
        return snapshot if snapshot.is_fresh else None

    def get_greeks(self, occ_symbol: str) -> OptionGreeks | None:
        """Get Greeks data for an option symbol."""
        payload = None

        if " " in occ_symbol:
            try:
                from tastytrade.instruments import Option

                streamer_symbol = Option.occ_to_streamer_symbol(occ_symbol)
                greeks_key = CacheManager.dxfeed_greeks(streamer_symbol)
                payload = cache.get(greeks_key)
            except Exception as e:
                logger.error(f"Failed to convert OCC symbol for Greeks: {e}")
        else:
            # For underlying symbols, use symbol directly
            greeks_key = CacheManager.dxfeed_greeks(occ_symbol)
            payload = cache.get(greeks_key)

        if not payload:
            logger.debug(f"No Greeks data found for {occ_symbol}")
            return None

        greeks = OptionGreeks.from_cache(occ_symbol, payload)
        return greeks if greeks.is_fresh else None

    def get_quote_payload(self, occ_symbol: str) -> dict | None:
        occ_key = CacheManager.quote(occ_symbol)
        payload = cache.get(occ_key)
        logger.info(
            f"Looking for OCC symbol {occ_symbol}, key: {occ_key}, found: {payload is not None}"
        )

        if not payload and " " in occ_symbol:
            try:
                from tastytrade.instruments import Option

                streamer_symbol = Option.occ_to_streamer_symbol(occ_symbol)
                streamer_key = CacheManager.quote(streamer_symbol)
                payload = cache.get(streamer_key)
                found = payload is not None
                logger.info(
                    f"Converted to streamer: {occ_symbol} -> {streamer_symbol}, "
                    f"key: {streamer_key}, found: {found}"
                )

                if payload:
                    bid = payload.get("bid")
                    ask = payload.get("ask")
                    logger.info(
                        f"Found payload for {occ_symbol} using streamer format: "
                        f"bid={bid}, ask={ask}"
                    )
            except Exception as e:
                logger.error(f"Failed to convert OCC symbol {occ_symbol}: {e}")

        if not payload:
            logger.warning(f"No payload found for {occ_symbol} in either format")
            return None

        bid = payload.get("bid")
        ask = payload.get("ask")
        last = payload.get("last")
        logger.info(f"Retrieved payload for {occ_symbol}: bid={bid}, ask={ask}, last={last}")
        return payload

    def build_pricing(self, bundle: SenexOccBundle) -> SenexPricing | None:
        logger.debug(f"Building pricing for {bundle.underlying}")

        snapshots: dict[str, dict] = {}
        put_credit = None
        call_credit = None

        for label, occ_symbol in bundle.legs.items():
            payload = self.get_quote_payload(occ_symbol)
            if not payload:
                logger.error(f"Failed to get payload for leg '{label}': {occ_symbol}")
                return None
            snapshots[label] = payload

        try:

            def _natural_credit(
                short_payload: dict | None, long_payload: dict | None
            ) -> Decimal | None:
                """Calculate natural credit (worst-case pricing for conservative risk)"""
                if not short_payload or not long_payload:
                    return None
                bid = short_payload.get("bid")
                ask = long_payload.get("ask")
                if bid is None or ask is None:
                    return None
                return Decimal(str(bid)) - Decimal(str(ask))

            def _mid_credit(
                short_payload: dict | None, long_payload: dict | None
            ) -> Decimal | None:
                """Calculate mid-price credit (realistic pricing for UI display)"""
                if not short_payload or not long_payload:
                    return None
                short_bid = short_payload.get("bid")
                short_ask = short_payload.get("ask")
                long_bid = long_payload.get("bid")
                long_ask = long_payload.get("ask")

                if any(x is None for x in [short_bid, short_ask, long_bid, long_ask]):
                    return None

                # Calculate mid-price for each leg
                short_mid = (Decimal(str(short_bid)) + Decimal(str(short_ask))) / Decimal("2")
                long_mid = (Decimal(str(long_bid)) + Decimal(str(long_ask))) / Decimal("2")

                return short_mid - long_mid

            # Get spread legs (for credit spreads, iron condors, etc.)
            short_put = snapshots.get("short_put")
            long_put = snapshots.get("long_put")
            short_call = snapshots.get("short_call")
            long_call = snapshots.get("long_call")

            # Get single legs (for cash-secured puts, covered calls, straddles, strangles)
            put_strike = snapshots.get("put_strike")
            call_strike = snapshots.get("call_strike")

            # Check what type of position we're building
            has_put_spread = short_put is not None and long_put is not None
            has_call_spread = short_call is not None and long_call is not None
            has_single_put = put_strike is not None
            has_single_call = call_strike is not None

            if not (has_put_spread or has_call_spread or has_single_put or has_single_call):
                logger.error("Bundle has no valid option legs")
                return None

            # Calculate put spread pricing if present
            if has_put_spread:
                put_credit = _natural_credit(short_put, long_put)
                put_mid_credit = _mid_credit(short_put, long_put)
                if put_credit is None or put_mid_credit is None:
                    logger.error("Failed to calculate put spread pricing")
                    return None
            else:
                put_credit = Decimal("0")
                put_mid_credit = Decimal("0")

            # Calculate call spread pricing if present
            if has_call_spread:
                call_credit = _natural_credit(short_call, long_call)
                call_mid_credit = _mid_credit(short_call, long_call)
                if call_credit is None or call_mid_credit is None:
                    logger.error("Failed to calculate call spread pricing")
                    return None
            else:
                call_credit = Decimal("0")
                call_mid_credit = Decimal("0")

            # Calculate single-leg put pricing (cash-secured put, straddle put leg, etc.)
            if has_single_put and not has_put_spread:
                bid = put_strike.get("bid")
                ask = put_strike.get("ask")
                if bid is None or ask is None:
                    logger.error("Missing bid/ask for single put leg")
                    return None
                # For sold options, credit = what we receive (bid for conservative, mid for realistic)
                put_credit = Decimal(str(bid))  # Natural (conservative)
                put_mid_credit = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")  # Mid

            # Calculate single-leg call pricing (covered call, straddle call leg, etc.)
            if has_single_call and not has_call_spread:
                bid = call_strike.get("bid")
                ask = call_strike.get("ask")
                if bid is None or ask is None:
                    logger.error("Missing bid/ask for single call leg")
                    return None
                # For sold options, credit = what we receive (bid for conservative, mid for realistic)
                call_credit = Decimal(str(bid))  # Natural (conservative)
                call_mid_credit = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")  # Mid

            # Calculate totals - generic sum of all components
            # The strategy layer handles quantity multipliers (e.g., Senex Trident's 2x put spreads)
            # This method just returns the per-contract pricing
            total_credit = put_credit + call_credit
            total_mid_credit = put_mid_credit + call_mid_credit

            pricing = SenexPricing(
                # Natural credit (conservative for risk calculations)
                put_credit=put_credit,
                call_credit=call_credit or Decimal("0"),
                total_credit=total_credit,
                # Mid-price credit (realistic for UI display)
                put_mid_credit=put_mid_credit,
                call_mid_credit=call_mid_credit or Decimal("0"),
                total_mid_credit=total_mid_credit,
                snapshots=snapshots,
            )

            # Debug freshness check
            if not pricing.is_fresh:
                logger.warning(
                    f"Pricing rejected as stale: latency={pricing.latency_ms}ms "
                    f"exceeds max_age={DEFAULT_MAX_AGE * 1000}ms"
                )
                return None

            return pricing
        except Exception:
            return None
