from django.conf import settings

from services.core.exceptions import EncryptionConfigError, InvalidEncryptionKeyError

try:
    from cryptography.fernet import Fernet  # type: ignore
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore


def _get_fernet() -> Fernet | None:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)

    if not key or Fernet is None:
        # Handle missing encryption key
        if getattr(settings, "DEBUG", False):
            # Development: Auto-generate temporary key with loud warnings
            if not hasattr(settings, "_temp_encryption_key"):
                temp_key = Fernet.generate_key().decode()
                settings.FIELD_ENCRYPTION_KEY = temp_key
                settings._temp_encryption_key = True

                # Print loud warning to console
                print("\n" + "=" * 80)
                print(" WARNING: AUTO-GENERATED TEMPORARY ENCRYPTION KEY")
                print("=" * 80)
                print("No FIELD_ENCRYPTION_KEY found in settings.")
                print("Generated temporary key for development use.")
                print(f"Set FIELD_ENCRYPTION_KEY={temp_key} in production!")
                print("Tokens will be encrypted with this temporary key.")
                print("=" * 80 + "\n")

                key = temp_key
            else:
                key = settings.FIELD_ENCRYPTION_KEY
        else:
            # Production: Fail fast - never allow unencrypted tokens
            raise EncryptionConfigError(
                "FIELD_ENCRYPTION_KEY is required for production deployment. "
                "OAuth tokens cannot be stored unencrypted. "
                "Generate a key with: python -c 'from cryptography.fernet import "
                "Fernet; print(Fernet.generate_key().decode())'"
            )

    if Fernet is None:
        raise ImportError("cryptography package is required for token encryption")

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise InvalidEncryptionKeyError(str(e))


def encrypt(value: str | None) -> str | None:
    """Encrypt a value for secure storage. Fails fast if encryption not available."""
    if value in (None, ""):
        return value

    f = _get_fernet()
    if not f:
        # This should never happen due to fail-fast logic in _get_fernet()
        raise EncryptionConfigError("Encryption not available")

    token = f.encrypt(str(value).encode("utf-8"))
    return token.decode("utf-8")


def decrypt(value: str | None) -> str | None:
    """Decrypt a value from secure storage. Fails fast if decryption not available."""
    if value in (None, ""):
        return value

    f = _get_fernet()
    if not f:
        # This should never happen due to fail-fast logic in _get_fernet()
        raise EncryptionConfigError("Decryption not available")

    try:
        plain = f.decrypt(str(value).encode("utf-8"))
        return plain.decode("utf-8")
    except Exception as e:
        # In production, this could be due to key rotation or corrupted data
        if getattr(settings, "DEBUG", False):
            print(f"WARNING: Failed to decrypt value: {e}")
            return value  # In development, return original value for debugging
        raise InvalidEncryptionKeyError(f"Failed to decrypt token: {e}")
