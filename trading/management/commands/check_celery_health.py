"""
Celery Health Check Management Command

Checks Celery worker and beat status to detect issues early.
Can be run as a cron job to monitor production Celery services.

Usage:
    python manage.py check_celery_health
    python manage.py check_celery_health --verbose

Exit codes:
    0 = Healthy
    1 = Unhealthy (errors detected)
"""

from django.conf import settings
from django.core.management.base import BaseCommand

import redis
from celery import current_app
from celery.app.control import Inspect


class Command(BaseCommand):
    help = "Check Celery worker and beat scheduler health"

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed health information",
        )

    def handle(self, *args, **options):
        verbose = options["verbose"]
        healthy = True

        self.stdout.write(self.style.MIGRATE_HEADING("🏥 Celery Health Check"))

        # Check 1: Redis broker connection
        try:
            redis_url = settings.CELERY_BROKER_URL
            r = redis.from_url(redis_url)
            r.ping()
            self.stdout.write(self.style.SUCCESS("Redis broker: Connected"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Redis broker: Failed - {e}"))
            healthy = False

        # Check 2: Active workers
        try:
            inspect = Inspect(app=current_app)
            active_workers = inspect.active()

            if active_workers:
                worker_count = len(active_workers)
                self.stdout.write(self.style.SUCCESS(f"Celery workers: {worker_count} active"))

                if verbose:
                    for worker_name, tasks in active_workers.items():
                        self.stdout.write(f"   - {worker_name}: {len(tasks)} active tasks")
            else:
                self.stdout.write(self.style.ERROR("Celery workers: No active workers found"))
                healthy = False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Celery workers: Failed to check - {e}"))
            healthy = False

        # Check 3: Scheduled tasks (beat)
        try:
            scheduled = inspect.scheduled()
            if scheduled is not None:
                total_scheduled = sum(len(tasks) for tasks in scheduled.values())
                self.stdout.write(
                    self.style.SUCCESS(f"Celery beat: {total_scheduled} scheduled tasks")
                )

                if verbose and scheduled:
                    for worker_name, tasks in scheduled.items():
                        self.stdout.write(f"   - {worker_name}: {len(tasks)} scheduled")
            else:
                self.stdout.write(
                    self.style.WARNING("Celery beat: No scheduled tasks (may be normal)")
                )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Celery beat: Failed to check - {e}"))
            healthy = False

        # Check 4: Registered tasks
        try:
            registered = inspect.registered()
            if registered:
                total_tasks = sum(len(tasks) for tasks in registered.values())
                self.stdout.write(
                    self.style.SUCCESS(f"Registered tasks: {total_tasks} tasks available")
                )

                if verbose:
                    # Check for critical DTE monitoring task
                    dte_task = "trading.tasks.monitor_positions_for_dte_closure"
                    found_dte = any(dte_task in tasks for tasks in registered.values())
                    if found_dte:
                        self.stdout.write(self.style.SUCCESS("   [OK] DTE monitoring task registered"))
                    else:
                        self.stdout.write(self.style.WARNING("   ⚠ DTE monitoring task NOT found"))
            else:
                self.stdout.write(self.style.ERROR("Registered tasks: No tasks registered"))
                healthy = False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Registered tasks: Failed to check - {e}"))
            healthy = False

        # Check 5: Check for recent "Event loop is closed" errors in logs (if possible)
        self.stdout.write('\nNote: Check journald logs for "Event loop is closed" errors:')
        self.stdout.write(
            '   journalctl CONTAINER_NAME=celery_worker --since "1 hour ago" | grep -i "event loop"'
        )

        # Final result
        self.stdout.write("")
        if healthy:
            self.stdout.write(self.style.SUCCESS("Overall Status: HEALTHY"))
            return  # Exit code 0
        self.stdout.write(self.style.ERROR("Overall Status: UNHEALTHY"))
        self.stdout.write("\nRecommended actions:")
        self.stdout.write(
            "1. Check service status: systemctl --machine=senex@ --user status celery-worker.service"
        )
        self.stdout.write(
            '2. Review logs: journalctl CONTAINER_NAME=celery_worker --since "1 hour ago" -p err'
        )
        self.stdout.write(
            "3. Restart if needed: systemctl --machine=senex@ --user restart celery-worker.service"
        )
        raise SystemExit(1)  # Exit code 1
