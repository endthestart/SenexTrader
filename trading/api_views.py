"""
Trading API views for business logic endpoints.
Implements server-side business logic that was previously in JavaScript.

Following CLAUDE.md principles:
- Business logic in service layer, not frontend
- Simple, direct API implementations without unnecessary dependencies
- Proper error handling and validation
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from services.api.error_responses import ErrorResponseBuilder
from services.core.logging import get_logger
from services.core.utils.async_utils import async_get_user, async_get_user_id
from services.execution.validators.execution_validator import ExecutionValidator
from services.risk.manager import EnhancedRiskManager
from services.risk.validation import RiskValidationService

logger = get_logger(__name__)


@login_required
@require_http_methods(["POST"])
async def validate_trade_risk(request):
    """
    Validate trade risk against available budget and utilization.

    Replaces the JavaScript validateRiskBudget method with proper
    server-side business logic.

    POST /trading/api/validate-trade-risk/
    Body: {"suggestion_id": "123"}

    Returns:
    {
        "valid": true/false,
        "message": "error message if invalid",
        "warning": "warning message if high utilization",
        "current_utilization": 45.2,
        "new_utilization": 67.8,
        "position_risk": 500.00,
        "remaining_budget": 1500.00
    }
    """
    try:
        # Async-safe user access (wraps synchronous lazy loading)
        user_id = await async_get_user_id(request)

        # Parse JSON body
        data = json.loads(request.body)
        suggestion_id = data.get("suggestion_id")

        if not suggestion_id:
            return JsonResponse(
                {"valid": False, "message": "Missing suggestion_id parameter"}, status=400
            )

        # Validate trade risk using service
        # Force SimpleLazyObject evaluation by accessing is_authenticated
        user = await async_get_user(request)
        validation_result = await RiskValidationService.validate_trade_risk(
            user=user, suggestion_id=suggestion_id
        )

        # Return appropriate status code based on validation result
        response_status = 200 if validation_result["valid"] else 400

        status_text = "valid" if validation_result["valid"] else "invalid"
        logger.info(
            f"Risk validation for user {user_id}, suggestion {suggestion_id}: {status_text}"
        )

        return JsonResponse(validation_result, status=response_status)

    except json.JSONDecodeError:
        return JsonResponse({"valid": False, "message": "Invalid JSON in request body"}, status=400)
    except Exception as e:
        try:
            user_id = await async_get_user_id(request)
        except Exception:
            user_id = "unknown"
        logger.error(f"Error in validate_trade_risk API for user {user_id}: {e}")
        return JsonResponse(
            {
                "valid": False,
                "message": f"Risk validation failed: {e!s}. Trade execution blocked for safety.",
            },
            status=500,
        )


@ensure_csrf_cookie
@login_required
@require_http_methods(["GET"])
async def get_risk_budget(request):
    """
    Get current risk budget and utilization.

    Now uses the consolidated EnhancedRiskManager.get_risk_budget_data() method
    following DRY principle - single source of truth for risk calculations.
    FAILS CLEARLY when account data unavailable - never guesses
    """
    # Force SimpleLazyObject evaluation by accessing is_authenticated
    user = await async_get_user(request)

    # Check if user has a configured primary trading account before attempting risk calculations
    from services.core.data_access import has_configured_primary_account

    if not await has_configured_primary_account(user):
        # Return 200 with success=False to avoid error logging for expected condition
        # This is a business logic state (no account), not an HTTP error
        return JsonResponse(
            {
                "success": False,
                "error": "No primary trading account configured",
                "message": (
                    "Cannot calculate risk budget without a connected brokerage account. "
                    "Please connect your trading account in Settings."
                ),
                "data_available": False,
            },
            status=200,
        )

    risk_manager = EnhancedRiskManager(user)
    is_stressed = request.GET.get("stressed", "false").lower() == "true"

    # Use the new consolidated method - all logic is in one place
    data = await risk_manager.a_get_risk_budget_data(is_stressed)

    if not data.get("data_available"):
        return JsonResponse(
            {
                "success": False,
                "error": data.get("error", "Risk calculations unavailable"),
                "message": (
                    "Cannot calculate risk budget without real account data. No estimates provided."
                ),
                "data_available": False,
            },
            status=503,
        )

    # Add formatted display values for UI presentation
    from services.sdk.trading_utils import format_currency_for_display

    data.update(
        {
            "success": True,
            "tradeable_capital_display": format_currency_for_display(data["tradeable_capital"]),
            "strategy_power_display": format_currency_for_display(data["strategy_power"]),
            "current_risk_display": format_currency_for_display(data["current_risk"]),
            "remaining_budget_display": format_currency_for_display(data["remaining_budget"]),
        }
    )

    return JsonResponse(data)


@login_required
@require_http_methods(["GET"])
async def check_streamer_readiness(request):
    """
    Check if the streaming infrastructure is ready with account balance data.
    Returns: {"ready": bool, "account_ready": bool, "data_ready": bool, "details": dict}
    """
    from django.core.cache import cache

    from streaming.services.stream_manager import GlobalStreamManager

    try:
        # Async-safe user access - force SimpleLazyObject evaluation
        user = await async_get_user(request)
        user_id = await async_get_user_id(request)

        # Get primary account asynchronously
        primary_account = await user.trading_accounts.filter(is_primary=True).afirst()

        if not primary_account:
            return JsonResponse(
                {
                    "ready": False,
                    "account_ready": False,
                    "data_ready": False,
                    "message": "No primary trading account configured",
                    "details": {"error": "account_not_found"},
                }
            )

        # Check if streaming account data is available in cache
        cache_key = f"acct_state:{user_id}:{primary_account.account_number}"
        cached_state = cache.get(cache_key)

        account_ready = False
        account_details = {}

        if cached_state and cached_state.get("available"):
            buying_power = cached_state.get("buying_power")
            balance = cached_state.get("balance")

            if buying_power is not None and balance is not None:
                # Don't require non-zero values - zero is valid
                account_ready = True
                account_details = {
                    "buying_power": buying_power,
                    "balance": balance,
                    "source": cached_state.get("source", "unknown"),
                }

        # Check if data streamer is active and has received data
        data_ready = False
        try:
            manager = await GlobalStreamManager.get_user_manager(user_id)
            if manager and manager.is_streaming:
                # Only return ready if we've actually received streaming data
                data_ready = manager.has_received_data
        except Exception as e:
            logger.debug(f"Could not check streamer status: {e}")

        # Overall readiness requires both
        ready = account_ready and data_ready

        return JsonResponse(
            {
                "ready": ready,
                "account_ready": account_ready,
                "data_ready": data_ready,
                "message": f"Streamer {'ready' if ready else 'initializing'}",
                "details": {
                    **account_details,
                    "account_number": primary_account.account_number,
                    "cache_key": cache_key,
                },
            }
        )

    except Exception as e:
        try:
            user_id = await async_get_user_id(request)
        except Exception:
            user_id = "unknown"
        logger.error(
            f"Error checking streamer readiness for user {user_id}: {e}", exc_info=True
        )
        return JsonResponse(
            {
                "ready": False,
                "account_ready": False,
                "data_ready": False,
                "message": f"Error checking streamer status: {e!s}",
                "details": {"error": "exception_occurred"},
            },
            status=500,
        )


# Dynamic Strategy API Endpoints (Phase 2)


@login_required
@require_http_methods(["POST"])
async def generate_suggestion(request, strategy):
    """
    Generate trading suggestion for given strategy.
    Dynamic strategy support - not hardcoded to "senex".
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    try:
        data = json.loads(request.body)
        symbol = data.get("symbol", "QQQ")

        # Normalize strategy name (convert dashes to underscores for internal use)
        strategy_key = strategy.replace("-", "_")

        # Dynamic strategy lookup via registry
        from services.strategies.registry import get_strategy, is_strategy_registered

        if not is_strategy_registered(strategy_key):
            return JsonResponse(
                {"success": False, "error": f"Unknown strategy: {strategy}"}, status=400
            )

        strategy_service = get_strategy(strategy_key, user)

        # Trigger async generation via existing service
        # This will use the stream manager and send results via WebSocket
        await strategy_service.a_request_suggestion_generation()

        logger.info(
            f"Suggestion generation triggered for user {user_id}, "
            f"strategy {strategy_key}, symbol {symbol}"
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Suggestion generation started. Results will arrive via WebSocket.",
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(e, context=f"generate_suggestion user={user_id}")


@login_required
@require_http_methods(["POST"])
async def execute_suggestion(request, suggestion_id):
    """
    Single endpoint for approve + execute (not separate steps).
    Validates risk budget before execution.
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    try:
        import json

        from services.execution.order_service import OrderExecutionService
        from trading.models import TradingSuggestion

        # Parse request body for custom parameters
        custom_credit_raw = None
        if request.body:
            try:
                data = json.loads(request.body)
                custom_credit_raw = data.get("custom_credit")
            except (json.JSONDecodeError, ValueError) as e:
                return ErrorResponseBuilder.from_exception(
                    e, context=f"execute_suggestion parse_body user={user_id}", log_level="warning"
                )

        # Validate custom credit using utility
        custom_credit, error = ExecutionValidator.validate_custom_credit(custom_credit_raw)
        if error:
            logger.warning(f"Credit validation failed for user {user_id}: {error}")
            return ErrorResponseBuilder.validation_error(error)

        # Get suggestion with optimized query (avoid N+1) - user filter ensures ownership
        try:
            suggestion = await TradingSuggestion.objects.select_related(
                "strategy_configuration", "user"
            ).aget(id=suggestion_id, user=user, status="pending")
        except TradingSuggestion.DoesNotExist:
            # Custom message because it's not just "not found" - could also be wrong status
            return JsonResponse(
                {"success": False, "error": "Suggestion not found or not in pending status"},
                status=404,
            )

        # Validate risk budget (reuse existing service)
        validation = await RiskValidationService.validate_trade_risk(
            user=user, suggestion_id=suggestion_id
        )
        if not validation["valid"]:
            return JsonResponse(
                {"success": False, "error": validation["message"], "risk_validation": validation},
                status=400,
            )

        # Check market hours before execution
        from services.sdk.trading_utils import is_market_open_now

        if not is_market_open_now():
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Cannot execute trades outside market hours "
                        "(9:30 AM - 4:00 PM ET, Monday-Friday)"
                    ),
                },
                status=400,
            )

        # Mark approved ONLY after validation passes
        suggestion.status = "approved"
        await suggestion.asave(update_fields=["status"])

        # Execute via existing service
        service = OrderExecutionService(user)
        try:
            result = await service.execute_suggestion_async(suggestion, custom_credit=custom_credit)

            from services.execution.order_service import DryRunResult

            if isinstance(result, DryRunResult):
                # Revert suggestion status back to pending (dry-run didn't create position)
                suggestion.status = "pending"
                await suggestion.asave(update_fields=["status"])

                logger.info(
                    f"DRY-RUN: Suggestion {suggestion_id} validated for user {user_id} "
                    "(status reverted to pending)"
                )
                return JsonResponse(
                    {
                        "success": True,
                        "dry_run": True,
                        "message": result.message,
                        "simulated_order": {
                            "order_id": result.order_id,
                            "legs": result.legs,
                            "expected_credit": str(result.expected_credit),
                            "status": result.simulated_status,
                            "strategy_type": result.strategy_type,
                            "would_create_profit_targets": result.would_create_profit_targets,
                        },
                        "buying_power_effect": result.buying_power_effect,
                        "fee_calculation": result.fee_calculation,
                    }
                )

            position = result
            # Success!
            logger.info(f"Successfully executed suggestion {suggestion_id} for user {user_id}")
            # Get trade_id asynchronously
            first_trade = await position.trades.afirst()
            trade_id = first_trade.id if first_trade else None

            return JsonResponse(
                {
                    "success": True,
                    "position_id": position.id,
                    "trade_id": trade_id,
                    "message": "Trade submitted to broker successfully",
                }
            )

        except Exception as e:
            # Import exception classes for specific error handling
            from services.execution.order_service import (
                InvalidPriceEffectError,
                NoAccountError,
                OAuthSessionError,
                OrderBuildError,
                OrderPlacementError,
                StalePricingError,
            )

            # Reset status to pending so user can retry
            suggestion.status = "pending"
            await suggestion.asave(update_fields=["status"])
            logger.error(f"Execution failed for suggestion {suggestion_id}: {e}", exc_info=True)

            # Map exceptions to structured error responses
            error_responses = {
                StalePricingError: {
                    "error_type": "stale_pricing",
                    "error": str(e),
                    "action": "generate_new",
                    "retryable": False,
                },
                NoAccountError: {
                    "error_type": "no_account",
                    "error": str(e),
                    "action": "configure_account",
                    "retryable": False,
                },
                OAuthSessionError: {
                    "error_type": "oauth_failed",
                    "error": str(e),
                    "action": "reconnect_account",
                    "retryable": True,
                },
                OrderBuildError: {
                    "error_type": "order_build_failed",
                    "error": str(e),
                    "action": "contact_support",
                    "retryable": False,
                },
                InvalidPriceEffectError: {
                    "error_type": "invalid_pricing",
                    "error": str(e),
                    "action": "generate_new",
                    "retryable": False,
                },
                OrderPlacementError: {
                    "error_type": "order_placement_failed",
                    "error": str(e),
                    "action": "retry",
                    "retryable": True,
                },
            }

            # Find matching error response
            for exception_class, response_data in error_responses.items():
                if isinstance(e, exception_class):
                    return JsonResponse(
                        {"success": False, **response_data},
                        status=400,  # Client error
                    )

            # Generic error fallback
            return JsonResponse(
                {
                    "success": False,
                    "error_type": "execution_error",
                    "error": f"Execution error: {e!s}",
                    "action": "retry",
                    "retryable": True,
                },
                status=500,
            )

    except Exception as e:
        # Try to reset suggestion status if it got stuck
        try:
            suggestion_reset = await TradingSuggestion.objects.aget(id=suggestion_id)
            if suggestion_reset.status == "approved":
                suggestion_reset.status = "pending"
                await suggestion_reset.asave(update_fields=["status"])
                logger.info(f"Reset suggestion {suggestion_id} back to pending after error")
        except Exception:
            pass  # Don't fail the error response if reset fails

        return ErrorResponseBuilder.from_exception(
            e, context=f"execute_suggestion user={user_id} suggestion={suggestion_id}"
        )


@login_required
@require_http_methods(["POST"])
async def reject_suggestion(request, suggestion_id):
    """
    Reject a trading suggestion with optional reason.
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    try:
        from trading.models import TradingSuggestion

        # Parse optional rejection reason
        try:
            data = json.loads(request.body)
            reason = data.get("reason", "User rejected")
        except json.JSONDecodeError:
            reason = "User rejected"

        # Get suggestion - user filter ensures ownership
        try:
            suggestion = await TradingSuggestion.objects.aget(
                id=suggestion_id, user=user, status="pending"
            )
        except TradingSuggestion.DoesNotExist:
            # Custom message because it's not just "not found" - could also be wrong status
            return JsonResponse(
                {"success": False, "error": "Suggestion not found or not in pending status"},
                status=404,
            )

        # Update suggestion status
        suggestion.status = "rejected"
        suggestion.rejection_reason = reason
        await suggestion.asave(update_fields=["status", "rejection_reason"])

        logger.info(f"Suggestion {suggestion_id} rejected by user {user_id}: {reason}")

        return JsonResponse({"success": True, "message": "Suggestion rejected successfully"})

    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"reject_suggestion user={user_id} suggestion={suggestion_id}"
        )


