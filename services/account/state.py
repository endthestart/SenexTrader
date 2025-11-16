from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from services.core.cache import CacheManager, CacheTTL
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async

logger = get_logger(__name__)


class AccountStateService:
    """Simple account state service with fallback strategy for Phase 3"""

    def __init__(self):
        # Configurable TTL and thresholds
        self.cache_ttl = CacheTTL.ACCOUNT_STATE
        self.snapshot_window = getattr(settings, "ACCOUNT_SNAPSHOT_WINDOW", 300)  # 5 minutes
        self.fresh_threshold = getattr(
            settings, "ACCOUNT_SNAPSHOT_FRESH_THRESHOLD", 120
        )  # 2 minutes

    def get(self, user, account_number=None):
        """Synchronous wrapper for the async get method."""
        return run_async(self.a_get(user, account_number))

    async def a_get(self, user, account_number=None):
        """
        Get account state with fallback strategy
        Returns: {buying_power, balance, pnl, asof, source, stale, error?}
        """
        # Use primary account if none specified
        if not account_number:
            from accounts.models import TradingAccount

            trading_account = await TradingAccount.objects.filter(
                user=user, is_primary=True
            ).afirst()
            if not trading_account:
                return self._unavailable_response("No primary trading account found")
            account_number = trading_account.account_number

        # 1. Try stream cache first
        cache_key = CacheManager.account_state(user.id, account_number)
        cached_state = cache.get(cache_key)
        if cached_state:
            logger.debug(f"Found cached account state for user {user.id}")
            return self._normalize_state(cached_state)

        # 2. Try recent DB snapshot
        from accounts.models import AccountSnapshot

        recent_cutoff = timezone.now() - timedelta(seconds=self.snapshot_window)
        snapshot = (
            await AccountSnapshot.objects.filter(
                user=user,
                account_number=account_number,
                created_at__gte=recent_cutoff,
            )
            .order_by("-created_at")
            .afirst()
        )
        if snapshot:
            age_seconds = (timezone.now() - snapshot.created_at).total_seconds()
            snapshot_state = {
                "buying_power": float(snapshot.buying_power),
                "balance": float(snapshot.balance),
                "pnl": 0.0,  # Not tracked in snapshot for simplicity
                "asof": snapshot.created_at.isoformat(),
                "source": "snapshot",
                "stale": age_seconds > self.fresh_threshold,
                "available": True,
            }
            return self._normalize_state(snapshot_state)

        # 3. Live SDK fetch as fallback
        from tastytrade import Account as TTAccount

        from services.core.data_access import get_oauth_session_for_account

        session = await get_oauth_session_for_account(user, account_number)
        if not session:
            logger.error(f"Failed to get OAuth session for account {account_number}")
            return self._unavailable_response("OAuth session unavailable")

        logger.info(f"Fetching live account state for {account_number}")
        try:
            account = await TTAccount.a_get(session, account_number)
            if isinstance(account, list):
                account = account[0] if account else None

            if not account:
                logger.error(f"No account found for {account_number}")
                return self._unavailable_response("Account not found")

            balances = await account.a_get_balances(session)
            if not balances:
                logger.error(f"No balances returned for account {account_number}")
                return self._unavailable_response("Balances not found")

            derivative_bp = getattr(balances, "derivative_buying_power", None)
            if derivative_bp is None:
                derivative_bp = getattr(balances, "buying_power", 0)

            buying_power = Decimal(str(derivative_bp))
            net_liquidating_value = Decimal(str(getattr(balances, "net_liquidating_value", 0)))

            snapshot = await AccountSnapshot.objects.acreate(
                user=user,
                account_number=account_number,
                buying_power=buying_power,
                balance=net_liquidating_value,
                source="sdk",
            )

            sdk_data = {
                "buying_power": float(buying_power),
                "balance": float(net_liquidating_value),
                "pnl": 0.0,
                "asof": snapshot.created_at.isoformat(),
                "source": "sdk",
                "stale": False,
                "available": True,
            }
            cache.set(cache_key, sdk_data, self.cache_ttl)
            return self._normalize_state(sdk_data)

        except Exception as e:
            logger.error(f"Live SDK fetch failed for user {user.id}: {e}", exc_info=True)
            return self._unavailable_response("Live SDK fetch failed")

    def _normalize_state(self, state):
        """Ensure consistent response shape regardless of source"""
        normalized = {
            "buying_power": state.get("buying_power"),
            "balance": state.get("balance"),
            "pnl": state.get("pnl"),
            "asof": state.get("asof", timezone.now().isoformat()),
            "source": state.get("source", "unknown"),
            "available": state.get("available", False),
        }

        asof_str = normalized.get("asof")
        stale_flag = state.get("stale")
        if asof_str:
            parsed = parse_datetime(asof_str)
            if parsed:
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                age_seconds = (timezone.now() - parsed).total_seconds()
                stale_flag = age_seconds > self.fresh_threshold

        normalized["stale"] = bool(stale_flag) if stale_flag is not None else True

        # Add error field if present
        if "error" in state:
            normalized["error"] = state["error"]

        return normalized

    def _unavailable_response(self, error_message):
        """Consistent error response structure - NEVER GUESS VALUES"""
        return {
            "buying_power": None,  # Never guess - None means unavailable
            "balance": None,  # Never guess - None means unavailable
            "pnl": None,  # Never guess - None means unavailable
            "asof": timezone.now().isoformat(),
            "source": "unavailable",
            "stale": True,
            "error": error_message,
            "available": False,  # Clear flag that data is not available
        }
