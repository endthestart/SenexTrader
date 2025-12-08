"""
OAuth Security Tests for Phase 2

Tests comprehensive security aspects of the OAuth implementation including:
- State token entropy and validation
- Token encryption verification
- Replay attack prevention
- Concurrent session isolation
- Error message hygiene
"""

import base64
from unittest.mock import AsyncMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import AsyncClient, TestCase
from django.urls import reverse

import pytest

from accounts.models import TradingAccount

User = get_user_model()


@pytest.mark.django_db
class OAuthSecurityTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            email="user1@example.com", username="user1", password="Pass12345!"
        )
        self.user2 = User.objects.create_user(
            email="user2@example.com", username="user2", password="Pass12345!"
        )
        self.async_client = AsyncClient()
        self.initiate_url = reverse("accounts:tastytrade_oauth_initiate")
        self.callback_url = reverse("accounts:tastytrade_oauth_callback")

    def test_state_entropy_validation(self):
        """Verify state tokens have sufficient cryptographic entropy."""
        states = set()

        # Generate multiple state tokens to test entropy
        for _i in range(100):
            self.client.login(username=self.user1.email, password="Pass12345!")
            self.client.get(self.initiate_url).wsgi_request

            # Check that state was set in session
            assert "oauth.state" in self.client.session
            state = self.client.session.get("oauth.state")

            # Verify minimum length (base64 of 32 bytes ≈ 43 chars)
            assert len(state) >= 40, f"State token too short: {len(state)} chars"

            # Verify state is unique
            assert state not in states, f"Duplicate state token generated: {state}"
            states.add(state)

            # Verify state is valid base64 (indicates proper randomness)
            try:
                base64.urlsafe_b64decode(state + "==")  # Add padding if needed
            except Exception:
                self.fail(f"State token is not valid base64: {state}")

            # Clear session for next iteration
            self.client.logout()

    def test_token_encryption_verification(self):
        """Verify tokens are actually encrypted in database storage."""
        self.client.login(username=self.user1.email, password="Pass12345!")

        # Start OAuth flow to set state
        self.client.get(self.initiate_url)
        state = self.client.session.get("oauth.state")

        # Mock successful OAuth callback
        with (
            patch(
                "accounts.views.GlobalStreamManager.remove_user_manager",
                new_callable=AsyncMock,
            ),
            patch(
                "accounts.views.TastyTradeSessionService.get_session_for_user",
                new_callable=AsyncMock,
            ) as mock_session,
            patch(
                "accounts.views.TastyTradeOAuthClient.exchange_code", new_callable=AsyncMock
            ) as mock_exchange,
            patch(
                "accounts.views.TastyTradeOAuthClient.fetch_accounts", new_callable=AsyncMock
            ) as mock_accounts,
        ):
            mock_session.return_value = {"success": True}

            test_access_token = "test_access_token_12345"
            test_refresh_token = "test_refresh_token_67890"

            mock_exchange.return_value = {
                "success": True,
                "data": {
                    "access_token": test_access_token,
                    "refresh_token": test_refresh_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "read trade",
                },
            }
            mock_accounts.return_value = {
                "success": True,
                "data": [{"account_number": "TEST123"}],
            }

            # Execute callback
            response = self.client.get(self.callback_url, {"state": state, "code": "test_code"})
            assert response.status_code == 302

            # Verify account was created and tokens stored
            acct = TradingAccount.objects.get(user=self.user1, connection_type="TASTYTRADE")

            # EncryptedTextField should transparently handle encryption/decryption
            # When we retrieve the value, it should be decrypted back to original
            assert acct.access_token == test_access_token
            assert acct.refresh_token == test_refresh_token

            # Verify that the raw database value is NOT the plaintext token
            # This requires querying the database directly to see encrypted values
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT access_token, refresh_token FROM "
                    "accounts_tradingaccount WHERE id = %s",
                    [acct.id],
                )
                row = cursor.fetchone()
                raw_access_db, raw_refresh_db = row

                # The raw database values should NOT match the plaintext tokens
                assert (
                    raw_access_db != test_access_token
                ), "Access token is stored as plaintext in database!"
                assert (
                    raw_refresh_db != test_refresh_token
                ), "Refresh token is stored as plaintext in database!"

                # The raw values should look like encrypted data (base64-like)
                assert len(raw_access_db) > len(
                    test_access_token
                ), "Encrypted token should be longer than plaintext"

    def test_state_replay_prevention(self):
        """Ensure used state tokens cannot be reused (replay attack prevention)."""
        self.client.force_login(self.user1)
        self.client.get(self.initiate_url)
        state = self.client.session.get("oauth.state")

        # Mock successful OAuth exchange
        with (
            patch(
                "accounts.views.GlobalStreamManager.remove_user_manager",
                new_callable=AsyncMock,
            ),
            patch(
                "accounts.views.TastyTradeSessionService.get_session_for_user",
                new_callable=AsyncMock,
            ) as mock_session,
            patch(
                "accounts.views.TastyTradeOAuthClient.exchange_code", new_callable=AsyncMock
            ) as mock_exchange,
            patch(
                "accounts.views.TastyTradeOAuthClient.fetch_accounts", new_callable=AsyncMock
            ) as mock_accounts,
        ):
            mock_session.return_value = {"success": True}

            mock_exchange.return_value = {
                "success": True,
                "data": {
                    "access_token": "token1",
                    "refresh_token": "refresh1",
                    "expires_in": 3600,
                },
            }
            mock_accounts.return_value = {
                "success": True,
                "data": [{"account_number": "TEST123"}],
            }

            # First callback should succeed
            response1 = self.client.get(self.callback_url, {"state": state, "code": "code1"})
            assert response1.status_code == 302

            # Second callback with same state should fail (replay attack)
            response2 = self.client.get(self.callback_url, {"state": state, "code": "code2"})
            assert response2.status_code == 200  # Error page, not redirect
            assert b"Invalid or expired OAuth state" in response2.content

    def test_concurrent_oauth_isolation(self):
        """Verify multiple users don't interfere with each other's OAuth flows."""
        # Start OAuth flow for user1
        self.client.force_login(self.user1)
        self.client.get(self.initiate_url)
        state1 = self.client.session.get("oauth.state")

        # Switch to user2 and start their OAuth flow
        client2 = self.client_class()
        client2.force_login(self.user2)
        client2.get(self.initiate_url)
        state2 = client2.session.get("oauth.state")

        # States should be different
        assert state1 != state2, "OAuth states should be unique per user session"

        # Mock OAuth responses
        with (
            patch(
                "accounts.views.GlobalStreamManager.remove_user_manager",
                new_callable=AsyncMock,
            ),
            patch(
                "accounts.views.TastyTradeSessionService.get_session_for_user",
                new_callable=AsyncMock,
            ) as mock_session,
            patch(
                "accounts.views.TastyTradeOAuthClient.exchange_code", new_callable=AsyncMock
            ) as mock_exchange,
            patch(
                "accounts.views.TastyTradeOAuthClient.fetch_accounts", new_callable=AsyncMock
            ) as mock_accounts,
        ):
            mock_session.return_value = {"success": True}

            mock_exchange.return_value = {
                "success": True,
                "data": {
                    "access_token": "token2",
                    "refresh_token": "refresh2",
                    "expires_in": 3600,
                },
            }
            mock_accounts.return_value = {
                "success": True,
                "data": [{"account_number": "USER2_ACCT"}],
            }

            # User2's callback should work with their state
            response = client2.get(self.callback_url, {"state": state2, "code": "code2"})
            assert response.status_code == 302

            # Verify user2's account was created correctly
            acct2 = TradingAccount.objects.get(user=self.user2, connection_type="TASTYTRADE")
            assert acct2.account_number == "USER2_ACCT"

            # User1 trying to use user2's state should fail
            response = self.client.get(self.callback_url, {"state": state2, "code": "code1"})
            assert response.status_code == 200  # Error page
            assert b"Invalid or expired OAuth state" in response.content

    def test_state_expiration(self):
        """Verify state tokens expire after 5 minutes."""
        self.client.force_login(self.user1)
        self.client.get(self.initiate_url)
        state = self.client.session.get("oauth.state")

        # Simulate time passage beyond 5 minutes via patching services.core.oauth.time.time
        import time

        future = int(time.time()) + 400
        with patch("services.core.oauth.time.time", return_value=future):
            response = self.client.get(self.callback_url, {"state": state, "code": "test_code"})
        assert response.status_code == 200  # Error page
        assert b"Invalid or expired OAuth state" in response.content

    def test_error_message_hygiene(self):
        """Verify error messages don't leak sensitive information."""
        self.client.force_login(self.user1)

        # Test various error conditions
        test_cases = [
            # Missing state
            {
                "params": {"code": "test_code"},
                "expected_error": b"Invalid or expired OAuth state",
            },
            # Invalid state
            {
                "params": {"state": "invalid_state", "code": "test_code"},
                "expected_error": b"Invalid or expired OAuth state",
            },
            # Missing code
            {
                "params": {"state": "valid_state"},
                "expected_error": b"No authorization code received",
            },
            # Provider error
            {
                "params": {
                    "state": "valid_state",
                    "error": "access_denied",
                    "error_description": "User denied access",
                },
                "expected_error": b"User denied access",
            },
        ]

        for i, test_case in enumerate(test_cases):
            with self.subTest(test_case=i):
                # Generate fresh state for each test
                test_client = self.client_class()
                test_client.force_login(self.user1)
                test_client.get(self.initiate_url)
                state = test_client.session.get("oauth.state")

                # Replace 'valid_state' with actual state
                params = test_case["params"].copy()
                if params.get("state") == "valid_state":
                    params["state"] = state

                response = test_client.get(self.callback_url, params)
                assert response.status_code == 200
                assert test_case["expected_error"] in response.content

                # Verify no sensitive info leaked (check for common secrets)
                # Allow CSRF field name to appear in templates (not sensitive)
                content = response.content.decode()
                content = content.replace("csrfmiddlewaretoken", "")
                sensitive_patterns = ["secret", "key", "token", "password", "client_id"]
                for pattern in sensitive_patterns:
                    assert pattern not in content, (
                        f"Sensitive pattern '{pattern}' found in " f"error response body"
                    )

    async def test_oauth_configuration_validation(self):
        """Test OAuth client behavior with missing/invalid configuration."""
        from services.brokers.tastytrade.client import TastyTradeOAuthClient

        # Test with empty configuration
        with patch("services.brokers.tastytrade.client.get_config") as mock_config:
            mock_config.return_value.token_url = ""
            mock_config.return_value.client_id = ""

            client = TastyTradeOAuthClient()
            result = await client.exchange_code("test_code")

            assert not result["success"]
            assert "OAuth configuration incomplete" in result["error"]

    def test_encryption_service_fail_fast(self):
        """Test that encryption service fails fast in production mode."""
        from services.core.encryption import encrypt
        from services.core.exceptions import EncryptionConfigError

        # Test production mode behavior (should fail fast)
        with (
            patch.object(settings, "DEBUG", False),
            patch.object(settings, "FIELD_ENCRYPTION_KEY", None),
        ):
            # Directly call encrypt with the patched settings
            with pytest.raises(EncryptionConfigError) as cm:
                encrypt("test_value")

            assert "FIELD_ENCRYPTION_KEY is required for production" in str(cm.value)
