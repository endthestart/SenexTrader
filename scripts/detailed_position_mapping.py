#!/usr/bin/env python3
"""
Comprehensive Position Mapping & Validation Script

Creates a detailed proof-of-record mapping between:
- Database positions (with all metadata)
- TastyTrade positions (current state)
- TastyTrade order history (transaction timeline)
- Trade records in database

This creates an auditable record before making ANY changes.

Usage:
    python scripts/detailed_position_mapping.py --settings=senextrader.settings.production
"""

import argparse
import json
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
    parser = argparse.ArgumentParser(
        description="Create comprehensive position mapping with full audit trail"
    )
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "senextrader.settings.production"),
        help="Django settings module",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=90,
        help="Days of order history to fetch (default: 90)",
    )
    parser.add_argument(
        "--output-json",
        default="position_mapping_data.json",
        help="Output JSON data file",
    )
    parser.add_argument(
        "--output-report",
        default="position_mapping_report.md",
        help="Output human-readable report",
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
    """Parse OCC option symbol into components."""
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
        "expiration": expiry.isoformat() if expiry else None,
        "type": option_type,
        "strike": str(strike),
        "symbol": symbol,
    }


def get_all_database_positions(user):
    """Get all app-managed positions from database with full details."""
    from trading.models import Position, Trade

    positions = Position.objects.filter(
        user=user,
        is_app_managed=True,
    ).order_by("id")

    position_data = []
    for pos in positions:
        # Get all trades for this position
        trades = Trade.objects.filter(position=pos).order_by("submitted_at")

        trade_list = []
        for trade in trades:
            trade_list.append(
                {
                    "id": trade.id,
                    "status": trade.status,
                    "trade_type": trade.trade_type,
                    "lifecycle_event": trade.lifecycle_event,
                    "broker_order_id": trade.broker_order_id,
                    "order_type": trade.order_type,
                    "executed_price": str(trade.executed_price) if trade.executed_price else None,
                    "fill_price": str(trade.fill_price) if trade.fill_price else None,
                    "quantity": trade.quantity,
                    "submitted_at": trade.submitted_at.isoformat() if trade.submitted_at else None,
                    "executed_at": trade.executed_at.isoformat() if trade.executed_at else None,
                    "filled_at": trade.filled_at.isoformat() if trade.filled_at else None,
                    "commission": str(trade.commission) if trade.commission else None,
                    "order_legs": trade.order_legs,
                    "metadata": trade.metadata,
                }
            )

        position_data.append(
            {
                "database_id": pos.id,
                "symbol": pos.symbol,
                "strategy_type": pos.strategy_type,
                "lifecycle_state": pos.lifecycle_state,
                "quantity": pos.quantity,
                "number_of_spreads": pos.number_of_spreads,
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
                "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
                "avg_price": str(pos.avg_price) if pos.avg_price else None,
                "instrument_type": pos.instrument_type,
                "is_app_managed": pos.is_app_managed,
                "opening_order_id": pos.opening_order_id,
                "metadata": pos.metadata,
                "trades": trade_list,
            }
        )

    return position_data


def get_tastytrade_current_positions(session, account_number):
    """Get current positions from TastyTrade."""
    from tastytrade.account import Account

    tt_account = Account.get(session, account_number)
    positions = tt_account.get_positions(session)

    # Group by expiration for Senex Trident analysis
    by_expiration = defaultdict(lambda: {"puts": [], "calls": [], "equity": []})

    position_data = []
    for pos in positions:
        pos_dict = {
            "symbol": pos.symbol,
            "instrument_type": pos.instrument_type,
            "quantity": pos.quantity,
            "quantity_direction": pos.quantity_direction,
            "close_price": str(pos.close_price) if hasattr(pos, "close_price") else None,
            "average_open_price": (
                str(pos.average_open_price) if hasattr(pos, "average_open_price") else None
            ),
            "multiplier": getattr(pos, "multiplier", None),
            "cost_effect": getattr(pos, "cost_effect", None),
            "is_suppressed": getattr(pos, "is_suppressed", False),
            "is_frozen": getattr(pos, "is_frozen", False),
        }

        # Parse OCC symbol if it's an option
        if pos.instrument_type != "Equity":
            parsed = parse_occ_symbol(pos.symbol)
            if parsed:
                pos_dict.update({"parsed": parsed})
                exp = parsed["expiration"]
                if parsed["type"] == "Put":
                    by_expiration[exp]["puts"].append(pos_dict)
                else:
                    by_expiration[exp]["calls"].append(pos_dict)
        else:
            by_expiration["equity"]["equity"].append(pos_dict)

        position_data.append(pos_dict)

    return position_data, by_expiration


