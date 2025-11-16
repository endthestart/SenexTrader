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
        """
        Get Greeks data for an option symbol.

        Epic 28 Task 008: Read Greeks from streaming cache.

        Args:
            occ_symbol: OCC option symbol (e.g., "SPY  250117C00450000")

        Returns:
            OptionGreeks object if found and fresh, None otherwise
        """
        # Cache uses streamer format (matches DXFeed event_symbol)
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
        # Use module-level logger

        # Try OCC symbol first
        occ_key = CacheManager.quote(occ_symbol)
        payload = cache.get(occ_key)
        logger.info(
            f"🔍 Looking for OCC symbol {occ_symbol}, key: {occ_key}, found: {payload is not None}"
        )

        # If not found and it's an option, try streamer symbol
        if not payload and " " in occ_symbol:
            try:
                from tastytrade.instruments import Option

                streamer_symbol = Option.occ_to_streamer_symbol(occ_symbol)
                streamer_key = CacheManager.quote(streamer_symbol)
                payload = cache.get(streamer_key)
                found = payload is not None
                logger.info(
                    f"🔄 Converted to streamer: {occ_symbol} -> {streamer_symbol}, "
                    f"key: {streamer_key}, found: {found}"
                )

                if payload:
                    bid = payload.get("bid")
                    ask = payload.get("ask")
                    logger.info(
                        f"✅ Found payload for {occ_symbol} using streamer format: "
                        f"bid={bid}, ask={ask}"
                    )
            except Exception as e:
                logger.error(f"❌ Failed to convert OCC symbol {occ_symbol}: {e}")

        if not payload:
            logger.warning(f"❌ No payload found for {occ_symbol} in either format")
            return None

        bid = payload.get("bid")
        ask = payload.get("ask")
        last = payload.get("last")
        logger.info(f"✅ Retrieved payload for {occ_symbol}: bid={bid}, ask={ask}, last={last}")
        return payload

    def build_pricing(self, bundle: SenexOccBundle) -> SenexPricing | None:
        # Use module-level logger

        leg_names = list(bundle.legs.keys())
        logger.info(
            f"📊 Starting build_pricing for {bundle.underlying} "
            f"with {len(bundle.legs)} legs: {leg_names}"
        )
        logger.debug(f"🕐 Freshness threshold: {DEFAULT_MAX_AGE}s ({DEFAULT_MAX_AGE * 1000}ms)")

        snapshots: dict[str, dict] = {}
        put_credit = None
        call_credit = None

        for label, occ_symbol in bundle.legs.items():
            logger.info(f"📋 Processing leg '{label}': {occ_symbol}")
            payload = self.get_quote_payload(occ_symbol)
            if not payload:
                logger.error(f"❌ Failed to get payload for leg '{label}': {occ_symbol}")
                return None
            snapshots[label] = payload
            logger.info(f"✅ Successfully got payload for leg '{label}': {occ_symbol}")

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
                logger.error("❌ Bundle has no valid option legs")
                return None

            # Calculate put spread pricing if present
            if has_put_spread:
                put_credit = _natural_credit(short_put, long_put)
                put_mid_credit = _mid_credit(short_put, long_put)
                if put_credit is None or put_mid_credit is None:
                    logger.error("❌ Failed to calculate put spread pricing")
                    return None
            else:
                put_credit = Decimal("0")
                put_mid_credit = Decimal("0")

            # Calculate call spread pricing if present
            if has_call_spread:
                call_credit = _natural_credit(short_call, long_call)
                call_mid_credit = _mid_credit(short_call, long_call)
                if call_credit is None or call_mid_credit is None:
                    logger.error("❌ Failed to calculate call spread pricing")
                    return None
            else:
                call_credit = Decimal("0")
                call_mid_credit = Decimal("0")

            # Calculate single-leg put pricing (cash-secured put, straddle put leg, etc.)
            if has_single_put and not has_put_spread:
                bid = put_strike.get("bid")
                ask = put_strike.get("ask")
                if bid is None or ask is None:
                    logger.error("❌ Missing bid/ask for single put leg")
                    return None
                # For sold options, credit = what we receive (bid for conservative, mid for realistic)
                put_credit = Decimal(str(bid))  # Natural (conservative)
                put_mid_credit = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")  # Mid

            # Calculate single-leg call pricing (covered call, straddle call leg, etc.)
            if has_single_call and not has_call_spread:
                bid = call_strike.get("bid")
                ask = call_strike.get("ask")
                if bid is None or ask is None:
                    logger.error("❌ Missing bid/ask for single call leg")
                    return None
                # For sold options, credit = what we receive (bid for conservative, mid for realistic)
                call_credit = Decimal(str(bid))  # Natural (conservative)
                call_mid_credit = (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")  # Mid

            # Calculate totals - generic sum of all components
            # The strategy layer handles quantity multipliers (e.g., Senex Trident's 2x put spreads)
            # This method just returns the per-contract pricing
            total_credit = put_credit + call_credit
            total_mid_credit = put_mid_credit + call_mid_credit

            # 🔍 DIAGNOSTIC LOGGING FOR NEGATIVE CREDIT BUG
            logger.info("=" * 80)
            logger.info("🔍 PRICING DIAGNOSTIC - OCC Symbols and Values")
            logger.info("=" * 80)

            # Log OCC symbols for each leg
            for label, occ_symbol in bundle.legs.items():
                snapshot = snapshots.get(label)
                if snapshot:
                    logger.info(
                        f"  {label}: {occ_symbol} | "
                        f"bid=${snapshot.get('bid')}, ask=${snapshot.get('ask')}, "
                        f"strike=${snapshot.get('strike', 'N/A')}"
                    )

            # Log put spread calculation
            if has_put_spread:
                short_put_bid = short_put.get("bid")
                long_put_ask = long_put.get("ask")
                logger.info(
                    f"\n📊 PUT SPREAD: "
                    f"short_put bid=${short_put_bid}, long_put ask=${long_put_ask}"
                )
                logger.info(f"  → put_credit = {short_put_bid} - {long_put_ask} = ${put_credit}")

            # Log call spread calculation
            if has_call_spread:
                short_call_bid = short_call.get("bid")
                long_call_ask = long_call.get("ask")
                logger.info(
                    f"\n📊 CALL SPREAD: "
                    f"short_call bid=${short_call_bid}, long_call ask=${long_call_ask}"
                )
                logger.info(
                    f"  → call_credit = {short_call_bid} - {long_call_ask} = ${call_credit}"
                )

            # Log total calculation
            logger.info(
                f"\n💰 TOTAL: ${put_credit} (put) + ${call_credit} (call) = ${total_credit}"
            )
            logger.info("=" * 80)

            # Note: Pricing can be positive (credit) or negative (debit) depending on strategy
            # - Credit spreads: sell expensive, buy cheap → positive credit
            # - Debit spreads: buy expensive, sell cheap → negative credit (actually a debit)
            # - Calendar spreads: sell near-term, buy far-term → typically negative (debit)
            # The strategy layer validates if pricing makes sense for its use case

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
            logger.debug(
                f"🕐 Pricing freshness check: latency_ms={pricing.latency_ms}, "
                f"is_fresh={pricing.is_fresh}, max_age={DEFAULT_MAX_AGE * 1000}ms"
            )

            # Log snapshot timestamps for debugging
            for label, snapshot in snapshots.items():
                ts = snapshot.get("updated_at") or snapshot.get("timestamp", "N/A")
                logger.debug(f"  📅 {label}: timestamp={ts}")

            if not pricing.is_fresh:
                logger.warning(
                    f"❌ Pricing rejected as stale: latency={pricing.latency_ms}ms "
                    f"exceeds max_age={DEFAULT_MAX_AGE * 1000}ms"
                )
                return None

            return pricing
        except Exception:
            return None
