#!/usr/bin/env python3
"""
Production Position Reconciliation Analysis Script

Validates all app-managed positions against TastyTrade and produces a detailed
report of discrepancies, with recommendations for database corrections.

Usage:
    python scripts/position_reconciliation_analysis.py --settings=senextrader.settings.production
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Analyze position sync issues and create correction plan"
    )
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "senextrader.settings.development"),
        help="Django settings module",
    )
    parser.add_argument(
        "--output",
        default="position_reconciliation_report.md",
        help="Output report filename",
    )
    return parser.parse_args()


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
        "expiration": expiry,
        "type": option_type,
        "strike": strike,
    }


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


def group_tt_legs_into_spreads(tt_positions):
    """
    Group TastyTrade option legs into logical spreads.

    For Senex Trident (3 spreads = 6 legs):
    - 2 put spreads (4 legs)
    - 1 call spread (2 legs)

    Returns list of spread groups with their component legs.
    """
    by_expiration = defaultdict(lambda: {"puts": [], "calls": []})

    for pos in tt_positions:
        parsed = parse_occ_symbol(pos.symbol)
        if not parsed:
            continue

        exp_key = parsed["expiration"]
        if parsed["type"] == "Put":
            by_expiration[exp_key]["puts"].append(pos)
        else:
            by_expiration[exp_key]["calls"].append(pos)

    spreads = []
    for exp_date, legs in by_expiration.items():
        # Sort by strike
        puts = sorted(legs["puts"], key=lambda p: parse_occ_symbol(p.symbol)["strike"])
        calls = sorted(legs["calls"], key=lambda p: parse_occ_symbol(p.symbol)["strike"])

        # Group puts into spreads (pairs with short position)
        put_spreads = []
        i = 0
        while i < len(puts) - 1:
            # Look for adjacent strikes forming a spread
            if puts[i].quantity_direction == "Short" or puts[i + 1].quantity_direction == "Short":
                put_spreads.append(
                    {
                        "type": "put_spread",
                        "expiration": exp_date,
                        "legs": [puts[i], puts[i + 1]],
                        "quantity": abs(puts[i].quantity),
                    }
                )
                i += 2
            else:
                i += 1

        # Group calls into spreads
        call_spreads = []
        i = 0
        while i < len(calls) - 1:
            if calls[i].quantity_direction == "Short" or calls[i + 1].quantity_direction == "Short":
                call_spreads.append(
                    {
                        "type": "call_spread",
                        "expiration": exp_date,
                        "legs": [calls[i], calls[i + 1]],
                        "quantity": abs(calls[i].quantity),
                    }
                )
                i += 2
            else:
                i += 1

        # A Senex Trident should have 2 put spreads + 1 call spread
        if len(put_spreads) == 2 and len(call_spreads) == 1:
            spreads.append(
                {
                    "strategy": "senex_trident",
                    "expiration": exp_date,
                    "put_spreads": put_spreads,
                    "call_spreads": call_spreads,
                    "total_legs": 6,
                    "status": "complete",
                }
            )
        elif len(put_spreads) > 0 or len(call_spreads) > 0:
            # Partial position
            spreads.append(
                {
                    "strategy": "senex_trident_partial",
                    "expiration": exp_date,
                    "put_spreads": put_spreads,
                    "call_spreads": call_spreads,
                    "total_legs": len(put_spreads) * 2 + len(call_spreads) * 2,
                    "status": "partial",
                }
            )

    return spreads


def analyze_positions(args):
    """Main analysis function."""
    from django.contrib.auth import get_user_model

    from tastytrade.account import Account

    from accounts.models import TradingAccount
    from trading.models import Position, Trade

    get_user_model()

    print("=" * 80)
    print("POSITION RECONCILIATION ANALYSIS")
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

    # Connect to TastyTrade
    print("\n### CONNECTING TO TASTYTRADE ###\n")
    session = build_session(account)
    tt_account = Account.get(session, account.account_number)
    tt_positions_all = tt_account.get_positions(session)

    # Filter to options only
    tt_option_positions = [p for p in tt_positions_all if p.instrument_type != "Equity"]

    print(
        f"TastyTrade positions: {len(tt_positions_all)} total, {len(tt_option_positions)} options"
    )

    # Get app-managed positions from database
    db_app_managed = (
        Position.objects.filter(
            user=account.user,
            is_app_managed=True,
        )
        .select_related("trading_account")
        .order_by("-opened_at")
    )

    db_open = db_app_managed.filter(lifecycle_state__in=["open_full", "open_partial"])

    db_closed_with_trades = []
    for pos in db_app_managed.filter(lifecycle_state="closed"):
        active_trades = Trade.objects.filter(
            position=pos,
            status__in=["submitted", "filled", "live", "received", "pending", "working"],
        ).count()
        if active_trades > 0:
            db_closed_with_trades.append((pos, active_trades))

    print("\nDatabase app-managed positions:")
    print(f"  - Open (any state): {db_open.count()}")
    print(f"  - Closed with active trades: {len(db_closed_with_trades)}")
    print(f"  - Total app-managed: {db_app_managed.count()}")

    # Group TastyTrade legs into spreads
    print("\n### ANALYZING TASTYTRADE SPREADS ###\n")
    tt_spreads = group_tt_legs_into_spreads(tt_option_positions)

    complete_tridents = [s for s in tt_spreads if s["strategy"] == "senex_trident"]
    partial_tridents = [s for s in tt_spreads if s["strategy"] == "senex_trident_partial"]

    print(f"Complete Senex Tridents at broker: {len(complete_tridents)}")
    print(f"Partial Senex Tridents at broker: {len(partial_tridents)}")

    # Build report
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "account": account.account_number,
        "user": account.user.email,
        "tastytrade": {
            "total_positions": len(tt_positions_all),
            "option_positions": len(tt_option_positions),
            "complete_tridents": len(complete_tridents),
            "partial_tridents": len(partial_tridents),
        },
        "database": {
            "app_managed_total": db_app_managed.count(),
            "open_positions": db_open.count(),
            "closed_with_active_trades": len(db_closed_with_trades),
        },
        "issues": [],
        "corrections": [],
    }

    # Issue 1: Closed positions with active trades
    if db_closed_with_trades:
        report["issues"].append(
            {
                "type": "closed_positions_with_active_trades",
                "severity": "HIGH",
                "count": len(db_closed_with_trades),
                "positions": [
                    {
                        "id": pos.id,
                        "symbol": pos.symbol,
                        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
                        "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
                        "active_trades": count,
                    }
                    for pos, count in db_closed_with_trades
                ],
            }
        )

    # Issue 2: Count mismatch
    expected_count = len(complete_tridents) + len(partial_tridents)
    if db_open.count() != expected_count:
        report["issues"].append(
            {
                "type": "position_count_mismatch",
                "severity": "MEDIUM",
                "tastytrade_count": expected_count,
                "database_count": db_open.count(),
                "difference": abs(expected_count - db_open.count()),
            }
        )

    # Generate report file
    output_path = PROJECT_ROOT / args.output
    with open(output_path, "w") as f:
        f.write(generate_markdown_report(report, tt_spreads, db_open, db_closed_with_trades))

    print(f"\nReport generated: {output_path}")
    print("\nSummary of issues found:")
    print(f"  - Closed positions with active trades: {len(db_closed_with_trades)}")
    print(f"  - Position count mismatch: {abs(expected_count - db_open.count())}")

    return report


def generate_markdown_report(report, tt_spreads, db_open, db_closed_with_trades):
    """Generate markdown report."""
    lines = []
    lines.append("# Position Reconciliation Analysis Report")
    lines.append(f"\n**Generated:** {report['timestamp']}")
    lines.append(f"**Account:** {report['account']} ({report['user']})")
    lines.append("\n---\n")

    lines.append("## Executive Summary\n")
    lines.append(f"- **TastyTrade:** {report['tastytrade']['option_positions']} option positions")
    lines.append(f"  - {report['tastytrade']['complete_tridents']} complete Senex Tridents")
    lines.append(f"  - {report['tastytrade']['partial_tridents']} partial Senex Tridents")
    lines.append(
        f"- **Database:** {report['database']['open_positions']} open app-managed positions"
    )
    lines.append(f"- **Issues:** {len(report['issues'])} critical issues found")

    lines.append("\n---\n")
    lines.append("## Issues Identified\n")

    for i, issue in enumerate(report["issues"], 1):
        lines.append(f"\n### Issue {i}: {issue['type'].replace('_', ' ').title()}")
        lines.append(f"**Severity:** {issue['severity']}\n")

        if issue["type"] == "closed_positions_with_active_trades":
            lines.append(f"**Count:** {issue['count']} positions\n")
            lines.append("| Position ID | Symbol | Opened | Closed | Active Trades |")
            lines.append("|-------------|--------|--------|--------|---------------|")
            for pos_info in issue["positions"]:
                lines.append(
                    f"| #{pos_info['id']} | {pos_info['symbol']} | "
                    f"{pos_info['opened_at'] or 'N/A'} | "
                    f"{pos_info['closed_at'] or 'N/A'} | "
                    f"{pos_info['active_trades']} |"
                )

        elif issue["type"] == "position_count_mismatch":
            lines.append(f"- TastyTrade: {issue['tastytrade_count']} positions")
            lines.append(f"- Database: {issue['database_count']} positions")
            lines.append(f"- **Difference: {issue['difference']}**")

    lines.append("\n---\n")
    lines.append("## Detailed Position Analysis\n")

    lines.append("\n### TastyTrade Positions (Grouped by Expiration)\n")
    for spread in tt_spreads:
        lines.append(f"\n**Expiration:** {spread['expiration']}")
        lines.append(f"**Strategy:** {spread['strategy']}")
        lines.append(f"**Status:** {spread['status']}")
        lines.append(f"**Total Legs:** {spread['total_legs']}")

    lines.append("\n### Database Open Positions\n")
    for pos in db_open:
        lines.append(f"\n- **Position #{pos.id}**")
        lines.append(f"  - Symbol: {pos.symbol}")
        lines.append(f"  - Lifecycle: {pos.lifecycle_state}")
        lines.append(f"  - Opened: {pos.opened_at}")
        lines.append(f"  - Quantity: {pos.quantity}")

    lines.append("\n---\n")
    lines.append("## Recommended Corrections\n")
    lines.append("\n*Will be generated after validation*\n")

    return "\n".join(lines)


def main():
    args = parse_args()
    ensure_field_encryption_key()
    bootstrap_django(args.settings)

    try:
        analyze_positions(args)
        return 0
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