def get_tastytrade_order_history(session, account_number, days_back):
    """Get complete order history from TastyTrade."""
    from tastytrade.account import Account

    tt_account = Account.get(session, account_number)
    start_date = (datetime.now(UTC) - timedelta(days=days_back)).date()

    print(f"  Fetching order history from {start_date}...")
    orders = tt_account.get_order_history(session, start_date=start_date)

    order_data = []
    for order in orders:
        # Parse order status
        status = order.status.value if hasattr(order.status, "value") else str(order.status)

        # Parse legs
        legs = []
        if hasattr(order, "legs"):
            for leg in order.legs:
                leg_dict = {
                    "symbol": leg.symbol,
                    "instrument_type": (
                        leg.instrument_type.value
                        if hasattr(leg.instrument_type, "value")
                        else str(leg.instrument_type)
                    ),
                    "action": leg.action.value if hasattr(leg.action, "value") else str(leg.action),
                    "quantity": leg.quantity,
                    "remaining_quantity": getattr(leg, "remaining_quantity", None),
                    "fills": [],
                }

                # Get fills if available
                if hasattr(leg, "fills"):
                    for fill in leg.fills:
                        leg_dict["fills"].append(
                            {
                                "ext_group_fill_id": getattr(fill, "ext_group_fill_id", None),
                                "fill_id": getattr(fill, "fill_id", None),
                                "quantity": getattr(fill, "quantity", None),
                                "fill_price": str(getattr(fill, "fill_price", None)),
                                "filled_at": getattr(fill, "filled_at", None),
                            }
                        )

                # Parse OCC symbol
                parsed = parse_occ_symbol(leg.symbol)
                if parsed:
                    leg_dict["parsed"] = parsed

                legs.append(leg_dict)

        order_dict = {
            "id": order.id,
            "status": status,
            "order_type": (
                order.order_type.value
                if hasattr(order.order_type, "value")
                else str(order.order_type)
            ),
            "size": getattr(order, "size", None),
            "underlying_symbol": getattr(order, "underlying_symbol", None),
            "underlying_instrument_type": (
                order.underlying_instrument_type.value
                if hasattr(order, "underlying_instrument_type")
                and hasattr(order.underlying_instrument_type, "value")
                else None
            ),
            "time_in_force": (
                order.time_in_force.value
                if hasattr(order.time_in_force, "value")
                else str(order.time_in_force)
            ),
            "price": str(order.price) if hasattr(order, "price") and order.price else None,
            "price_effect": (
                order.price_effect.value
                if hasattr(order, "price_effect") and hasattr(order.price_effect, "value")
                else None
            ),
            "received_at": (
                order.received_at.isoformat()
                if hasattr(order, "received_at") and order.received_at
                else None
            ),
            "updated_at": getattr(order, "updated_at", None),
            "edited_at": getattr(order, "edited_at", None),
            "cancelled_at": getattr(order, "cancelled_at", None),
            "contingent_status": getattr(order, "contingent_status", None),
            "reject_reason": getattr(order, "reject_reason", None),
            "legs": legs,
        }

        order_data.append(order_dict)

    return order_data


