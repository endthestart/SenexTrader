"""
Unified reconciliation management command.

This command provides a single interface for all reconciliation operations:
- Sync order history from TastyTrade
- Sync positions from TastyTrade
- Reconcile trade states (pending_entry → open_full)
- Validate and fix profit targets

Usage:
    # Full reconciliation for a user
    python manage.py reconcile --user=user@example.com

    # Full reconciliation for all users (same as scheduled task)
    python manage.py reconcile --all

    # Specific phases only
    python manage.py reconcile --user=user@example.com --orders-only
    python manage.py reconcile --user=user@example.com --positions-only
    python manage.py reconcile --user=user@example.com --profit-targets-only

    # Specific position
    python manage.py reconcile --position=123

    # Dry run mode (see what would change)
    python manage.py reconcile --user=user@example.com --dry-run

    # Verbose output
    python manage.py reconcile --user=user@example.com --verbose
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from services.core.utils.async_utils import run_async
from services.reconciliation.orchestrator import (
    ReconciliationOptions,
    ReconciliationOrchestrator,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Reconcile positions and orders between database and TastyTrade"

    def add_arguments(self, parser):
        # User selection
        user_group = parser.add_mutually_exclusive_group()
        user_group.add_argument(
            "--user",
            type=str,
            help="Email address of user to reconcile",
        )
        user_group.add_argument(
            "--all",
            action="store_true",
            help="Reconcile all active users (same as scheduled task)",
        )
        user_group.add_argument(
            "--position",
            type=int,
            help="Reconcile specific position ID only",
        )

        # Phase selection
        phase_group = parser.add_mutually_exclusive_group()
        phase_group.add_argument(
            "--orders-only",
            action="store_true",
            help="Only sync order history",
        )
        phase_group.add_argument(
            "--positions-only",
            action="store_true",
            help="Only sync positions",
        )
        phase_group.add_argument(
            "--trades-only",
            action="store_true",
            help="Only reconcile trade states",
        )
        phase_group.add_argument(
            "--profit-targets-only",
            action="store_true",
            help="Only validate/fix profit targets",
        )

        # Behavior options
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )
        # Note: Django provides -v/--verbosity natively, use that instead
        parser.add_argument(
            "--days-back",
            type=int,
            default=30,
            help="Days of order history to sync (default: 30)",
        )

        # Fix options
        parser.add_argument(
            "--cancel-orphaned",
            action="store_true",
            help="Cancel orders at broker that are not in database",
        )
        parser.add_argument(
            "--replace-cancelled",
            action="store_true",
            help="Replace cancelled profit target orders with new ones",
        )

        # Symbol filter
        parser.add_argument(
            "--symbol",
            type=str,
            help="Only reconcile positions with this underlying symbol",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Execute the reconciliation."""
        # Build options
        reconciliation_options = self._build_options(options)

        # Validate user selection
        has_target = options.get("all") or options.get("user") or options.get("position")
        if not has_target:
            self.stderr.write(self.style.ERROR("Must specify --user, --position, or --all"))
            return

        # Print header
        self._print_header(options)

        # Run reconciliation
        orchestrator = ReconciliationOrchestrator(options=reconciliation_options)
        result = run_async(orchestrator.run())

        # Print results
        self._print_results(result, options)

    def _build_options(self, options: dict) -> ReconciliationOptions:
        """Build ReconciliationOptions from command line arguments."""
        # Determine which phases to run
        sync_order_history = True
        sync_positions = True
        reconcile_trades = True
        fix_profit_targets = True

        if options.get("orders_only"):
            sync_positions = False
            reconcile_trades = False
            fix_profit_targets = False
        elif options.get("positions_only"):
            sync_order_history = False
            reconcile_trades = False
            fix_profit_targets = False
        elif options.get("trades_only"):
            sync_order_history = False
            sync_positions = False
            fix_profit_targets = False
        elif options.get("profit_targets_only"):
            sync_order_history = False
            sync_positions = False
            reconcile_trades = False

        # Get user ID if specified
        user_id = None
        if options.get("user"):
            try:
                user = User.objects.get(email=options["user"])
                user_id = user.pk
            except User.DoesNotExist as exc:
                self.stderr.write(self.style.ERROR(f"User not found: {options['user']}"))
                raise SystemExit(1) from exc

        return ReconciliationOptions(
            sync_order_history=sync_order_history,
            sync_positions=sync_positions,
            reconcile_trades=reconcile_trades,
            fix_profit_targets=fix_profit_targets,
            user_id=user_id,
            position_id=options.get("position"),
            symbol=options.get("symbol"),
            dry_run=options.get("dry_run", False),
            cancel_orphaned_orders=options.get("cancel_orphaned", False),
            replace_cancelled_targets=options.get("replace_cancelled", False),
            days_back=options.get("days_back", 30),
            # Django's verbosity: 0=silent, 1=normal, 2+=verbose
            verbose=options.get("verbosity", 1) >= 2,
        )

    def _print_header(self, options: dict):
        """Print command header."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RECONCILIATION")
        self.stdout.write("=" * 80)

        if options.get("dry_run"):
            self.stdout.write(self.style.WARNING("\nDRY RUN MODE - No changes will be made\n"))

        # Print what will be reconciled
        if options.get("user"):
            self.stdout.write(f"User: {options['user']}")
        elif options.get("position"):
            self.stdout.write(f"Position: {options['position']}")
        else:
            self.stdout.write("Scope: All active users")

        # Print phases
        phases = []
        if options.get("orders_only"):
            phases = ["order history sync"]
        elif options.get("positions_only"):
            phases = ["position sync"]
        elif options.get("trades_only"):
            phases = ["trade reconciliation"]
        elif options.get("profit_targets_only"):
            phases = ["profit target validation"]
        else:
            phases = [
                "order history sync",
                "position sync",
                "trade reconciliation",
                "profit target validation",
            ]

        self.stdout.write(f"Phases: {', '.join(phases)}")
        self.stdout.write("")

    def _print_results(self, result, options: dict):
        """Print reconciliation results."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RESULTS")
        self.stdout.write("=" * 80)

        # Print phase summaries
        for phase_name, phase_result in result.phase_results.items():
            phase_display = phase_name.replace("_", " ").title()

            status = self.style.SUCCESS("") if phase_result.success else self.style.ERROR("")

            self.stdout.write(f"\n{status} {phase_display} [{phase_result.duration_seconds}s]")
            self.stdout.write(f"   Processed: {phase_result.items_processed}")
            self.stdout.write(f"   Created: {phase_result.items_created}")
            self.stdout.write(f"   Updated: {phase_result.items_updated}")

            if phase_result.details:
                for key, value in phase_result.details.items():
                    self.stdout.write(f"   {key.replace('_', ' ').title()}: {value}")

            if phase_result.errors:
                self.stdout.write(self.style.WARNING(f"   Errors: {len(phase_result.errors)}"))
                if options.get("verbose"):
                    for error in phase_result.errors[:5]:  # Show first 5 errors
                        self.stdout.write(f"      - {error}")

        # Print summary
        self.stdout.write("\n" + "-" * 80)
        completed = len(result.phases_completed)
        total = len(result.phase_results)
        duration = result.total_duration_seconds

        if result.success:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Reconciliation complete: {completed}/{total} phases "
                    f"succeeded in {duration}s"
                )
            )
        else:
            failed = len(result.phases_failed)
            self.stdout.write(
                self.style.ERROR(
                    f"Reconciliation completed with errors: "
                    f"{completed}/{total} phases succeeded, "
                    f"{failed} failed in {duration}s"
                )
            )

        self.stdout.write("")