@login_required
@require_http_methods(["GET"])
async def get_order_status(request, order_id):
    """
    Get current status of an order by ID.
    Checks both database and broker API if needed.
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    try:
        from trading.models import Trade

        # Phase 4.2: Find trade with optimized query (avoid N+1)
        try:
            trade = await Trade.objects.select_related("position", "trading_account", "user").aget(
                broker_order_id=order_id, user=user
            )
        except Trade.DoesNotExist:
            return ErrorResponseBuilder.not_found("Order")

        # Return current status from database
        # The stream manager should be keeping this up to date
        # Get position symbol asynchronously
        position_symbol = (await trade.position).symbol

        return JsonResponse(
            {
                "success": True,
                "order_id": order_id,
                "trade_id": trade.id,
                "status": trade.status,
                "position_symbol": position_symbol,
                "submitted_at": trade.submitted_at.isoformat() if trade.submitted_at else None,
                "filled_at": trade.filled_at.isoformat() if trade.filled_at else None,
                "fill_price": float(trade.fill_price) if trade.fill_price else None,
            }
        )

    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"get_order_status order={order_id} user={user_id}"
        )


@login_required
@require_http_methods(["GET"])
def get_pending_orders(request):
    """
    Get all pending orders for the user.
    Used for page load to show existing pending orders.
    """
    try:
        from trading.models import Trade

        # Phase 4.2: Get pending trades with optimized query (avoid N+1)
        # Include all TastyTrade working statuses: submitted, routed, live, working
        pending_trades = list(
            Trade.objects.filter(
                user=request.user, status__in=["pending", "submitted", "routed", "live", "working"]
            )
            .select_related("position", "trading_account")
            .order_by("-submitted_at")
        )

        # Format for response
        orders = []
        for trade in pending_trades:
            orders.append(
                {
                    "trade_id": trade.id,
                    "order_id": trade.broker_order_id,
                    "symbol": trade.position.symbol,
                    "trade_type": trade.trade_type,
                    "status": trade.status,
                    "status_display": trade.get_status_display(),
                    "quantity": trade.quantity,
                    "submitted_at": trade.submitted_at.isoformat() if trade.submitted_at else None,
                }
            )

        logger.info(f"Retrieved {len(orders)} pending orders for user {request.user.id}")

        return JsonResponse({"success": True, "pending_orders": orders, "count": len(orders)})

    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"get_pending_orders user={request.user.id}"
        )


@login_required
@require_http_methods(["POST"])
def save_risk_settings(request):
    """Save user's risk allocation settings"""
    try:
        data = json.loads(request.body)
        allocation_method = data.get("allocation_method")

        if allocation_method not in ["conservative", "moderate", "aggressive"]:
            return JsonResponse({"success": False, "error": "Invalid allocation method"})

        # OptionsAllocation is created automatically via signals when user is created
        allocation = request.user.options_allocation
        allocation.allocation_method = allocation_method
        allocation.save()

        logger.info(f"Risk settings saved for user {request.user.id}: {allocation_method}")
        return JsonResponse({"success": True})

    except Exception as e:
        logger.error(f"Error saving risk settings: {e}")
        return JsonResponse({"success": False, "error": str(e)})