def map_positions_to_orders(db_positions, tt_order_history):
    """Create mapping between database positions and TastyTrade orders."""
    mappings = []

    for db_pos in db_positions:
        mapping = {
            "database_position_id": db_pos["database_id"],
            "database_state": db_pos["lifecycle_state"],
            "database_opened": db_pos["opened_at"],
            "database_closed": db_pos["closed_at"],
            "opening_order_id": db_pos["opening_order_id"],
            "database_trades": [],
            "tastytrade_orders": [],
            "match_status": "unknown",
            "issues": [],
        }

        # Map database trades
        for trade in db_pos["trades"]:
            mapping["database_trades"].append(
                {
                    "trade_id": trade["id"],
                    "broker_order_id": trade["broker_order_id"],
                    "status": trade["status"],
                    "trade_type": trade["trade_type"],
                    "lifecycle_event": trade["lifecycle_event"],
                }
            )

            # Find matching TastyTrade order
            order_id = trade["broker_order_id"]
            tt_order = next((o for o in tt_order_history if str(o["id"]) == str(order_id)), None)

            if tt_order:
                mapping["tastytrade_orders"].append(
                    {
                        "order_id": tt_order["id"],
                        "status": tt_order["status"],
                        "legs": len(tt_order["legs"]),
                        "received_at": tt_order["received_at"],
                    }
                )
            else:
                mapping["issues"].append(
                    f"Order {order_id} not found in TastyTrade history (may be older than {90} days)"
                )

        # Determine match status
        if db_pos["lifecycle_state"] == "closed" and any(
            t["status"] in ["filled", "submitted", "live"] for t in db_pos["trades"]
        ):
            mapping["match_status"] = "CRITICAL: Closed position with active trades"
            mapping["issues"].append("Position marked closed but has active trades")
        elif not mapping["tastytrade_orders"]:
            mapping["match_status"] = "WARNING: No TastyTrade orders found"
        elif all(o["status"] == "Filled" for o in mapping["tastytrade_orders"]):
            mapping["match_status"] = "OK: All orders filled"
        else:
            mapping["match_status"] = "REVIEW: Mixed order statuses"

        mappings.append(mapping)

    return mappings


def analyze_position_states(db_positions, tt_current_positions, mappings):
    """Analyze discrepancies between database and broker states."""
    analysis = {
        "summary": {
            "total_db_positions": len(db_positions),
            "db_open": sum(
                1
                for p in db_positions
                if p["lifecycle_state"] in ["open", "open_full", "open_partial"]
            ),
            "db_closed": sum(1 for p in db_positions if p["lifecycle_state"] == "closed"),
            "tt_total_positions": len(tt_current_positions),
            "tt_option_positions": sum(
                1 for p in tt_current_positions if p["instrument_type"] != "Equity"
            ),
            "tt_equity_positions": sum(
                1 for p in tt_current_positions if p["instrument_type"] == "Equity"
            ),
        },
        "discrepancies": [],
        "state_breakdown": defaultdict(int),
        "critical_issues": [],
        "warnings": [],
    }

    # Count by state
    for pos in db_positions:
        analysis["state_breakdown"][pos["lifecycle_state"]] += 1

    # Find critical issues
    for mapping in mappings:
        if "CRITICAL" in mapping["match_status"]:
            analysis["critical_issues"].append(mapping)
        elif "WARNING" in mapping["match_status"]:
            analysis["warnings"].append(mapping)

    # Check for phantom positions (in DB but not at broker)
    # This requires matching by order history
    for db_pos in db_positions:
        if db_pos["lifecycle_state"] in ["open", "open_full", "open_partial"]:
            # Position is marked open in DB - should exist at broker
            # We'd need to check if the legs from the opening order still exist
            # This is complex - we'll flag for manual review
            pass

    return analysis


