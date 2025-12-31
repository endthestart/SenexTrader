#!/usr/bin/env python3
"""
Position State Validation Script

Queries TastyTrade order history to determine the actual current state of each
position and creates a specific correction plan with exact SQL statements.

Based on scripts/qqq_assignment_report.py pattern.
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def load_env_file():
    if load_dotenv is None:
        return
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


load_env_file()


def ensure_field_encryption_key():
    load_env_file()
    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if key:
        return
    fallback = os.environ.get("DEFAULT_DEV_FIELD_ENCRYPTION_KEY")
    if fallback:
        os.environ["FIELD_ENCRYPTION_KEY"] = fallback
        print("[info] Using DEFAULT_DEV_FIELD_ENCRYPTION_KEY")
        return
    raise SystemExit("FIELD_ENCRYPTION_KEY required")


def bootstrap_django(settings_module):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    import django

    django.setup()


def parse_args():
    parser = argparse.ArgumentParser(description="Validate position states against TastyTrade")
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "senextrader.settings.production"),
        help="Django settings module",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=60,
        help="Days of history to analyze (default: 60)",
    )
    parser.add_argument(
        "--output",
        default="position_validation_results.md",
        help="Output validation report",
    )
    return parser.parse_args()


def build_session(account):
    """Create TastyTrade session."""
    from asgiref.sync import async_to_sync

    from services.brokers.tastytrade.session import TastyTradeSessionService

    result = async_to_sync(TastyTradeSessionService.get_session_for_user)(
        account.user_id, account.refresh_token, is_test=account.is_test
    )
    if not result.get("success"):
        raise SystemExit(f"Failed to create session: {result.get('error')}")
    return result["session"]


def parse_occ_symbol(symbol):
    """Parse OCC option symbol."""
    text = (symbol or "").strip()
    if len(text) < 15:
        return None
    root = text[:6].strip()
    expiry_raw = text[6:12]
    try:
        expiry = datetime.strptime(expiry_raw, "%y%m%d").date()
    except ValueError:
        expiry = None
    option_type = "Call" if text[12].upper() == "C" else "Put"
    strike_text = text[13:]
    try:
        strike = Decimal(strike_text) / Decimal("1000")
    except Exception:
        strike = None
    return {
        "root": root,
        "expiration": expiry,
        "type": option_type,
        "strike": strike,
        "symbol": symbol,
    }


def get_order_activity(session, account_number, broker_order_id):
    """
    Get detailed activity for a specific order from TastyTrade.

    Returns dict with order status, fills, and leg details.
    """
    from tastytrade.account import Account

    tt_account = Account.get(session, account_number)

    # Get order by ID - need to search through recent orders
    # TastyTrade doesn't have a direct get-by-ID API, so we search history
    start_date = (datetime.now(UTC) - timedelta(days=120)).date()
    orders = tt_account.get_order_history(session, start_date=start_date)

    target_order = None
    for order in orders:
        if str(order.id) == str(broker_order_id):
            target_order = order
            break

    if not target_order:
        return {"found": False, "order_id": broker_order_id}

    # Parse order details
    status = (
        target_order.status.value
        if hasattr(target_order.status, "value")
        else str(target_order.status)
    )

    legs = []
    if hasattr(target_order, "legs"):
        for leg in target_order.legs:
            leg_info = {
                "symbol": leg.symbol,
                "action": leg.action.value if hasattr(leg.action, "value") else str(leg.action),
                "quantity": leg.quantity,
            }
            parsed = parse_occ_symbol(leg.symbol)
            if parsed:
                leg_info.update(parsed)
            legs.append(leg_info)

    return {
        "found": True,
        "order_id": broker_order_id,
        "status": status,
        "legs": legs,
        "filled_at": getattr(target_order, "received_at", None),
        "price": getattr(target_order, "price", None),
    }


def check_position_at_broker(session, account_number, order_info):
    """
    Check if the position from this order still exists at the broker.

    Returns dict with current leg count and status.
    """
    from tastytrade.account import Account

    if not order_info.get("found") or not order_info.get("legs"):
        return {"exists": False, "leg_count": 0}

    tt_account = Account.get(session, account_number)
    current_positions = tt_account.get_positions(session)

    # Get unique symbols from the original order
    order_symbols = {leg["symbol"] for leg in order_info["legs"]}

    # Check how many of those symbols still exist
    existing_symbols = set()
    for pos in current_positions:
        if pos.symbol in order_symbols:
            existing_symbols.add(pos.symbol)

    leg_count = len(existing_symbols)
    original_count = len(order_symbols)

    return {
        "exists": leg_count > 0,
        "leg_count": leg_count,
        "original_count": original_count,
        "closed_legs": original_count - leg_count,
        "symbols_remaining": list(existing_symbols),
    }


def validate_positions(args):
    """Main validation function."""
    from accounts.models import TradingAccount
    from trading.models import Position, Trade

    print("=" * 80)
    print("POSITION STATE VALIDATION")
    print(f"Started: {datetime.now(UTC)}")
    print("=" * 80)

    # Get account
    account = (
        TradingAccount.objects.filter(
            is_active=True,
            connection_type="TASTYTRADE",
        )
        .select_related("user")
        .first()
    )

    if not account:
        raise SystemExit("No active TastyTrade account")

    print(f"\nAccount: {account.account_number}")
    print(f"User: {account.user.email}")
    print(f"Analyzing last {args.days_back} days of activity...\n")

    # Connect to TastyTrade
    session = build_session(account)

    # Get problematic positions
    problematic_positions = []

    # 1. Closed positions with active trades
    print("### Validating Closed Positions with Active Trades ###\n")
    closed_with_trades = Position.objects.filter(
        user=account.user,
        is_app_managed=True,
        lifecycle_state="closed",
    )

    for pos in closed_with_trades:
        active_trades = Trade.objects.filter(
            position=pos,
            status__in=["submitted", "filled", "live", "received", "pending", "working"],
        )

        if not active_trades.exists():
            continue

        print(f"Position #{pos.id} (closed {pos.closed_at}):")

        # Get the opening trade
        opening_trade = active_trades.filter(trade_type="open").first()
        if not opening_trade:
            opening_trade = active_trades.first()

        order_id = opening_trade.broker_order_id
        print(f"  Checking order {order_id}...")

        # Check order history
        order_info = get_order_activity(session, account.account_number, order_id)

        if not order_info["found"]:
            print("  Order not found in history (may be too old)")
            broker_status = {"exists": False, "leg_count": 0}
        else:
            print(f"  Order status: {order_info['status']}")
            print(f"  Order legs: {len(order_info['legs'])}")

            # Check if position still exists
            broker_status = check_position_at_broker(session, account.account_number, order_info)
            print(f"  Broker position exists: {broker_status['exists']}")
            print(
                f"  Legs at broker: {broker_status['leg_count']}/{broker_status.get('original_count', '?')}"
            )

        # Determine correct state
        if broker_status["exists"]:
            leg_count = broker_status["leg_count"]
            if leg_count == 6:
                correct_state = "open_full"
            elif leg_count in [2, 4]:
                correct_state = "open_partial"
            else:
                correct_state = "unknown"

            print(f"  Correct state should be: {correct_state}\n")

            problematic_positions.append(
                {
                    "position_id": pos.id,
                    "current_state": "closed",
                    "correct_state": correct_state,
                    "broker_order_id": order_id,
                    "leg_count": leg_count,
                    "action": "update_to_open",
                    "sql": f"UPDATE trading_position SET lifecycle_state = '{correct_state}', closed_at = NULL WHERE id = {pos.id};",
                }
            )
        else:
            print("  Position is actually closed - trades need to be closed\n")

            problematic_positions.append(
                {
                    "position_id": pos.id,
                    "current_state": "closed",
                    "correct_state": "closed",
                    "broker_order_id": order_id,
                    "leg_count": 0,
                    "action": "close_trades",
                    "sql": f"UPDATE trading_trade SET status = 'closed', lifecycle_event = 'close' WHERE position_id = {pos.id} AND status IN ('filled', 'submitted', 'live');",
                }
            )

    # 2. Validate open positions
    print("\n### Validating Open Positions ###\n")
    open_positions = Position.objects.filter(
        user=account.user,
        is_app_managed=True,
        lifecycle_state__in=["open_full", "open_partial"],
    )

    for pos in open_positions:
        print(f"Position #{pos.id} ({pos.lifecycle_state}):")

        trades = Trade.objects.filter(position=pos)
        opening_trade = trades.filter(trade_type="open").first()

        if not opening_trade:
            print("  No opening trade found\n")
            continue

        order_id = opening_trade.broker_order_id
        print(f"  Checking order {order_id}...")

        order_info = get_order_activity(session, account.account_number, order_id)

        if not order_info["found"]:
            print("  Order not found - may need manual review\n")
            continue

        broker_status = check_position_at_broker(session, account.account_number, order_info)

        if not broker_status["exists"]:
            print("  Position NOT at broker - should be closed")
            print(f"  Current state: {pos.lifecycle_state}")
            print("  Correct state: closed\n")

            problematic_positions.append(
                {
                    "position_id": pos.id,
                    "current_state": pos.lifecycle_state,
                    "correct_state": "closed",
                    "broker_order_id": order_id,
                    "leg_count": 0,
                    "action": "close_position",
                    "sql": f"UPDATE trading_position SET lifecycle_state = 'closed', closed_at = NOW() WHERE id = {pos.id};",
                }
            )
        else:
            leg_count = broker_status["leg_count"]
            if leg_count == 6:
                correct_state = "open_full"
            elif leg_count in [2, 4]:
                correct_state = "open_partial"
            else:
                correct_state = "unknown"

            if correct_state != pos.lifecycle_state:
                print("  State mismatch")
                print(f"  Current: {pos.lifecycle_state}")
                print(f"  Correct: {correct_state}\n")

                problematic_positions.append(
                    {
                        "position_id": pos.id,
                        "current_state": pos.lifecycle_state,
                        "correct_state": correct_state,
                        "broker_order_id": order_id,
                        "leg_count": leg_count,
                        "action": "update_state",
                        "sql": f"UPDATE trading_position SET lifecycle_state = '{correct_state}' WHERE id = {pos.id};",
                    }
                )
            else:
                print(f"  State correct ({correct_state})\n")

    # Generate report
    output_path = PROJECT_ROOT / args.output
    with open(output_path, "w") as f:
        f.write(generate_validation_report(problematic_positions, account))

    print("\nValidation complete")
    print(f"Report: {output_path}")
    print(f"Positions needing correction: {len(problematic_positions)}\n")

    return problematic_positions


def generate_validation_report(problems, account):
    """Generate markdown validation report."""
    lines = []
    lines.append("# Position Validation Results\n")
    lines.append(f"**Generated:** {datetime.now(UTC).isoformat()}")
    lines.append(f"**Account:** {account.account_number} ({account.user.email})\n")
    lines.append("---\n")

    lines.append("## Summary\n")
    lines.append(f"**Positions Validated:** {len(problems)}")
    lines.append(f"**Corrections Needed:** {len(problems)}\n")

    by_action = defaultdict(list)
    for p in problems:
        by_action[p["action"]].append(p)

    lines.append("### By Action Type\n")
    for action, items in by_action.items():
        lines.append(f"- **{action}**: {len(items)} positions")

    lines.append("\n---\n")
    lines.append("## Detailed Corrections\n")

    for i, problem in enumerate(problems, 1):
        lines.append(f"\n### {i}. Position #{problem['position_id']}\n")
        lines.append(f"- **Current State:** `{problem['current_state']}`")
        lines.append(f"- **Correct State:** `{problem['correct_state']}`")
        lines.append(f"- **Broker Order ID:** {problem['broker_order_id']}")
        lines.append(f"- **Legs at Broker:** {problem['leg_count']}")
        lines.append(f"- **Action:** {problem['action']}\n")
        lines.append("**SQL:**")
        lines.append("```sql")
        lines.append(problem["sql"])
        lines.append("```\n")

    lines.append("---\n")
    lines.append("## Execution Plan\n")
    lines.append("1. Review all SQL statements above")
    lines.append("2. Test in development environment first")
    lines.append("3. Backup production database")
    lines.append("4. Run SQL in transaction with ability to rollback")
    lines.append("5. Verify results against TastyTrade")
    lines.append("6. Monitor for 24 hours\n")

    return "\n".join(lines)


def main():
    args = parse_args()
    ensure_field_encryption_key()
    bootstrap_django(args.settings)

    try:
        validate_positions(args)
        return 0
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
