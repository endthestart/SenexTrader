"""
Unit tests to ensure TastyTrade OAuth URLs are correctly configured.

CRITICAL: These tests prevent wrong OAuth URLs from being deployed.
"""

from django.conf import settings
from django.test import TestCase

import pytest

from services.brokers.tastytrade.client import TastyTradeOAuthClient, get_config
from services.core.exceptions import ConfigurationError


class TestOAuthURLs(TestCase):
    """Test OAuth URLs are correctly configured and validation works"""

    def test_tastytrade_oauth_urls_are_correct(self):
        """Ensure TastyTrade OAuth URLs are never wrong"""
        oauth_config = settings.TASTYTRADE_OAUTH_CONFIG
        auth_url = oauth_config.get("AUTHORIZATION_URL", "")
        token_url = oauth_config.get("TOKEN_URL", "")

        # These patterns should NEVER appear in our URLs
        forbidden_patterns = [
            "signin.tastytrade.com",
            "signin.tastyworks.com",
            "/oauth2/authorization",
            "/oauth2/token",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in auth_url, (
                f"CRITICAL: Wrong OAuth URL pattern '{pattern}' found in "
                f"AUTHORIZATION_URL: {auth_url}"
            )
            assert pattern not in token_url, (
                f"CRITICAL: Wrong OAuth URL pattern '{pattern}' found in " f"TOKEN_URL: {token_url}"
            )

        # Verify correct patterns exist
        assert (
            "auth.html" in auth_url
        ), f"Authorization URL should end with auth.html, got: {auth_url}"
        assert "api." in token_url, f"Token URL should contain api. subdomain, got: {token_url}"
        assert (
            "/oauth/token" in token_url
        ), f"Token URL should end with /oauth/token, got: {token_url}"

    def test_oauth_config_validation_raises_error_for_wrong_urls(self):
        """Test that get_config() raises ConfigurationError for wrong URLs"""
        # Temporarily patch settings to test validation
        original_config = settings.TASTYTRADE_OAUTH_CONFIG.copy()

        try:
            # Test wrong authorization URL
            settings.TASTYTRADE_OAUTH_CONFIG["AUTHORIZATION_URL"] = (
                "https://signin.tastytrade.com/oauth2/authorization"
            )
            with pytest.raises(ConfigurationError) as cm:
                get_config()
            assert "signin.tastytrade.com" in str(cm.value)
            assert "CRITICAL" in str(cm.value)

            # Restore config and test wrong token URL
            settings.TASTYTRADE_OAUTH_CONFIG.update(original_config)
            settings.TASTYTRADE_OAUTH_CONFIG["TOKEN_URL"] = (
                "https://signin.tastytrade.com/oauth2/token"
            )
            with pytest.raises(ConfigurationError) as cm:
                get_config()
            assert "signin.tastytrade.com" in str(cm.value)
            assert "CRITICAL" in str(cm.value)

        finally:
            # Always restore original config
            settings.TASTYTRADE_OAUTH_CONFIG.update(original_config)

    def test_oauth_client_initialization_with_correct_urls(self):
        """Test that OAuth client initializes correctly with proper URLs"""
        # This should NOT raise any errors
        try:
            client = TastyTradeOAuthClient()
            assert client.config is not None
            assert client.config.authorization_url is not None
            assert client.config.token_url is not None
        except ValueError as e:
            self.fail(f"OAuth client initialization failed with correct URLs: {e}")

    def test_required_oauth_configuration_fields(self):
        """Test that all required OAuth configuration fields are present"""
        oauth_config = settings.TASTYTRADE_OAUTH_CONFIG

        required_fields = [
            "CLIENT_ID",
            "CLIENT_SECRET",
            "AUTHORIZATION_URL",
            "TOKEN_URL",
            "SCOPES",
        ]
        for field in required_fields:
            assert field in oauth_config, f"Required OAuth configuration field '{field}' is missing"

    def test_oauth_urls_are_https(self):
        """Ensure OAuth URLs use HTTPS for security"""
        oauth_config = settings.TASTYTRADE_OAUTH_CONFIG
        auth_url = oauth_config.get("AUTHORIZATION_URL", "")
        token_url = oauth_config.get("TOKEN_URL", "")

        assert auth_url.startswith("https://"), f"Authorization URL must use HTTPS: {auth_url}"
        assert token_url.startswith("https://"), f"Token URL must use HTTPS: {token_url}"

    def test_oauth_urls_match_expected_patterns(self):
        """Test that OAuth URLs match expected TastyTrade patterns"""
        oauth_config = settings.TASTYTRADE_OAUTH_CONFIG
        auth_url = oauth_config.get("AUTHORIZATION_URL", "")
        token_url = oauth_config.get("TOKEN_URL", "")

        # Check for expected production URLs (most common case)
        expected_auth_patterns = [
            "my.tastytrade.com/auth.html",
            "cert-my.staging-tasty.works/auth.html",  # Sandbox
        ]

        expected_token_patterns = [
            "api.tastyworks.com/oauth/token",
            "api.cert.tastyworks.com/oauth/token",  # Sandbox
        ]

        auth_matches_pattern = any(pattern in auth_url for pattern in expected_auth_patterns)
        token_matches_pattern = any(pattern in token_url for pattern in expected_token_patterns)

        assert (
            auth_matches_pattern
        ), f"Authorization URL doesn't match expected patterns. Got: {auth_url}"
        assert token_matches_pattern, f"Token URL doesn't match expected patterns. Got: {token_url}"

    def test_validation_error_contains_helpful_message(self):
        """Test that validation errors provide helpful guidance"""
        # Temporarily patch settings to test error message
        original_config = settings.TASTYTRADE_OAUTH_CONFIG.copy()

        try:
            settings.TASTYTRADE_OAUTH_CONFIG["AUTHORIZATION_URL"] = (
                "https://signin.tastytrade.com/bad"
            )
            with pytest.raises(ConfigurationError) as cm:
                get_config()

            error_message = str(cm.value)
            # Check that error message is helpful
            assert "Use correct URLs" in error_message
            assert "my.tastytrade.com/auth.html" in error_message
            assert "api.tastyworks.com/oauth/token" in error_message

        finally:
            # Always restore original config
            settings.TASTYTRADE_OAUTH_CONFIG.update(original_config)
