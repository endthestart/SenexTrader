from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import api_views, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/update/", views.profile_update, name="profile_update"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    # Settings sub-pages
    path("settings/account/", views.AccountSettingsView.as_view(), name="settings_account"),
    path("settings/risk/", views.RiskSettingsView.as_view(), name="settings_risk"),
    path(
        "settings/brokerage/",
        views.BrokerageSettingsView.as_view(),
        name="settings_brokerage",
    ),
    path(
        "settings/strategy/",
        views.StrategySettingsView.as_view(),
        name="settings_strategy",
    ),
    # API endpoints
    path(
        "api/automated-trading-toggle/",
        api_views.automated_trading_toggle,
        name="api_automated_trading_toggle",
    ),
    path(
        "api/email-preference/",
        api_views.email_preference,
        name="api_email_preference",
    ),
    path(
        "api/daily-suggestion-toggle/",
        api_views.daily_suggestion_toggle,
        name="api_daily_suggestion_toggle",
    ),
    path(
        "api/privacy-mode-toggle/",
        api_views.privacy_mode_toggle,
        name="api_privacy_mode_toggle",
    ),
    path(
        "api/profit-target-settings/",
        api_views.profit_target_settings,
        name="api_profit_target_settings",
    ),
    # OAuth (Phase 2)
    path(
        "oauth/tastytrade/initiate/",
        views.tastytrade_oauth_initiate,
        name="tastytrade_oauth_initiate",
    ),
    path(
        "oauth/tastytrade/callback/",
        views.tastytrade_oauth_callback,
        name="tastytrade_oauth_callback",
    ),
    path(
        "oauth/tastytrade/select-primary/",
        views.tastytrade_select_primary,
        name="tastytrade_select_primary",
    ),
    path(
        "oauth/tastytrade/disconnect/",
        views.tastytrade_disconnect,
        name="tastytrade_disconnect",
    ),
    # Password change (built-in view, inline form in settings)
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(success_url="/accounts/settings/account/"),
        name="password_change",
    ),
    # Password reset (built-in views, dark theme templates)
    path(
        "password/reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password/reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password/reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
