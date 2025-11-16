"""Streaming views for monitoring and management.

Provides health checks and status endpoints for the streaming infrastructure.
"""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView

from services.core.utils.async_utils import async_get_user_id
from streaming.services.enhanced_cache import enhanced_cache


class WebSocketTestView(LoginRequiredMixin, TemplateView):
    """Simple test view for WebSocket connections."""

    template_name = "streaming/test.html"


@method_decorator(login_required, name="dispatch")
class SessionStatusView(View):
    """API endpoint for checking streaming session status.

    Works with the simplified POC architecture using GlobalStreamManager.
    """

    async def get(self, request):
        """Get current session status."""
        try:
            from streaming.services.stream_manager import GlobalStreamManager

            # Async-safe user access - force SimpleLazyObject evaluation
            user_id = await async_get_user_id(request)
            global_manager = GlobalStreamManager()

            # Check if user has an active manager
            if user_id in GlobalStreamManager._user_managers:
                user_manager = await global_manager.get_user_manager(user_id)
                status = await user_manager.get_status()

                response_data = {
                    "status": "active" if status["is_streaming"] else "inactive",
                    "is_streaming": status["is_streaming"],
                    "connection_count": status["connection_count"],
                    "subscribed_symbols": status["subscribed_symbols"],
                    "last_activity": status["last_activity"],
                    "message": (
                        "Streaming active"
                        if status["is_streaming"]
                        else "Manager exists but not streaming"
                    ),
                }
            else:
                response_data = {
                    "status": "inactive",
                    "is_streaming": False,
                    "connection_count": 0,
                    "subscribed_symbols": [],
                    "message": "No active streaming session",
                }

            return JsonResponse(response_data)

        except Exception as e:
            return JsonResponse(
                {
                    "status": "error",
                    "error": f"Failed to get session status: {e!s}",
                    "message": "Internal error checking session status",
                }
            )


@method_decorator(login_required, name="dispatch")
class SessionControlView(View):
    """API endpoint for controlling streaming sessions.

    Works with the simplified POC architecture using GlobalStreamManager.
    """

    async def post(self, request):
        """Handle session control actions."""
        try:
            from streaming.services.stream_manager import GlobalStreamManager

            action = request.POST.get("action")
            # Async-safe user access - force SimpleLazyObject evaluation
            user_id = await async_get_user_id(request)

            if action == "terminate":
                # Terminate current session
                await GlobalStreamManager.remove_user_manager(user_id)

                return JsonResponse({"success": True, "message": "Session terminated successfully"})

            if action == "refresh_status":
                # Get current status
                global_manager = GlobalStreamManager()

                if user_id in GlobalStreamManager._user_managers:
                    user_manager = await global_manager.get_user_manager(user_id)
                    status = await user_manager.get_status()
                    return JsonResponse(
                        {
                            "success": True,
                            "status": ("active" if status["is_streaming"] else "inactive"),
                            "message": (
                                "Streaming is active"
                                if status["is_streaming"]
                                else "Manager exists but not streaming"
                            ),
                            "info": status,
                        }
                    )
                return JsonResponse(
                    {
                        "success": True,
                        "status": "inactive",
                        "message": "No active streaming session",
                    }
                )

            return JsonResponse({"success": False, "message": f"Unknown action: {action}"})

        except Exception as e:
            return JsonResponse({"success": False, "message": f"Action failed: {e!s}"})


class StreamingHealthView(View):
    """Public health check endpoint for streaming infrastructure.

    Returns overall streaming system health without requiring authentication.
    Safe to expose for monitoring systems.
    """

    async def get(self, request):
        """Get streaming system health status."""
        try:
            from streaming.services.stream_manager import GlobalStreamManager

            global_manager = GlobalStreamManager()

            # Get overall system status
            total_users = len(global_manager._user_managers)

            # Count active streaming users
            active_streaming_users = 0
            total_connections = 0

            for _user_id, manager in global_manager._user_managers.items():
                total_connections += manager.context.reference_count
                if manager.is_streaming:
                    active_streaming_users += 1

            # Determine overall health
            if total_users == 0:
                status = "healthy"
                message = "No active users - system ready"
            elif active_streaming_users > 0:
                status = "healthy"
                message = f"Streaming active for {active_streaming_users} users"
            else:
                status = "degraded"
                message = f"{total_users} connected users but no active streaming"

            response_data = {
                "status": status,
                "timestamp": request.META.get("HTTP_DATE", "unknown"),
                "version": "simplified-v1",
                "metrics": {
                    "total_users": total_users,
                    "active_streaming_users": active_streaming_users,
                    "total_connections": total_connections,
                },
                "message": message,
            }

            return JsonResponse(response_data)

        except Exception as e:
            # Even health checks should be resilient
            return JsonResponse(
                {
                    "status": "error",
                    "timestamp": request.META.get("HTTP_DATE", "unknown"),
                    "version": "simplified-v1",
                    "error": str(e),
                    "message": "Health check failed - system may be degraded",
                },
                status=500,
            )


@method_decorator(login_required, name="dispatch")
class CacheMonitorView(View):
    """Cache performance monitoring endpoint.

    Provides cache statistics and performance metrics for monitoring
    and debugging cache operations.
    """

    async def get(self, request):
        """Get cache performance statistics."""
        try:
            # Get cache statistics
            cache_stats = enhanced_cache.get_stats()

            # Add cache health assessment
            hit_rate = cache_stats.get("hit_rate", 0)
            avg_latency = cache_stats.get("average_latency_ms", 0)
            error_count = cache_stats.get("errors", 0)
            total_ops = cache_stats.get("total_operations", 0)

            # Determine cache health
            if total_ops == 0:
                health = "unknown"
                health_message = "No cache operations recorded yet"
            elif error_count > 0 and (error_count / total_ops) > 0.1:  # >10% error rate
                health = "unhealthy"
                health_message = f"High error rate: {error_count}/{total_ops} operations failed"
            elif hit_rate < 50.0:  # Low hit rate
                health = "degraded"
                health_message = f"Low cache hit rate: {hit_rate:.1f}%"
            elif avg_latency > 100.0:  # High latency
                health = "degraded"
                health_message = f"High cache latency: {avg_latency:.1f}ms average"
            else:
                health = "healthy"
                health_message = (
                    f"Cache performing well: {hit_rate:.1f}% hit rate, "
                    f"{avg_latency:.1f}ms avg latency"
                )

            response_data = {
                "status": "success",
                "timestamp": request.META.get("HTTP_DATE", "unknown"),
                "cache_health": health,
                "cache_message": health_message,
                "statistics": cache_stats,
                "recommendations": [],
            }

            # Add performance recommendations
            if hit_rate < 70.0:
                response_data["recommendations"].append(
                    "Consider increasing cache TTL for frequently accessed data"
                )
            if avg_latency > 50.0:
                response_data["recommendations"].append(
                    "Consider cache backend optimization or adding more cache servers"
                )
            if error_count > 0:
                response_data["recommendations"].append(
                    "Investigate cache connection issues or backend problems"
                )

            return JsonResponse(response_data)

        except Exception as e:
            return JsonResponse(
                {
                    "status": "error",
                    "timestamp": request.META.get("HTTP_DATE", "unknown"),
                    "error": str(e),
                    "message": "Failed to retrieve cache statistics",
                },
                status=500,
            )

    async def post(self, request):
        """Reset cache statistics."""
        try:
            enhanced_cache.reset_stats()
            return JsonResponse(
                {"status": "success", "message": "Cache statistics reset successfully"}
            )
        except Exception as e:
            return JsonResponse(
                {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to reset cache statistics",
                },
                status=500,
            )
