"""Context processors for Senex Trader."""

from django.conf import settings


def dry_run_mode(request):
    """Inject DRY_RUN_MODE into templates for UI badge display."""
    return {"DRY_RUN_MODE": settings.TASTYTRADE_DRY_RUN}


def privacy_mode(request):
    """Inject privacy_mode and primary_account into templates."""
    if not request.user.is_authenticated:
        return {"privacy_mode": False, "primary_account": None}

    primary_account = request.user.trading_accounts.filter(is_primary=True).first()
    return {
        "privacy_mode": primary_account.privacy_mode if primary_account else False,
        "primary_account": primary_account,
    }


def app_environment(request):
    """Expose environment flags (e.g., DEBUG) to templates."""
    return {"APP_DEBUG": settings.DEBUG}
