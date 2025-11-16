from dataclasses import dataclass

from django.conf import settings

import httpx

from services.core.constants import API_TIMEOUT_SHORT
from services.core.exceptions import ConfigurationError
from services.core.oauth import build_redirect_uri


@dataclass
class TastyTradeOAuthConfig:
    client_id: str
    client_secret: str | None
    authorization_url: str
    token_url: str
    scopes: str


def get_config() -> TastyTradeOAuthConfig:
    cfg = getattr(settings, "TASTYTRADE_OAUTH_CONFIG", {})

    # CRITICAL: Validate URLs to prevent wrong URLs from being used
    auth_url = cfg.get("AUTHORIZATION_URL", "")
    token_url = cfg.get("TOKEN_URL", "")

    # Check for wrong URL patterns that should NEVER be used
    wrong_patterns = [
        "signin.tastytrade.com",
        "signin.tastyworks.com",
        "/oauth2/authorization",
        "/oauth2/token",
    ]

    for pattern in wrong_patterns:
        if pattern in auth_url or pattern in token_url:
            raise ConfigurationError(
                f"CRITICAL: Invalid TastyTrade OAuth URL detected containing "
                f"'{pattern}'! Use correct URLs: 'https://my.tastytrade.com/auth.html' "
                f"and 'https://api.tastyworks.com/oauth/token'. "
                f"Current auth_url='{auth_url}', token_url='{token_url}'"
            )

    return TastyTradeOAuthConfig(
        client_id=cfg.get("CLIENT_ID", ""),
        client_secret=cfg.get("CLIENT_SECRET"),
        authorization_url=auth_url,
        token_url=token_url,
        scopes=cfg.get("SCOPES", "read trade openid"),
    )


class TastyTradeOAuthClient:
    def __init__(self) -> None:
        self.config = get_config()

    def build_authorization_url(self, request) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "redirect_uri": build_redirect_uri(request, "accounts:tastytrade_oauth_callback"),
            "scope": self.config.scopes,
            # 'state' provided by the caller; url will be composed by view
        }
        return f"{self.config.authorization_url}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange authorization code for tokens."""
        if not self.config.token_url or not self.config.client_id:
            return {"success": False, "error": "OAuth configuration incomplete"}

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.config.client_id,
            "code": code,
        }
        if redirect_uri:
            payload["redirect_uri"] = redirect_uri
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.config.token_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=API_TIMEOUT_SHORT,
                )
                response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPStatusError as e:
            error_msg = str(e)
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error_description") or error_data.get("error") or str(e)
            except Exception:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            return {"success": False, "error": error_msg}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Network error: {e!s}"}

    async def refresh_token(self, refresh_token: str) -> dict:
        """Refresh an access token using a refresh token."""
        if not self.config.token_url or not self.config.client_id:
            return {"success": False, "error": "OAuth configuration incomplete"}

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "refresh_token": refresh_token,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.config.token_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=API_TIMEOUT_SHORT,
                )
                response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPStatusError as e:
            error_msg = str(e)
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error_description") or error_data.get("error") or str(e)
            except Exception:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            return {"success": False, "error": error_msg}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Network error: {e!s}"}

    async def fetch_accounts(self, refresh_token: str) -> dict:
        """
        Fetch user accounts using TastyTrade SDK.
        """
        if not refresh_token:
            return {"success": False, "error": "Refresh token is required"}

        try:
            from .session import TastyTradeSessionService

            session_service = TastyTradeSessionService()
            return await session_service.fetch_accounts(refresh_token)

        except ImportError as e:
            return {
                "success": False,
                "error": f"Session service not available: {e!s}",
            }
        except Exception as e:
            return {"success": False, "error": f"SDK account fetch failed: {e!s}"}

    # Optional helper to normalize token payloads from provider into a consistent shape
    @staticmethod
    def normalize_token_payload(payload: dict) -> dict:
        # Expected: access_token, refresh_token, token_type, expires_in, scope
        return {
            "access_token": payload.get("access_token"),
            "refresh_token": payload.get("refresh_token"),
            "token_type": payload.get("token_type", "Bearer"),
            "expires_in": payload.get("expires_in"),
            "scope": payload.get("scope", ""),
        }
