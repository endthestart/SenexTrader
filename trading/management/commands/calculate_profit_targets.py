"""
SIMPLE profit target calculator for Senex positions.
Shows exact prices for manual order creation.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from trading.models import Position, Trade, TradingSuggestion

User = get_user_model()


class Command(BaseCommand):
    help = "Calculate and display profit target prices for Senex positions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--position",
            type=int,
            required=True,
            help="Position ID to calculate profit targets for",
        )

    def handle(self, *args, **options):
        """Calculate profit targets synchronously."""
        try:
            position = Position.objects.get(id=options["position"])

            self.stdout.write("\nPROFIT TARGET CALCULATOR")
            self.stdout.write(f"Position: {position.id}")
            self.stdout.write(f"Strategy: {position.strategy_type}")
            self.stdout.write(f"User: {position.user.email}")

            # Get opening trade
            opening_trade = Trade.objects.filter(position=position, trade_type="open").first()
            if not opening_trade:
                raise CommandError(f"No opening trade found for position {position.id}")

            self.stdout.write(f"Opening Trade: {opening_trade.id}")
            self.stdout.write(f"Broker Order ID: {opening_trade.broker_order_id}")

            # Get suggestion
            metadata = position.metadata or {}
            suggestion_id = metadata.get("suggestion_id")
            if not suggestion_id:
                raise CommandError("No suggestion_id in position metadata")

            suggestion = TradingSuggestion.objects.get(id=suggestion_id)
            self.stdout.write(f"Suggestion: #{suggestion.id}")

            if position.strategy_type == "senex_trident":
                self._calculate_senex_targets(suggestion)
            else:
                self.stdout.write("Only Senex Trident strategy supported")

        except Exception as e:
            raise CommandError(f"Calculation failed: {e!s}")

    def _calculate_senex_targets(self, suggestion: TradingSuggestion):
        """Calculate Senex Trident profit targets: 40%, 60%, 50%"""
        self.stdout.write("\nSENEX TRIDENT PROFIT TARGETS")
        self.stdout.write("Original Credits:")
        self.stdout.write(f"  Put Spread Credit: ${suggestion.put_spread_credit}")
        self.stdout.write(f"  Call Spread Credit: ${suggestion.call_spread_credit}")
        self.stdout.write(f"  Total Credit: ${suggestion.total_credit}")

        self.stdout.write("\n💰 PROFIT TARGET PRICES (Buy-to-Close):")

        # 1. Put Spread #1 - 40% profit (buy back at 60% of credit)
        if suggestion.put_spread_quantity >= 1 and suggestion.put_spread_credit:
            target_price_1 = suggestion.put_spread_credit * Decimal("0.60")
            profit_1 = suggestion.put_spread_credit - target_price_1
            profit_pct_1 = (profit_1 / suggestion.put_spread_credit) * 100

            self.stdout.write("  1️⃣  Put Spread #1 (40% Target):")
            self.stdout.write(f"      Buy-to-Close at: ${target_price_1:.2f}")
            self.stdout.write(f"      Profit: ${profit_1:.2f} ({profit_pct_1:.1f}%)")

        # 2. Put Spread #2 - 60% profit (buy back at 40% of credit)
        if suggestion.put_spread_quantity >= 2 and suggestion.put_spread_credit:
            target_price_2 = suggestion.put_spread_credit * Decimal("0.40")
            profit_2 = suggestion.put_spread_credit - target_price_2
            profit_pct_2 = (profit_2 / suggestion.put_spread_credit) * 100

            self.stdout.write("  2️⃣  Put Spread #2 (60% Target):")
            self.stdout.write(f"      Buy-to-Close at: ${target_price_2:.2f}")
            self.stdout.write(f"      Profit: ${profit_2:.2f} ({profit_pct_2:.1f}%)")

        # 3. Call Spread - 50% profit (buy back at 50% of credit)
        if suggestion.call_spread_quantity >= 1 and suggestion.call_spread_credit:
            target_price_3 = suggestion.call_spread_credit * Decimal("0.50")
            profit_3 = suggestion.call_spread_credit - target_price_3
            profit_pct_3 = (profit_3 / suggestion.call_spread_credit) * 100

            self.stdout.write("  3️⃣  Call Spread (50% Target):")
            self.stdout.write(f"      Buy-to-Close at: ${target_price_3:.2f}")
            self.stdout.write(f"      Profit: ${profit_3:.2f} ({profit_pct_3:.1f}%)")

        self.stdout.write("\nMANUAL ORDER INSTRUCTIONS:")
        self.stdout.write("Create 3 separate GTC Buy-to-Close orders in TastyTrade:")
        self.stdout.write("  • Use the exact prices shown above")
        self.stdout.write("  • Set Time-in-Force to GTC (Good Till Cancelled)")
        self.stdout.write("  • Each order should close 1 contract of the respective spread")

        self.stdout.write("\nCALCULATION COMPLETE")
