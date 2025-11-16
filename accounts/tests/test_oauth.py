from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import AsyncClient, TestCase
from django.urls import reverse

import pytest

User = get_user_model()


@pytest.mark.django_db
class OAuthFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="oauth@example.com",
            username="oauth@example.com",
            password="Pass12345!",
        )
        self.async_client = AsyncClient()
        self.initiate_url = reverse("accounts:tastytrade_oauth_initiate")
        self.callback_url = reverse("accounts:tastytrade_oauth_callback")
        self.settings_url = reverse("accounts:settings")
        self.select_primary_url = reverse("accounts:tastytrade_select_primary")

    def test_initiate_sets_state_and_redirects(self):
        self.client.login(username=self.user.email, password="Pass12345!")
        resp = self.client.get(self.initiate_url)
        assert resp.status_code == 302
        # State should be in session
        assert "oauth.state" in self.client.session
        # Redirect should include state param
        assert "state=" in resp.url

    def test_callback_invalid_state_shows_error(self):
        self.client.force_login(self.user)
        # No state set in session
        resp = self.client.get(self.callback_url, {"state": "bad", "code": "abc"})
        assert resp.status_code == 200
        assert b"Invalid or expired OAuth state" in resp.content

    @patch("accounts.views.GlobalStreamManager.remove_user_manager", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeSessionService.clear_user_session", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeSessionService.get_session_for_user", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeOAuthClient.fetch_accounts", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeOAuthClient.exchange_code", new_callable=AsyncMock)
    def test_callback_success_single_account_persists(
        self, mock_exchange, mock_accounts, mock_session, mock_clear_session, mock_remove_manager
    ):
        self.client.force_login(self.user)
        self.client.get(self.initiate_url)
        state = self.client.session.get("oauth.state")

        mock_exchange.return_value = {
            "success": True,
            "data": {
                "access_token": "at",
                "refresh_token": "rt",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read",
            },
        }
        mock_accounts.return_value = {
            "success": True,
            "data": [{"account_number": "TT123"}],
        }
        mock_session.return_value = {"success": True}
        resp = self.client.get(self.callback_url, {"state": state, "code": "abc"})
        assert resp.status_code == 302
        assert resp.url == self.settings_url
        from accounts.models import TradingAccount

        acct = TradingAccount.objects.get(user=self.user, connection_type="TASTYTRADE")
        assert acct.account_number == "TT123"
        assert acct.is_active
        assert acct.access_token == "at"

    @patch("accounts.views.GlobalStreamManager.remove_user_manager", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeSessionService.clear_user_session", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeSessionService.get_session_for_user", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeOAuthClient.fetch_accounts", new_callable=AsyncMock)
    @patch("accounts.views.TastyTradeOAuthClient.exchange_code", new_callable=AsyncMock)
    def test_callback_success_multi_accounts_requires_selection(
        self, mock_exchange, mock_accounts, mock_session, mock_clear_session, mock_remove_manager
    ):
        self.client.force_login(self.user)
        self.client.get(self.initiate_url)
        state = self.client.session.get("oauth.state")

        mock_exchange.return_value = {
            "success": True,
            "data": {
                "access_token": "at",
                "refresh_token": "rt",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read",
            },
        }
        mock_accounts.return_value = {
            "success": True,
            "data": [{"account_number": "TT123"}, {"account_number": "TT999"}],
        }
        mock_session.return_value = {"success": True}
        resp = self.client.get(self.callback_url, {"state": state, "code": "abc"})
        assert resp.status_code == 302
        from accounts.models import TradingAccount

        acct = TradingAccount.objects.get(user=self.user, connection_type="TASTYTRADE")
        assert acct.account_number == ""
        assert "accounts" in acct.metadata

        # Now simulate primary selection
        resp2 = self.client.post(self.select_primary_url, {"account_number": "TT123"})
        assert resp2.status_code == 302
        acct.refresh_from_db()
        assert acct.account_number == "TT123"
