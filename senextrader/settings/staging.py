"""
Staging environment settings.

Inherits from production settings but with relaxed validation for staging deployments.
"""

from .production import *  # noqa: F403

# Staging uses production-like settings but with more lenient validation
# This allows us to test production configuration in a staging environment

# ================================================================================
# STAGING-SPECIFIC OVERRIDES
# ================================================================================

# Staging is behind nginx reverse proxy that handles SSL
# Trust X-Forwarded-Proto header from proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Disable forced SSL redirect since nginx handles it
SECURE_SSL_REDIRECT = False
