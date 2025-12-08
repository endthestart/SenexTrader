#!/usr/bin/env python3
"""Utility script that guarantees a FIELD_ENCRYPTION_KEY before running pytest."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ensure_field_encryption_key() -> str:
    """Ensure FIELD_ENCRYPTION_KEY is defined, generating one when necessary."""
    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if key:
        return key

    fallback = os.environ.get("DEFAULT_DEV_FIELD_ENCRYPTION_KEY")
    if fallback:
        os.environ["FIELD_ENCRYPTION_KEY"] = fallback
        print("Using DEFAULT_DEV_FIELD_ENCRYPTION_KEY for encrypted fields.")
        return fallback

    try:
        from cryptography.fernet import Fernet  # Lazy import to avoid dependency at import time
    except Exception as exc:  # pragma: no cover - import failure path
        raise SystemExit(
            "cryptography package is required to generate a FIELD_ENCRYPTION_KEY"
            " (install via 'pip install cryptography')."
        ) from exc

    key = Fernet.generate_key().decode()
    os.environ["FIELD_ENCRYPTION_KEY"] = key
    print("Generated temporary FIELD_ENCRYPTION_KEY for this test run.")
    print("Set DEFAULT_DEV_FIELD_ENCRYPTION_KEY to reuse the same key locally.")
    return key


def run_pytest(pytest_args: list[str]) -> int:
    """Invoke pytest with the provided arguments and return its exit code."""
    cmd = [sys.executable, "-m", "pytest", *pytest_args]
    print(f"Running pytest via: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, cwd=PROJECT_ROOT)
    return result.returncode


def main() -> int:
    ensure_field_encryption_key()
    pytest_args = sys.argv[1:]
    return run_pytest(pytest_args)


if __name__ == "__main__":
    raise SystemExit(main())
