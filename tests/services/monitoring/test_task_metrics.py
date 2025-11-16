"""Tests for task monitoring decorator."""

import time
from unittest.mock import patch

import pytest

from services.monitoring.task_metrics import monitor_task


class TestMonitorTask:
    """Test monitor_task decorator."""

    def test_successful_task_execution(self):
        """Test decorator logs success metrics for successful task."""

        @monitor_task
        def successful_task():
            return "result"

        with patch("services.monitoring.task_metrics.logger") as mock_logger:
            result = successful_task()

            assert result == "result"
            assert mock_logger.info.call_count == 2
            assert "Task started: successful_task" in str(mock_logger.info.call_args_list[0])
            assert "Task completed: successful_task" in str(mock_logger.info.call_args_list[1])

    def test_failed_task_execution(self):
        """Test decorator logs failure metrics for failed task."""

        @monitor_task
        def failing_task():
            raise ValueError("Test error")

        with patch("services.monitoring.task_metrics.logger") as mock_logger:
            with pytest.raises(ValueError, match="Test error"):
                failing_task()

            assert mock_logger.info.call_count == 1
            assert "Task started: failing_task" in str(mock_logger.info.call_args_list[0])
            assert mock_logger.error.call_count == 1
            assert "Task failed: failing_task" in str(mock_logger.error.call_args_list[0])

    def test_duration_tracking(self):
        """Test decorator tracks task duration."""

        @monitor_task
        def slow_task():
            time.sleep(0.1)
            return "done"

        with patch("services.monitoring.task_metrics.logger") as mock_logger:
            slow_task()

            # Check that success log was called with duration
            success_calls = [
                call for call in mock_logger.info.call_args_list if "Task completed" in str(call)
            ]
            assert len(success_calls) == 1

            # Extract the extra dict from the call
            extra = success_calls[0][1]["extra"]
            assert "duration" in extra
            assert extra["duration"] >= 0.1
            assert extra["status"] == "success"
            assert extra["task_name"] == "slow_task"

    def test_error_details_logged(self):
        """Test decorator logs error details."""

        @monitor_task
        def task_with_error():
            raise RuntimeError("Custom error message")

        with patch("services.monitoring.task_metrics.logger") as mock_logger:
            with pytest.raises(RuntimeError):
                task_with_error()

            # Check that error log was called with details
            error_calls = [
                call for call in mock_logger.error.call_args_list if "Task failed" in str(call)
            ]
            assert len(error_calls) == 1

            # Extract the extra dict
            extra = error_calls[0][1]["extra"]
            assert extra["task_name"] == "task_with_error"
            assert extra["status"] == "failure"
            assert extra["error"] == "Custom error message"
            assert extra["error_type"] == "RuntimeError"
            assert "duration" in extra

    def test_preserves_function_metadata(self):
        """Test decorator preserves original function metadata."""

        @monitor_task
        def my_task():
            """Task docstring."""
            pass

        assert my_task.__name__ == "my_task"
        assert my_task.__doc__ == "Task docstring."

    def test_handles_task_with_arguments(self):
        """Test decorator works with tasks that accept arguments."""

        @monitor_task
        def task_with_args(x, y, z=3):
            return x + y + z

        result = task_with_args(1, 2, z=5)
        assert result == 8

    def test_handles_task_with_return_none(self):
        """Test decorator handles tasks that return None."""

        @monitor_task
        def task_returns_none():
            return None

        with patch("services.monitoring.task_metrics.logger") as mock_logger:
            result = task_returns_none()

            assert result is None
            assert mock_logger.info.call_count == 2
            assert "Task completed: task_returns_none" in str(mock_logger.info.call_args_list[1])
