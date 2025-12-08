"""
Staging environment settings.

Inherits from production settings with staging-specific overrides.
"""

from .production import *  # noqa: F403

# ================================================================================
# STAGING-SPECIFIC OVERRIDES
# ================================================================================

# Staging is behind nginx reverse proxy that handles SSL
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False
