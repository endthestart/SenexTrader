#!/usr/bin/env python3
"""
Senex Trader Watchdog Service

Monitors the web application health and automatically restarts it if unresponsive.
Sends email notifications on restart.

This service:
- Checks /health/simple/ endpoint every run
- Tracks consecutive failures
- Restarts web service after 3 consecutive failures
- Sends email notification on restart
- Logs all actions
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Configuration
HEALTH_URL = "http://localhost:8000/health/simple/"
HEALTH_TIMEOUT = 5  # seconds
MAX_FAILURES = 3  # consecutive failures before restart
SERVICE_NAME = "web.service"
SERVICE_USER = "senex"
STATE_FILE = "/var/lib/senex-watchdog/failures.txt"
LOG_FILE = "/var/log/senextrader/watchdog.log"


def log(message: str, level: str = "INFO"):
    """Log message to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} [{level:7}] {message}"

    print(log_line)

    # Ensure log directory exists
    log_dir = Path(LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_line + "\n")
    except Exception as e:
        print(f"Failed to write to log file: {e}")


def get_failure_count() -> int:
    """Get current failure count from state file."""
    try:
        state_dir = Path(STATE_FILE).parent
        state_dir.mkdir(parents=True, exist_ok=True)

        if Path(STATE_FILE).exists():
            with open(STATE_FILE) as f:
                return int(f.read().strip())
        return 0
    except Exception as e:
        log(f"Failed to read state file: {e}", "WARNING")
        return 0


def set_failure_count(count: int):
    """Set failure count in state file."""
    try:
        state_dir = Path(STATE_FILE).parent
        state_dir.mkdir(parents=True, exist_ok=True)

        with open(STATE_FILE, "w") as f:
            f.write(str(count))
    except Exception as e:
        log(f"Failed to write state file: {e}", "ERROR")


def check_health() -> bool:
    """Check if the web application is healthy."""
    try:
        log(f"Checking health endpoint: {HEALTH_URL}")
        response = requests.get(HEALTH_URL, timeout=HEALTH_TIMEOUT)

        if response.status_code == 200:
            log("PASS: Health check passed")
            return True
        log(f"FAIL: Health check failed: HTTP {response.status_code}", "WARNING")
        return False

    except requests.exceptions.Timeout:
        log(f"FAIL: Health check timed out after {HEALTH_TIMEOUT}s", "WARNING")
        return False
    except requests.exceptions.ConnectionError as e:
        log(f"FAIL: Health check failed: Connection error - {e}", "WARNING")
        return False
    except Exception as e:
        log(f"FAIL: Health check failed: {e}", "ERROR")
        return False


def restart_service() -> bool:
    """Restart the web service."""
    try:
        log("Attempting to restart web service...", "WARNING")

        # Use systemctl to restart the user service
        cmd = ["systemctl", "--machine=senex@", "--user", "restart", SERVICE_NAME]

        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            log(f"PASS: Successfully restarted {SERVICE_NAME}", "WARNING")
            return True
        log(f"FAIL: Failed to restart service: {result.stderr}", "ERROR")
        return False

    except subprocess.TimeoutExpired:
        log("FAIL: Service restart timed out", "ERROR")
        return False
    except Exception as e:
        log(f"FAIL: Failed to restart service: {e}", "ERROR")
        return False


def send_email_notification(failure_count: int):
    """Send email notification about service restart."""
    try:
        log("📧 Sending email notification...")

        # Build email via Django management command
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        email_body = (
            f"The web service was automatically restarted after {failure_count} consecutive health check failures.\\n\\n"
            f"Time: {timestamp}\\n"
            f"Server: example.com\\n\\n"
            f"The service has been restarted and should be operational."
        )

        email_cmd = [
            "su",
            "-",
            SERVICE_USER,
            "-c",
            f'cd /app && python manage.py shell -c "'
            "from django.core.mail import mail_admins; "
            f"mail_admins("
            f"'Senex Trader Web Service Restarted', "
            f"'{email_body}', "
            f"fail_silently=False"
            f')"',
        ]

        result = subprocess.run(
            email_cmd,  # noqa: S603
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            log("PASS: Email notification sent", "INFO")
        else:
            log(f"FAIL: Failed to send email: {result.stderr}", "WARNING")

    except Exception as e:
        log(f"FAIL: Failed to send email notification: {e}", "WARNING")


def main():
    """Main watchdog logic."""
    log("=" * 70)
    log("Senex Trader Watchdog - Starting health check")

    # Check if service is healthy
    is_healthy = check_health()

    # Get current failure count
    failure_count = get_failure_count()

    if is_healthy:
        # Reset failure count on success
        if failure_count > 0:
            log(f"Service recovered after {failure_count} failure(s)")
        set_failure_count(0)
        log("Watchdog check complete - service healthy")
        return 0

    # Increment failure count
    failure_count += 1
    set_failure_count(failure_count)
    log(f"Consecutive failures: {failure_count}/{MAX_FAILURES}", "WARNING")

    # Check if we should restart
    if failure_count >= MAX_FAILURES:
        log(f"CRITICAL: Service unhealthy for {failure_count} consecutive checks", "ERROR")
        log("Initiating automatic restart...", "ERROR")

        if restart_service():
            # Wait a bit for service to start
            log("Waiting 10 seconds for service to initialize...")
            time.sleep(10)

            # Verify it's working
            if check_health():
                log("PASS: Service restart successful - now healthy", "WARNING")
                send_email_notification(failure_count)
                set_failure_count(0)
                return 0
            log("FAIL: Service still unhealthy after restart", "ERROR")
            send_email_notification(failure_count)
            return 1
        log("FAIL: Failed to restart service", "ERROR")
        send_email_notification(failure_count)
        return 1

    log("Watchdog check complete - waiting for next check")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Watchdog interrupted by user", "INFO")
        sys.exit(0)
    except Exception as e:
        log(f"Watchdog crashed: {e}", "ERROR")
        sys.exit(1)
