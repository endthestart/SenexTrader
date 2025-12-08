"""
Dead field cleanup and position lifecycle improvements.

This migration:
1. Adds closure_reason field for tracking how position was closed
2. Adds assigned_at field for tracking when assignment occurred
3. Removes redundant Position fields (use related_position FK instead):
   - opening_transaction_ids
   - closing_transaction_ids
   - broker_order_ids (use opening_order_id instead)
4. Removes unused Trade.realized_pnl (use Position.total_realized_pnl)

NOTE: TradingAccount OAuth fields are removed in accounts/migrations/0002_*.py
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trading", "0001_initial"),
    ]

    operations = [
        # ============================================================
        # Position Model Changes
        # ============================================================
        # Add closure_reason field
        migrations.AddField(
            model_name="position",
            name="closure_reason",
            field=models.CharField(
                max_length=50,
                null=True,
                blank=True,
                help_text="Reason position was closed: profit_target, "
                "manual_close, assignment, expired_worthless, exercise, unknown",
            ),
        ),
        # Add assigned_at field
        migrations.AddField(
            model_name="position",
            name="assigned_at",
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text="Timestamp when option was assigned (if applicable)",
            ),
        ),
        # Remove redundant Position fields - use related_position FK instead
        migrations.RemoveField(
            model_name="position",
            name="opening_transaction_ids",
        ),
        migrations.RemoveField(
            model_name="position",
            name="closing_transaction_ids",
        ),
        migrations.RemoveField(
            model_name="position",
            name="broker_order_ids",
        ),
        # ============================================================
        # Trade Model Changes
        # ============================================================
        # Remove unused realized_pnl - use Position.total_realized_pnl
        migrations.RemoveField(
            model_name="trade",
            name="realized_pnl",
        ),
    ]
