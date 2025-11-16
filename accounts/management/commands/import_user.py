"""
Import user data from JSON file exported by export_user command.

Usage:
    python manage.py import_user --input user_export.json --dry-run
    python manage.py import_user --input user_export.json
"""

import contextlib
import json
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from accounts.models import AccountSnapshot, OptionsAllocation, TradingAccount, User
from trading.models import (
    CachedOrder,
    CachedOrderChain,
    Position,
    StrategyConfiguration,
    Trade,
    TradingSuggestion,
)


class Command(BaseCommand):
    help = "Import user data from JSON file"

    def __init__(self):
        super().__init__()
        self.pk_mappings = {
            "trading_account": {},  # old_pk -> new instance
            "strategy_config": {},  # old_pk -> new instance
            "position": {},  # old_pk -> new instance
        }
        self.stats = {}

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=str,
            required=True,
            help="Input JSON file path",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate import without writing to database",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing user if they exist",
        )

    def handle(self, *args, **options):
        input_path = options["input"]
        dry_run = options["dry_run"]
        force = options["force"]

        self.stdout.write(f"Importing user data from: {input_path}")

        # Load JSON data
        try:
            with open(input_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {input_path}")
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON: {e}")

        # Validate structure
        required_keys = [
            "user",
            "trading_accounts",
            "account_snapshots",
            "strategy_configs",
            "positions",
            "suggestions",
            "trades",
            "cached_orders",
            "cached_chains",
        ]
        for key in required_keys:
            if key not in data:
                raise CommandError(f"Missing required key in JSON: {key}")

        email = data["user"]["email"]

        # Check if user exists
        if User.objects.filter(email=email).exists():
            if not force:
                raise CommandError(
                    f"User {email} already exists. Use --force to delete existing user first"
                )
            self.stdout.write(self.style.WARNING(f"User {email} exists, deleting..."))
            # Delete existing user (CASCADE will remove all related data)
            User.objects.filter(email=email).delete()
            self.stdout.write(self.style.SUCCESS("Existing user deleted"))

        if dry_run:
            self.stdout.write(self.style.WARNING("\n🔍 DRY RUN MODE - No changes will be made\n"))
            self._validate_import(data)
            return

        # Perform import
        self._import_data(data)

    def _validate_import(self, data):
        """Validate the import data structure and contents."""
        self.stdout.write("Validating import data...")

        user_data = data["user"]
        self.stdout.write(f"  User: {user_data['email']}")
        self.stdout.write(f"  Trading Accounts: {len(data['trading_accounts'])}")
        self.stdout.write(f"  Options Allocation: {1 if data['options_allocation'] else 0}")
        self.stdout.write(f"  Account Snapshots: {len(data['account_snapshots'])}")
        self.stdout.write(f"  Strategy Configs: {len(data['strategy_configs'])}")
        self.stdout.write(f"  Positions: {len(data['positions'])}")
        self.stdout.write(f"  Suggestions: {len(data['suggestions'])}")
        self.stdout.write(f"  Trades: {len(data['trades'])}")
        self.stdout.write(f"  Cached Orders: {len(data['cached_orders'])}")
        self.stdout.write(f"  Cached Order Chains: {len(data['cached_chains'])}")

        self.stdout.write(self.style.SUCCESS("\n✅ Validation passed"))

    def _import_data(self, data):
        """Import all data with transaction safety."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("IMPORTING USER DATA")
        self.stdout.write("=" * 80 + "\n")

        try:
            with transaction.atomic():
                # Import in dependency order
                new_user = self._import_user(data["user"])
                self._import_trading_accounts(data["trading_accounts"], new_user)
                self._import_options_allocation(data["options_allocation"], new_user)
                self._import_account_snapshots(data["account_snapshots"], new_user)
                self._import_strategy_configs(data["strategy_configs"], new_user)
                self._import_positions(data["positions"], new_user)
                self._import_suggestions(data["suggestions"], new_user)
                self._import_trades(data["trades"], new_user)
                self._import_cached_orders(data["cached_orders"], new_user)
                self._import_cached_chains(data["cached_chains"], new_user)

            # Print summary
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(self.style.SUCCESS("✅ IMPORT COMPLETED SUCCESSFULLY"))
            self.stdout.write("=" * 80)
            self.stdout.write("\nImported:")
            for key, count in self.stats.items():
                self.stdout.write(f"  {key}: {count}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Import failed: {e!s}"))
            raise

    def _parse_datetime(self, value):
        """Parse datetime string or return None."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return parse_datetime(value)

    def _parse_decimal(self, value):
        """Parse decimal string or return None."""
        if value is None:
            return None
        return Decimal(str(value))

    def _import_user(self, user_data):
        """Import User model."""
        self.stdout.write("Importing User...")

        user = User(
            username=user_data["username"],
            email=user_data["email"],
            first_name=user_data.get("first_name", ""),
            last_name=user_data.get("last_name", ""),
            password=user_data["password"],
            email_verified=user_data.get("email_verified", False),
            email_verification_token=user_data.get("email_verification_token"),
            email_preference=user_data.get("email_preference", "important"),
            is_staff=user_data.get("is_staff", False),
            is_superuser=user_data.get("is_superuser", False),
            is_active=user_data.get("is_active", True),
        )

        # Set timestamps
        user.date_joined = self._parse_datetime(user_data.get("date_joined"))
        if user_data.get("last_login"):
            user.last_login = self._parse_datetime(user_data["last_login"])

        user.save()

        self.stats["user"] = 1
        self.stdout.write(f"  ✅ User created: {user.email} (pk={user.pk})")
        return user

    def _import_trading_accounts(self, accounts_data, user):
        """Import TradingAccount models."""
        self.stdout.write("\nImporting Trading Accounts...")

        for account_data in accounts_data:
            old_pk = account_data["id"]

            account = TradingAccount(
                user=user,
                connection_type=account_data["connection_type"],
                account_number=account_data["account_number"],
                account_nickname=account_data.get("account_nickname", ""),
                access_token=account_data.get("access_token", ""),
                refresh_token=account_data.get("refresh_token", ""),
                token_type=account_data.get("token_type", ""),
                scope=account_data.get("scope", ""),
                token_expires_at=self._parse_datetime(account_data.get("token_expires_at")),
                metadata=account_data.get("metadata", {}),
                is_active=account_data.get("is_active", True),
                is_primary=account_data.get("is_primary", False),
                is_automated_trading_enabled=account_data.get(
                    "is_automated_trading_enabled", False
                ),
                automated_entry_offset_cents=account_data.get("automated_entry_offset_cents", 0),
                is_test=account_data.get("is_test", False),
                is_token_valid=account_data.get("is_token_valid", True),
                last_authenticated=self._parse_datetime(account_data.get("last_authenticated")),
                token_refresh_count=account_data.get("token_refresh_count", 0),
                last_token_rotation=self._parse_datetime(account_data.get("last_token_rotation")),
            )
            account.save()

            self.pk_mappings["trading_account"][old_pk] = account
            self.stats["trading_accounts"] = self.stats.get("trading_accounts", 0) + 1
            self.stdout.write(
                f"  ✅ {account.account_number} (old_pk={old_pk} → new_pk={account.pk})"
            )

    def _import_options_allocation(self, allocation_data, user):
        """Import OptionsAllocation model."""
        if not allocation_data:
            self.stdout.write("\n⚠️  No options allocation to import")
            return

        self.stdout.write("\nImporting Options Allocation...")

        allocation = OptionsAllocation(
            user=user,
            allocation_method=allocation_data["allocation_method"],
            risk_tolerance=self._parse_decimal(allocation_data["risk_tolerance"]),
            stressed_risk_tolerance=self._parse_decimal(
                allocation_data.get("stressed_risk_tolerance")
            ),
            strategy_power=self._parse_decimal(allocation_data.get("strategy_power")),
        )
        allocation.save()

        self.stats["options_allocation"] = 1
        self.stdout.write("  ✅ Options allocation created")

    def _import_account_snapshots(self, snapshots_data, user):
        """Import AccountSnapshot models."""
        self.stdout.write("\nImporting Account Snapshots...")

        snapshots = []
        for snapshot_data in snapshots_data:
            snapshots.append(
                AccountSnapshot(
                    user=user,
                    account_number=snapshot_data["account_number"],
                    buying_power=self._parse_decimal(snapshot_data["buying_power"]),
                    balance=self._parse_decimal(snapshot_data["balance"]),
                    source=snapshot_data.get("source", "sdk"),
                )
            )

        AccountSnapshot.objects.bulk_create(snapshots)
        self.stats["account_snapshots"] = len(snapshots)
        self.stdout.write(f"  ✅ Created {len(snapshots)} snapshots")

    def _import_strategy_configs(self, configs_data, user):
        """Import StrategyConfiguration models."""
        self.stdout.write("\nImporting Strategy Configurations...")

        for config_data in configs_data:
            old_pk = config_data["id"]

            config = StrategyConfiguration(
                user=user,
                strategy_id=config_data["strategy_id"],
                parameters=config_data.get("parameters", {}),
                is_active=config_data.get("is_active", True),
            )
            # Preserve timestamps
            if config_data.get("created_at"):
                config.created_at = self._parse_datetime(config_data["created_at"])
            if config_data.get("updated_at"):
                config.updated_at = self._parse_datetime(config_data["updated_at"])
            config.save()

            self.pk_mappings["strategy_config"][old_pk] = config
            self.stats["strategy_configs"] = self.stats.get("strategy_configs", 0) + 1
            self.stdout.write(f"  ✅ {config.strategy_id} (old_pk={old_pk} → new_pk={config.pk})")

    def _import_positions(self, positions_data, user):
        """Import Position models."""
        self.stdout.write("\nImporting Positions...")

        for pos_data in positions_data:
            old_pk = pos_data["id"]
            account_number = pos_data["_trading_account_number"]

            # Find trading account by natural key
            trading_account = TradingAccount.objects.get(user=user, account_number=account_number)

            position = Position(
                user=user,
                trading_account=trading_account,
                strategy_type=pos_data.get("strategy_type"),
                symbol=pos_data["symbol"],
                lifecycle_state=pos_data.get("lifecycle_state", "pending_entry"),
                quantity=self._parse_decimal(pos_data.get("quantity")),
                avg_price=self._parse_decimal(pos_data.get("avg_price")),
                unrealized_pnl=self._parse_decimal(pos_data.get("unrealized_pnl")),
                total_realized_pnl=self._parse_decimal(pos_data.get("total_realized_pnl")),
                metadata=pos_data.get("metadata", {}),
                opened_at=self._parse_datetime(pos_data.get("opened_at")),
                closed_at=self._parse_datetime(pos_data.get("closed_at")),
                is_app_managed=pos_data.get("is_app_managed", False),
                initial_risk=self._parse_decimal(pos_data.get("initial_risk")),
                spread_width=self._parse_decimal(pos_data.get("spread_width")),
                number_of_spreads=pos_data.get("number_of_spreads"),
                broker_order_ids=pos_data.get("broker_order_ids", []),
                opening_price_effect=pos_data.get("opening_price_effect"),
                profit_targets_created=pos_data.get("profit_targets_created", False),
                profit_target_details=pos_data.get("profit_target_details", {}),
            )
            # Preserve timestamps
            if pos_data.get("created_at"):
                position.created_at = self._parse_datetime(pos_data["created_at"])
            if pos_data.get("updated_at"):
                position.updated_at = self._parse_datetime(pos_data["updated_at"])
            position.save()

            self.pk_mappings["position"][old_pk] = position
            self.stats["positions"] = self.stats.get("positions", 0) + 1
            self.stdout.write(f"  ✅ {position.symbol} (old_pk={old_pk} → new_pk={position.pk})")

    def _import_suggestions(self, suggestions_data, user):
        """Import TradingSuggestion models."""
        self.stdout.write("\nImporting Trading Suggestions...")

        for sugg_data in suggestions_data:
            strategy_id = sugg_data["_strategy_id"]
            strategy_config = StrategyConfiguration.objects.get(user=user, strategy_id=strategy_id)

            # Find executed position if exists
            executed_position = None
            if sugg_data.get("_executed_position_symbol"):
                # Try natural key first (symbol + opened_at)
                if sugg_data.get("_executed_position_opened_at"):
                    with contextlib.suppress(Position.DoesNotExist):
                        executed_position = Position.objects.get(
                            user=user,
                            symbol=sugg_data["_executed_position_symbol"],
                            opened_at=self._parse_datetime(
                                sugg_data["_executed_position_opened_at"]
                            ),
                        )

                # Fallback: use old PK from mapping if natural key didn't work
                if not executed_position and sugg_data.get("_executed_position_pk"):
                    old_position_pk = sugg_data["_executed_position_pk"]
                    executed_position = self.pk_mappings["position"].get(old_position_pk)

            suggestion = TradingSuggestion(
                user=user,
                strategy_configuration=strategy_config,
                underlying_symbol=sugg_data["underlying_symbol"],
                underlying_price=self._parse_decimal(sugg_data.get("underlying_price")),
                expiration_date=sugg_data.get("expiration_date"),
                short_put_strike=self._parse_decimal(sugg_data.get("short_put_strike")),
                long_put_strike=self._parse_decimal(sugg_data.get("long_put_strike")),
                short_call_strike=self._parse_decimal(sugg_data.get("short_call_strike")),
                long_call_strike=self._parse_decimal(sugg_data.get("long_call_strike")),
                put_spread_quantity=sugg_data.get("put_spread_quantity"),
                call_spread_quantity=sugg_data.get("call_spread_quantity"),
                put_spread_credit=self._parse_decimal(sugg_data.get("put_spread_credit")),
                call_spread_credit=self._parse_decimal(sugg_data.get("call_spread_credit")),
                total_credit=self._parse_decimal(sugg_data.get("total_credit")),
                put_spread_mid_credit=self._parse_decimal(sugg_data.get("put_spread_mid_credit")),
                call_spread_mid_credit=self._parse_decimal(sugg_data.get("call_spread_mid_credit")),
                total_mid_credit=self._parse_decimal(sugg_data.get("total_mid_credit")),
                max_risk=self._parse_decimal(sugg_data.get("max_risk")),
                price_effect=sugg_data.get("price_effect"),
                max_profit=self._parse_decimal(sugg_data.get("max_profit")),
                iv_rank=self._parse_decimal(sugg_data.get("iv_rank")),
                is_near_bollinger_band=sugg_data.get("is_near_bollinger_band", False),
                is_range_bound=sugg_data.get("is_range_bound", False),
                market_stress_level=sugg_data.get("market_stress_level"),
                market_conditions=sugg_data.get("market_conditions", {}),
                status=sugg_data.get("status", "pending"),
                expires_at=self._parse_datetime(sugg_data.get("expires_at")),
                executed_position=executed_position,
                has_real_pricing=sugg_data.get("has_real_pricing", False),
                pricing_source=sugg_data.get("pricing_source"),
                streaming_latency_ms=sugg_data.get("streaming_latency_ms"),
                is_automated=sugg_data.get("is_automated", False),
                generation_notes=sugg_data.get("generation_notes", ""),
                rejection_reason=sugg_data.get("rejection_reason"),
            )
            # Preserve timestamps
            if sugg_data.get("generated_at"):
                suggestion.generated_at = self._parse_datetime(sugg_data["generated_at"])
            suggestion.save()

            self.stats["suggestions"] = self.stats.get("suggestions", 0) + 1

        self.stdout.write(f"  ✅ Created {self.stats.get('suggestions', 0)} suggestions")

    def _import_trades(self, trades_data, user):
        """Import Trade models."""
        self.stdout.write("\nImporting Trades...")

        for trade_data in trades_data:
            # Find position by natural key or fallback to PK mapping
            position = None
            if trade_data.get("_position_opened_at"):
                with contextlib.suppress(Position.DoesNotExist):
                    position = Position.objects.get(
                        user=user,
                        symbol=trade_data["_position_symbol"],
                        opened_at=self._parse_datetime(trade_data["_position_opened_at"]),
                    )

            # Fallback: use old PK from mapping
            if not position and trade_data.get("_position_pk"):
                old_position_pk = trade_data["_position_pk"]
                position = self.pk_mappings["position"].get(old_position_pk)

            if not position:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ⚠️  Skipping trade {trade_data.get('broker_order_id')}: "
                        f"position not found"
                    )
                )
                continue

            trading_account = TradingAccount.objects.get(
                user=user, account_number=trade_data["_trading_account_number"]
            )

            trade = Trade(
                user=user,
                position=position,
                trading_account=trading_account,
                broker_order_id=trade_data.get("broker_order_id"),
                trade_type=trade_data["trade_type"],
                order_legs=trade_data.get("order_legs", []),
                executed_price=self._parse_decimal(trade_data.get("executed_price")),
                quantity=trade_data.get("quantity"),
                status=trade_data.get("status", "pending"),
                parent_order_id=trade_data.get("parent_order_id"),
                child_order_ids=trade_data.get("child_order_ids", []),
                filled_at=self._parse_datetime(trade_data.get("filled_at")),
                fill_price=self._parse_decimal(trade_data.get("fill_price")),
                commission=self._parse_decimal(trade_data.get("commission")),
                lifecycle_event=trade_data.get("lifecycle_event"),
                realized_pnl=self._parse_decimal(trade_data.get("realized_pnl")),
                lifecycle_snapshot=trade_data.get("lifecycle_snapshot", {}),
                order_type=trade_data.get("order_type"),
                time_in_force=trade_data.get("time_in_force"),
                metadata=trade_data.get("metadata", {}),
            )
            # Preserve timestamps
            if trade_data.get("submitted_at"):
                trade.submitted_at = self._parse_datetime(trade_data["submitted_at"])
            if trade_data.get("executed_at"):
                trade.executed_at = self._parse_datetime(trade_data["executed_at"])
            trade.save()

            self.stats["trades"] = self.stats.get("trades", 0) + 1

        self.stdout.write(f"  ✅ Created {self.stats.get('trades', 0)} trades")

    def _import_cached_orders(self, orders_data, user):
        """Import CachedOrder models."""
        self.stdout.write("\nImporting Cached Orders...")

        for order_data in orders_data:
            trading_account = TradingAccount.objects.get(
                user=user, account_number=order_data["_trading_account_number"]
            )

            order = CachedOrder(
                user=user,
                trading_account=trading_account,
                broker_order_id=order_data.get("broker_order_id"),
                complex_order_id=order_data.get("complex_order_id"),
                parent_order_id=order_data.get("parent_order_id"),
                replaces_order_id=order_data.get("replaces_order_id"),
                replacing_order_id=order_data.get("replacing_order_id"),
                underlying_symbol=order_data.get("underlying_symbol"),
                order_type=order_data.get("order_type"),
                status=order_data.get("status"),
                price=self._parse_decimal(order_data.get("price")),
                price_effect=order_data.get("price_effect"),
                received_at=self._parse_datetime(order_data.get("received_at")),
                live_at=self._parse_datetime(order_data.get("live_at")),
                filled_at=self._parse_datetime(order_data.get("filled_at")),
                cancelled_at=self._parse_datetime(order_data.get("cancelled_at")),
                terminal_at=self._parse_datetime(order_data.get("terminal_at")),
                order_data=order_data.get("order_data", {}),
            )
            order.save()

            self.stats["cached_orders"] = self.stats.get("cached_orders", 0) + 1

        self.stdout.write(f"  ✅ Created {self.stats.get('cached_orders', 0)} cached orders")

    def _import_cached_chains(self, chains_data, user):
        """Import CachedOrderChain models."""
        self.stdout.write("\nImporting Cached Order Chains...")

        for chain_data in chains_data:
            trading_account = TradingAccount.objects.get(
                user=user, account_number=chain_data["_trading_account_number"]
            )

            chain = CachedOrderChain(
                user=user,
                trading_account=trading_account,
                chain_id=chain_data.get("chain_id"),
                underlying_symbol=chain_data.get("underlying_symbol"),
                description=chain_data.get("description", ""),
                total_commissions=self._parse_decimal(chain_data.get("total_commissions")),
                total_fees=self._parse_decimal(chain_data.get("total_fees")),
                realized_pnl=self._parse_decimal(chain_data.get("realized_pnl")),
                unrealized_pnl=self._parse_decimal(chain_data.get("unrealized_pnl")),
                chain_data=chain_data.get("chain_data", {}),
                created_at=self._parse_datetime(chain_data.get("created_at")),
                updated_at=self._parse_datetime(chain_data.get("updated_at")),
            )
            chain.save()

            self.stats["cached_chains"] = self.stats.get("cached_chains", 0) + 1

        self.stdout.write(f"  ✅ Created {self.stats.get('cached_chains', 0)} cached chains")
