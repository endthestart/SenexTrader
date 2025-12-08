from __future__ import annotations

import contextlib
import time
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as BaseLoginView
from django.contrib.auth.views import LogoutView as BaseLogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.generic import CreateView, TemplateView

from asgiref.sync import sync_to_async

from services.account.state import AccountStateService
from services.brokers.tastytrade.client import TastyTradeOAuthClient
from services.brokers.tastytrade.session import TastyTradeSessionService
from services.core.logging import get_logger
from services.core.oauth import build_redirect_uri, clear_state, generate_state, validate_state
from services.core.utils.async_utils import async_get_user, async_get_user_id
from services.risk.manager import EnhancedRiskManager
from streaming.services.stream_manager import GlobalStreamManager

from .forms import EmailAuthenticationForm, EmailUserCreationForm
from .models import TradingAccount

User = get_user_model()
logger = get_logger(__name__)

async_render = sync_to_async(render, thread_sensitive=True)


class LoginView(BaseLoginView):
    template_name: str = "accounts/login.html"
    redirect_authenticated_user: bool = True
    authentication_form = EmailAuthenticationForm

    def get_success_url(self) -> str:
        return str(reverse_lazy("trading:dashboard"))


class LogoutView(BaseLogoutView):
    next_page = reverse_lazy("home")

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from services.core.utils.async_utils import run_async
        from services.core.utils.logging_utils import log_error_with_context
        from streaming.services.stream_manager import GlobalStreamManager

        user_id: int = request.user.id

        async def cleanup() -> None:
            # Note: clear_user_session removed - sessions are now created per-task, not cached
            await GlobalStreamManager.remove_user_manager(user_id)

        try:
            run_async(cleanup())
        except Exception as e:
            log_error_with_context("cleanup_on_logout", e, context={"user_id": user_id})

        messages.success(request, "You have been logged out successfully.")
        return super().post(request, *args, **kwargs)


class RegisterView(CreateView):  # type: ignore[type-arg]
    model = User
    template_name: str = "accounts/register.html"
    form_class = EmailUserCreationForm
    success_url = reverse_lazy("trading:dashboard")

    def form_valid(self, form: Any) -> HttpResponse:
        response = super().form_valid(form)
        with contextlib.suppress(Exception):
            login(
                self.request,
                self.object,
                backend="django.contrib.auth.backends.ModelBackend",
            )
        messages.success(self.request, "Account created successfully!")
        return response


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name: str = "accounts/profile.html"


