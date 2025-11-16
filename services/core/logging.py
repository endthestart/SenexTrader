"""
Structured logging configuration for Senex Trader.

This module provides comprehensive logging setup for development and production
environments, with proper handlers, formatters, and loggers for all application components.
"""

import logging
import re
from pathlib import Path

# Get the base directory for log files (project root, not services/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"

# Ensure logs directory exists
LOGS_DIR.mkdir(exist_ok=True)


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter that redacts sensitive information from log messages.

    This filter identifies and replaces sensitive data patterns such as OAuth tokens,
    passwords, API keys, credit card numbers, and SSNs with redacted placeholders.
    """

    def __init__(self):
        super().__init__()
        # Define regex patterns for sensitive data (case-insensitive)
        self.patterns = [
            # OAuth tokens (Bearer tokens, access tokens)
            (re.compile(r"(bearer\s+)[a-zA-Z0-9\-._~+/]+=*", re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
            (
                re.compile(r"(access[_-]?token[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE),
                r"\1[REDACTED_TOKEN]",
            ),
            # Passwords
            (
                re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE),
                r"\1[REDACTED_PASSWORD]",
            ),
            (
                re.compile(r"(pwd[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE),
                r"\1[REDACTED_PASSWORD]",
            ),
            (
                re.compile(r"(pass[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE),
                r"\1[REDACTED_PASSWORD]",
            ),
            # API keys and secrets
            (
                re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE),
                r"\1[REDACTED_API_KEY]",
            ),
            (
                re.compile(r"(secret[_-]?key[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE),
                r"\1[REDACTED_SECRET]",
            ),
            (
                re.compile(
                    r"(client[_-]?secret[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]+)", re.IGNORECASE
                ),
                r"\1[REDACTED_SECRET]",
            ),
            # Credit card numbers (basic patterns for common formats)
            (re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"), "[REDACTED_CREDIT_CARD]"),
            # SSNs (XXX-XX-XXXX format)
            (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
        ]

    def filter(self, record):
        """
        Filter log record to redact sensitive information.

        Args:
            record: LogRecord instance to filter

        Returns:
            bool: True to allow the record to be logged, False to suppress it
        """
        # Redact sensitive data from the message
        if hasattr(record, "msg"):
            msg = str(record.msg)
            for pattern, replacement in self.patterns:
                msg = pattern.sub(replacement, msg)
            record.msg = msg

        # Redact sensitive data from args if present
        if hasattr(record, "args") and record.args:
            if isinstance(record.args, dict):
                # Handle dictionary args - only process string values
                filtered_args = {}
                for key, value in record.args.items():
                    if isinstance(value, str):
                        filtered_value = value
                        for pattern, replacement in self.patterns:
                            filtered_value = pattern.sub(replacement, filtered_value)
                        filtered_args[key] = filtered_value
                    else:
                        # Preserve non-string types (floats, ints, etc.)
                        filtered_args[key] = value
                record.args = filtered_args
            elif isinstance(record.args, (list, tuple)):
                # Handle list/tuple args - only process string values
                filtered_args = []
                for arg in record.args:
                    if isinstance(arg, str):
                        filtered_arg = arg
                        for pattern, replacement in self.patterns:
                            filtered_arg = pattern.sub(replacement, filtered_arg)
                        filtered_args.append(filtered_arg)
                    else:
                        # Preserve non-string types
                        filtered_args.append(arg)
                record.args = (
                    tuple(filtered_args) if isinstance(record.args, tuple) else filtered_args
                )

        return True  # Always allow the record through (just with redacted content)


# Base logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sensitive_data": {
            "()": "services.core.logging.SensitiveDataFilter",
        }
    },
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "console_dev": {
            "format": "{asctime} {levelname:8} {name:20} {message}",
            "style": "{",
            "datefmt": "%H:%M:%S",
        },
        "console_journald": {
            "format": "[{levelname:8}] {name:30} {message}",
            "style": "{",
        },
        "structured": {
            "format": (
                "{asctime} [{levelname:8}] {name:30} PID:{process:5} TID:{thread:8} {message}"
            ),
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "console_dev",
            "filters": ["sensitive_data"],
        },
        "file_structured": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "structured",
            "filename": LOGS_DIR / "application.log",
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "filters": ["sensitive_data"],
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "verbose",
            "filename": LOGS_DIR / "errors.log",
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "filters": ["sensitive_data"],
        },
        "trading_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "structured",
            "filename": LOGS_DIR / "trading.log",
            "maxBytes": 50 * 1024 * 1024,  # 50MB
            "backupCount": 10,
            "filters": ["sensitive_data"],
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file_structured"],
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file_structured", "error_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console", "file_structured"],
            "level": "WARNING",  # Set to DEBUG to see SQL queries
            "propagate": False,
        },
        # Application-specific loggers
        "services": {
            "handlers": ["console", "file_structured", "trading_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "trading": {
            "handlers": ["console", "file_structured", "trading_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "streaming": {
            "handlers": ["console", "file_structured", "trading_file"],
            "level": "INFO",  # Reduced from DEBUG to avoid cache operation logs
            "propagate": False,
        },
        "streaming.services.enhanced_cache": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",  # Suppress verbose cache DEBUG logs
            "propagate": False,
        },
        "accounts": {
            "handlers": ["console", "file_structured"],
            "level": "DEBUG",
            "propagate": False,
        },
        # External API loggers
        "tastytrade": {
            "handlers": ["console", "file_structured", "trading_file"],
            "level": "INFO",  # Reduced from DEBUG to avoid verbose streaming logs
            "propagate": False,
        },
        "alpaca": {
            "handlers": ["console", "file_structured", "trading_file"],
            "level": "INFO",  # Reduced from DEBUG to avoid verbose API logs
            "propagate": False,
        },
        "websockets": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",  # Suppress verbose websocket client logs
            "propagate": False,
        },
        "websockets.client": {
            "handlers": ["console", "file_structured"],
            "level": "WARNING",  # Only show warnings and errors
            "propagate": False,
        },
        # HTTP client library logging
        "httpcore": {
            "handlers": ["console", "file_structured"],
            "level": "WARNING",  # Suppress verbose HTTP connection logs
            "propagate": False,
        },
        "httpx": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",  # Show HTTP requests but not connection details
            "propagate": False,
        },
        # Security and audit logging
        "django.security": {
            "handlers": ["console", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        # Channels/WebSocket logging
        "channels": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",
            "propagate": False,
        },
        "daphne": {
            "handlers": ["console", "file_structured"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


def get_development_logging():
    """Get logging configuration optimized for development."""
    config = LOGGING.copy()

    # More verbose console output for development
    config["handlers"]["console"]["level"] = "DEBUG"
    config["root"]["level"] = "DEBUG"

    # Enable SQL query logging for development (optional)
    # Uncomment the next line to see all SQL queries
    # config["loggers"]["django.db.backends"]["level"] = "DEBUG"

    return config


def get_production_logging():
    """Get logging configuration optimized for production."""
    config = LOGGING.copy()

    # Less verbose console output for production
    config["handlers"]["console"]["level"] = "WARNING"
    config["root"]["level"] = "WARNING"

    # Production focuses on file logging
    config["root"]["handlers"] = ["file_structured", "error_file"]

    return config


def get_logger(name: str):
    """
    Factory function for consistent logger creation.
    Replaces duplicate logger setup across service files.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    import logging

    return logging.getLogger(name)
