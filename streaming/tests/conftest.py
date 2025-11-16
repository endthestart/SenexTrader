"""
Pytest configuration for streaming tests.
"""

import os

# Configure Django settings BEFORE any Django imports
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "senextrader.settings.development")

# Set test encryption key for encrypted fields
if "FIELD_ENCRYPTION_KEY" not in os.environ:
    from cryptography.fernet import Fernet

    os.environ["FIELD_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

# Setup Django
import django

django.setup()
