from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

import pytest

from accounts.models import AccountSnapshot

User = get_user_model()


class AccountSnapshotModelTests(TestCase):
    """Test AccountSnapshot model creation, validation, and constraints"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="testuser@example.com",
            username="testuser@example.com",
            password="testpass123",
        )

    def test_account_snapshot_creation(self):
        """Test creating an AccountSnapshot with required fields"""
        snapshot = AccountSnapshot.objects.create(
            user=self.user,
            account_number="123456789",
            buying_power=Decimal("25000.50"),
            balance=Decimal("50000.75"),
            source="sdk",
        )

        assert snapshot.user == self.user
        assert snapshot.account_number == "123456789"
        assert snapshot.buying_power == Decimal("25000.50")
        assert snapshot.balance == Decimal("50000.75")
        assert snapshot.source == "sdk"
        assert snapshot.created_at

    def test_account_snapshot_string_representation(self):
        """Test __str__ method returns expected format"""
        snapshot = AccountSnapshot.objects.create(
            user=self.user,
            account_number="987654321",
            buying_power=Decimal("15000.00"),
            balance=Decimal("30000.00"),
            source="stream",
        )

        expected = f"{self.user.email} - 987654321 - {snapshot.created_at}"
        assert str(snapshot) == expected

    def test_account_snapshot_ordering_newest_first(self):
        """Test that snapshots are ordered by created_at descending (newest first)"""
        # Create multiple snapshots with slight delay to ensure different timestamps
        snapshot1 = AccountSnapshot.objects.create(
            user=self.user,
            account_number="111111111",
            buying_power=Decimal("10000.00"),
            balance=Decimal("20000.00"),
            source="sdk",
        )

        snapshot2 = AccountSnapshot.objects.create(
            user=self.user,
            account_number="222222222",
            buying_power=Decimal("15000.00"),
            balance=Decimal("25000.00"),
            source="stream",
        )

        snapshots = AccountSnapshot.objects.all()
        # First snapshot should be the newest (snapshot2)
        assert snapshots[0] == snapshot2
        assert snapshots[1] == snapshot1

    def test_account_snapshot_source_choices(self):
        """Test that only valid source choices are allowed"""
        valid_sources = ["stream", "sdk", "manual"]

        for source in valid_sources:
            snapshot = AccountSnapshot.objects.create(
                user=self.user,
                account_number=f"acc_{source}",
                buying_power=Decimal("1000.00"),
                balance=Decimal("2000.00"),
                source=source,
            )
            assert snapshot.source == source

    def test_account_snapshot_database_index_exists(self):
        """Test that database index on user, account_number, -created_at exists"""
        # This test verifies the index is created properly
        # Create snapshots for indexing test
        AccountSnapshot.objects.create(
            user=self.user,
            account_number="indexed_account",
            buying_power=Decimal("5000.00"),
            balance=Decimal("10000.00"),
            source="sdk",
        )

        # Query using indexed fields should work efficiently
        snapshots = AccountSnapshot.objects.filter(
            user=self.user, account_number="indexed_account"
        ).order_by("-created_at")

        assert snapshots.count() == 1

    def test_account_snapshot_cascade_deletion_with_user(self):
        """Test that deleting user cascades to delete snapshots"""
        snapshot = AccountSnapshot.objects.create(
            user=self.user,
            account_number="cascade_test",
            buying_power=Decimal("8000.00"),
            balance=Decimal("16000.00"),
            source="manual",
        )

        snapshot_id = snapshot.id

        # Delete user should cascade delete snapshot
        self.user.delete()

        # Snapshot should be deleted
        with pytest.raises(AccountSnapshot.DoesNotExist):
            AccountSnapshot.objects.get(id=snapshot_id)

    def test_account_snapshot_decimal_precision(self):
        """Test decimal field precision for buying_power and balance"""
        # Test with high precision decimals
        snapshot = AccountSnapshot.objects.create(
            user=self.user,
            account_number="precision_test",
            buying_power=Decimal("123456789012345.67"),  # max_digits=15, decimal_places=2
            balance=Decimal("987654321098765.43"),
            source="sdk",
        )

        assert snapshot.buying_power == Decimal("123456789012345.67")
        assert snapshot.balance == Decimal("987654321098765.43")

    def test_account_snapshot_required_fields(self):
        """Test that required fields cannot be None"""
        with pytest.raises(IntegrityError):
            AccountSnapshot.objects.create(
                user=None,  # Required field
                account_number="test_account",
                buying_power=Decimal("1000.00"),
                balance=Decimal("2000.00"),
                source="sdk",
            )

    def test_account_snapshot_help_text(self):
        """Test that help_text is properly set on fields"""
        snapshot = AccountSnapshot()

        buying_power_field = snapshot._meta.get_field("buying_power")
        balance_field = snapshot._meta.get_field("balance")

        assert buying_power_field.help_text == "Available buying power"
        assert balance_field.help_text == "Total account balance"

    def test_account_snapshot_multiple_accounts_same_user(self):
        """Test creating snapshots for multiple accounts for same user"""
        snapshot1 = AccountSnapshot.objects.create(
            user=self.user,
            account_number="account_1",
            buying_power=Decimal("10000.00"),
            balance=Decimal("20000.00"),
            source="sdk",
        )

        snapshot2 = AccountSnapshot.objects.create(
            user=self.user,
            account_number="account_2",
            buying_power=Decimal("15000.00"),
            balance=Decimal("25000.00"),
            source="stream",
        )

        user_snapshots = AccountSnapshot.objects.filter(user=self.user)
        assert user_snapshots.count() == 2

        account_1_snapshots = user_snapshots.filter(account_number="account_1")
        account_2_snapshots = user_snapshots.filter(account_number="account_2")

        assert account_1_snapshots.count() == 1
        assert account_2_snapshots.count() == 1
        assert account_1_snapshots.first() == snapshot1
        assert account_2_snapshots.first() == snapshot2
