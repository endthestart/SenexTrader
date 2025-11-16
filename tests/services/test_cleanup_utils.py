"""Tests for cleanup utilities."""

from datetime import timedelta
from unittest.mock import MagicMock

from django.utils import timezone

from services.account.utils.cleanup_utils import cleanup_old_records


class TestCleanupUtils:
    """Test cleanup utility functions."""

    def test_cleanup_old_records_success(self):
        """Test successful cleanup of old records."""
        # Mock model and queryset
        mock_model = MagicMock()
        mock_queryset = MagicMock()
        mock_model.objects.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 5
        mock_queryset.delete.return_value = (5, {})

        result = cleanup_old_records(
            model=mock_model,
            days=30,
            statuses=["completed", "cancelled"],
            date_field="created_at",
            record_type="test_records",
        )

        assert result["status"] == "success"
        assert result["deleted"] == 5
        mock_queryset.delete.assert_called_once()

    def test_cleanup_old_records_no_records(self):
        """Test cleanup when no old records exist."""
        mock_model = MagicMock()
        mock_queryset = MagicMock()
        mock_model.objects.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0

        result = cleanup_old_records(
            model=mock_model,
            days=30,
            statuses=["completed"],
            date_field="created_at",
            record_type="test_records",
        )

        assert result["status"] == "success"
        assert result["deleted"] == 0
        mock_queryset.delete.assert_not_called()

    def test_cleanup_old_records_error_handling(self):
        """Test error handling during cleanup."""
        mock_model = MagicMock()
        mock_model.objects.filter.side_effect = Exception("Database error")

        result = cleanup_old_records(
            model=mock_model,
            days=30,
            statuses=["completed"],
            date_field="created_at",
            record_type="test_records",
        )

        assert result["status"] == "error"
        assert "Database error" in result["message"]

    def test_cleanup_old_records_date_field_parameter(self):
        """Test that date_field parameter is used correctly."""
        mock_model = MagicMock()
        mock_queryset = MagicMock()
        mock_model.objects.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0

        cleanup_old_records(
            model=mock_model,
            days=90,
            statuses=["expired"],
            date_field="updated_at",
            record_type="test_records",
        )

        # Verify filter was called with updated_at field
        filter_kwargs = mock_model.objects.filter.call_args[1]
        assert "updated_at__lt" in filter_kwargs

    def test_cleanup_old_records_uses_correct_cutoff_date(self):
        """Test that cleanup uses correct cutoff date calculation."""
        mock_model = MagicMock()
        mock_queryset = MagicMock()
        mock_model.objects.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0

        cleanup_old_records(
            model=mock_model,
            days=45,
            statuses=["expired"],
            date_field="created_at",
            record_type="test_records",
        )

        # Verify filter was called with cutoff date in the right format
        filter_kwargs = mock_model.objects.filter.call_args[1]
        assert "created_at__lt" in filter_kwargs

        # Verify cutoff date is approximately 45 days ago (within 2 seconds)
        cutoff = filter_kwargs["created_at__lt"]
        expected_cutoff = timezone.now() - timedelta(days=45)
        assert abs((expected_cutoff - cutoff).total_seconds()) < 2

    def test_cleanup_old_records_status_filtering(self):
        """Test that status filtering works correctly."""
        mock_model = MagicMock()
        mock_queryset = MagicMock()
        mock_model.objects.filter.return_value = mock_queryset
        mock_queryset.count.return_value = 0

        statuses_to_clean = ["completed", "cancelled", "expired"]

        cleanup_old_records(
            model=mock_model,
            days=30,
            statuses=statuses_to_clean,
            date_field="created_at",
            record_type="test_records",
        )

        # Verify filter was called with correct statuses
        filter_kwargs = mock_model.objects.filter.call_args[1]
        assert filter_kwargs["status__in"] == statuses_to_clean
