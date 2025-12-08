"""
Remove unused OAuth metadata fields from TradingAccount.

These fields were stored during OAuth token exchange but never read:
- token_type: Always "Bearer" in OAuth 2.0
- scope: OAuth scope, never used
- token_refresh_count: Telemetry counter, never read
- last_token_rotation: Telemetry timestamp, never read
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tradingaccount",
            name="token_type",
        ),
        migrations.RemoveField(
            model_name="tradingaccount",
            name="scope",
        ),
        migrations.RemoveField(
            model_name="tradingaccount",
            name="token_refresh_count",
        ),
        migrations.RemoveField(
            model_name="tradingaccount",
            name="last_token_rotation",
        ),
    ]
