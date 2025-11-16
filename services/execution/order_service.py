"""Order execution services for Senex strategies."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from tastytrade.order import Leg

from accounts.models import TradingAccount
from services.core.data_access import get_primary_tastytrade_account
from services.core.exceptions import (
    InvalidPriceEffectError,
    MarketClosedError,
    MissingPricingDataError,
    NoAccountError,
    OAuthSessionError,
    OrderBuildError,
    OrderPlacementError,
    StalePricingError,
    SuggestionNotApprovedError,
)
from services.core.logging import get_logger
from services.core.utils.async_utils import run_async
from services.sdk.trading_utils import PriceEffect, is_market_open_now
from trading.models import Position, Trade, TradingSuggestion

logger = get_logger(__name__)


@dataclass
class DryRunResult:
    """Order validation result when TASTYTRADE_DRY_RUN=True. See planning/33-dry-run-support/"""

    is_dry_run: bool = True
    order_id: int = -1
    legs: list[dict] = field(default_factory=list)
    expected_credit: Decimal = Decimal("0")
    simulated_status: str = "simulated"
    message: str = ""
    would_create_profit_targets: bool = False
    suggestion_id: int | None = None
    strategy_type: str | None = None
    buying_power_effect: dict | None = None
    fee_calculation: dict | None = None


class OrderExecutionService:
    """Execute Senex suggestions against the TastyTrade API."""

    def __init__(self, user):
        self.user = user
        self._dry_run_enabled = settings.TASTYTRADE_DRY_RUN

    def _should_dry_run(self, order_context: dict | None = None) -> bool:
        """Check if dry-run mode active. See planning/33-dry-run-support/"""
        return self._dry_run_enabled

    async def _execute_dry_run(
        self,
        suggestion: TradingSuggestion,
        session,
        account: TradingAccount,
        order_legs: list[Leg],
        order_legs_dict: list[dict],
        net_credit: Decimal,
    ) -> DryRunResult:
        """Validate order via TastyTrade without database writes."""
        try:
            response = await self._submit_order(
                session, account.account_number, order_legs, net_credit, dry_run=True
            )

            if not response:
                return DryRunResult(
                    legs=order_legs_dict,
                    expected_credit=net_credit,
                    message="Dry-run validation failed: No response from TastyTrade API",
                    suggestion_id=suggestion.id,
                    strategy_type=suggestion.strategy_type,
                )

            buying_power_effect = None
            fee_calculation = None

            if hasattr(response, "buying_power_effect"):
                buying_power_effect = {
                    "change_in_margin_requirement": (
                        str(response.buying_power_effect.change_in_margin_requirement)
                        if hasattr(response.buying_power_effect, "change_in_margin_requirement")
                        else None
                    ),
                    "change_in_buying_power": (
                        str(response.buying_power_effect.change_in_buying_power)
                        if hasattr(response.buying_power_effect, "change_in_buying_power")
                        else None
                    ),
                }

            if hasattr(response, "fee_calculation"):
                fee_calculation = {
                    "total_fees": (
                        str(response.fee_calculation.total_fees)
                        if hasattr(response.fee_calculation, "total_fees")
                        else None
                    ),
                    "regulatory_fees": (
                        str(response.fee_calculation.regulatory_fees)
                        if hasattr(response.fee_calculation, "regulatory_fees")
                        else None
                    ),
                    "clearing_fees": (
                        str(response.fee_calculation.clearing_fees)
                        if hasattr(response.fee_calculation, "clearing_fees")
                        else None
                    ),
                }

            return DryRunResult(
                order_id=-1,
                legs=order_legs_dict,
                expected_credit=net_credit,
                simulated_status="validated",
                message=f"✅ Dry-run validated successfully for {suggestion.strategy_id} on {suggestion.underlying_symbol}",
                would_create_profit_targets=True,
                suggestion_id=suggestion.id,
                strategy_type=suggestion.strategy_id,
                buying_power_effect=buying_power_effect,
                fee_calculation=fee_calculation,
            )

        except Exception as e:
            logger.error(f"Dry-run validation failed for suggestion {suggestion.id}: {e}")
            return DryRunResult(
                legs=order_legs_dict,
                expected_credit=net_credit,
                message=f"❌ Dry-run validation failed: {e!s}",
                simulated_status="validation_failed",
                suggestion_id=suggestion.id,
                strategy_type=suggestion.strategy_id,
            )

    async def execute_suggestion_async(
        self, suggestion: TradingSuggestion, custom_credit: Decimal | None = None
    ) -> Position | DryRunResult | None:
        """Execute suggestion. Returns DryRunResult if TASTYTRADE_DRY_RUN=True."""
        if suggestion.status != "approved":
            raise SuggestionNotApprovedError(
                suggestion_id=suggestion.id, current_status=suggestion.status
            )

        if not suggestion.has_real_pricing:
            raise MissingPricingDataError(suggestion_id=suggestion.id)

        # Validate Senex Trident structure before execution
        from services.execution.validators.execution_validator import ExecutionValidator

        structure_error = ExecutionValidator.validate_senex_trident_structure(suggestion)
        if structure_error:
            from services.core.exceptions import InvalidDataError

            logger.error(
                f"Structure validation failed for suggestion {suggestion.id}: {structure_error}"
            )
            raise InvalidDataError(
                field_name="structure",
                value=f"put_qty={suggestion.put_spread_quantity}, call_qty={suggestion.call_spread_quantity}",
                reason=structure_error,
            )

        account = await get_primary_tastytrade_account(self.user)
        if not account:
            logger.error("No primary trading account available for user %s", self.user.id)
            raise NoAccountError(user_id=self.user.id)

        # Check test mode flag (controls sandbox vs production environment)
        is_test_mode = account.is_test
        if is_test_mode:
            logger.warning(
                f"🧪 SANDBOX MODE: Order for {suggestion.underlying_symbol} "
                f"will be submitted to TastyTrade sandbox environment"
            )

        # Get TastyTrade session
        from services.core.data_access import get_oauth_session

        session = await get_oauth_session(self.user)
        if not session:
            logger.error(
                "Failed to get valid OAuth session for user %s. "
                "User may need to reconnect their TastyTrade account.",
                self.user.id,
            )
            raise OAuthSessionError(
                user_id=self.user.id,
                message="Unable to authenticate with TastyTrade. Please reconnect your account.",
            )

        if not self._is_pricing_current(suggestion):
            age_seconds = (timezone.now() - suggestion.generated_at).total_seconds()
            logger.warning(
                "Suggestion %s pricing is stale (%s seconds old); aborting execution",
                suggestion.id,
                age_seconds,
            )
            raise StalePricingError(suggestion_id=suggestion.id, age_seconds=age_seconds)

        order_legs = await self._build_senex_order_legs(session, suggestion)
        if not order_legs:
            logger.error("Failed to build order legs for suggestion %s", suggestion.id)
            raise OrderBuildError(suggestion_id=suggestion.id)

        # Convert Leg objects to dicts for database storage
        order_legs_dict = []
        for leg in order_legs:
            if leg.quantity is None:
                from services.core.exceptions import InvalidDataError

                raise InvalidDataError(
                    field_name="quantity",
                    value=None,
                    reason=f"Leg quantity missing for {leg.symbol} ({leg.action}); cannot persist order legs",
                )
            order_legs_dict.append(
                {
                    "instrument_type": leg.instrument_type.value,
                    "symbol": leg.symbol,
                    "action": leg.action.value,
                    "quantity": int(leg.quantity),
                }
            )

        # Use custom credit if provided, otherwise use calculated mid-price credit
        if custom_credit is not None:
            net_credit = custom_credit.quantize(Decimal("0.01"))
            credit_source = "custom (automated offset or manual input)"
        else:
            # Use mid-price credit (realistic) instead of natural credit (conservative)
            # This fixes the ~$0.40-0.50 gap between submitted and filled prices
            net_credit = suggestion.total_mid_credit.quantize(Decimal("0.01"))
            credit_source = "mid-price fallback"

        # Comprehensive pricing breakdown for every order
        logger.info(
            f"\n{'=' * 70}\n"
            f"ORDER PRICING BREAKDOWN - Suggestion {suggestion.id}\n"
            f"{'=' * 70}\n"
            f"Symbol: {suggestion.underlying_symbol}\n"
            f"Strategy: {suggestion.strategy_configuration.strategy_id if suggestion.strategy_configuration else 'Unknown'}\n"
            f"Expiration: {suggestion.expiration_date}\n"
            f"\n"
            f"PRICING DETAILS:\n"
            f"  Natural Credit (conservative):  ${suggestion.total_credit:.4f}\n"
            f"  Mid-Price Credit (realistic):   ${suggestion.total_mid_credit:.4f}\n"
            f"  Custom Credit (if provided):    ${f'{custom_credit:.4f}' if custom_credit is not None else 'None'}\n"
            f"  → Final Submitted Price:        ${net_credit:.4f}\n"
            f"\n"
            f"SPREAD BREAKDOWN:\n"
            f"  Put Spread ({suggestion.put_spread_quantity}x):\n"
            f"    Natural:   ${f'{suggestion.put_spread_credit:.4f}' if suggestion.put_spread_credit is not None else 'N/A'}\n"
            f"    Mid:       ${f'{suggestion.put_spread_mid_credit:.4f}' if suggestion.put_spread_mid_credit is not None else 'N/A'}\n"
            f"  Call Spread ({suggestion.call_spread_quantity}x):\n"
            f"    Natural:   ${f'{suggestion.call_spread_credit:.4f}' if suggestion.call_spread_credit is not None else 'N/A'}\n"
            f"    Mid:       ${f'{suggestion.call_spread_mid_credit:.4f}' if suggestion.call_spread_mid_credit is not None else 'N/A'}\n"
            f"\n"
            f"METADATA:\n"
            f"  Source: {credit_source}\n"
            f"  Price Effect: {suggestion.price_effect}\n"
            f"  Pricing Source: {suggestion.pricing_source if hasattr(suggestion, 'pricing_source') else 'Unknown'}\n"
            f"  Has Real Pricing: {suggestion.has_real_pricing}\n"
            f"  Streaming Latency: {suggestion.streaming_latency_ms if hasattr(suggestion, 'streaming_latency_ms') else 'N/A'}ms\n"
            f"{'=' * 70}\n"
        )

        # Validate using PriceEffect enum for standardization
        effect = PriceEffect.CREDIT if net_credit and net_credit > 0 else PriceEffect.DEBIT
        if effect != PriceEffect.CREDIT:
            logger.error(
                "Invalid price effect for suggestion %s: expected CREDIT, got %s (amount: %s)",
                suggestion.id,
                effect.value,
                net_credit,
            )
            raise InvalidPriceEffectError(
                expected_effect="credit",
                actual_effect=effect.value,
                amount=net_credit,
            )

        if self._should_dry_run():
            logger.info(
                f"🧪 DRY-RUN MODE: Validating order for {suggestion.underlying_symbol} "
                f"via TastyTrade API without database persistence"
            )
            return await self._execute_dry_run(
                suggestion, session, account, order_legs, order_legs_dict, net_credit
            )

        # CRITICAL: Create pending database records FIRST using async transaction
        # This prevents data loss if DB writes fail after successful order placement
        try:
            position, trade = await self._create_pending_records_async(
                account, suggestion, order_legs_dict
            )
            logger.info(f"Created pending records - Position {position.id}, Trade {trade.id}")
        except Exception as e:
            logger.error(f"Failed to create pending database records: {e}")
            return None

        # NOW submit the order to TastyTrade
        # Note: is_test_mode controls environment (sandbox vs production)
        # not dry_run behavior - actual orders are placed in both environments
        try:
            response = await self._submit_order(
                session, account.account_number, order_legs, net_credit
            )
            if not response:
                # Order submission failed - clean up pending records
                logger.error(
                    "Order placement failed for suggestion %s, cleaning up pending records",
                    suggestion.id,
                )
                await self._delete_pending_records(position, trade)
                raise OrderPlacementError(
                    reason="Order submission returned no response",
                    order_details={"suggestion_id": suggestion.id},
                )

            # Order succeeded! Extract order ID and update records
            order_id = self._extract_order_id(response)
            logger.info(f"✅ ORDER PLACED: {order_id} - Updating database records...")

            # Update records with actual order info
            await self._finalize_position_record(position, response)
            await self._finalize_trade_record(trade, response, order_id)
            await self._mark_suggestion_executed(suggestion, position)
            logger.info(f"✅ DATABASE SYNC SUCCESS: Order {order_id} fully recorded")

        except Exception as e:
            # Order may or may not have been placed - log extensively
            logger.error(f"🚨 CRITICAL ERROR during order execution: {e}")
            logger.error(f"🚨 User: {self.user.id}, Suggestion: {suggestion.id}")
            logger.error(f"🚨 Position: {position.id}, Trade: {trade.id}")
            logger.error("🚨 MANUAL VERIFICATION REQUIRED - Check TastyTrade for order status")
            # Clean up pending records - if order succeeded, AlertStreamer will detect it
            await self._delete_pending_records(position, trade)
            raise

        # Profit targets are created asynchronously via AlertStreamer when the order fills
        # See streaming/services/stream_manager.py::_create_profit_targets_for_trade()

        logger.info(
            "Executed suggestion %s as position %s (trade %s)",
            suggestion.id,
            position.id,
            trade.id,
        )
        return position

    async def _create_pending_records_async(
        self, account: TradingAccount, suggestion: TradingSuggestion, order_legs: list[dict]
    ) -> tuple[Position, Trade]:
        """Creates pending Position and Trade records within an async atomic transaction."""
        from django.db import transaction

        from asgiref.sync import sync_to_async

        @sync_to_async
        def _create_records():
            with transaction.atomic():
                # Create position with 'pending entry' lifecycle state
                # Calculate number of spreads (each vertical spread counts as 1)
                num_spreads = suggestion.put_spread_quantity + suggestion.call_spread_quantity

                position = Position.objects.create(
                    user=self.user,
                    trading_account=account,
                    strategy_type="senex_trident",
                    symbol=suggestion.underlying_symbol,
                    lifecycle_state="pending_entry",
                    quantity=num_spreads,
                    initial_risk=suggestion.max_risk,
                    spread_width=None,
                    number_of_spreads=num_spreads,  # Senex Trident: 2 put spreads + 1 call spread
                    is_app_managed=True,
                    opening_price_effect=PriceEffect.CREDIT.value,
                    opened_at=timezone.now(),
                    metadata={
                        "suggestion_id": suggestion.id,
                        "strategy_type": "senex_trident",
                        "is_complete_trident": suggestion.call_spread_quantity > 0,
                        "strikes": {
                            "short_put": str(suggestion.short_put_strike),
                            "long_put": str(suggestion.long_put_strike),
                            "short_call": (
                                str(suggestion.short_call_strike)
                                if suggestion.short_call_strike
                                else None
                            ),
                            "long_call": (
                                str(suggestion.long_call_strike)
                                if suggestion.long_call_strike
                                else None
                            ),
                        },
                        "expiration": suggestion.expiration_date.isoformat(),
                        "streaming_pricing": {
                            "put_credit": str(suggestion.put_spread_credit),
                            "call_credit": (
                                str(suggestion.call_spread_credit)
                                if suggestion.call_spread_credit
                                else None
                            ),
                            "total_credit": str(suggestion.total_credit),
                            "pricing_source": suggestion.pricing_source,
                            "streaming_latency_ms": suggestion.streaming_latency_ms,
                        },
                    },
                )

                # Create trade with 'pending' status
                trade = Trade.objects.create(
                    user=self.user,
                    position=position,
                    trading_account=account,
                    broker_order_id=f"pending_{timezone.now().timestamp()}",
                    trade_type="open",
                    order_legs=order_legs,
                    quantity=sum(leg.get("quantity", 0) for leg in order_legs),
                    status="pending",
                    submitted_at=timezone.now(),
                    parent_order_id="",
                    order_type="LIMIT",
                    time_in_force="DAY",
                )
                return position, trade

        return await _create_records()

    def execute_suggestion(self, suggestion: TradingSuggestion) -> Position | DryRunResult | None:
        """Sync wrapper for execute_suggestion_async."""
        try:
            return run_async(self.execute_suggestion_async(suggestion))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error executing suggestion %s: %s", suggestion.id, exc)
            return None

    async def _submit_order(
        self,
        session,
        account_number: str,
        order_legs: list[Leg],
        limit_price: Decimal,
        dry_run: bool = False,
    ) -> dict | None:
        """
        Submit the multi-leg order via the tastytrade SDK.

        Args:
            session: TastyTrade OAuth session (already configured for sandbox/production)
            account_number: Account number to submit order for
            order_legs: List of order legs
            limit_price: Limit price for the order
            dry_run: If True, validates order without submitting (returns order_id=-1)

        Note: The session's is_test flag determines environment (sandbox vs production).
        The dry_run parameter is separate and controls whether to actually submit.
        """
        # Check market hours before submission
        if not is_market_open_now():
            raise MarketClosedError()

        try:
            from tastytrade import Account
            from tastytrade.order import NewOrder, OrderTimeInForce, OrderType
        except ImportError:
            logger.error("tastytrade SDK not installed; cannot submit orders")
            return None

        tt_account = await Account.a_get(session, account_number)

        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.LIMIT,
            legs=order_legs,  # Directly use the list of Leg objects
            # Opening credit spreads - positive price for credit received
            # Round to 2 decimal places for the API
            price=round(float(limit_price), 2),
        )

        # dry_run validates without submitting (useful for testing order building)
        if dry_run:
            logger.info("🔍 DRY RUN: Validating order without submission (will return order_id=-1)")
        return await tt_account.a_place_order(session, new_order, dry_run=dry_run)

    async def _build_senex_order_legs(self, session, suggestion: TradingSuggestion) -> list:
        """Construct the OCC legs for the Senex structure using centralized async utility."""
        from services.orders.utils.order_builder_utils import build_senex_trident_legs

        # Prepare put strikes
        put_strikes = {
            "short_put": suggestion.short_put_strike,
            "long_put": suggestion.long_put_strike,
        }

        # Prepare call strikes if present
        call_strikes = None
        if suggestion.call_spread_quantity and suggestion.call_spread_quantity > 0:
            if suggestion.short_call_strike and suggestion.long_call_strike:
                call_strikes = {
                    "short_call": suggestion.short_call_strike,
                    "long_call": suggestion.long_call_strike,
                }
            else:
                logger.warning("Call spread quantity set without strikes; skipping call legs")

        # Validate quantities before building legs (fail fast, no silent fallbacks)
        put_quantity = suggestion.put_spread_quantity
        call_quantity = suggestion.call_spread_quantity

        if not put_quantity or put_quantity != 2:
            from services.core.exceptions import InvalidDataError

            logger.error(
                f"Invalid put_spread_quantity for Senex Trident: {put_quantity} (must be 2)"
            )
            raise InvalidDataError(
                field_name="put_spread_quantity",
                value=put_quantity,
                reason="Senex Trident requires exactly 2 put spreads",
            )

        if call_quantity and call_quantity != 1:
            from services.core.exceptions import InvalidDataError

            logger.error(
                f"Invalid call_spread_quantity for Senex Trident: {call_quantity} (must be 1)"
            )
            raise InvalidDataError(
                field_name="call_spread_quantity",
                value=call_quantity,
                reason="Senex Trident requires exactly 1 call spread when included",
            )

        # Use centralized async utility to build legs
        return await build_senex_trident_legs(
            session,
            suggestion.underlying_symbol,
            suggestion.expiration_date,
            put_strikes,
            call_strikes,
            put_quantity,
            call_quantity or 1,
        )

    def _extract_order_id(self, response) -> str | None:
        """Extract order ID from TastyTrade PlacedOrderResponse."""
        if response is None:
            return None

        if hasattr(response, "order") and hasattr(response.order, "id"):
            order_id = response.order.id
            if order_id and order_id != -1:  # -1 = dry_run
                return str(order_id)

        logger.warning(f"Could not extract order ID from response: {response}")
        return None

    @staticmethod
    def _map_action(action: str):
        try:
            from tastytrade.order import OrderAction
        except ImportError:  # pragma: no cover - only hits without SDK
            return action

        mapping = {
            "sell_to_open": OrderAction.SELL_TO_OPEN,
            "buy_to_open": OrderAction.BUY_TO_OPEN,
            "sell_to_close": OrderAction.SELL_TO_CLOSE,
            "buy_to_close": OrderAction.BUY_TO_CLOSE,
        }
        return mapping[action]

    @staticmethod
    def _is_pricing_current(suggestion: TradingSuggestion) -> bool:
        return suggestion.generated_at >= timezone.now() - timedelta(minutes=10)

    @staticmethod
    def calculate_net_effect_from_legs(legs: list[dict]) -> str:
        """
        Calculate whether a set of legs results in net credit or debit.

        This is a helper to verify our price effect logic:
        - Sell actions contribute positive (credit)
        - Buy actions contribute negative (debit)

        Returns "credit" if net positive, "debit" if net negative.
        """
        # Count sell vs buy actions
        sell_count = sum(
            leg.get("quantity", 1) for leg in legs if "sell" in str(leg.get("action", "")).lower()
        )
        buy_count = sum(
            leg.get("quantity", 1) for leg in legs if "buy" in str(leg.get("action", "")).lower()
        )

        # For options, sells are credits, buys are debits
        # This is simplified - actual calculation would need prices
        net_effect = sell_count - buy_count

        logger.debug(
            f"Leg effect calculation: {sell_count} sells - {buy_count} buys = {net_effect}"
        )

        return "credit" if net_effect > 0 else "debit"

    async def _create_position_record(
        self,
        suggestion: TradingSuggestion,
        account: TradingAccount,
        response: dict,
    ) -> Position:
        # Calculate number of spreads (each vertical spread counts as 1)
        num_spreads = suggestion.put_spread_quantity + suggestion.call_spread_quantity

        return await Position.objects.acreate(
            user=self.user,
            trading_account=account,
            strategy_type="senex_trident",
            symbol=suggestion.underlying_symbol,
            lifecycle_state="open_full",
            quantity=num_spreads,
            initial_risk=suggestion.max_risk,
            spread_width=None,
            number_of_spreads=num_spreads,  # Senex Trident: 2 put spreads + 1 call spread
            is_app_managed=True,
            opening_price_effect="credit",  # Senex Trident always opens for credit
            opened_at=timezone.now(),
            metadata={
                "suggestion_id": suggestion.id,
                "strategy_type": "senex_trident",
                "is_complete_trident": suggestion.call_spread_quantity > 0,
                "strikes": {
                    "short_put": str(suggestion.short_put_strike),
                    "long_put": str(suggestion.long_put_strike),
                    "short_call": (
                        str(suggestion.short_call_strike)
                        if suggestion.short_call_strike is not None
                        else None
                    ),
                    "long_call": (
                        str(suggestion.long_call_strike)
                        if suggestion.long_call_strike is not None
                        else None
                    ),
                },
                "expiration": suggestion.expiration_date.isoformat(),
                "streaming_pricing": {
                    "put_credit": str(suggestion.put_spread_credit),
                    "call_credit": (
                        str(suggestion.call_spread_credit)
                        if suggestion.call_spread_credit is not None
                        else None
                    ),
                    "total_credit": str(suggestion.total_credit),
                    "pricing_source": suggestion.pricing_source,
                    "streaming_latency_ms": suggestion.streaming_latency_ms,
                },
                "broker_response": {
                    "order_id": self._extract_order_id(response),
                    "status": getattr(
                        response.order if hasattr(response, "order") else response, "status", None
                    ),
                    "created_at": getattr(
                        response.order if hasattr(response, "order") else response,
                        "created_at",
                        None,
                    ),
                    "price": getattr(
                        response.order if hasattr(response, "order") else response, "price", None
                    ),
                    "filled_quantity": getattr(
                        response.order if hasattr(response, "order") else response,
                        "filled_quantity",
                        None,
                    ),
                    "order_type": getattr(
                        response.order if hasattr(response, "order") else response,
                        "order_type",
                        None,
                    ),
                    "time_in_force": getattr(
                        response.order if hasattr(response, "order") else response,
                        "time_in_force",
                        None,
                    ),
                },
            },
        )

    async def _create_trade_record(
        self,
        position: Position,
        account: TradingAccount,
        response: dict,
        order_legs: list[dict[str, object]],
    ) -> Trade:
        broker_order_id = (
            self._extract_order_id(response) or f"pending_{timezone.now().timestamp()}"
        )
        return await Trade.objects.acreate(
            user=self.user,
            position=position,
            trading_account=account,
            broker_order_id=broker_order_id,
            trade_type="open",
            order_legs=order_legs,
            quantity=sum(leg.get("quantity", 0) for leg in order_legs),
            status="pending",
            submitted_at=timezone.now(),
            parent_order_id="",  # This is the parent order, no parent
            order_type="LIMIT",
            time_in_force="DAY",
        )

    async def _mark_suggestion_executed(
        self, suggestion: TradingSuggestion, position: Position
    ) -> None:
        suggestion.status = "executed"
        suggestion.executed_position = position
        await suggestion.asave(update_fields=["status", "executed_position"])

    async def _create_pending_position_record(
        self,
        suggestion: TradingSuggestion,
        account: TradingAccount,
    ) -> Position:
        """Create a position record with 'pending' lifecycle state before order submission."""
        # Calculate number of spreads (each vertical spread counts as 1)
        num_spreads = suggestion.put_spread_quantity + suggestion.call_spread_quantity

        return await Position.objects.acreate(
            user=self.user,
            trading_account=account,
            strategy_type="senex_trident",
            symbol=suggestion.underlying_symbol,
            lifecycle_state="pending_entry",  # Will be updated after successful order
            quantity=num_spreads,
            initial_risk=suggestion.max_risk,
            spread_width=None,
            number_of_spreads=num_spreads,  # Senex Trident: 2 put spreads + 1 call spread
            is_app_managed=True,
            opening_price_effect="credit",
            opened_at=timezone.now(),
            metadata={
                "suggestion_id": suggestion.id,
                "strategy_type": "senex_trident",
                "is_complete_trident": suggestion.call_spread_quantity > 0,
                "strikes": {
                    "short_put": str(suggestion.short_put_strike),
                    "long_put": str(suggestion.long_put_strike),
                    "short_call": (
                        str(suggestion.short_call_strike) if suggestion.short_call_strike else None
                    ),
                    "long_call": (
                        str(suggestion.long_call_strike) if suggestion.long_call_strike else None
                    ),
                },
                "expiration": suggestion.expiration_date.isoformat(),
                "streaming_pricing": {
                    "put_credit": str(suggestion.put_spread_credit),
                    "call_credit": (
                        str(suggestion.call_spread_credit)
                        if suggestion.call_spread_credit
                        else None
                    ),
                    "total_credit": str(suggestion.total_credit),
                    "pricing_source": suggestion.pricing_source,
                    "streaming_latency_ms": suggestion.streaming_latency_ms,
                },
            },
        )

    async def _create_pending_trade_record(
        self,
        position: Position,
        account: TradingAccount,
        order_legs: list[dict[str, object]],
    ) -> Trade:
        """Create a trade record with 'pending' status before order submission."""
        return await Trade.objects.acreate(
            user=self.user,
            position=position,
            trading_account=account,
            broker_order_id=f"pending_{timezone.now().timestamp()}",  # Temporary ID
            trade_type="open",
            order_legs=order_legs,
            quantity=sum(leg.get("quantity", 0) for leg in order_legs),
            status="pending",  # Will be updated after successful order
            submitted_at=timezone.now(),
            parent_order_id="",
            order_type="LIMIT",
            time_in_force="DAY",
        )

    async def _finalize_position_record(
        self,
        position: Position,
        response: dict,
    ) -> None:
        """Update position record with broker response after successful order placement."""
        # Keep status as "pending" until order fills
        # AlertStreamer will update to "open" when filled
        # position.lifecycle_state = "open_full"  # REMOVED - don't mark open until filled

        # Extract order ID from response
        order_id = self._extract_order_id(response)

        # Set broker_order_ids list for order history linking
        # Skip None (dry-run orders) to prevent monitoring task errors
        if order_id:
            position.broker_order_ids = [order_id]
        else:
            position.broker_order_ids = []

        # Store detailed broker response in metadata
        position.metadata["broker_response"] = {
            "order_id": order_id,
            "status": getattr(
                response.order if hasattr(response, "order") else response, "status", None
            ),
            "created_at": getattr(
                response.order if hasattr(response, "order") else response, "created_at", None
            ),
            "price": getattr(
                response.order if hasattr(response, "order") else response, "price", None
            ),
            "filled_quantity": getattr(
                response.order if hasattr(response, "order") else response, "filled_quantity", None
            ),
            "order_type": getattr(
                response.order if hasattr(response, "order") else response, "order_type", None
            ),
            "time_in_force": getattr(
                response.order if hasattr(response, "order") else response, "time_in_force", None
            ),
        }
        await position.asave()

    async def _finalize_trade_record(
        self,
        trade: Trade,
        response: dict,
        order_id: str,
    ) -> None:
        """Update trade record with broker order ID after successful order placement."""
        trade.broker_order_id = order_id if order_id else "UNKNOWN"
        trade.status = "submitted"
        await trade.asave()

    async def _delete_pending_records(
        self,
        position: Position,
        trade: Trade,
    ) -> None:
        """Delete pending records if order submission failed."""
        try:
            await trade.adelete()
            await position.adelete()
            logger.info(f"Cleaned up pending records: Position {position.id}, Trade {trade.id}")
        except Exception as e:
            logger.error(f"Failed to clean up pending records: {e}")

    async def check_order_status(self, broker_order_id: str) -> dict[str, object]:
        """Poll TastyTrade for order status updates."""
        account = await get_primary_tastytrade_account(self.user)
        if not account:
            return {"status": "error", "message": "No primary trading account"}

        # Get TastyTrade session
        from services.core.data_access import get_oauth_session

        session = await get_oauth_session(self.user)
        if not session:
            return {"status": "error", "message": "Failed to get OAuth session"}

        try:
            from tastytrade import Account

            tt_account = await Account.a_get(session, account.account_number)
            order = await tt_account.a_get_order(session, broker_order_id)

            # Parse order status (normalize to lowercase for consistency)
            return {
                "status": (
                    order.status.value if hasattr(order.status, "value") else str(order.status)
                ).lower(),
                "filled": order.status in ["FILLED", "COMPLETE"],
                "filled_at": order.terminal_at if order.terminal_at else None,
                "fill_price": order.price if order.price else None,
                "quantity_filled": order.size if order.size else None,
                "order_id": broker_order_id,
                "raw_order": order,
            }

        except Exception as e:
            logger.error("Error checking order status for %s: %s", broker_order_id, e)
            return {"status": "error", "message": str(e)}

    def _build_closing_legs(self, position: Position, metadata: dict) -> list[dict[str, object]]:
        """Build opposite legs to close a position using centralized utility."""
        from datetime import datetime

        from services.orders.utils.order_builder_utils import build_closing_spread_legs

        strikes = metadata.get("strikes", {})
        underlying = position.symbol
        expiration = metadata.get("expiration")

        if not expiration:
            return []

        exp_date = datetime.fromisoformat(expiration).date()
        legs = []

        # Close put spreads (quantity 2 for Senex Trident)
        if strikes.get("short_put") and strikes.get("long_put"):
            put_strikes = {
                "short_put": Decimal(strikes["short_put"]),
                "long_put": Decimal(strikes["long_put"]),
            }
            put_legs = build_closing_spread_legs(
                underlying,
                exp_date,
                "put_spread_1",  # Senex has 2 put spreads but closes them together
                put_strikes,
                quantity=2,  # Close both put spreads together
            )
            # Convert OrderLeg objects to dict format
            legs.extend(
                [
                    {
                        "instrument_type": leg.instrument_type,
                        "symbol": leg.symbol,
                        "action": leg.action,
                        "quantity": leg.quantity,
                    }
                    for leg in put_legs
                ]
            )

        # Close call spread (quantity 1 for Senex Trident)
        if strikes.get("short_call") and strikes.get("long_call"):
            call_strikes = {
                "short_call": Decimal(strikes["short_call"]),
                "long_call": Decimal(strikes["long_call"]),
            }
            call_legs = build_closing_spread_legs(
                underlying, exp_date, "call_spread", call_strikes, quantity=1
            )
            # Convert OrderLeg objects to dict format
            legs.extend(
                [
                    {
                        "instrument_type": leg.instrument_type,
                        "symbol": leg.symbol,
                        "action": leg.action,
                        "quantity": leg.quantity,
                    }
                    for leg in call_legs
                ]
            )

        return legs

    async def _submit_closing_order(
        self,
        session,
        account_number: str,
        order_legs: list[dict[str, object]],
        limit_price: Decimal,
        opening_price_effect: str,  # "credit" or "debit"
        parent_order_id: str | None = None,
    ) -> dict | None:
        """Submit a closing order with optional parent linkage.

        The price sign is determined by the opening_price_effect:
        - If opened for credit, close for debit (negative price)
        - If opened for debit, close for credit (positive price)
        """
        # Check market hours before submission
        if not is_market_open_now():
            raise MarketClosedError()

        try:
            from tastytrade import Account
            from tastytrade.order import InstrumentType, Leg, NewOrder, OrderTimeInForce, OrderType
        except ImportError:
            logger.error("tastytrade SDK not installed; cannot submit orders")
            return None

        try:
            tt_account = await Account.a_get(session, account_number)
        except AttributeError:
            loop = asyncio.get_running_loop()
            tt_account = await loop.run_in_executor(None, Account.get, session, account_number)

        # Build order with DAY time in force for profit targets
        order_kwargs = {
            "time_in_force": OrderTimeInForce.DAY,
            "order_type": OrderType.LIMIT,
            "legs": [
                Leg(
                    instrument_type=InstrumentType.EQUITY_OPTION,
                    symbol=leg["symbol"],
                    action=self._map_action(leg["action"]),
                    quantity=leg["quantity"],
                )
                for leg in order_legs
            ],
        }

        # Determine price sign based on how position was opened
        # If opened for credit, close for debit (negative price)
        # If opened for debit, close for credit (positive price)
        if opening_price_effect == PriceEffect.CREDIT.value:
            order_kwargs["price"] = -abs(float(limit_price))  # Pay to close
            logger.info(
                f"Closing credit position: using negative price -${abs(float(limit_price))}"
            )
        else:  # opening_price_effect == PriceEffect.DEBIT.value
            order_kwargs["price"] = abs(float(limit_price))  # Receive to close
            logger.info(f"Closing debit position: using positive price ${abs(float(limit_price))}")

        # Add parent linkage if provided
        if parent_order_id:
            order_kwargs["parent_id"] = parent_order_id

        new_order = NewOrder(**order_kwargs)
        return await tt_account.a_place_order(session, new_order, dry_run=False)

    async def execute_profit_targets(self, profit_target_specs: list) -> dict:
        """
        Execute profit target orders from any strategy.
        Generic method that works with any strategy's profit targets.

        Args:
            profit_target_specs: List of ProfitTargetSpec objects from a strategy

        Returns:
            Dict with order_ids, targets, and total_orders
        """
        order_ids = []
        results = []

        for spec in profit_target_specs:
            order_id = await self.execute_order_spec(spec.order_spec)
            if order_id:
                order_ids.append(order_id)
                results.append(
                    {
                        "spread_type": spec.spread_type,
                        "order_id": order_id,
                        "profit_percentage": spec.profit_percentage,
                        "target_price": float(spec.order_spec.limit_price),
                    }
                )
                logger.info(
                    f"✅ Created {spec.spread_type} profit target "
                    f"({spec.profit_percentage}%): {order_id}"
                )
            else:
                logger.error(f"❌ Failed to create {spec.spread_type} profit target")

        return {"order_ids": order_ids, "targets": results, "total_orders": len(order_ids)}

    def execute_profit_targets_sync(self, profit_target_specs: list) -> dict:
        """
        Synchronous wrapper for profit target execution.

        Args:
            profit_target_specs: List of ProfitTargetSpec objects from a strategy

        Returns:
            Dict with order_ids, targets, and total_orders
        """
        return run_async(self.execute_profit_targets(profit_target_specs))

    async def execute_order_spec(self, order_spec) -> str | None:
        """
        Execute a generic OrderSpec in a strategy-agnostic way.

        Args:
            order_spec: OrderSpec object containing order details

        Returns:
            Optional[str]: Order ID if successful, None if failed
        """
        try:
            # Get account and session
            account = await get_primary_tastytrade_account(self.user)
            if not account:
                logger.error("No primary account available for order execution")
                return None

            from services.core.data_access import get_oauth_session

            session = await get_oauth_session(self.user)
            if not session:
                logger.error("Failed to get OAuth session for order execution")
                return None

            # Submit the order using the generic submission method
            response = await self._submit_order_spec(session, account.account_number, order_spec)

            if response:
                order_id = self._extract_order_id(response)
                logger.info(f"✅ Executed order spec: {order_spec.description} -> {order_id}")
                return order_id
            logger.error(f"❌ Failed to execute order spec: {order_spec.description}")
            return None

        except Exception as e:
            logger.error(f"❌ Error executing order spec '{order_spec.description}': {e}")
            return None

    async def _submit_order_spec(self, session, account_number: str, order_spec) -> dict | None:
        """Submit an OrderSpec to TastyTrade API."""
        # Check market hours before submission
        if not is_market_open_now():
            raise MarketClosedError()

        try:
            from tastytrade import Account
            from tastytrade.order import InstrumentType, Leg, NewOrder, OrderTimeInForce, OrderType
        except ImportError:
            logger.error("tastytrade SDK not installed; cannot submit orders")
            return None

        # Map time in force string to enum
        # Note: TastyTrade only supports DAY, GTC, and IOC (not FOK)
        time_in_force_map = {
            "DAY": OrderTimeInForce.DAY,
            "GTC": OrderTimeInForce.GTC,
            "IOC": OrderTimeInForce.IOC,
        }

        # Map order type string to enum
        order_type_map = {
            "LIMIT": OrderType.LIMIT,
            "MARKET": OrderType.MARKET,
            "STOP": OrderType.STOP,
            "STOP_LIMIT": OrderType.STOP_LIMIT,
        }

        try:
            tt_account = await Account.a_get(session, account_number)
        except AttributeError:
            loop = asyncio.get_running_loop()
            tt_account = await loop.run_in_executor(None, Account.get, session, account_number)

        # Build order from OrderSpec
        # Determine if this is a debit or credit order based on price_effect
        price_effect = getattr(order_spec, "price_effect", PriceEffect.CREDIT.value)

        order_kwargs = {
            "time_in_force": time_in_force_map.get(order_spec.time_in_force, OrderTimeInForce.GTC),
            "order_type": order_type_map.get(
                getattr(order_spec, "order_type", "LIMIT"), OrderType.LIMIT
            ),
            "legs": [
                Leg(
                    instrument_type=InstrumentType.EQUITY_OPTION,
                    symbol=leg.symbol,
                    action=self._map_action(leg.action),
                    quantity=leg.quantity,
                )
                for leg in order_spec.legs
            ],
        }

        # Set the price based on the price_effect
        # TastyTrade SDK Convention:
        # - Credit orders: positive price (money received)
        # - Debit orders: negative price (money paid)
        if price_effect == PriceEffect.DEBIT.value:
            # For debit orders, use negative price to indicate payment
            order_kwargs["price"] = -abs(round(float(order_spec.limit_price), 2))
        else:
            # For credit orders, use positive price to indicate receipt
            order_kwargs["price"] = abs(round(float(order_spec.limit_price), 2))

        new_order = NewOrder(**order_kwargs)
        return await tt_account.a_place_order(session, new_order, dry_run=False)

    def create_profit_targets_sync(
        self,
        position: Position,
        parent_order_id: str,
        preserve_existing: bool = False,
        filter_spread_types: list[str] | None = None,
    ) -> dict:
        """
        Synchronous version using strategy pattern.
        Works for any strategy that provides profit target specifications.

        Args:
            position: Position to create profit targets for
            parent_order_id: Broker order ID of the opening trade
            preserve_existing: If True, merge new targets with existing ones instead of replacing
            filter_spread_types: If provided, only create profit targets for these spread types
        """
        logger.info(f"📊 SYNC PROFIT TARGETS: Starting for position {position.id}")

        from trading.models import Trade

        # Stock holdings (strategy_type=None) don't have profit targets
        if position.strategy_type is None:
            logger.debug(f"Position {position.id} is a stock holding, skipping profit targets")
            return {
                "status": "skipped",
                "message": "Stock holdings do not have profit targets",
            }

        # Determine strategy type and get appropriate strategy
        if position.strategy_type == "senex_trident":
            from services.strategies.senex_trident_strategy import SenexTridentStrategy

            strategy = SenexTridentStrategy(self.user)
        else:
            logger.warning(f"Unknown strategy type: {position.strategy_type}")
            return {
                "status": "error",
                "message": f"Strategy {position.strategy_type} not supported",
            }

        # Get the opening trade
        trade = Trade.objects.filter(position=position, trade_type="open").first()
        if not trade:
            logger.error(f"No opening trade found for position {position.id}")
            return {"status": "error", "message": "No opening trade found"}

        # Get profit targets from strategy
        profit_target_specs = strategy.get_profit_target_specifications_sync(position, trade)

        if not profit_target_specs:
            logger.warning(f"No profit target specs generated for position {position.id}")
            return {"status": "error", "message": "No profit targets generated"}

        # Filter profit targets if requested
        if filter_spread_types:
            original_count = len(profit_target_specs)
            profit_target_specs = [
                spec for spec in profit_target_specs if spec.spread_type in filter_spread_types
            ]
            logger.info(
                f"Position {position.id}: Filtered profit targets from {original_count} "
                f"to {len(profit_target_specs)} (types: {filter_spread_types})"
            )

        if not profit_target_specs:
            logger.warning(f"Position {position.id}: No profit targets to create after filtering")
            return {"status": "error", "message": "No profit targets after filtering"}

        # Execute profit targets
        result = self.execute_profit_targets_sync(profit_target_specs)

        # Update position tracking
        if result["order_ids"]:
            # Build new profit target details
            new_targets = {
                target["spread_type"]: {
                    "order_id": target["order_id"],
                    "percent": target["profit_percentage"],
                    "target_price": target["target_price"],
                }
                for target in result["targets"]
            }

            if preserve_existing:
                # Merge with existing profit target details
                existing_details = position.profit_target_details or {}
                position.profit_target_details = {**existing_details, **new_targets}
                logger.info(
                    f"Position {position.id}: Merged {len(new_targets)} new profit targets "
                    f"with {len(existing_details)} existing (total: {len(position.profit_target_details)})"
                )
            else:
                # Replace all profit target details
                position.profit_target_details = new_targets

            # Determine if ALL expected profit targets are now created
            # Check total count of profit_target_details vs strategy expectation
            expected_count = self._get_expected_profit_target_count(position.strategy_type)
            if expected_count is not None:
                actual_count = (
                    len(position.profit_target_details) if position.profit_target_details else 0
                )
                position.profit_targets_created = actual_count == expected_count
                if not position.profit_targets_created:
                    logger.warning(
                        f"Position {position.id}: Only {actual_count}/{expected_count} profit targets created"
                    )
            else:
                # Unknown strategy, use old logic (all current batch succeeded)
                position.profit_targets_created = len(result["order_ids"]) == len(
                    profit_target_specs
                )

            position.save()

            # Update trade with child order IDs
            if preserve_existing:
                # Extend existing child_order_ids
                existing_ids = trade.child_order_ids or []
                trade.child_order_ids = existing_ids + result["order_ids"]
                logger.info(
                    f"Position {position.id}: Extended child_order_ids from {len(existing_ids)} "
                    f"to {len(trade.child_order_ids)}"
                )
            else:
                # Replace all child_order_ids
                trade.child_order_ids = result["order_ids"]

            trade.save()

        return {
            "status": "success",
            "strategy": position.strategy_type,
            **result,
            "message": f"Created {len(result['order_ids'])} profit targets",
        }

    def _get_expected_profit_target_count(self, strategy_type: str) -> int | None:
        """
        Get expected number of profit targets for a strategy type.

        Args:
            strategy_type: Strategy identifier (e.g., "senex_trident", "iron_condor")

        Returns:
            Expected count or None if unknown strategy
        """
        if strategy_type == "senex_trident":
            return 3  # 40%, 50%, 60%
        if strategy_type in ["iron_condor", "short_iron_condor", "long_iron_condor"]:
            return 2  # Call and put spreads
        if strategy_type in [
            "short_put_vertical",
            "short_call_vertical",
            "long_call_vertical",
            "long_put_vertical",
            "cash_secured_put",
            "covered_call",
        ]:
            return 1  # Single profit target
        return None  # Unknown strategy
