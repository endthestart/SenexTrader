"""
Export user data to JSON file for migration between environments.

Usage:
    python manage.py export_user --email user@example.com --output user_export.json
"""

import json
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from accounts.models import OptionsAllocation, User
from trading.models import (
    CachedOrderChain,
    Position,
    StrategyConfiguration,
    TastyTradeOrderHistory,
    Trade,
    TradingSuggestion,
)


class ExtendedJSONEncoder(DjangoJSONEncoder):
    """Extended JSON encoder to handle additional types."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class Command(BaseCommand):
    help = "Export all data for a user to a JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            required=True,
            help="Email of the user to export",
        )
        parser.add_argument(
            "--output",
            type=str,
            required=True,
            help="Output JSON file path",
        )

    def handle(self, *args, **options):
        email = options["email"]
        output_path = options["output"]

        self.stdout.write(f"Exporting user: {email}")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{email}' does not exist")

        # Collect all user data
        data = {
            "export_metadata": {
                "exported_at": timezone.now().isoformat(),
                "user_email": email,
                "version": "1.0",
            },
            "user": self._serialize_user(user),
            "trading_accounts": self._serialize_trading_accounts(user),
            "options_allocation": self._serialize_options_allocation(user),
            "account_snapshots": self._serialize_account_snapshots(user),
            "strategy_configs": self._serialize_strategy_configs(user),
            "positions": self._serialize_positions(user),
            "suggestions": self._serialize_suggestions(user),
            "trades": self._serialize_trades(user),
            "cached_orders": self._serialize_cached_orders(user),
            "cached_chains": self._serialize_cached_chains(user),
        }

        # Write to file
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, cls=ExtendedJSONEncoder)

        # Print statistics
        self.stdout.write(self.style.SUCCESS(f"\nExport completed: {output_path}"))
        self.stdout.write("\nExported data:")
        self.stdout.write(f"  Trading Accounts: {len(data['trading_accounts'])}")
        self.stdout.write(f"  Options Allocation: {1 if data['options_allocation'] else 0}")
        self.stdout.write(f"  Account Snapshots: {len(data['account_snapshots'])}")
        self.stdout.write(f"  Strategy Configs: {len(data['strategy_configs'])}")
        self.stdout.write(f"  Positions: {len(data['positions'])}")
        self.stdout.write(f"  Suggestions: {len(data['suggestions'])}")
        self.stdout.write(f"  Trades: {len(data['trades'])}")
        self.stdout.write(f"  Cached Orders: {len(data['cached_orders'])}")
        self.stdout.write(f"  Cached Order Chains: {len(data['cached_chains'])}")

    def _model_to_dict(self, instance, exclude_fields=None):
        """Convert model instance to dictionary."""
        exclude_fields = exclude_fields or []
        data = {}

        for field in instance._meta.fields:
            if field.name in exclude_fields:
                continue

            # For ForeignKey fields, get the ID value instead of the object
            if isinstance(field, models.ForeignKey):
                value = getattr(instance, f"{field.name}_id")
            else:
                value = getattr(instance, field.name)

            # Handle special types
            if isinstance(value, Decimal):
                data[field.name] = str(value)
            elif isinstance(value, (datetime,)) or hasattr(value, "isoformat"):
                data[field.name] = value.isoformat() if value else None
            else:
                data[field.name] = value

        return data

    def _serialize_user(self, user):
        """Serialize User model."""
        return self._model_to_dict(user)

    def _serialize_trading_accounts(self, user):
        """Serialize TradingAccount models with encrypted fields."""
        accounts = []
        for account in user.trading_accounts.all():
            account_data = self._model_to_dict(account, exclude_fields=["user"])
            # Encrypted fields are automatically decrypted by Django when accessed
            # They will be re-encrypted when saved in the import
            accounts.append(account_data)
        return accounts

    def _serialize_options_allocation(self, user):
        """Serialize OptionsAllocation model."""
        try:
            allocation = user.options_allocation
            return self._model_to_dict(allocation, exclude_fields=["user"])
        except OptionsAllocation.DoesNotExist:
            return None

    def _serialize_account_snapshots(self, user):
        """Serialize AccountSnapshot models."""
        snapshots = []
        for snapshot in user.account_snapshots.all():
            snapshots.append(self._model_to_dict(snapshot, exclude_fields=["user"]))
        return snapshots

    def _serialize_strategy_configs(self, user):
        """Serialize StrategyConfiguration models."""
        configs = []
        for config in StrategyConfiguration.objects.filter(user=user):
            configs.append(self._model_to_dict(config, exclude_fields=["user"]))
        return configs

    def _serialize_positions(self, user):
        """Serialize Position models."""
        positions = []
        for position in Position.objects.filter(user=user):
            pos_data = self._model_to_dict(position, exclude_fields=["user"])
            # Store the trading account number for FK remapping during import
            pos_data["_trading_account_number"] = position.trading_account.account_number
            positions.append(pos_data)
        return positions

    def _serialize_suggestions(self, user):
        """Serialize TradingSuggestion models."""
        suggestions = []
        for suggestion in TradingSuggestion.objects.filter(user=user):
            sugg_data = self._model_to_dict(suggestion, exclude_fields=["user"])
            # Store strategy_id for FK remapping
            sugg_data["_strategy_id"] = suggestion.strategy_id
            # Store position symbol if exists for FK remapping
            if suggestion.executed_position:
                sugg_data["_executed_position_symbol"] = suggestion.executed_position.symbol
                sugg_data["_executed_position_opened_at"] = (
                    suggestion.executed_position.opened_at.isoformat()
                    if suggestion.executed_position.opened_at
                    else None
                )
                sugg_data["_executed_position_pk"] = suggestion.executed_position.pk
            else:
                sugg_data["_executed_position_symbol"] = None
                sugg_data["_executed_position_opened_at"] = None
                sugg_data["_executed_position_pk"] = None
            suggestions.append(sugg_data)
        return suggestions

    def _serialize_trades(self, user):
        """Serialize Trade models."""
        trades = []
        for trade in Trade.objects.filter(user=user):
            trade_data = self._model_to_dict(trade, exclude_fields=["user"])
            # Store natural keys for FK remapping
            trade_data["_position_symbol"] = trade.position.symbol
            trade_data["_position_opened_at"] = (
                trade.position.opened_at.isoformat() if trade.position.opened_at else None
            )
            trade_data["_position_pk"] = (
                trade.position.pk
            )  # Fallback for positions without opened_at
            trade_data["_trading_account_number"] = trade.trading_account.account_number
            trades.append(trade_data)
        return trades

    def _serialize_cached_orders(self, user):
        """Serialize TastyTradeOrderHistory models."""
        orders = []
        for order in TastyTradeOrderHistory.objects.filter(user=user):
            order_data = self._model_to_dict(order, exclude_fields=["user"])
            order_data["_trading_account_number"] = order.trading_account.account_number
            orders.append(order_data)
        return orders

    def _serialize_cached_chains(self, user):
        """Serialize CachedOrderChain models."""
        chains = []
        for chain in CachedOrderChain.objects.filter(user=user):
            chain_data = self._model_to_dict(chain, exclude_fields=["user"])
            chain_data["_trading_account_number"] = chain.trading_account.account_number
            chains.append(chain_data)
        return chains
