"""Synchronous facade for reading streaming-backed option data."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from threading import Lock

from django.conf import settings
from django.core.cache import cache

from channels.layers import get_channel_layer

from services.core.cache import CacheManager
from services.core.constants import OPTION_CHAIN_CACHE_TTL
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async
from services.market_data.option_chains import (
    OptionChainService,
    extract_call_strikes,
    extract_put_strikes,
)
from services.streaming.dataclasses import (
    OptionGreeks,
    SenexOccBundle,
    SenexPricing,
    UnderlyingSnapshot,
)
from services.streaming.options_cache import OptionsCache

logger = get_logger(__name__)
CHAIN_LOCKS: dict[str, Lock] = defaultdict(Lock)


class StreamingOptionsDataService:
    """Read-only access to streaming caches for synchronous callers."""

    def __init__(self, user):
        self.user = user
        self.cache = OptionsCache()
        self._chain_ttl = getattr(settings, "OPTION_CHAIN_CACHE_TTL", 600)

    def read_underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        """Read underlying data"""
        underlying = self.cache.get_underlying(symbol)
        if not underlying:
            logger.debug(f"No underlying data available for {symbol}")
            return None
        return underlying

    def read_spread_pricing(self, bundle: SenexOccBundle) -> SenexPricing | None:
        leg_names = list(bundle.legs.keys())
        logger.info(f"read_spread_pricing called for {bundle.underlying} with legs: {leg_names}")

        try:
            pricing = self.cache.build_pricing(bundle)
            if not pricing:
                logger.warning(f"cache.build_pricing returned None for {bundle.underlying}")
                return None

            logger.info(
                f"Successfully built pricing: put_credit={pricing.put_credit}, "
                f"call_credit={pricing.call_credit}, total_credit={pricing.total_credit}"
            )

            return pricing
        except Exception as e:
            logger.error(f"Exception in read_spread_pricing: {e}", exc_info=True)
            return None

    def read_greeks(self, occ_symbol: str) -> OptionGreeks | None:
        """
        Read Greeks data for an option symbol.


        Args:
            occ_symbol: OCC option symbol (e.g., "SPY  250117C00450000")

        Returns:
            OptionGreeks object if found in cache, None otherwise

        Example:
            >>> service = StreamingOptionsDataService(user)
            >>> greeks = service.read_greeks("SPY  250117C00450000")
            >>> if greeks:
            ...     print(f"Delta: {greeks.delta}, Theta: {greeks.theta}")
        """
        try:
            greeks = self.cache.get_greeks(occ_symbol)
            if not greeks:
                logger.debug(f"No Greeks data available for {occ_symbol}")
                return None

            logger.debug(
                f"Greeks for {occ_symbol}: delta={greeks.delta}, "
                f"gamma={greeks.gamma}, theta={greeks.theta}, vega={greeks.vega}"
            )
            return greeks
        except Exception as e:
            logger.error(f"Exception reading Greeks for {occ_symbol}: {e}", exc_info=True)
            return None

    def ensure_leg_stream(self, symbol: str, expiration: date, occ_symbols: list[str]) -> None:
        """Synchronous wrapper for the async ensure_leg_stream method."""
        return run_async(self.a_ensure_leg_stream(symbol, expiration, occ_symbols))

    async def a_ensure_leg_stream(
        self, symbol: str, expiration: date, occ_symbols: list[str]
    ) -> None:
        """Sends a message to the user's stream manager to subscribe to new symbols."""
        if not self.user or not occ_symbols:
            return

        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                logger.warning("Channel layer not available, cannot subscribe to legs.")
                return

            group_name = f"stream_control_{self.user.id}"
            message = {
                "type": "subscribe_legs",
                "symbols": occ_symbols,
            }

            await channel_layer.group_send(group_name, message)
            logger.info(f"Sent subscription request for {len(occ_symbols)} symbols to {group_name}")

        except Exception as e:
            logger.error(f"Failed to send leg subscription message: {e}", exc_info=True)

    async def build_occ_bundle(
        self, symbol: str, expiration: date, strikes: dict[str, Decimal]
    ) -> SenexOccBundle | None:
        """Build OCC bundle from strikes and cached option chain."""
        logger.info(
            f"User {self.user.id}: Building OCC bundle for {symbol} expiring {expiration}"
        )
        chain = await self._get_option_chain(symbol, expiration)
        if not chain:
            return None

        put_strikes = extract_put_strikes(chain.get("strikes", []))
        call_strikes = extract_call_strikes(chain.get("strikes", []))

        logger.debug(f"User {self.user.id}: Strikes to validate: {strikes}")
        logger.debug(
            f"User {self.user.id}: Available put strikes (sample): {sorted(put_strikes)[:10]}"
        )
        logger.debug(
            f"User {self.user.id}: Available call strikes (sample): {sorted(call_strikes)[:10]}"
        )

        # Validate strikes exist
        if not self._validate_strikes(strikes, put_strikes, call_strikes):
            logger.warning(f"User {self.user.id}: Strike validation failed for {strikes}")
            return None

        symbols = {}
        strikes_list = chain.get("strikes", [])

        if not strikes_list:
            logger.error(
                f"User {self.user.id}: No strikes list in chain for {symbol} {expiration}. "
                f"Cannot build OCC bundle without chain-provided OCC symbols."
            )
            return None

        # Use chain-provided OCC symbols (SDK pattern)
        for leg, strike_price in strikes.items():
            option_type = "P" if "put" in leg else "C"
            # Find Strike object with matching price
            strike_obj = next(
                (s for s in strikes_list if Decimal(s["strike_price"]) == strike_price), None
            )
            if not strike_obj:
                logger.error(
                    f"User {self.user.id}: Strike {strike_price} not found in chain for {leg}"
                )
                return None

            # Extract OCC symbol from Strike object
            occ_symbol = strike_obj["put"] if option_type == "P" else strike_obj["call"]
            if not occ_symbol:
                logger.error(
                    f"User {self.user.id}: No OCC symbol for {option_type} at strike {strike_price}"
                )
                return None

            symbols[leg] = occ_symbol
            logger.debug(
                f"User {self.user.id}: {leg} @ {strike_price} -> {occ_symbol} (from chain)"
            )

        return SenexOccBundle(underlying=symbol, expiration=expiration, legs=symbols)

    def _validate_strikes(self, strikes: dict, put_strikes: set, call_strikes: set) -> bool:
        """Validate that selected strikes are available in the chain."""
        # Spread strikes validation
        if "short_put" in strikes and strikes["short_put"] not in put_strikes:
            logger.warning(f"short_put {strikes['short_put']} not in put_strikes")
            return False
        if "long_put" in strikes and strikes["long_put"] not in put_strikes:
            logger.warning(f"long_put {strikes['long_put']} not in put_strikes")
            return False
        if "short_call" in strikes and strikes["short_call"] not in call_strikes:
            logger.warning(f"short_call {strikes['short_call']} not in call_strikes")
            return False
        if "long_call" in strikes and strikes["long_call"] not in call_strikes:
            logger.warning(f"long_call {strikes['long_call']} not in call_strikes")
            return False

        # Single-leg strikes validation (cash secured put, covered call)
        if "put_strike" in strikes and strikes["put_strike"] not in put_strikes:
            logger.error(
                f"User {self.user.id}: Strike {strikes['put_strike']} not found in chain for put_strike"
            )
            return False
        if "call_strike" in strikes and strikes["call_strike"] not in call_strikes:
            logger.error(
                f"User {self.user.id}: Strike {strikes['call_strike']} not found in chain for call_strike"
            )
            return False

        return True

    async def _get_option_chain(self, symbol: str, expiration: date | None = None) -> dict | None:
        """Get option chain from cache or fetch from API using OptionChainService."""
        option_chain_service = OptionChainService()

        # Use exact expiration if provided, otherwise use default DTE
        if expiration:
            cache_key = CacheManager.option_chain_with_expiration(symbol, expiration)
            logger.info(f"User {self.user.id}: Using exact expiration {expiration}")

            cached_chain = cache.get(cache_key)
            if cached_chain:
                logger.info(f"User {self.user.id}: Using cached option chain for {symbol}")
                return cached_chain

            logger.info(
                f"User {self.user.id}: Fetching option chain for {symbol} "
                f"at exact expiration {expiration}"
            )
            chain_data = await option_chain_service.get_option_chain_by_expiration(
                self.user, symbol, target_expiration=expiration
            )
        else:
            target_dte = 45
            cache_key = CacheManager.full_option_chain(symbol)
            logger.info(f"User {self.user.id}: Using default DTE: {target_dte}")

            cached_chain = cache.get(cache_key)
            if cached_chain:
                logger.info(f"User {self.user.id}: Using cached option chain for {symbol}")
                return cached_chain

            logger.info(
                f"User {self.user.id}: Fetching option chain for {symbol} "
                f"with target_dte={target_dte}"
            )
            chain_data = await option_chain_service.get_option_chain(
                self.user, symbol, target_dte=target_dte
            )

        if chain_data:
            chain = {
                "strikes": chain_data.get("strikes", []),
            }
            cache.set(cache_key, chain, timeout=OPTION_CHAIN_CACHE_TTL)
            strikes_list = chain["strikes"]
            num_puts = len(extract_put_strikes(strikes_list))
            num_calls = len(extract_call_strikes(strikes_list))
            num_strikes = len(strikes_list)
            logger.info(
                f"User {self.user.id}: Option chain fetched and cached for {symbol} "
                f"(strikes: {num_strikes}, puts: {num_puts}, calls: {num_calls})"
            )
            return chain

        if expiration:
            logger.warning(
                f"User {self.user.id}: Failed to fetch option chain for {symbol} "
                f"at exact expiration {expiration}"
            )
        else:
            logger.warning(
                f"User {self.user.id}: Failed to fetch option chain for {symbol} "
                f"with target_dte={target_dte}"
            )
        return None

    def _resolve_leg(
        self,
        strike_map: dict[str, dict[str, str | None]],
        strike_value: Decimal,
        side: str,
    ) -> str | None:
        if strike_value is None:
            return None
        strike_key = self._strike_key(strike_value)
        entry = strike_map.get(strike_key)
        if not entry:
            entry = self._nearest_entry(strike_map, strike_value)
        if not entry:
            return None
        return entry.get(side)

    @staticmethod
    def _strike_key(value: Decimal) -> str:
        dec = Decimal(str(value))
        return str(int(dec * Decimal("1000")))

    @staticmethod
    def _nearest_entry(
        strike_map: dict[str, dict[str, str | None]], strike_value: Decimal
    ) -> dict[str, str | None] | None:
        if not strike_map:
            return None
        target_int = int(Decimal(str(strike_value)) * Decimal("1000"))
        closest_key = min(strike_map.keys(), key=lambda key: abs(int(key) - target_int))
        return strike_map.get(closest_key)
