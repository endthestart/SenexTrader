"""Streaming models module - simplified architecture.

The new streaming architecture uses in-memory contexts instead of database models.
NO BACKWARD COMPATIBILITY - following SIMPLICITY FIRST principle.
"""

# Import only the new model from stream_context.py
from .stream_context import UserStreamContext

__all__ = ["UserStreamContext"]