@login_required
@require_http_methods(["DELETE"])
async def cancel_trade(request, trade_id):
    """
    Cancel a working trade.

    DELETE /api/trades/<trade_id>/cancel

    Handles all multi-leg strategies (Senex Trident, Bull/Bear Put Spreads).
    Uses TastyTrade's delete_complex_order API.

    Returns:
        200: Cancellation successful
        409: Race condition - order filled during cancel
        400: Cannot cancel (wrong status)
        404: Trade not found
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    from services.orders.cancellation import OrderCancellationService
    from trading.models import Trade

    try:
        # Verify trade exists and belongs to user
        await Trade.objects.select_related("position").aget(id=trade_id, user=user)
    except Trade.DoesNotExist:
        logger.error(f"Trade {trade_id} not found for user {user_id}")
        # Note: This has different format (no "success" field) - keeping as-is for compatibility
        return JsonResponse({"error": "Trade not found"}, status=404)

    # Get optional reason from query params
    reason = request.GET.get("reason", None)

    # Call cancellation service
    service = OrderCancellationService()
    success, result = await service.cancel_trade(trade_id=trade_id, user=user, reason=reason)

    logger.info(
        f"Trade {trade_id} cancellation result: success={success}, "
        f"final_status={result.get('final_status')}"
    )

    # Return appropriate status code
    if success:
        return JsonResponse(result, status=200)
    if result.get("race_condition"):
        return JsonResponse(result, status=409)  # Conflict - order filled
    return JsonResponse(result, status=400)


@login_required
@require_http_methods(["POST"])
def sync_positions(request):
    """Sync positions from TastyTrade - simple endpoint"""
    logger.info(
        "Position sync endpoint requested",
        extra={
            "user_id": request.user.id,
            "username": request.user.username,
            "action": "sync_positions_start",
        },
    )
    logger.info(f"Position sync requested by user {request.user.id}")

    try:
        from asgiref.sync import async_to_sync

        from services.positions.sync import PositionSyncService

        service = PositionSyncService()
        result = async_to_sync(service.sync_all_positions)(request.user)

        logger.info(f"Position sync result: {result}")
        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Position sync error for user {request.user.id}: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": str(e)})


@login_required
@require_http_methods(["POST"])
async def generate_suggestion_auto(request):
    """
    Auto strategy selection - scores all strategies, picks best.

    POST /trading/api/suggestions/auto/
    Body: {"symbol": "SPY"}

    Returns:
    {
        "success": true,
        "strategy": "short_put_vertical",
        "suggestion": {...},
        "explanation": "Selected: Short Put Vertical (MEDIUM confidence, score: 72.3)..."
    }
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    try:
        data = json.loads(request.body)
        symbol = data.get("symbol", "SPY")

        from services.strategies.selector import StrategySelector

        selector = StrategySelector(user)

        strategy_name, suggestion, explanation = await selector.a_select_and_generate(symbol)

        # Get market conditions and strategy scores from the selector's last analysis
        # Note: These are computed during a_select_and_generate
        market_report = (
            selector._last_market_report if hasattr(selector, "_last_market_report") else None
        )
        strategy_scores = selector._last_scores if hasattr(selector, "_last_scores") else {}

        # Build market conditions dict for frontend
        market_conditions = {}
        if market_report:
            # Fix: current_iv is already stored as percentage (21.22) not decimal (0.2122)
            # No conversion needed - just round for display
            current_iv_pct = (
                round(market_report.current_iv, 1) if market_report.current_iv is not None else None
            )

            market_conditions = {
                "direction": market_report.macd_signal,
                "iv_rank": market_report.iv_rank,
                "volatility": current_iv_pct,  # Already percentage format from storage
                "range_bound": market_report.is_range_bound,
                "stress_level": market_report.market_stress_level,
            }

        # Get confidence level from score
        selected_score = (
            strategy_scores.get(strategy_name, {}).get("score", 0) if strategy_name else 0
        )
        confidence = selector._score_to_confidence(selected_score) if strategy_name else None

        if not strategy_name:
            logger.info(f"Auto selection for user {user_id}, {symbol}: No strategy selected")
            return JsonResponse(
                {
                    "success": False,
                    "strategy": None,
                    "suggestion": None,
                    "explanation": explanation,
                    "market_conditions": market_conditions,
                    "message": "No suitable strategy for current market conditions",
                },
                status=200,
            )  # Not an error - just no trade

        suggestion_status = "present" if suggestion else "none"
        logger.info(
            f"Auto selection for user {user_id}, {symbol}: {strategy_name} "
            f"(suggestion={suggestion_status})"
        )

        # Format strategy scores for frontend
        formatted_scores = {}
        for name, data in strategy_scores.items():
            formatted_scores[name] = {
                "score": data.get("score", 0),
                "explanation": data.get("explanation", ""),
            }

        # Serialize TradingSuggestion to dict if present
        suggestion_data = suggestion.to_dict() if suggestion else None

        # Build response message
        if suggestion_data:
            message = f"{strategy_name.replace('_', ' ').title()} suggestion generated"
        else:
            message = "Suggestion generation started. Results will arrive via WebSocket."

        return JsonResponse(
            {
                "success": True,
                "strategy": strategy_name,
                "suggestion": suggestion_data,
                "message": message,
                "explanation": explanation,
                "confidence": confidence,
                "market_conditions": market_conditions,
                "strategy_scores": formatted_scores,
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"generate_suggestion_auto user={user_id}"
        )


@login_required
@require_http_methods(["POST"])
async def generate_suggestion_forced(request):
    """
    Forced strategy selection - generate specific strategy with warnings.

    POST /trading/api/suggestions/forced/
    Body: {"symbol": "SPY", "strategy": "short_put_vertical"}

    Valid strategies (14 total):
    - Credit Spreads: short_put_vertical, short_call_vertical
    - Debit Spreads: long_call_vertical, long_put_vertical, cash_secured_put
    - Volatility: long_call_ratio_backspread, long_straddle, long_strangle,
                  short_iron_condor, long_iron_condor, iron_butterfly
    - Stock-Based: long_call_calendar, covered_call

    Note: Senex Trident has its own dedicated endpoint

    Returns:
    {
        "success": true,
        "strategy": "short_put_vertical",
        "suggestion": {...},
        "explanation": "Requested: Short Put Vertical (LOW confidence, score: 35)...",
        "confidence_warning": true
    }
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)
    user_id = await async_get_user_id(request)

    try:
        data = json.loads(request.body)
        symbol = data.get("symbol", "SPY")
        strategy_name = data.get("strategy")

        logger.info(
            f"[TRACE] generate_suggestion_forced called: user={user_id}, symbol={symbol}, strategy={strategy_name}"
        )

        if not strategy_name:
            return JsonResponse(
                {"success": False, "error": "strategy parameter required"}, status=400
            )

        from services.strategies.selector import StrategySelector

        logger.info(f"[TRACE] Creating StrategySelector for user {user_id}")
        selector = StrategySelector(user)

        logger.info(
            f"[TRACE] Calling selector.a_select_and_generate: symbol={symbol}, forced_strategy={strategy_name}"
        )
        selected_strategy, suggestion, explanation = await selector.a_select_and_generate(
            symbol, forced_strategy=strategy_name
        )
        logger.info(
            f"[TRACE] selector.a_select_and_generate returned: selected_strategy={selected_strategy}, has_suggestion={suggestion is not None}"
        )

        # Get market conditions and strategy score
        market_report = (
            selector._last_market_report if hasattr(selector, "_last_market_report") else None
        )
        strategy_scores = selector._last_scores if hasattr(selector, "_last_scores") else {}

        # Build market conditions dict
        market_conditions = {}
        if market_report:
            # Fix: current_iv is already stored as percentage (21.22) not decimal (0.2122)
            # No conversion needed - just round for display
            current_iv_pct = (
                round(market_report.current_iv, 1) if market_report.current_iv is not None else None
            )

            market_conditions = {
                "direction": market_report.macd_signal,
                "iv_rank": market_report.iv_rank,
                "volatility": current_iv_pct,  # Already percentage format from storage
                "range_bound": market_report.is_range_bound,
                "stress_level": market_report.market_stress_level,
            }

        if not selected_strategy:
            logger.warning(
                f"Forced selection for user {user_id}, {symbol}: Invalid strategy {strategy_name}"
            )
            return JsonResponse(
                {
                    "success": False,
                    "strategy": None,
                    "suggestion": None,
                    "explanation": explanation,
                    "market_conditions": market_conditions,
                    "error": f"Unknown strategy: {strategy_name}",
                },
                status=400,
            )

        # Get score and confidence for the selected strategy
        strategy_score = strategy_scores.get(strategy_name, {}).get("score", 0)
        confidence = selector._score_to_confidence(strategy_score)

        # Detect low confidence warnings
        has_warning = confidence in ["LOW", "VERY LOW"]

        logger.info(
            f"Forced selection for user {user_id}, {symbol}: {strategy_name} "
            f"(confidence={confidence}, warning={has_warning})"
        )

        # Serialize TradingSuggestion to dict if present
        suggestion_data = suggestion.to_dict() if suggestion else None

        logger.info(
            f"[TRACE] Building response: has_suggestion_data={suggestion_data is not None}, confidence={confidence}"
        )

        # Build response message
        if suggestion_data:
            message = f"{strategy_name.replace('_', ' ').title()} suggestion generated"
        else:
            message = "Suggestion generation started. Results will arrive via WebSocket."

        logger.info(
            f"[TRACE] Returning JsonResponse with success=True, suggestion={'present' if suggestion_data else 'null'}"
        )

        return JsonResponse(
            {
                "success": True,
                "strategy": strategy_name,
                "suggestion": suggestion_data,
                "message": message,
                "explanation": explanation,
                "confidence": confidence,
                "confidence_warning": has_warning,
                "market_conditions": market_conditions,
            }
        )

    except json.JSONDecodeError:
        return ErrorResponseBuilder.json_decode_error()
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"generate_suggestion_forced user={user_id}"
        )


@login_required
@require_http_methods(["GET"])
async def get_position_greeks(request, position_id):
    """
    Get Greeks for a specific position.

    GET /trading/api/positions/<position_id>/greeks/

    Returns:
        {
            "success": true,
            "greeks": {
                "delta": 0.15,
                "gamma": 0.02,
                "theta": -0.45,
                "vega": 0.30,
                "rho": 0.05
            }
        }
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)

    try:
        from services.market_data.greeks import GreeksService
        from trading.models import Position

        # Phase 4.2: Fetch position with optimized query (avoid N+1)
        position = await Position.objects.select_related("trading_account").aget(
            id=position_id, user=user
        )

        from asgiref.sync import sync_to_async

        service = GreeksService()
        greeks = await sync_to_async(service.get_position_greeks_cached)(position)

        if greeks:
            return JsonResponse({"success": True, "greeks": greeks})
        return ErrorResponseBuilder.service_unavailable("Greeks data not available")

    except Position.DoesNotExist:
        return ErrorResponseBuilder.not_found("Position")
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"get_position_greeks position={position_id}"
        )


