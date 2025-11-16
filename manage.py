#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    """Run administrative tasks."""
    # Load .env file before Django settings are loaded
    BASE_DIR = Path(__file__).resolve().parent
    load_dotenv(BASE_DIR / ".env")

    # Set Django settings module based on ENVIRONMENT variable (matches entrypoint.sh logic)
    # This ensures commands run in production containers use production settings
    environment = os.environ.get("ENVIRONMENT", "development")
    if environment in ["production", "staging"]:
        settings_module = f"senextrader.settings.{environment}"
    else:
        settings_module = "senextrader.settings.development"

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