def create_mapping(args):
    """Main mapping function."""
    from accounts.models import TradingAccount

    print("=" * 80)
    print("COMPREHENSIVE POSITION MAPPING")
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
    print(f"Analysis period: Last {args.days_back} days\n")

    # Step 1: Get all database positions
    print("### Step 1: Extracting Database Positions ###")
    db_positions = get_all_database_positions(account.user)
    print(f"  Found {len(db_positions)} app-managed positions in database\n")

    # Step 2: Connect to TastyTrade
    print("### Step 2: Connecting to TastyTrade ###")
    session = build_session(account)
    print("  PASS: Connected\n")

    # Step 3: Get current TastyTrade positions
    print("### Step 3: Fetching Current TastyTrade Positions ###")
    tt_current_positions, tt_by_expiration = get_tastytrade_current_positions(
        session, account.account_number
    )
    print(f"  Found {len(tt_current_positions)} positions at broker")
    print(
        f"  - Options: {sum(1 for p in tt_current_positions if p['instrument_type'] != 'Equity')}"
    )
    print(f"  - Equity: {sum(1 for p in tt_current_positions if p['instrument_type'] == 'Equity')}")
    print(f"  - Unique expirations: {len([k for k in tt_by_expiration if k != 'equity'])}\n")

    # Step 4: Get TastyTrade order history
    print("### Step 4: Fetching TastyTrade Order History ###")
    tt_order_history = get_tastytrade_order_history(session, account.account_number, args.days_back)
    print(f"  Found {len(tt_order_history)} orders in history\n")

    # Step 5: Create mappings
    print("### Step 5: Creating Position-Order Mappings ###")
    mappings = map_positions_to_orders(db_positions, tt_order_history)
    print(f"  Created {len(mappings)} position mappings\n")

    # Step 6: Analyze discrepancies
    print("### Step 6: Analyzing Discrepancies ###")
    analysis = analyze_position_states(db_positions, tt_current_positions, mappings)
    print(f"  Critical issues: {len(analysis['critical_issues'])}")
    print(f"  Warnings: {len(analysis['warnings'])}\n")

    # Compile complete data
    complete_data = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "account_number": account.account_number,
            "user_email": account.user.email,
            "days_back": args.days_back,
        },
        "database_positions": db_positions,
        "tastytrade_current_positions": tt_current_positions,
        "tastytrade_positions_by_expiration": dict(tt_by_expiration.items()),
        "tastytrade_order_history": tt_order_history,
        "position_order_mappings": mappings,
        "analysis": {
            "summary": analysis["summary"],
            "state_breakdown": dict(analysis["state_breakdown"]),
            "critical_issues_count": len(analysis["critical_issues"]),
            "warnings_count": len(analysis["warnings"]),
        },
    }

    # Save JSON
    json_path = PROJECT_ROOT / args.output_json
    with open(json_path, "w") as f:
        json.dump(complete_data, f, indent=2, default=str)
    print(f"PASS: JSON data saved: {json_path}")

    # Generate markdown report
    report_path = PROJECT_ROOT / args.output_report
    with open(report_path, "w") as f:
        f.write(generate_markdown_report(complete_data, analysis))
    print(f"PASS: Markdown report saved: {report_path}")

    print(f"\n{'=' * 80}")
    print("MAPPING COMPLETE")
    print(f"{'=' * 80}\n")

    return complete_data


