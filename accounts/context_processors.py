"""
Context processors for accounts app.

Provides template context variables for brokerage account status.
"""


def broker_account_status(request):
    """
    Add broker account status to template context.

    Provides 'has_broker_account' boolean that indicates if the authenticated
    user has a configured TastyTrade account. Used to conditionally enable
    streaming and brokerage-dependent features in templates.

    Returns:
        dict: Context with 'has_broker_account' boolean
    """
    if not request.user.is_authenticated:
        return {"has_broker_account": False}

    from accounts.models import TradingAccount

    try:
        account = TradingAccount.objects.filter(
            user=request.user, connection_type="TASTYTRADE", is_primary=True
        ).first()

        has_account = account is not None and account.is_configured
        return {"has_broker_account": has_account}
    except Exception:
        # If there's any error checking account status, default to False
        return {"has_broker_account": False}
