# services/utils/async_utils.py
from asgiref.sync import async_to_sync, sync_to_async


@async_to_sync
async def run_async_in_new_loop(coro):
    """
    Runs a coroutine in a new event loop, making it safe to call from
    a sync context that may or may not have a running loop.
    """
    return await coro


# Simplified alias for clarity
run_async = run_async_in_new_loop


async def async_get_user(request):
    """
    Safely get the authenticated user from a request in async context.

    Returns the user object if authenticated, None otherwise.
    Handles Django's SimpleLazyObject evaluation safely.

    Args:
        request: Django HttpRequest object

    Returns:
        User object if authenticated, None otherwise
    """
    return await sync_to_async(lambda: request.user if request.user.is_authenticated else None)()


async def async_get_user_id(request):
    """
    Safely get the authenticated user's ID from a request in async context.

    Handles Django's SimpleLazyObject evaluation safely.

    Args:
        request: Django HttpRequest object

    Returns:
        User ID (int)

    Raises:
        AttributeError: If user is not authenticated
    """
    return await sync_to_async(lambda: request.user.id)()