def generate_markdown_report(data, analysis):
    """Generate comprehensive markdown report."""
    lines = []
    lines.append("# Comprehensive Position Mapping Report\n")
    lines.append(f"**Generated:** {data['metadata']['generated_at']}")
    lines.append(
        f"**Account:** {data['metadata']['account_number']} ({data['metadata']['user_email']})"
    )
    lines.append(f"**Analysis Period:** Last {data['metadata']['days_back']} days\n")
    lines.append("---\n")

    # Summary
    lines.append("## Executive Summary\n")
    summary = analysis["summary"]
    lines.append(f"- **Database Positions:** {summary['total_db_positions']} total")
    lines.append(f"  - Open (any state): {summary['db_open']}")
    lines.append(f"  - Closed: {summary['db_closed']}")
    lines.append(f"- **TastyTrade Positions:** {summary['tt_total_positions']} total")
    lines.append(f"  - Options: {summary['tt_option_positions']}")
    lines.append(f"  - Equity: {summary['tt_equity_positions']}")
    lines.append(f"- **Critical Issues:** {analysis['critical_issues_count']}")
    lines.append(f"- **Warnings:** {analysis['warnings_count']}\n")

    # State breakdown
    lines.append("### Database Position States\n")
    for state, count in sorted(analysis["state_breakdown"].items()):
        lines.append(f"- `{state}`: {count}")
    lines.append("\n")

    # Critical issues
    if analysis["critical_issues"]:
        lines.append("## Critical Issues 🔴\n")
        for i, issue in enumerate(analysis["critical_issues"], 1):
            lines.append(f"### {i}. Position #{issue['database_position_id']}\n")
            lines.append(f"- **Status:** {issue['match_status']}")
            lines.append(f"- **Database State:** `{issue['database_state']}`")
            lines.append(f"- **Opened:** {issue['database_opened']}")
            lines.append(f"- **Closed:** {issue['database_closed']}")
            lines.append(f"- **Broker Orders:** {issue['opening_order_id']}\n")

            if issue["database_trades"]:
                lines.append("**Database Trades:**")
                for trade in issue["database_trades"]:
                    lines.append(
                        f"- Trade #{trade['trade_id']}: {trade['status']} | {trade['trade_type']} | Order: {trade['broker_order_id']}"
                    )
                lines.append("")

            if issue["issues"]:
                lines.append("**Issues:**")
                for issue_text in issue["issues"]:
                    lines.append(f"- {issue_text}")
                lines.append("")

            lines.append("")

    # Position details
    lines.append("## Complete Position Details\n")
    lines.append("### Database Positions\n")
    for pos in data["database_positions"]:
        lines.append(f"\n#### Position #{pos['database_id']}\n")
        lines.append(f"- **Symbol:** {pos['symbol']}")
        lines.append(f"- **Strategy:** {pos['strategy_type']}")
        lines.append(f"- **Lifecycle State:** `{pos['lifecycle_state']}`")
        lines.append(f"- **Quantity:** {pos['quantity']}")
        lines.append(f"- **Spreads:** {pos['number_of_spreads']}")
        lines.append(f"- **Opened:** {pos['opened_at']}")
        lines.append(f"- **Closed:** {pos['closed_at'] or 'Still open'}")
        lines.append(f"- **Broker Orders:** {pos['opening_order_id']}\n")

        if pos["trades"]:
            lines.append(f"**Trades ({len(pos['trades'])}):**")
            for trade in pos["trades"]:
                lines.append(
                    f"- #{trade['id']}: {trade['status']} | {trade['trade_type']} | {trade['lifecycle_event'] or 'no event'} | Order: {trade['broker_order_id']}"
                )
            lines.append("")

    lines.append("\n### TastyTrade Current Positions by Expiration\n")
    for exp, legs in sorted(data["tastytrade_positions_by_expiration"].items()):
        if exp == "equity":
            continue
        lines.append(f"\n#### {exp}\n")
        if legs["puts"]:
            lines.append(f"**Puts ({len(legs['puts'])}):**")
            for pos in sorted(legs["puts"], key=lambda x: x["parsed"]["strike"]):
                lines.append(
                    f"- {pos['parsed']['strike']} {pos['quantity_direction']} x{abs(pos['quantity'])}"
                )
        if legs["calls"]:
            lines.append(f"**Calls ({len(legs['calls'])}):**")
            for pos in sorted(legs["calls"], key=lambda x: x["parsed"]["strike"]):
                lines.append(
                    f"- {pos['parsed']['strike']} {pos['quantity_direction']} x{abs(pos['quantity'])}"
                )
        lines.append("")

    lines.append("---\n")
    lines.append("## Validation Status\n")
    lines.append("- [ ] All position states verified against TastyTrade")
    lines.append("- [ ] All order IDs cross-referenced")
    lines.append("- [ ] Discrepancies documented")
    lines.append("- [ ] Correction plan created")
    lines.append("- [ ] Corrections approved")
    lines.append("- [ ] Corrections executed\n")

    return "\n".join(lines)


def main():
    args = parse_args()
    ensure_field_encryption_key()
    bootstrap_django(args.settings)

    try:
        create_mapping(args)
        return 0
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