@login_required
@require_http_methods(["GET"])
async def get_portfolio_greeks(request):
    """
    Get aggregated Greeks for user's entire portfolio.

    GET /trading/api/portfolio/greeks/

    Returns:
        {
            "success": true,
            "greeks": {
                "delta": 0.25,
                "gamma": 0.05,
                "theta": -1.20,
                "vega": 0.80,
                "rho": 0.15,
                "position_count": 3
            }
        }
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)

    try:
        from asgiref.sync import sync_to_async

        from services.market_data.greeks import GreeksService

        service = GreeksService()
        greeks = await sync_to_async(service.get_portfolio_greeks_cached)(user)

        return JsonResponse({"success": True, "greeks": greeks})

    except Exception as e:
        return ErrorResponseBuilder.from_exception(e, context="get_portfolio_greeks")


@login_required
@require_http_methods(["GET"])
async def get_all_positions_greeks(request):
    """
    Get Greeks for all user positions in a single batch call.
    Eliminates N+1 query pattern from frontend.

    GET /trading/api/positions/greeks/

    Returns:
        {
            "success": true,
            "positions": {
                1: {"delta": 0.15, "gamma": 0.02, ...},
                25: {"delta": -0.30, "gamma": 0.01, ...}
            },
            "count": 5
        }
    """
    user = await async_get_user(request)

    try:
        from services.market_data.greeks import GreeksService
        from trading.models import Position

        # Phase 4.2: Get all open positions with optimized query (avoid N+1)
        positions = [
            position
            async for position in Position.objects.filter(
                user=user,
                is_app_managed=True,
                lifecycle_state__in=["open_full", "open_partial", "closing"],
            ).select_related("trading_account")
        ]

        from asgiref.sync import sync_to_async

        service = GreeksService()
        result = {}

        # Fetch Greeks for each position using cached service method
        for position in positions:
            greeks = await sync_to_async(service.get_position_greeks_cached)(position)
            if greeks:
                result[position.id] = greeks

        return JsonResponse({"success": True, "positions": result, "count": len(result)})

    except Exception as e:
        return ErrorResponseBuilder.from_exception(e, context="get_all_positions_greeks")


@login_required
@require_http_methods(["GET"])
async def get_position_details(request, position_id):
    """
    Get detailed position information including legs and Greeks.

    GET /trading/api/positions/<position_id>/details/

    Returns:
        {
            "success": true,
            "position": {
                "id": 123,
                "symbol": "QQQ",
                "strategy_type": "Senex Trident",
                "quantity": 1,
                "avg_price": 1.50,
                "unrealized_pnl": 75.00,
                "opened_at": "2025-10-01T09:30:00",
                "metadata": {
                    "legs": [...],
                    "strikes": {...}
                },
                "greeks": {
                    "delta": 0.15,
                    "gamma": 0.02,
                    "theta": -0.45,
                    "vega": 0.30
                }
            }
        }
    """
    # Async-safe user access - force SimpleLazyObject evaluation
    user = await async_get_user(request)

    try:
        from services.market_data.greeks import GreeksService
        from trading.models import Position

        # Phase 4.2: Fetch position with optimized query including trades (avoid N+1)
        position = await (
            Position.objects.select_related("trading_account")
            .prefetch_related("trades")
            .aget(id=position_id, user=user)
        )

        # Get Greeks from existing service (with error handling)
        try:
            from asgiref.sync import sync_to_async

            service = GreeksService()
            greeks = await sync_to_async(service.get_position_greeks_cached)(position)
        except Exception as e:
            logger.warning(
                f"Failed to fetch Greeks for position {position.id}: {e}",
                exc_info=True,
            )
            greeks = None  # Graceful degradation

        # Get opening trade for profit target info (with error handling)
        # Now uses prefetched trades instead of separate query
        try:
            opening_trade = await position.trades.filter(trade_type="open").afirst()
        except Exception as e:
            logger.warning(
                f"Failed to fetch opening trade for position {position.id}: {e}",
                exc_info=True,
            )
            opening_trade = None

        # Build response
        data = {
            "success": True,
            "position": {
                "id": position.id,
                "symbol": position.symbol,
                "strategy_type": position.get_strategy_type_display(),
                "strategy_key": position.strategy_type,
                "lifecycle_state": position.lifecycle_state,
                "status": position.lifecycle_state,
                "quantity": position.quantity,
                "avg_price": float(position.avg_price) if position.avg_price else None,
                "unrealized_pnl": (
                    float(position.unrealized_pnl) if position.unrealized_pnl else None
                ),
                "realized_pnl": (
                    float(position.total_realized_pnl) if position.total_realized_pnl else None
                ),
                "opened_at": position.opened_at.isoformat() if position.opened_at else None,
                "created_at": position.created_at.isoformat(),
                "is_app_managed": position.is_app_managed,
                "metadata": position.metadata or {},
                "greeks": greeks,
                "profit_targets": {
                    "created": position.profit_targets_created,
                    "details": position.profit_target_details,
                    "order_ids": opening_trade.child_order_ids if opening_trade else [],
                },
            },
        }

        return JsonResponse(data)

    except Position.DoesNotExist:
        return ErrorResponseBuilder.not_found("Position")
    except Exception as e:
        return ErrorResponseBuilder.from_exception(
            e, context=f"get_position_details position={position_id}"
        )


@login_required
@require_http_methods(["GET"])
async def get_all_positions_leg_symbols(request):
    """
    Get leg symbols for all user positions in a single query.

    GET /trading/api/positions/leg-symbols/

    Returns:
        {
            "success": true,
            "positions": {
                "123": ["AAPL250117C00150000", "AAPL250117P00145000"],
                "124": ["SPY250221C00400000", "SPY250221P00395000"]
            }
        }
    """
    user = await async_get_user(request)

    try:
        from trading.models import Position

        positions = Position.objects.filter(
            user=user, lifecycle_state__in=["open_full", "open_partial", "pending_entry"]
        ).only("id", "metadata")

        result = {}
        async for position in positions:
            if position.metadata and position.metadata.get("legs"):
                leg_symbols = [
                    leg["symbol"] for leg in position.metadata["legs"] if "symbol" in leg
                ]
                if leg_symbols:
                    result[str(position.id)] = leg_symbols

        return JsonResponse({"success": True, "positions": result})

    except Exception as e:
        return ErrorResponseBuilder.from_exception(e, context="get_all_positions_leg_symbols")


@login_required
@require_http_methods(["GET"])
async def watchlist_symbol_search(request):
    """
    Search for symbols using TastyTrade API.

    GET /api/watchlist/search/?q={query}

    Returns:
        {"results": [{"symbol": "AAPL", "description": "Apple Inc."}, ...]}
    """
    user = await async_get_user(request)
    query = request.GET.get("q", "").strip()

    if not query or len(query) < 1:
        return JsonResponse({"results": []})

    try:
        from asgiref.sync import sync_to_async
        from tastytrade.search import a_symbol_search

        from accounts.models import TradingAccount

        trading_account = await TradingAccount.objects.filter(user=user, is_primary=True).afirst()

        if not trading_account:
            return JsonResponse({"error": "No trading account configured"}, status=400)

        session = await sync_to_async(trading_account.get_oauth_session)()
        results = await a_symbol_search(session, query)

        return JsonResponse(
            {
                "results": [
                    {"symbol": r.symbol, "description": r.description}
                    for r in results[:10]  # Limit to top 10 results
                ]
            }
        )

    except Exception as e:
        logger.error(f"Symbol search error: {e}", exc_info=True)
        return JsonResponse({"error": "Search failed"}, status=500)


@login_required
@require_http_methods(["GET", "POST"])
async def watchlist_api(request):
    """
    RESTful watchlist endpoint.

    GET /api/watchlist/ - List watchlist items
    POST /api/watchlist/ - Add symbol to watchlist
    """
    user = await async_get_user(request)

    if request.method == "GET":
        # List watchlist items
        from trading.models import Watchlist

        items = [
            {
                "id": item.id,
                "symbol": item.symbol,
                "description": item.description,
                "order": item.order,
                "added_at": item.added_at.isoformat(),
            }
            async for item in Watchlist.objects.filter(user=user).order_by("order", "symbol")
        ]

        return JsonResponse({"items": items, "count": len(items)})

    if request.method == "POST":
        # Add symbol to watchlist
        try:
            from asgiref.sync import sync_to_async

            from trading.models import Watchlist

            data = json.loads(request.body)
            symbol = data.get("symbol", "").strip().upper()
            description = data.get("description", "").strip()

            if not symbol:
                return JsonResponse({"success": False, "error": "Symbol is required"}, status=400)

            # Check if already in watchlist
            exists = await Watchlist.objects.filter(user=user, symbol=symbol).aexists()
            if exists:
                return JsonResponse(
                    {"success": False, "error": f"{symbol} is already in your watchlist"},
                    status=400,
                )

            # Check 20-symbol limit
            count = await Watchlist.objects.filter(user=user).acount()
            if count >= 20:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Maximum 20 symbols allowed. Remove a symbol before adding another.",
                    },
                    status=400,
                )

            # Get next order number
            max_order_result = await sync_to_async(
                lambda: Watchlist.objects.filter(user=user).aggregate(models.Max("order"))
            )()
            next_order = (max_order_result["order__max"] or -1) + 1

            # Create watchlist item
            item = await Watchlist.objects.acreate(
                user=user, symbol=symbol, description=description, order=next_order
            )

            # Auto-load historical data for the symbol (non-blocking)
            # Load in background - don't block watchlist add if this fails
            try:
                from services.market_data.historical import HistoricalDataProvider

                provider = HistoricalDataProvider()
                # Use sync wrapper - ensure_minimum_data is sync
                await sync_to_async(provider.ensure_minimum_data)(symbol, min_days=90)
                logger.info(f"Historical data auto-load triggered for {symbol}")
            except Exception as auto_load_error:
                # Log but don't fail the watchlist add
                logger.warning(
                    f"Historical data auto-load failed for {symbol}: {auto_load_error}",
                    exc_info=True,
                )

            return JsonResponse(
                {
                    "success": True,
                    "item": {
                        "id": item.id,
                        "symbol": item.symbol,
                        "description": item.description,
                        "order": item.order,
                        "added_at": item.added_at.isoformat(),
                    },
                }
            )

        except ValidationError as e:
            # Model-level validation error (e.g., 15-symbol limit from save())
            error_msgs = e.messages if hasattr(e, "messages") else [str(e)]
            error_msg = error_msgs[0] if error_msgs else "Validation failed"
            logger.warning(f"Watchlist validation error for user {user.id}: {error_msg}")
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        except Exception as e:
            logger.error(f"Add to watchlist error: {e}", exc_info=True)
            return JsonResponse({"success": False, "error": "Failed to add symbol"}, status=500)
    return None


@login_required
@require_http_methods(["DELETE"])
async def watchlist_remove(request, item_id):
    """Remove symbol from watchlist."""
    user = await async_get_user(request)

    try:
        from asgiref.sync import sync_to_async

        from trading.models import Watchlist

        item = await Watchlist.objects.filter(id=item_id, user=user).afirst()

        if not item:
            return JsonResponse({"success": False, "error": "Item not found"}, status=404)

        await sync_to_async(item.delete)()

        return JsonResponse({"success": True})

    except Exception as e:
        logger.error(f"Remove from watchlist error: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": "Failed to remove symbol"}, status=500)


@require_http_methods(["POST"])
@login_required
def trigger_suggestion(request):
    """
    Trigger asynchronous suggestion generation.
    """
    from services.strategies.senex_trident_strategy import SenexTridentStrategy

    try:
        strategy = SenexTridentStrategy(request.user)
        strategy.generate_suggestion()
        return JsonResponse({"status": "success", "message": "Suggestion generation started."})
    except Exception as e:
        logger.error(f"Error triggering suggestion for user {request.user.id}: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
