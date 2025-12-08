"""Option chain service with strike selection for Senex Trident strategy."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.core.cache import CacheManager, CacheTTL
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async
from trading.models import Position

User = get_user_model()
logger = get_logger(__name__)


def extract_put_strikes(strikes_list: list[dict]) -> set[Decimal]:
    """
    Extract put strike prices from strikes list of Strike objects.

    Args:
        strikes_list: List of Strike dicts with 'strike_price' and 'put' keys

    Returns:
        Set of Decimal strike prices where put options exist

    Example:
        >>> strikes = [
        ...     {"strike_price": "565", "put": "SPY 251121P565", "call": None},
        ...     {"strike_price": "570", "put": "SPY 251121P570", "call": "SPY 251121C570"}
        ... ]
        >>> extract_put_strikes(strikes)
        {Decimal('565'), Decimal('570')}
    """
    return {Decimal(str(s["strike_price"])) for s in strikes_list if s.get("put")}


def extract_call_strikes(strikes_list: list[dict]) -> set[Decimal]:
    """
    Extract call strike prices from strikes list of Strike objects.

    Args:
        strikes_list: List of Strike dicts with 'strike_price' and 'call' keys

    Returns:
        Set of Decimal strike prices where call options exist

    Example:
        >>> strikes = [
        ...     {"strike_price": "565", "put": "SPY 251121P565", "call": None},
        ...     {"strike_price": "570", "put": "SPY 251121P570", "call": "SPY 251121C570"}
        ... ]
        >>> extract_call_strikes(strikes)
        {Decimal('570')}
    """
    return {Decimal(str(s["strike_price"])) for s in strikes_list if s.get("call")}


class OptionChainService:
    """Simple, direct option data access for strike selection."""

    def get_nested_option_chain(self, user: User, symbol: str):
        """Synchronous wrapper for a_get_nested_option_chain."""
        return run_async(self.a_get_nested_option_chain(user, symbol))

    async def a_get_nested_option_chain(self, user: User, symbol: str):
        """Fetches the full nested option chain, using a 24-hour cache."""
        cache_key = CacheManager.option_chain_nested(symbol)
        cached_chain = cache.get(cache_key)
        if cached_chain:
            logger.debug(f"Using cached nested option chain for {symbol}")
            return cached_chain

        try:
            # Get TastyTrade session
            from services.core.data_access import get_oauth_session

            session = await get_oauth_session(user)
            if not session:
                logger.error(f"Failed to get OAuth session for user {user.id}")
                return None

            from tastytrade.instruments import NestedOptionChain

            chain = await NestedOptionChain.a_get(session, symbol)
            if chain:
                # Cache the chain for 24 hours as it's static for the day.
                cache.set(cache_key, chain, timeout=CacheTTL.NESTED_CHAIN)
            return chain
        except Exception as e:
            logger.error(
                f"Error fetching nested option chain for {symbol}: {e}",
                exc_info=True,
            )
            return None

    def get_all_expirations(self, user: User, symbol: str) -> list[date] | None:
        """Synchronous wrapper for a_get_all_expirations."""
        return run_async(self.a_get_all_expirations(user, symbol))

    async def a_get_all_expirations(self, user: User, symbol: str) -> list[date] | None:
        """Extracts all available option expiration dates from the nested chain."""
        chains = await self.a_get_nested_option_chain(user, symbol)
        if not chains:
            return None

        expirations = []
        for chain in chains:
            for expiration_data in chain.expirations:
                expirations.append(expiration_data.expiration_date)

        return sorted(expirations)

    async def get_option_chain(self, user: User, symbol: str, target_dte: int) -> dict | None:
        """
        Fetch options for target expiration.

        Args:
            user: User for session access
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            target_dte: Target days to expiration

        Returns:
            Dict with option chain data or None if failed
        """
        cache_key = CacheManager.option_chain_with_dte(symbol, target_dte)
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug(f"Using cached option chain for {symbol} {target_dte} DTE")
            return cached_data

        try:
            # Get TastyTrade session
            from services.core.data_access import get_oauth_session

            session = await get_oauth_session(user)
            if not session:
                logger.error(f"Failed to get OAuth session for user {user.id}")
                return None

            # Find target expiration date
            target_expiration = await self._find_target_expiration(target_dte)
            if not target_expiration:
                return None

            # Fetch option chain from TastyTrade
            chain_data = await self._fetch_tastytrade_option_chain(
                session, symbol, target_expiration, user
            )
            if not chain_data:
                return None

            # Cache the result
            cache.set(cache_key, chain_data, CacheTTL.OPTION_CHAIN)
            logger.info(f"Cached option chain for {symbol} {target_expiration}")

            return chain_data

        except Exception as e:
            logger.error(f"Error fetching option chain for {symbol}: {e}", exc_info=True)
            return None

    async def get_option_chain_by_expiration(
        self, user: User, symbol: str, target_expiration: date
    ) -> dict | None:
        """
        Fetch option chain for EXACT expiration date (no DTE conversion/rounding).

        Use this method when you need options for a specific expiration date.
        Unlike get_option_chain() which rounds to "next Friday", this method
        fetches the exact expiration provided.

        Args:
            user: User for session access
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            target_expiration: Exact expiration date to fetch

        Returns:
            Dict with option chain data or None if exact expiration not available
        """
        cache_key = CacheManager.option_chain_with_expiration(symbol, target_expiration)
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug(f"Using cached option chain for {symbol} {target_expiration}")
            return cached_data

        try:
            # Get TastyTrade session
            from services.core.data_access import get_oauth_session

            session = await get_oauth_session(user)
            if not session:
                logger.error(f"Failed to get OAuth session for user {user.id}")
                return None

            # Fetch option chain for exact expiration (no DTE rounding)
            chain_data = await self._fetch_tastytrade_option_chain(
                session, symbol, target_expiration, user
            )
            if not chain_data:
                logger.warning(
                    f"No option chain data available for {symbol} "
                    f"at exact expiration {target_expiration}"
                )
                return None

            # Cache the result
            cache.set(cache_key, chain_data, CacheTTL.OPTION_CHAIN)
            logger.info(f"Cached option chain for {symbol} {target_expiration}")

            return chain_data

        except Exception as e:
            logger.error(
                f"Error fetching option chain for {symbol} at {target_expiration}: {e}",
                exc_info=True,
            )
            return None

    async def get_multi_expiration_chains(
        self, user: User, symbol: str, target_dtes: list[int]
    ) -> dict[str, dict]:
        """
        Fetch option chains for multiple target DTEs efficiently.

        Epic 22 Task 011: Multi-expiration support for Calendar Spreads.

        Args:
            user: User for session access
            symbol: Underlying symbol
            target_dtes: List of target DTEs [25, 55] for calendar spread

        Returns:
            {
                '25': {
                    'expiration_date': date(2025, 11, 15),
                    'actual_dte': 25,
                    'strikes': [...],
                    ...
                },
                '55': {
                    'expiration_date': date(2025, 12, 15),
                    'actual_dte': 56,
                    'strikes': [...],
                    ...
                }
            }
        """
        results = {}

        for target_dte in target_dtes:
            try:
                chain = await self.get_option_chain(user, symbol, target_dte)
                if chain:
                    results[str(target_dte)] = chain
                else:
                    logger.warning(f"Could not fetch chain for {symbol} at {target_dte} DTE")
                    results[str(target_dte)] = None
            except Exception as e:
                logger.warning(f"Error fetching chain for {target_dte} DTE: {e}")
                results[str(target_dte)] = None

        return results

    async def select_strikes(
        self, current_price: Decimal, chain: dict, width: int
    ) -> dict[str, Decimal] | None:
        """
        Strike selection with fallback logic for testing.

        NOTE: This is a test utility method used by test_option_chain_service.py
        and test_senex_trident_integration.py. Production code should use
        SenexTridentStrategy._select_even_strikes() instead.

        This method intentionally duplicates strategy logic to provide fallback
        behavior (selecting higher strikes when exact strikes unavailable) which
        is useful for test scenarios.

        Args:
            current_price: Current underlying price
            chain: Option chain data from get_option_chain
            width: Spread width (3, 5, 7, or 9)

        Returns:
            Dict with selected strikes or None if invalid
        """
        try:
            # Calculate base strike using Senex Trident formula: round(price/2)*2
            base_strike = Decimal(str(round(float(current_price) / 2) * 2))

            put_strikes = extract_put_strikes(chain.get("strikes", []))
            call_strikes = extract_call_strikes(chain.get("strikes", []))

            # Step 2: Select put spread strikes
            put_strikes_selected = self._select_put_spread_strikes(base_strike, width, put_strikes)
            if not put_strikes_selected:
                logger.warning(
                    f"Could not select put strikes for base {base_strike}, width {width}"
                )
                return None

            # Step 3: Select call spread strikes (optional)
            call_strikes_selected = self._select_call_spread_strikes(
                base_strike, width, call_strikes
            )

            strikes = {
                "short_put": put_strikes_selected["short"],
                "long_put": put_strikes_selected["long"],
            }

            if call_strikes_selected:
                strikes.update(
                    {
                        "short_call": call_strikes_selected["short"],
                        "long_call": call_strikes_selected["long"],
                    }
                )

            logger.info(f"Selected strikes: {strikes}")
            return strikes

        except Exception as e:
            logger.error(f"Error selecting strikes: {e}", exc_info=True)
            return None

    def _select_strike_with_fallback(
        self, target_strike: Decimal, available_strikes: set[Decimal]
    ) -> Decimal | None:
        """If exact unavailable, choose HIGHER for more credit."""
        if target_strike in available_strikes:
            return target_strike

        # Find next higher strike
        higher_strikes = [s for s in available_strikes if s > target_strike]
        if higher_strikes:
            return min(higher_strikes)

        return None

    def _select_put_spread_strikes(
        self, base_strike: Decimal, width: int, put_strikes: set[Decimal]
    ) -> dict[str, Decimal] | None:
        """Select put spread strikes (sell higher, buy lower)."""
        # Short put: at or near base strike
        short_put = self._select_strike_with_fallback(base_strike, put_strikes)
        if not short_put:
            return None

        # Long put: width points below short put
        long_put = short_put - Decimal(str(width))
        if long_put not in put_strikes:
            available_near = sorted([s for s in put_strikes if abs(s - long_put) <= 5])[:5]
            logger.warning(
                f"Long put strike {long_put} not available. "
                f"Short put: {short_put}, Width: {width}. "
                f"Nearest available strikes: {available_near}"
            )
            return None

        return {"short": short_put, "long": long_put}

    def _select_call_spread_strikes(
        self, base_strike: Decimal, width: int, call_strikes: set[Decimal]
    ) -> dict[str, Decimal] | None:
        """Select call spread strikes (sell lower, buy higher)."""
        # Short call: at or near base strike
        short_call = self._select_strike_with_fallback(base_strike, call_strikes)
        if not short_call:
            return None

        # Long call: width points above short call
        long_call = short_call + Decimal(str(width))
        if long_call not in call_strikes:
            available_near = sorted([s for s in call_strikes if abs(s - long_call) <= 5])[:5]
            logger.warning(
                f"Long call strike {long_call} not available. "
                f"Short call: {short_call}, Width: {width}. "
                f"Nearest available strikes: {available_near}"
            )
            return None

        return {"short": short_call, "long": long_call}

    async def validate_strike_availability(self, strikes: dict[str, Decimal], chain: dict) -> bool:
        """Ensure all strikes exist in the option chain."""
        put_strikes = extract_put_strikes(chain.get("strikes", []))
        call_strikes = extract_call_strikes(chain.get("strikes", []))

        # Validate put strikes
        if "short_put" in strikes and strikes["short_put"] not in put_strikes:
            return False
        if "long_put" in strikes and strikes["long_put"] not in put_strikes:
            return False

        # Validate call strikes (if present)
        if "short_call" in strikes and strikes.get("short_call"):
            if strikes["short_call"] not in call_strikes:
                return False
        if "long_call" in strikes and strikes.get("long_call"):
            if strikes["long_call"] not in call_strikes:
                return False

        return True

    async def check_strike_overlap(
        self, user: User, new_strikes: dict[str, Decimal], symbol: str, expiration: date
    ) -> tuple[bool, str | None]:
        """
        Prevent conflicts with existing positions.

        Returns:
            (has_overlap, reason) - True if overlap detected
        """
        try:
            # Get existing positions for this symbol and expiration
            existing_positions = await sync_to_async(
                lambda: list(
                    Position.objects.filter(
                        user=user,
                        symbol=symbol,
                        lifecycle_state__in=["open_full", "open_partial", "closing"],
                        is_app_managed=True,  # Only check app-managed positions
                    )
                )
            )()

            if not existing_positions:
                return False, None

            # Check for strike overlaps
            for position in existing_positions:
                metadata = position.metadata or {}
                strikes_data = metadata.get("strikes", {})

                # Check if expiration matches
                position_exp = metadata.get("expiration")
                if position_exp:
                    from datetime import datetime

                    position_exp_date = datetime.fromisoformat(position_exp).date()
                    if position_exp_date != expiration:
                        continue  # Different expiration, no conflict

                # Check for overlapping strikes
                overlap_found = False
                overlap_details = []

                for strike_type, strike_value in new_strikes.items():
                    if strike_value and str(strike_value) in strikes_data.values():
                        overlap_found = True
                        overlap_details.append(f"{strike_type}: {strike_value}")

                if overlap_found:
                    reason = (
                        f"Strike overlap with position {position.id}: {', '.join(overlap_details)}"
                    )
                    return True, reason

            return False, None

        except Exception as e:
            logger.error(f"Error checking strike overlap: {e}", exc_info=True)
            return True, f"Error checking overlap: {e!s}"

    async def _find_target_expiration(self, target_dte: int) -> date | None:
        """Find target expiration date based on DTE."""
        today = timezone.now().date()
        target_date = today + timedelta(days=target_dte)

        # Find next Friday after target date (standard options expiration)
        days_ahead = (4 - target_date.weekday()) % 7  # Friday is 4
        if days_ahead == 0 and target_date.weekday() == 4:  # Already Friday
            next_friday = target_date
        else:
            next_friday = target_date + timedelta(days=days_ahead)

        return next_friday

    async def _fetch_tastytrade_option_chain(
        self, session, symbol: str, expiration: date, user: User
    ) -> dict | None:
        """Fetch REAL option chain data from TastyTrade API."""
        try:
            from tastytrade.instruments import NestedOptionChain

            # Log the actual API call
            logger.info(
                f"Fetching REAL option chain for {symbol} targeting EXACT expiration {expiration}"
            )

            # Get all option chains for symbol using TastyTrade SDK async method
            chains = await NestedOptionChain.a_get(session, symbol)

            if not chains:
                logger.warning(f"No option chains available for {symbol}")
                return None

            # Find EXACT expiration match (not "closest")
            target_exp = self._find_exact_expiration(chains, expiration)
            if not target_exp:
                logger.error(
                    f"EXACT expiration {expiration} not found for {symbol}. "
                    f"This indicates a mismatch between expiration selection and available chains."
                )
                return None

            # Extract strikes from the matching chain
            strikes_list = []  # Initialize to prevent UnboundLocalError

            for chain_item in chains:
                # NestedOptionChain: look through each expiration
                if hasattr(chain_item, "expirations") and chain_item.expirations:
                    for expiration_obj in chain_item.expirations:
                        # Handle both datetime and date objects
                        exp_date = expiration_obj.expiration_date
                        if hasattr(exp_date, "date"):
                            exp_date = exp_date.date()

                        if exp_date == target_exp:
                            logger.debug(f"Found matching expiration: {target_exp}")

                            # Extract strikes from this expiration
                            if hasattr(expiration_obj, "strikes") and expiration_obj.strikes:
                                # Epic 28 Task 010: Preserve Strike objects with OCC symbols
                                strikes_list = []
                                for strike in expiration_obj.strikes:
                                    strike_price = Decimal(str(strike.strike_price))

                                    # Build Strike dict with OCC symbols
                                    strike_dict = {
                                        "strike_price": str(strike_price),
                                        "call": strike.call if hasattr(strike, "call") else None,
                                        "put": strike.put if hasattr(strike, "put") else None,
                                        "call_streamer_symbol": (
                                            strike.call_streamer_symbol
                                            if hasattr(strike, "call_streamer_symbol")
                                            else None
                                        ),
                                        "put_streamer_symbol": (
                                            strike.put_streamer_symbol
                                            if hasattr(strike, "put_streamer_symbol")
                                            else None
                                        ),
                                    }
                                    strikes_list.append(strike_dict)
                            else:
                                logger.warning(f"Expiration {target_exp} has no strikes")
                                strikes_list = []
                            break  # Found the target expiration
                else:
                    logger.debug("Chain item missing expirations attribute")

            logger.info(f"Strikes extraction complete for {symbol} {target_exp}:")
            put_strikes_set = extract_put_strikes(strikes_list)
            call_strikes_set = extract_call_strikes(strikes_list)
            put_display = sorted(put_strikes_set) if put_strikes_set else "None"
            logger.info(f"   Put strikes: {len(put_strikes_set)} found ({put_display})")
            call_display = sorted(call_strikes_set) if call_strikes_set else "None"
            logger.info(f"   Call strikes: {len(call_strikes_set)} found ({call_display})")

            if not put_strikes_set and not call_strikes_set:
                logger.warning(f"No valid strikes found for {symbol} {target_exp}")
                return None

            # Fetch current price from MarketAnalyzer
            # (TastyTrade NestedOptionChainExpiration doesn't include underlying_price)
            from services.market_data.analysis import MarketAnalyzer

            analyzer = MarketAnalyzer(user)
            price_float = await analyzer._get_current_quote(symbol)
            if price_float:
                current_price = Decimal(str(price_float))
                logger.debug(f"Fetched current price for {symbol}: {current_price}")
            else:
                current_price = None

            # CRITICAL: Fail fast if current price unavailable
            if current_price is None:
                logger.error(
                    f"No current price available for {symbol} {target_exp}. "
                    f"Cannot build option chain without underlying price."
                )
                return None

            result = {
                "symbol": symbol,
                "expiration": target_exp.isoformat(),
                "strikes": strikes_list,  # Epic 28 Task 010: Full Strike objects with OCC symbols
                "fetched_at": timezone.now().isoformat(),
                "source": "tastytrade_api",
                "total_strikes": len(put_strikes_set | call_strikes_set),
            }

            # Add current price if available
            if current_price:
                result["current_price"] = current_price

            logger.info(
                f"Successfully fetched {result['total_strikes']} strikes for {symbol} "
                f"expiring {target_exp}"
            )

            return result

        except Exception as e:
            logger.error(f"Error fetching TastyTrade option chain: {e}", exc_info=True)
            return None

    def _find_exact_expiration(self, chains: list, target: date) -> date | None:
        """Find EXACT expiration match in chains. Returns None if not found."""
        logger.info(f"Looking for EXACT expiration {target}")

        if not chains:
            logger.warning("No chains provided")
            return None

        expirations = []
        for chain in chains:
            if hasattr(chain, "expirations") and chain.expirations:
                for expiration_obj in chain.expirations:
                    if hasattr(expiration_obj, "expiration_date"):
                        exp_date = expiration_obj.expiration_date
                        if hasattr(exp_date, "date"):
                            exp_date = exp_date.date()
                        expirations.append(exp_date)

        logger.debug(f"Found {len(expirations)} total expirations")

        # Look for EXACT match
        if target in expirations:
            logger.info(f"Found EXACT expiration match: {target}")
            return target
        available_sample = sorted(set(expirations))[:10]
        logger.error(
            f"EXACT expiration {target} not found in chain. "
            f"Available (sample): {available_sample}"
        )
        return None

    def _find_closest_expiration(self, chains: list, target: date) -> date | None:
        """Find the expiration date closest to target from chains."""
        chains_count = len(chains) if chains else 0
        logger.info(f"Looking for closest expiration to {target} from {chains_count} chains")

        if not chains:
            logger.warning("No chains provided")
            return None

        expirations = []
        for i, chain in enumerate(chains):
            has_exp = hasattr(chain, "expirations")
            logger.debug(f"Chain {i}: type={type(chain)}, hasattr expirations: {has_exp}")

            # NestedOptionChain: chain.expirations list with dates
            if hasattr(chain, "expirations") and chain.expirations:
                logger.debug(f"Chain {i} has {len(chain.expirations)} expiration objects")
                for j, expiration_obj in enumerate(chain.expirations):
                    has_exp_date = hasattr(expiration_obj, "expiration_date")
                    logger.debug(
                        f"  Expiration {j}: type={type(expiration_obj)}, "
                        f"hasattr expiration_date: {has_exp_date}"
                    )
                    if hasattr(expiration_obj, "expiration_date"):
                        # Handle both datetime and date objects
                        exp_date = expiration_obj.expiration_date
                        if hasattr(exp_date, "date"):
                            exp_date = exp_date.date()
                        expirations.append(exp_date)
                        logger.debug(f"    Found expiration: {exp_date}")
                    else:
                        logger.debug(f"    Expiration {j} missing expiration_date attribute")
            else:
                logger.debug(f"Chain {i} missing expirations attribute or empty")

        exp_display = sorted(expirations) if expirations else "None"
        logger.info(f"Found {len(expirations)} total expirations: {exp_display}")

        if not expirations:
            logger.warning("No expiration dates found in chains")
            return None

        # Filter for expirations on or after target
        future_expirations = [exp for exp in expirations if exp >= target]
        future_display = sorted(future_expirations) if future_expirations else "None"
        logger.info(f"Future expirations (>= {target}): {future_display}")

        if future_expirations:
            # Find closest future expiration
            closest = min(future_expirations, key=lambda x: abs((x - target).days))
            dte = (closest - target).days
            logger.info(f"Selected closest future expiration: {closest} (DTE: {dte})")
        else:
            # If no future expirations, get the closest past one
            closest = min(expirations, key=lambda x: abs((x - target).days))
            logger.warning(f"No future expirations found, using past expiration: {closest}")

        return closest

    async def _get_primary_account(self, user: User) -> TradingAccount | None:
        """Get user's primary TastyTrade account."""
        # Use centralized data_access utility
        from services.core.data_access import get_primary_tastytrade_account

        return await get_primary_tastytrade_account(user)

    def validate_strikes_available(
        self, strikes: list[Decimal], symbol: str, expiration: date
    ) -> bool:
        """
        Generic validation that strikes exist for symbol/expiration.

        This is a reusable method that any strategy can use to validate
        that required strikes exist in the option chain before attempting
        to build positions.

        Args:
            strikes: List of strike prices to validate
            symbol: Underlying symbol (e.g. 'SPY', 'QQQ')
            expiration: Option expiration date

        Returns:
            bool: True if all strikes are available, False otherwise
        """
        try:
            # Get available strikes from option chain
            option_chain = self.get_option_chain(symbol, expiration)
            if not option_chain:
                return False

            # Combine all available strikes (puts and calls)
            put_strikes = extract_put_strikes(option_chain.get("strikes", []))
            call_strikes = extract_call_strikes(option_chain.get("strikes", []))
            all_available = put_strikes.union(call_strikes)

            # Check if all required strikes are available
            return all(strike in all_available for strike in strikes)

        except Exception as e:
            logger.error(f"Error validating strikes for {symbol}: {e}")
            return False
