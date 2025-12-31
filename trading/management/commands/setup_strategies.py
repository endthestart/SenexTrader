"""
Management command to set up initial strategy configurations for users.

not just Senex Trident. Ensures all strategies can generate suggestions.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from services.management.utils import add_user_arguments, get_user_from_options
from services.strategies.factory import list_strategies
from trading.models import SENEX_TRIDENT_DEFAULTS, StrategyConfiguration

User = get_user_model()


class Command(BaseCommand):
    help = "Set up initial strategy configurations for ALL registered strategies"

    def add_arguments(self, parser):
        add_user_arguments(parser, required=False, allow_superuser_fallback=False)
        parser.add_argument(
            "--symbol",
            type=str,
            default="QQQ",
            help="Default symbol for strategy configurations (default: QQQ)",
        )
        parser.add_argument(
            "--target-dte",
            type=int,
            default=45,
            help="Default target days to expiration (default: 45)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update existing configurations",
        )
        parser.add_argument(
            "--strategy",
            type=str,
            help="Only set up this specific strategy (e.g., short_put_vertical)",
        )

    def handle(self, *args, **options):
        options.get("user_id")
        symbol = options.get("symbol", "QQQ").upper()
        target_dte = options.get("target_dte", 45)
        force = options.get("force", False)
        specific_strategy = options.get("strategy")

        # Validate parameters
        if target_dte < 7 or target_dte > 90:
            self.stdout.write(self.style.ERROR("Target DTE must be between 7 and 90 days"))
            return

        # Get strategies to set up
        if specific_strategy:
            strategies = [specific_strategy]
            self.stdout.write(f"Setting up configuration for strategy: {specific_strategy}")
        else:
            strategies = list_strategies()
            self.stdout.write(f"Setting up configurations for {len(strategies)} strategies")

        # Get users to process
        user = get_user_from_options(options, require_user=False, allow_superuser_fallback=False)
        if user:
            users = [user]
            self.stdout.write(f"Setting up for user: {user.email}")
        else:
            users = User.objects.filter(is_active=True)
            self.stdout.write(f"Setting up for {users.count()} active users\n")

        # Set up configurations
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for user in users:
            for strategy_id in strategies:
                try:
                    # Check if configuration already exists
                    existing = StrategyConfiguration.objects.filter(
                        user=user, strategy_id=strategy_id
                    ).first()

                    if existing and not force:
                        skipped_count += 1
                        continue

                    # Build default parameters based on strategy
                    if strategy_id == "senex_trident":
                        params = {
                            **SENEX_TRIDENT_DEFAULTS,
                            "underlying_symbol": symbol,
                            "target_dte": target_dte,
                            "min_dte": max(7, target_dte - 15),
                            "max_dte": min(90, target_dte + 15),
                        }
                    elif strategy_id in (
                        "short_put_vertical",
                        "short_call_vertical",
                        "long_put_vertical",
                        "long_call_vertical",
                    ):
                        # Spread strategies with configurable profit targets
                        params = {
                            "underlying_symbol": symbol,
                            "target_dte": target_dte,
                            "min_dte": max(7, target_dte - 15),
                            "max_dte": min(90, target_dte + 15),
                            "profit_target_pct": 50,  # User configurable: 40, 50, or 60
                        }
                    else:
                        # Generic parameters for all other strategies
                        params = {
                            "underlying_symbol": symbol,
                            "target_dte": target_dte,
                            "min_dte": max(7, target_dte - 15),
                            "max_dte": min(90, target_dte + 15),
                            "profit_target_pct": 50,
                        }

                    # Create or update configuration
                    _config, created = StrategyConfiguration.objects.update_or_create(
                        user=user,
                        strategy_id=strategy_id,
                        defaults={
                            "is_active": True,
                            "parameters": params,
                        },
                    )

                    if created:
                        self.stdout.write(
                            self.style.SUCCESS(f"  [OK] Created {strategy_id} for {user.email}")
                        )
                        created_count += 1
                    else:
                        self.stdout.write(f"  ↻ Updated {strategy_id} for {user.email}")
                        updated_count += 1

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  [FAIL] Error {strategy_id} for {user.email}: {e}")
                    )

        # Summary
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("SETUP SUMMARY:")
        self.stdout.write(f"  Strategies: {len(strategies)}")
        self.stdout.write(f"  Users: {len(users)}")
        self.stdout.write(f"  Created: {created_count} configurations")
        self.stdout.write(f"  Updated: {updated_count} configurations")
        self.stdout.write(f"  Skipped: {skipped_count} configurations")
        self.stdout.write("=" * 70)

        if created_count > 0 or updated_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nStrategy setup complete! All strategies can now generate suggestions."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\nNo configurations were created or updated. "
                    "Use --force to update existing configurations."
                )
            )