class SettingsView(LoginRequiredMixin, TemplateView):
    """
    Settings overview - redirects to brokerage section.

    The old monolithic settings page has been replaced with a sidebar-based
    navigation structure for better organization. This view redirects to the
    brokerage section as the default entry point.
    """

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Redirect to the brokerage settings section (sidebar structure)."""
        return redirect("accounts:settings_brokerage")


@login_required
def profile_update(request: HttpRequest) -> HttpResponse:
    """Handle profile update form submission."""
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()

        name_parts = full_name.split(None, 1)
        request.user.first_name = name_parts[0] if len(name_parts) > 0 else ""
        request.user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        request.user.save()

        messages.success(request, "Profile updated successfully!")

    return redirect("accounts:settings_account")


def health_check(request: HttpRequest) -> HttpResponse:
    """
    Comprehensive health check endpoint for container health checks.
    Tests database and Redis connectivity.

    Used by Docker/Podman HEALTHCHECK and load balancers.
    """
    import os

    from django.db import connection
    from django.http import JsonResponse

    import redis

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()

        return JsonResponse({"status": "healthy"}, status=200)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JsonResponse({"status": "unhealthy", "error": str(e)}, status=500)


def health_check_simple(request: HttpRequest) -> HttpResponse:
    """
    Ultra-simple health check (no dependencies).
    Use for liveness probes.
    """
    from django.http import JsonResponse

    return JsonResponse({"status": "ok"}, status=200)


@login_required
@require_http_methods(["GET"])
def tastytrade_oauth_initiate(request):
    client = TastyTradeOAuthClient()
    state = generate_state(request)
    base_url = client.build_authorization_url(request)
    connector = "&" if "?" in base_url else "?"
    return redirect(f"{base_url}{connector}state={state}")


@login_required
@require_http_methods(["GET"])
async def tastytrade_oauth_callback(request):
    if not validate_state(request, request.GET.get("state")):
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": "Invalid or expired OAuth state. Please try again.",
            },
        )
    ts = request.session.get("oauth.state_ts")
    try:
        if ts is None or (int(time.time()) - int(ts)) >= 300:
            clear_state(request)
            return await async_render(
                request,
                "accounts/oauth_error.html",
                {
                    "provider": "TastyTrade",
                    "error": "Invalid or expired OAuth state. Please try again.",
                },
            )
    except Exception:
        clear_state(request)
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": "Invalid or expired OAuth state. Please try again.",
            },
        )
    clear_state(request)
    if request.GET.get("error"):
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": request.GET.get("error_description", "Authorization failed"),
            },
        )

    code = request.GET.get("code")
    if not code:
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {"provider": "TastyTrade", "error": "No authorization code received."},
        )

    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    # Note: clear_user_session removed - sessions are now created per-task, not cached
    await GlobalStreamManager.remove_user_manager(user_id)

    existing = await TradingAccount.objects.filter(user=user, connection_type="TASTYTRADE").afirst()
    if existing and not existing.is_configured:
        existing.access_token = ""
        existing.refresh_token = ""
        existing.metadata = {}
        await existing.asave()

    client = TastyTradeOAuthClient()
    redirect_uri = build_redirect_uri(request, "accounts:tastytrade_oauth_callback")
    token_result = await client.exchange_code(code, redirect_uri=redirect_uri)
    if not token_result.get("success"):
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": token_result.get("error", "Failed to exchange tokens."),
            },
        )

    token_data = client.normalize_token_payload(token_result.get("data", {}))

    raw_refresh = token_data.get("refresh_token", "")
    if not raw_refresh:
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": "No refresh token received from OAuth provider.",
            },
        )

    # Fetch accounts BEFORE saving anything - we need account_number to be configured
    accounts_result = await client.fetch_accounts(raw_refresh)
    if not accounts_result.get("success"):
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": accounts_result.get("error", "Failed to fetch accounts."),
            },
        )

    accounts = accounts_result.get("data", [])
    if not accounts:
        return await async_render(
            request,
            "accounts/oauth_error.html",
            {
                "provider": "TastyTrade",
                "error": "No accounts found. Please ensure your TastyTrade account has at least one trading account.",
            },
        )

    acct = existing or TradingAccount(user=user, connection_type="TASTYTRADE")
    raw_access = token_data.get("access_token", "")
    acct.access_token = raw_access
    acct.refresh_token = raw_refresh
    expires_in = token_data.get("expires_in")
    if expires_in:
        acct.token_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
    acct.is_active = True
    acct.is_token_valid = True
    acct.last_authenticated = timezone.now()

    acct.account_number = accounts[0].get("account_number") or accounts[0].get("id") or ""
    primary_exists = await TradingAccount.objects.filter(user=user, is_primary=True).aexists()
    if not primary_exists:
        acct.is_primary = True

    acct.metadata = {"accounts": accounts}

    await acct.asave()

    # Try to create session (non-critical - will be created on first use if this fails)
    if raw_refresh:
        session_result = await TastyTradeSessionService.get_session_for_user(
            user_id, raw_refresh, is_test=acct.is_test
        )
        if session_result.get("success"):
            logger.info(
                f"Session created and cached for user {user_id} after OAuth reconnection"
            )
        else:
            logger.warning(
                f"Failed to create session after OAuth: {session_result.get('error')} "
                f"(session will be created on first use)"
            )

    stream_manager = await GlobalStreamManager.get_user_manager(user_id)
    if stream_manager:
        await stream_manager.notify_oauth_restored()

    return redirect("accounts:settings")


@login_required
@require_http_methods(["POST"])
def tastytrade_select_primary(request):
    account_number = request.POST.get("account_number", "").strip()
    acct = TradingAccount.objects.filter(user=request.user, connection_type="TASTYTRADE").first()
    if not acct or not account_number:
        return redirect("accounts:settings")
    acct.account_number = account_number
    acct.is_primary = True
    acct.save()
    return redirect("accounts:settings")


@login_required
@require_http_methods(["POST"])
async def tastytrade_disconnect(request):
    user_id = await async_get_user_id(request)

    # Note: clear_user_session removed - sessions are now created per-task, not cached
    await GlobalStreamManager.remove_user_manager(user_id)
    logger.info(f"Removed stream manager for user {user_id}")

    acct = await TradingAccount.objects.filter(
        user__id=user_id, connection_type="TASTYTRADE"
    ).afirst()
    if acct:
        acct.is_active = False
        acct.access_token = ""
        acct.refresh_token = ""
        acct.account_number = ""
        acct.metadata = {}
        await acct.asave()

    return redirect("accounts:settings")


class SettingsBaseView(LoginRequiredMixin, TemplateView):
    """Base class for all settings sub-pages."""

    section_name = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_section"] = self.section_name
        return context


class AccountSettingsView(SettingsBaseView):
    """Account settings: password, email, profile."""

    template_name = "settings/account.html"
    section_name = "account"


class RiskSettingsView(SettingsBaseView):
    """Risk management settings: allocation, risk tolerance, position limits."""

    template_name = "settings/risk.html"
    section_name = "risk"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # OptionsAllocation is created automatically via signals when user is created
        allocation = self.request.user.options_allocation
        context["allocation"] = allocation

        risk_manager = EnhancedRiskManager(self.request.user)
        context["app_managed_risk"] = float(risk_manager.get_app_managed_risk())

        account_state_service = AccountStateService()
        account_state = account_state_service.get(self.request.user)

        context["initial_balance"] = account_state.get("balance")
        context["initial_buying_power"] = account_state.get("buying_power")
        context["account_state_source"] = account_state.get("source", "unavailable")
        context["account_state_stale"] = account_state.get("stale", True)

        return context


class BrokerageSettingsView(SettingsBaseView):
    """Brokerage settings: OAuth, is_test flag, account selection."""

    template_name = "settings/brokerage.html"
    section_name = "brokerage"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["tastytrade_account"] = TradingAccount.objects.filter(
            user=self.request.user, connection_type="TASTYTRADE"
        ).first()

        return context


class StrategySettingsView(SettingsBaseView):
    """Strategy settings: automated trading, email preferences, daily suggestions."""

    template_name = "settings/strategy.html"
    section_name = "strategy"

    def get_context_data(self, **kwargs):
        from trading.models import StrategyConfiguration

        context = super().get_context_data(**kwargs)

        context["tastytrade_account"] = TradingAccount.objects.filter(
            user=self.request.user, connection_type="TASTYTRADE"
        ).first()

        # Get profit target settings for spread strategies
        credit_config = StrategyConfiguration.objects.filter(
            user=self.request.user, strategy_id="short_put_vertical"
        ).first()
        debit_config = StrategyConfiguration.objects.filter(
            user=self.request.user, strategy_id="long_call_vertical"
        ).first()

        context["credit_spread_profit_target_pct"] = (
            credit_config.parameters.get("profit_target_pct", 50)
            if credit_config and credit_config.parameters
            else 50
        )
        context["debit_spread_profit_target_pct"] = (
            debit_config.parameters.get("profit_target_pct", 50)
            if debit_config and debit_config.parameters
            else 50
        )

        return context
