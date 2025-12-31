"""
Data migration to update profit_target_details spread type keys.

For vertical spreads that were created with old naming (call_spread, put_spread),
update to the generic 'spread' key used by the new unified naming.
"""

from django.db import migrations


def migrate_spread_types_forward(apps, schema_editor):
    """Update profit_target_details spread type keys for vertical spreads."""
    Position = apps.get_model("trading", "Position")
    
    vertical_strategies = [
        "short_put_vertical",
        "short_call_vertical", 
        "long_call_vertical",
        "long_put_vertical",
    ]
    
    # Old spread type keys that should be renamed to 'spread'
    old_spread_keys = ["call_spread", "put_spread"]
    
    for position in Position.objects.filter(strategy_type__in=vertical_strategies):
        if not position.profit_target_details:
            continue
            
        updated = False
        new_details = {}
        
        for key, value in position.profit_target_details.items():
            if key in old_spread_keys:
                new_details["spread"] = value
                updated = True
            else:
                new_details[key] = value
        
        if updated:
            position.profit_target_details = new_details
            position.save(update_fields=["profit_target_details"])


def migrate_spread_types_reverse(apps, schema_editor):
    """Revert spread type keys (reverse migration)."""
    Position = apps.get_model("trading", "Position")
    
    # For reverse, we need to know the original key - use option type from legs
    for position in Position.objects.filter(
        strategy_type__in=[
            "short_put_vertical",
            "short_call_vertical",
            "long_call_vertical", 
            "long_put_vertical",
        ]
    ):
        if not position.profit_target_details or "spread" not in position.profit_target_details:
            continue
        
        # Determine if it was call or put based on strategy type
        if "call" in position.strategy_type:
            old_key = "call_spread"
        else:
            old_key = "put_spread"
            
        position.profit_target_details[old_key] = position.profit_target_details.pop("spread")
        position.save(update_fields=["profit_target_details"])


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0005_migrate_strategy_names"),
    ]

    operations = [
        migrations.RunPython(
            migrate_spread_types_forward,
            migrate_spread_types_reverse,
        ),
    ]
