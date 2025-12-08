"""
HashiCorp Vault Integration for Secrets Management.

This module fetches secrets from Vault at application startup, keeping
encryption keys and credentials out of environment files on disk.

Usage:
    Secrets are loaded once at Django startup via settings/production.py.
    The app server only needs VAULT_ADDR and VAULT_TOKEN (or AppRole credentials).

Environment Variables Required:
    VAULT_ADDR: Vault server URL (e.g., https://vault.example.com)
    VAULT_TOKEN: Authentication token (for simple setup)
    
    OR for AppRole (more secure, recommended for production):
    VAULT_ROLE_ID: AppRole role ID
    VAULT_SECRET_ID: AppRole secret ID

Vault Path Structure:
    senex/<environment>/
        field_encryption_key
        secret_key
        db_user
        db_password
        tastytrade_client_id
        tastytrade_client_secret
"""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)


class VaultError(Exception):
    """Base exception for Vault operations."""

    pass


class VaultConnectionError(VaultError):
    """Failed to connect to Vault server."""

    pass


class VaultAuthenticationError(VaultError):
    """Failed to authenticate with Vault."""

    pass


class VaultSecretNotFoundError(VaultError):
    """Requested secret path not found."""

    pass


@dataclass
class VaultConfig:
    """Configuration for Vault connection."""

    addr: str
    token: str | None = None
    role_id: str | None = None
    secret_id: str | None = None
    mount_path: str = "senex"
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> "VaultConfig":
        """Create config from environment variables."""
        addr = os.environ.get("VAULT_ADDR")
        if not addr:
            raise VaultError("VAULT_ADDR environment variable is required")

        return cls(
            addr=addr.rstrip("/"),
            token=os.environ.get("VAULT_TOKEN"),
            role_id=os.environ.get("VAULT_ROLE_ID"),
            secret_id=os.environ.get("VAULT_SECRET_ID"),
            mount_path=os.environ.get("VAULT_MOUNT_PATH", "senex"),
        )


class VaultClient:
    """
    Simple Vault client for fetching secrets.

    Uses httpx for HTTP requests - no heavy Vault SDK dependency.
    """

    def __init__(self, config: VaultConfig):
        self.config = config
        self._token: str | None = config.token

    def _get_token(self) -> str:
        """Get authentication token, using AppRole if configured."""
        if self._token:
            return self._token

        if self.config.role_id and self.config.secret_id:
            self._token = self._authenticate_approle()
            return self._token

        raise VaultAuthenticationError(
            "No authentication method configured. "
            "Set VAULT_TOKEN or both VAULT_ROLE_ID and VAULT_SECRET_ID."
        )

    def _authenticate_approle(self) -> str:
        """Authenticate using AppRole and return token."""
        url = f"{self.config.addr}/v1/auth/approle/login"
        payload = {
            "role_id": self.config.role_id,
            "secret_id": self.config.secret_id,
        }

        try:
            response = httpx.post(url, json=payload, timeout=self.config.timeout)
            response.raise_for_status()
            data = response.json()
            return data["auth"]["client_token"]
        except httpx.HTTPStatusError as e:
            raise VaultAuthenticationError(f"AppRole authentication failed: {e}")
        except httpx.RequestError as e:
            raise VaultConnectionError(f"Failed to connect to Vault: {e}")

    def get_secrets(self, path: str) -> dict[str, str]:
        """
        Fetch all secrets from a KV v2 path.

        Args:
            path: Secret path (e.g., "production" for senex/production)

        Returns:
            Dictionary of secret key-value pairs
        """
        token = self._get_token()
        # KV v2 API path format: /v1/<mount>/data/<path>
        url = f"{self.config.addr}/v1/{self.config.mount_path}/data/{path}"
        headers = {"X-Vault-Token": token}

        try:
            response = httpx.get(url, headers=headers, timeout=self.config.timeout)

            if response.status_code == 404:
                raise VaultSecretNotFoundError(f"Secret path not found: {path}")

            response.raise_for_status()
            data = response.json()

            # KV v2 nests data under "data.data"
            return data.get("data", {}).get("data", {})

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                raise VaultAuthenticationError(f"Permission denied for path: {path}")
            raise VaultError(f"Failed to fetch secrets: {e}")
        except httpx.RequestError as e:
            raise VaultConnectionError(f"Failed to connect to Vault: {e}")

    def get_secret(self, path: str, key: str) -> str:
        """
        Fetch a single secret value.

        Args:
            path: Secret path (e.g., "production")
            key: Secret key name (e.g., "field_encryption_key")

        Returns:
            Secret value as string
        """
        secrets = self.get_secrets(path)
        if key not in secrets:
            raise VaultSecretNotFoundError(f"Secret key not found: {key} at path {path}")
        return secrets[key]


@lru_cache(maxsize=1)
def get_vault_secrets(environment: str) -> dict[str, str]:
    """
    Fetch all secrets for an environment from Vault.

    Results are cached for the lifetime of the process.

    Args:
        environment: Environment name (e.g., "production", "staging")

    Returns:
        Dictionary of all secrets for the environment
    """
    try:
        config = VaultConfig.from_env()
        client = VaultClient(config)
        secrets = client.get_secrets(environment)
        logger.info(f"Successfully loaded {len(secrets)} secrets from Vault for {environment}")
        return secrets
    except VaultError as e:
        logger.error(f"Failed to load secrets from Vault: {e}")
        raise


def get_secret(key: str, environment: str | None = None, default: str | None = None) -> str:
    """
    Get a single secret, with fallback to environment variable.

    This allows gradual migration - secrets can come from Vault or env vars.

    Args:
        key: Secret key name (e.g., "FIELD_ENCRYPTION_KEY")
        environment: Vault environment path (defaults to DJANGO_ENV or "production")
        default: Default value if not found anywhere

    Returns:
        Secret value
    """
    # Normalize key name (Vault uses lowercase, env vars use uppercase)
    vault_key = key.lower()
    env_key = key.upper()

    # Check if Vault is configured
    vault_addr = os.environ.get("VAULT_ADDR")

    if vault_addr:
        try:
            env = environment or os.environ.get("DJANGO_ENV", "production")
            secrets = get_vault_secrets(env)
            if vault_key in secrets:
                return secrets[vault_key]
        except VaultError:
            # Fall through to environment variable
            logger.warning(f"Vault unavailable, falling back to env var for {key}")

    # Fallback to environment variable
    value = os.environ.get(env_key)
    if value:
        return value

    if default is not None:
        return default

    raise VaultError(f"Secret {key} not found in Vault or environment variables")
