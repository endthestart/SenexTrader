"""
Data migration to update legacy strategy names.

Mapping:
- bull_put_spread -> short_put_vertical
- bear_call_spread -> short_call_vertical
- bull_call_spread -> long_call_vertical
- bear_put_spread -> long_put_vertical
"""

from django.db import migrations


def migrate_strategy_names_forward(apps, schema_editor):
    """Update legacy strategy names to new naming convention."""
    Position = apps.get_model("trading", "Position")
    TradingSuggestion = apps.get_model("trading", "TradingSuggestion")
    StrategyConfiguration = apps.get_model("trading", "StrategyConfiguration")

    name_mapping = {
        "bull_put_spread": "short_put_vertical",
        "bear_call_spread": "short_call_vertical",
        "bull_call_spread": "long_call_vertical",
        "bear_put_spread": "long_put_vertical",
    }

    for old_name, new_name in name_mapping.items():
        # Update Position.strategy_type
        Position.objects.filter(strategy_type=old_name).update(strategy_type=new_name)

        # Update TradingSuggestion.strategy_id
        TradingSuggestion.objects.filter(strategy_id=old_name).update(strategy_id=new_name)

        # Update StrategyConfiguration.strategy_id
        StrategyConfiguration.objects.filter(strategy_id=old_name).update(strategy_id=new_name)


def migrate_strategy_names_reverse(apps, schema_editor):
    """Revert to legacy strategy names (reverse migration)."""
    Position = apps.get_model("trading", "Position")
    TradingSuggestion = apps.get_model("trading", "TradingSuggestion")
    StrategyConfiguration = apps.get_model("trading", "StrategyConfiguration")

    name_mapping = {
        "short_put_vertical": "bull_put_spread",
        "short_call_vertical": "bear_call_spread",
        "long_call_vertical": "bull_call_spread",
        "long_put_vertical": "bear_put_spread",
    }

    for old_name, new_name in name_mapping.items():
        Position.objects.filter(strategy_type=old_name).update(strategy_type=new_name)
        TradingSuggestion.objects.filter(strategy_id=old_name).update(strategy_id=new_name)
        StrategyConfiguration.objects.filter(strategy_id=old_name).update(strategy_id=new_name)


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0004_add_is_automated_entry_to_position"),
    ]

    operations = [
        migrations.RunPython(
            migrate_strategy_names_forward,
            migrate_strategy_names_reverse,
        ),
    ]
