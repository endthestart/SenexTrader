"""
Update Senex Trident max_dte from 45 to 50.

This migration updates existing StrategyConfiguration records to widen the
acceptable DTE range from 30-45 to 30-50 days, while keeping the target at 45.

This allows the algorithm to select 46-50 DTE expirations when they are the
closest available option to the 45 DTE target.
"""

from django.db import migrations


def update_senex_max_dte(apps, schema_editor):
    """Update max_dte from 45 to 50 in existing configurations."""
    StrategyConfiguration = apps.get_model("trading", "StrategyConfiguration")
    
    configs = StrategyConfiguration.objects.filter(strategy_id="senex_trident")
    
    updated_count = 0
    for config in configs:
        # Get the senex_trident parameters
        senex_params = config.parameters.get("senex_trident", {})
        
        # Only update if max_dte is currently set to 45
        if senex_params.get("max_dte") == 45:
            senex_params["max_dte"] = 50
            config.parameters["senex_trident"] = senex_params
            config.save(update_fields=["parameters"])
            updated_count += 1
    
    if updated_count > 0:
        print(
            f"Updated max_dte to 50 for {updated_count} "
            f"Senex Trident configuration(s)"
        )


def reverse_senex_max_dte(apps, schema_editor):
    """Reverse the migration by setting max_dte back to 45."""
    StrategyConfiguration = apps.get_model("trading", "StrategyConfiguration")
    
    configs = StrategyConfiguration.objects.filter(strategy_id="senex_trident")
    
    for config in configs:
        senex_params = config.parameters.get("senex_trident", {})
        
        # Only reverse if max_dte is currently set to 50
        if senex_params.get("max_dte") == 50:
            senex_params["max_dte"] = 45
            config.parameters["senex_trident"] = senex_params
            config.save(update_fields=["parameters"])


class Migration(migrations.Migration):
    dependencies = [
        ("trading", "0002_position_closure_fields"),
    ]

    operations = [
        migrations.RunPython(update_senex_max_dte, reverse_senex_max_dte),
    ]
