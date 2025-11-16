"""
API URL configuration for accounts app.
Phase 6: Account state API endpoints.
"""

from django.urls import path

from . import api_views

app_name = "accounts_api"

urlpatterns = [
    # Account state endpoints
    path("state/", api_views.account_state, name="account_state"),
    path("positions/", api_views.positions, name="positions"),
]
