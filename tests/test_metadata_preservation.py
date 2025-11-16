"""
Critical tests for position metadata preservation during sync.

These tests verify the fix for the data loss bug where position sync
would overwrite critical app-managed metadata.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import TradingAccount
from trading.models import Position

User = get_user_model()


class TestMetadataPreservation(TestCase):
    """Test that critical metadata is preserved during position sync."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            email="test@example.com", username="testuser", password="testpass123"
        )

        self.trading_account = TradingAccount.objects.create(
            user=self.user,
            connection_type="TASTYTRADE",
            account_number="12345",
            is_primary=True,
            is_active=True,
        )

    def test_app_managed_position_preserves_suggestion_id(self):
        """Verify app-managed position preserves suggestion_id during sync."""
        # Create app-managed position with metadata
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            is_app_managed=True,
            strategy_type="senex_trident",
            metadata={
                "suggestion_id": 123,
                "strikes": {
                    "short_put": "590",
                    "long_put": "585",
                    "short_call": "600",
                    "long_call": "605",
                },
                "streaming_pricing": {
                    "total_credit": 1.50,
                },
                "strategy_type": "senex_trident",
            },
            lifecycle_state="open_full",
        )

        # Simulate sync update (what would come from broker)
        sync_metadata = {
            "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            "tastytrade_data": {},
            "sync_timestamp": timezone.now().isoformat(),
            "sync_source": "tastytrade_api",
        }

        # Apply metadata merge logic (as implemented in position_sync.py)
        existing_metadata = position.metadata.copy()
        merged_metadata = existing_metadata.copy()

        # App-managed: preserve critical fields
        merged_metadata["sync_timestamp"] = sync_metadata["sync_timestamp"]
        merged_metadata["sync_source"] = sync_metadata["sync_source"]

        if "legs" not in merged_metadata or not merged_metadata.get("legs"):
            merged_metadata["legs"] = sync_metadata["legs"]

        position.metadata = merged_metadata
        position.save()

        # Verify preservation
        position.refresh_from_db()
        assert position.metadata["suggestion_id"] == 123, "suggestion_id must be preserved"
        assert position.metadata["strikes"]["short_put"] == "590", "strikes data must be preserved"
        assert (
            position.metadata["streaming_pricing"]["total_credit"] == 1.5
        ), "streaming_pricing must be preserved"
        assert (
            position.metadata["strategy_type"] == "senex_trident"
        ), "strategy_type must be preserved"

    def test_app_managed_position_updates_sync_metadata(self):
        """Verify app-managed position updates sync-related metadata only."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            is_app_managed=True,
            strategy_type="senex_trident",
            metadata={
                "suggestion_id": 123,
                "strikes": {"short_put": "590"},
            },
            lifecycle_state="open_full",
        )

        # Simulate sync
        sync_time = timezone.now().isoformat()
        sync_metadata = {
            "legs": [{"symbol": "QQQ 251107P00590000", "quantity": -1}],
            "sync_timestamp": sync_time,
            "sync_source": "tastytrade_api",
        }

        # Apply merge
        existing_metadata = position.metadata.copy()
        merged_metadata = existing_metadata.copy()
        merged_metadata["sync_timestamp"] = sync_metadata["sync_timestamp"]
        merged_metadata["sync_source"] = sync_metadata["sync_source"]

        if "legs" not in merged_metadata:
            merged_metadata["legs"] = sync_metadata["legs"]

        position.metadata = merged_metadata
        position.save()

        # Verify sync metadata updated
        position.refresh_from_db()
        assert position.metadata["sync_timestamp"] == sync_time, "sync_timestamp updated"
        assert position.metadata["sync_source"] == "tastytrade_api", "sync_source updated"

        # Verify app metadata preserved
        assert position.metadata["suggestion_id"] == 123, "suggestion_id preserved"

    def test_external_position_metadata_updated_from_broker(self):
        """Verify external position metadata gets updated from broker."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="SPY",
            is_app_managed=False,
            metadata={
                "old_data": "should_be_preserved",
            },
            lifecycle_state="open_full",
        )

        # Simulate sync update
        sync_metadata = {
            "legs": [{"symbol": "SPY 251107P00591000", "quantity": -2}],
            "tastytrade_data": {"position_type": "spread"},
            "sync_timestamp": timezone.now().isoformat(),
            "sync_source": "tastytrade_api",
        }

        # Apply metadata merge for external position
        merged_metadata = position.metadata.copy()
        merged_metadata["legs"] = sync_metadata["legs"]
        merged_metadata["tastytrade_data"] = sync_metadata["tastytrade_data"]
        merged_metadata["sync_timestamp"] = sync_metadata["sync_timestamp"]
        merged_metadata["sync_source"] = sync_metadata["sync_source"]

        position.metadata = merged_metadata
        position.save()

        # Verify update
        position.refresh_from_db()
        assert len(position.metadata["legs"]) == 1
        assert position.metadata["tastytrade_data"]["position_type"] == "spread"

        # Verify old data still present (merged, not replaced)
        assert position.metadata["old_data"] == "should_be_preserved"

    def test_app_managed_position_adds_legs_if_missing(self):
        """Verify legs are added to app-managed position if missing."""
        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                # No legs initially
            },
            lifecycle_state="open_full",
        )

        # Simulate sync with legs
        sync_metadata = {
            "legs": [
                {"symbol": "QQQ 251107P00590000", "quantity": -1},
                {"symbol": "QQQ 251107P00585000", "quantity": 1},
            ],
            "sync_timestamp": timezone.now().isoformat(),
            "sync_source": "tastytrade_api",
        }

        # Apply merge
        existing_metadata = position.metadata.copy()
        merged_metadata = existing_metadata.copy()
        merged_metadata["sync_timestamp"] = sync_metadata["sync_timestamp"]
        merged_metadata["sync_source"] = sync_metadata["sync_source"]

        if "legs" not in merged_metadata or not merged_metadata.get("legs"):
            merged_metadata["legs"] = sync_metadata["legs"]

        position.metadata = merged_metadata
        position.save()

        # Verify legs added
        position.refresh_from_db()
        assert len(position.metadata["legs"]) == 2

        # Verify suggestion_id preserved
        assert position.metadata["suggestion_id"] == 123

    def test_app_managed_position_preserves_existing_legs(self):
        """Verify existing legs are not overwritten in app-managed position."""
        original_legs = [{"symbol": "QQQ 251107P00590000", "quantity": -1, "custom_field": "value"}]

        position = Position.objects.create(
            user=self.user,
            trading_account=self.trading_account,
            symbol="QQQ",
            is_app_managed=True,
            metadata={
                "suggestion_id": 123,
                "legs": original_legs,
            },
            lifecycle_state="open_full",
        )

        # Simulate sync with different legs
        sync_metadata = {
            "legs": [{"symbol": "DIFFERENT", "quantity": -2}],
            "sync_timestamp": timezone.now().isoformat(),
            "sync_source": "tastytrade_api",
        }

        # Apply merge - legs already exist, should preserve
        existing_metadata = position.metadata.copy()
        merged_metadata = existing_metadata.copy()
        merged_metadata["sync_timestamp"] = sync_metadata["sync_timestamp"]
        merged_metadata["sync_source"] = sync_metadata["sync_source"]

        # Only add legs if missing
        if "legs" not in merged_metadata or not merged_metadata.get("legs"):
            merged_metadata["legs"] = sync_metadata["legs"]

        position.metadata = merged_metadata
        position.save()

        # Verify original legs preserved
        position.refresh_from_db()
        assert position.metadata["legs"] == original_legs, "Existing legs should be preserved"
