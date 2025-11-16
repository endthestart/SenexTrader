"""
API views for account-related endpoints.
Phase 6: Account state API for dashboard integration.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from asgiref.sync import sync_to_async

from accounts.models import TradingAccount
from services.account.state import AccountStateService
from services.api.error_responses import ErrorResponseBuilder
from services.core.logging import get_logger
from services.core.utils.async_utils import async_get_user, async_get_user_id

logger = get_logger(__name__)


@login_required
@require_http_methods(["GET"])
async def account_state(request):
    """Get current account state including buying power and balance."""
    try:
        # Async-safe user access - force SimpleLazyObject evaluation
        user = await async_get_user(request)

        # Get primary trading account
        primary = await sync_to_async(
            TradingAccount.objects.filter(user=user, is_primary=True).first
        )()

        if not primary:
            return JsonResponse(
                {
                    "success": False,
                    "error": "No primary trading account configured",
                    "buying_power": None,
                    "balance": None,
                    "data_available": False,
                },
                status=404,
            )

        # Get account state from service
        account_state = await AccountStateService().get(user, primary.account_number)

        if not account_state.get("available", False):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Account data currently unavailable",
                    "message": "Account data service is down or account not accessible",
                    "buying_power": None,
                    "balance": None,
                    "data_available": False,
                },
                status=503,
            )

        # Return account state data
        return JsonResponse(
            {
                "success": True,
                "account_number": primary.account_number,
                "buying_power": account_state.get("buying_power"),
                "balance": account_state.get("balance"),
                "day_trade_buying_power": account_state.get("day_trade_buying_power"),
                "positions_count": len(account_state.get("positions", [])),
                "data_available": True,
                "last_updated": account_state.get("updated_at"),
            }
        )

    except Exception:
        # Try to get user ID safely for logging
        try:
            user_id = await async_get_user_id(request) if hasattr(request, "user") else "unknown"
        except Exception:
            user_id = "unknown"
        logger.exception("Error fetching account state for user %s", user_id)
        return JsonResponse(
            {
                "success": False,
                "error": "Internal error fetching account data",
                "buying_power": None,
                "balance": None,
                "data_available": False,
            },
            status=500,
        )


@login_required
@require_http_methods(["GET"])
async def positions(request):
    """Get current positions for the authenticated user."""
    try:
        # Async-safe user access - force SimpleLazyObject evaluation
        user = await async_get_user(request)

        # Get primary trading account
        primary = await sync_to_async(
            TradingAccount.objects.filter(user=user, is_primary=True).first
        )()

        if not primary:
            return JsonResponse(
                {
                    "success": False,
                    "error": "No primary trading account configured",
                    "positions": [],
                },
                status=404,
            )

        # Get account state from service
        account_state = await AccountStateService().get(user, primary.account_number)

        if not account_state.get("available", False):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Account data currently unavailable",
                    "positions": [],
                },
                status=503,
            )

        # Return positions data
        positions = account_state.get("positions", [])
        return JsonResponse(
            {
                "success": True,
                "account_number": primary.account_number,
                "positions": positions,
                "count": len(positions),
                "data_available": True,
            }
        )

    except Exception:
        # Try to get user ID safely for logging
        try:
            user_id = await async_get_user_id(request) if hasattr(request, "user") else "unknown"
        except Exception:
            user_id = "unknown"
        logger.exception("Error fetching positions for user %s", user_id)
        return JsonResponse(
            {
                "success": False,
                "error": "Internal error fetching positions",
                "positions": [],
            },
            status=500,
        )


@login_required
@require_http_methods(["POST"])
def automated_trading_toggle(request):  # noqa: PLR0911
    """Toggle automated trading for the user's primary account."""
    try:
        data = json.loads(request.body)

        # Get primary trading account
        primary = TradingAccount.objects.filter(user=request.user, is_primary=True).first()

        if not primary:
            return JsonResponse(
                {"success": False, "error": "No primary trading account configured"}, status=404
            )

        if not primary.is_active:
            return JsonResponse(
                {"success": False, "error": "Trading account is not active"}, status=400
            )

        if "is_enabled" in data:
            is_enabled = bool(data.get("is_enabled"))
        else:
            is_enabled = primary.is_automated_trading_enabled

        offset_raw = data.get("offset_cents")
        if offset_raw is None:
            offset_cents = primary.automated_entry_offset_cents
        else:
            try:
                offset_cents = int(offset_raw)
            except (TypeError, ValueError):
                return JsonResponse(
                    {"success": False, "error": "offset_cents must be an integer"},
                    status=400,
                )

            if offset_cents < 0 or offset_cents > 25:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "offset_cents must be between 0 and 25",
                    },
                    status=400,
                )

        # Update the setting
        primary.is_automated_trading_enabled = is_enabled
        primary.automated_entry_offset_cents = offset_cents
        primary.save(update_fields=["is_automated_trading_enabled", "automated_entry_offset_cents"])

        logger.info(
            f"Automated trading {'enabled' if is_enabled else 'disabled'} "
            f"for user {request.user.email} (offset={offset_cents}¢)"
        )

        return JsonResponse(
            {
                "success": True,
                "is_enabled": is_enabled,
                "offset_cents": offset_cents,
                "message": f"Automated trading {'enabled' if is_enabled else 'disabled'}",
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"automated_trading_toggle user={request.user.id}"
        )


@login_required
@require_http_methods(["POST"])
def email_preference(request):
    """Update user email notification preference."""
    try:
        data = json.loads(request.body)
        preference = data.get("email_preference")

        if not preference:
            return JsonResponse(
                {"success": False, "error": "email_preference is required"}, status=400
            )

        # Validate preference value
        valid_preferences = ["none", "immediate", "summary"]
        if preference not in valid_preferences:
            valid_prefs_str = ", ".join(valid_preferences)
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Invalid email_preference. Must be one of: {valid_prefs_str}",
                },
                status=400,
            )

        # Update user preference
        request.user.email_preference = preference
        request.user.save(update_fields=["email_preference"])

        logger.info(f"Email preference updated to '{preference}' for user {request.user.email}")

        return JsonResponse(
            {
                "success": True,
                "email_preference": preference,
                "message": "Email preference updated successfully",
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"email_preference user={request.user.id}"
        )


@login_required
@require_http_methods(["POST"])
def daily_suggestion_toggle(request):
    """Toggle daily trade suggestion email for the user."""
    try:
        data = json.loads(request.body)
        is_enabled = bool(data.get("is_enabled", False))

        # Check if user has email disabled
        if request.user.email_preference == "none" and is_enabled:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Cannot enable daily suggestions when email preference is set to 'No Emails'",
                },
                status=400,
            )

        # Update the setting
        request.user.email_daily_trade_suggestion = is_enabled
        request.user.save(update_fields=["email_daily_trade_suggestion"])

        logger.info(
            f"Daily trade suggestion email {'enabled' if is_enabled else 'disabled'} "
            f"for user {request.user.email}"
        )

        return JsonResponse(
            {
                "success": True,
                "is_enabled": is_enabled,
                "message": f"Daily trade suggestion email {'enabled' if is_enabled else 'disabled'}",
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"daily_suggestion_toggle user={request.user.id}"
        )


@login_required
@require_http_methods(["POST"])
def privacy_mode_toggle(request):
    """Toggle privacy mode for the user's primary account."""
    try:
        data = json.loads(request.body)
        is_enabled = bool(data.get("is_enabled", False))

        primary = TradingAccount.objects.filter(user=request.user, is_primary=True).first()

        if not primary:
            return JsonResponse(
                {"success": False, "error": "No primary trading account configured"}, status=404
            )

        primary.privacy_mode = is_enabled
        primary.save(update_fields=["privacy_mode"])

        logger.info(
            f"Privacy mode {'enabled' if is_enabled else 'disabled'} for user {request.user.email}"
        )

        return JsonResponse(
            {
                "success": True,
                "is_enabled": is_enabled,
                "message": f"Privacy mode {'enabled' if is_enabled else 'disabled'}",
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"privacy_mode_toggle user={request.user.id}"
        )
