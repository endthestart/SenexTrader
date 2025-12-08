#!/usr/bin/env python3
"""Generate an assignment + residual put report for QQQ using live TastyTrade data."""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback if dependency missing
    load_dotenv = None  # type: ignore[assignment]


def load_env_file() -> None:
    if load_dotenv is None:
        return
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


load_env_file()

ASSIGNMENT_KEYWORDS = {
    "assignment",
    "assigned",
    "exercise",
    "exercised",
    "delivery",
    "deliver",
}


@dataclass
class LegRecord:
    order_id: int
    complex_id: str | int | None
    action: str
    quantity: Decimal
    status: str
    received_at: datetime | None
    order: object | None


@dataclass
class AssignmentNode:
    chain_id: int
    chain_description: str
    node_type: str | None
    description: str | None
    occurred_at: datetime | None
    option_legs: list[str]
    equity_legs: list[str]
    raw_node: object | None
    linked_symbols: set[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Connect to TastyTrade via stored refresh token and build a QQQ assignment report."
        )
    )
    parser.add_argument(
        "--user-email",
        help="Target user email (defaults to whoever owns the primary production account)",
    )
    parser.add_argument(
        "--account-number",
        help="Specific TastyTrade account number to inspect (defaults to the primary production account)",
    )
    parser.add_argument(
        "--symbol",
        default="QQQ",
        help="Underlying symbol to analyze (default: QQQ)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="How many days back to inspect (default: 60, roughly two months)",
    )
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "senextrader.settings.development"),
        help=(
            "Django settings module to use (defaults to senextrader.settings.development unless"
            " DJANGO_SETTINGS_MODULE is already set)"
        ),
    )
    parser.add_argument(
        "--show-all-nodes",
        action="store_true",
        help="Also list non-assignment nodes for each chain",
    )
    return parser.parse_args()


def ensure_field_encryption_key() -> None:
    load_env_file()
    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if key:
        return
    fallback = os.environ.get("DEFAULT_DEV_FIELD_ENCRYPTION_KEY")
    if fallback:
        os.environ["FIELD_ENCRYPTION_KEY"] = fallback
        print("[info] Using DEFAULT_DEV_FIELD_ENCRYPTION_KEY for encrypted fields.")
        return
    raise SystemExit("FIELD_ENCRYPTION_KEY is required to decrypt TradingAccount refresh tokens.")


def bootstrap_django(settings_module: str) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    import django

    django.setup()


def resolve_user_and_account(args: argparse.Namespace):
    from django.contrib.auth import get_user_model

    from accounts.models import TradingAccount

    User = get_user_model()

    user = None
    if args.user_email:
        user = User.objects.filter(is_active=True).filter(email__iexact=args.user_email).first()
        if not user:
            raise SystemExit(f"No active user found for {args.user_email}")

    account_qs = TradingAccount.objects.filter(
        connection_type="TASTYTRADE",
        is_active=True,
        is_token_valid=True,
    )

    if user:
        account_qs = account_qs.filter(user=user)

    if args.account_number:
        account = account_qs.filter(account_number=args.account_number).first()
        if not account:
            target = user.email if user else "any user"
            raise SystemExit(
                f"Account {args.account_number} not found or missing valid token for {target}"
            )
    else:
        # Prefer primary production account from the database
        account = account_qs.filter(is_primary=True, is_test=False).first()
        if not account:
            account = account_qs.filter(is_primary=True).first()
        if not account:
            account = account_qs.filter(is_test=False).first()
        if not account:
            account = account_qs.first()
        if not account:
            raise SystemExit("No active TastyTrade accounts available with valid tokens")

    if not user:
        user = account.user

    if not account.refresh_token:
        raise SystemExit(f"Account {account.account_number} has no refresh token")

    return user, account


def build_session(account) -> Session:
    from asgiref.sync import async_to_sync

    from services.brokers.tastytrade.session import TastyTradeSessionService

    result = async_to_sync(TastyTradeSessionService.get_session_for_user)(
        account.user_id, account.refresh_token, is_test=account.is_test
    )
    if not result.get("success"):
        raise SystemExit(f"Failed to create TastyTrade session: {result.get('error')}")
    return result["session"]


def parse_occ_symbol(symbol: str) -> dict[str, object] | None:
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


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "-"
    try:
        return f"${Decimal(value):,.2f}"
    except Exception:
        return str(value)


def format_quantity(qty) -> str:
    if qty is None:
        return "0"
    try:
        qty_decimal = Decimal(str(qty))
    except Exception:
        return str(qty)
    as_int = int(qty_decimal)
    if Decimal(as_int) == qty_decimal:
        return str(as_int)
    return f"{qty_decimal:.2f}"


def describe_leg(leg) -> str:
    details = parse_occ_symbol(leg.symbol)
    suffix = ""
    if details:
        exp = details["expiration"]
        strike = details["strike"]
        opt_type = details["type"]
        suffix = f" ({exp} {strike} {opt_type})"
    return (
        f"{leg.action.value if hasattr(leg.action, 'value') else leg.action} "
        f"{format_quantity(leg.fill_quantity or leg.order_quantity)} x {leg.symbol}{suffix}"
    )


def describe_entry(entry) -> str:
    base_qty = format_quantity(entry.quantity_numeric)
    suffix = ""
    symbol = (entry.symbol or "?").strip()
    instrument_name = getattr(entry.instrument_type, "value", entry.instrument_type)
    if instrument_name == "Equity Option":
        details = parse_occ_symbol(symbol)
        if details:
            suffix = f" ({details['expiration']} {details['strike']} {details['type']})"
    return f"{entry.quantity_type} {base_qty} x {symbol}{suffix}"


def find_assignment_nodes(chains: Sequence[OrderChain], symbol: str) -> list[AssignmentNode]:
    from tastytrade.order import InstrumentType

    significant_nodes: list[AssignmentNode] = []
    symbol_upper = symbol.upper()

    for chain in chains:
        for node in chain.lite_nodes or []:
            text = " ".join(filter(None, [node.description, node.node_type or ""])).lower()
            has_keyword = any(word in text for word in ASSIGNMENT_KEYWORDS)
            option_legs: list[str] = []
            equity_legs: list[str] = []
            linked_symbols: set[str] = set()

            for leg in node.legs or []:
                if leg.instrument_type == InstrumentType.EQUITY_OPTION:
                    option_legs.append(describe_leg(leg))
                if leg.instrument_type == InstrumentType.EQUITY:
                    equity_legs.append(describe_leg(leg))
                if getattr(leg, "symbol", None):
                    linked_symbols.add(leg.symbol.strip())

            entry_symbols = {
                (entry.symbol or "").strip(): entry for entry in node.entries or [] if entry.symbol
            }
            linked_symbols.update(entry_symbols.keys())
            has_symbol_match = any(sym.startswith(symbol_upper) for sym in entry_symbols)
            equity_entries = [
                entry
                for entry in node.entries or []
                if getattr(entry.instrument_type, "value", entry.instrument_type)
                == InstrumentType.EQUITY.value
            ]

            if has_keyword or equity_legs or equity_entries or has_symbol_match:
                significant_nodes.append(
                    AssignmentNode(
                        chain_id=chain.id,
                        chain_description=chain.description,
                        node_type=node.node_type,
                        description=node.description,
                        occurred_at=node.occurred_at,
                        option_legs=option_legs,
                        equity_legs=equity_legs,
                        raw_node=node,
                        linked_symbols=linked_symbols,
                    )
                )
    return significant_nodes


def collect_account_data(account, session, symbol: str, start_dt: datetime, end_dt: datetime):
    from tastytrade.account import Account
    from tastytrade.order import InstrumentType

    tt_account = Account.get(session, account.account_number)

    chains: list = []
    transactions: list = []
    positions: list = []
    orders: list = []
    chain_warning: str | None = "Order chains disabled (VAST endpoint blocked)"

    # NOTE: VAST (order chain) endpoint rejects OAuth partner tokens; skip call for now.
    # Leaving chains empty avoids repeated warnings while we reconstruct lifecycle manually
    # from orders + transactions.

    try:
        transactions = tt_account.get_history(
            session,
            start_date=start_dt.date(),
            end_date=end_dt.date(),
            underlying_symbol=symbol,
            page_offset=None,
        )
    except Exception as exc:
        print(f"[warn] Failed to fetch transaction history: {exc}")

    try:
        orders = tt_account.get_order_history(
            session,
            start_date=start_dt.date(),
        )
    except Exception as exc:
        print(f"[warn] Failed to fetch order history: {exc}")

    try:
        positions = tt_account.get_positions(
            session,
            underlying_symbols=[symbol],
            include_marks=True,
        )
    except Exception as exc:
        print(f"[warn] Failed to fetch positions: {exc}")

    equity_positions = [
        pos
        for pos in positions
        if pos.instrument_type == InstrumentType.EQUITY and pos.symbol.upper() == symbol.upper()
    ]

    option_positions = [
        pos for pos in positions if pos.instrument_type == InstrumentType.EQUITY_OPTION
    ]

    filtered_orders = [order for order in orders if order.underlying_symbol == symbol]

    return chains, transactions, filtered_orders, equity_positions, option_positions, chain_warning


def summarize_positions(equity_positions, option_positions, symbol: str):
    long_stock = None
    total_shares = Decimal("0")
    total_cost = Decimal("0")

    for pos in equity_positions:
        qty = Decimal(pos.quantity)
        if qty <= 0:
            continue
        avg_price = Decimal(pos.average_open_price or 0)
        total_shares += qty
        total_cost += qty * avg_price

    if total_shares > 0:
        avg_price = total_cost / total_shares if total_cost else Decimal("0")
        long_stock = SimpleNamespace(
            quantity=total_shares,
            average_open_price=avg_price,
        )

    long_puts = []
    for pos in option_positions:
        if pos.quantity <= 0:
            continue
        details = parse_occ_symbol(pos.symbol)
        if not details or details.get("type") != "Put":
            continue
        if details.get("root", "").upper() != symbol.upper():
            continue
        long_puts.append(
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "expiration": details.get("expiration"),
                "strike": details.get("strike"),
                "avg_price": pos.average_open_price,
                "mark": pos.mark_price or pos.mark,
            }
        )

    def sort_key(item):
        exp = item["expiration"] or date.max
        strike = item["strike"] if item["strike"] is not None else Decimal("0")
        return (exp, strike)

    return long_stock, sorted(long_puts, key=sort_key)


def summarize_transactions(transactions) -> list:
    summary = []
    for tx in transactions:
        haystack = " ".join(
            filter(
                None,
                [tx.transaction_type, tx.transaction_sub_type, tx.description],
            )
        ).lower()
        if any(word in haystack for word in ASSIGNMENT_KEYWORDS):
            summary.append(tx)
    return summary


def synthesize_assignment_nodes_from_transactions(transactions) -> list[AssignmentNode]:
    nodes: list[AssignmentNode] = []
    for tx in transactions:
        description = tx.description or f"{tx.transaction_type} / {tx.transaction_sub_type}"
        quantity = format_quantity(tx.quantity)
        symbol = (tx.symbol or "").strip()
        linked_symbols = {symbol} if symbol else set()
        option_legs: list[str] = []
        equity_legs: list[str] = []
        leg_desc = f"{tx.transaction_sub_type or tx.action or '-'} {quantity} x {symbol or '?'}"
        if " " in symbol.strip():
            option_legs.append(leg_desc)
        elif symbol:
            equity_legs.append(leg_desc)
        nodes.append(
            AssignmentNode(
                chain_id=0,
                chain_description="Transaction Ledger",
                node_type=tx.transaction_sub_type or tx.transaction_type,
                description=description,
                occurred_at=tx.executed_at,
                option_legs=option_legs,
                equity_legs=equity_legs,
                raw_node=None,
                linked_symbols=linked_symbols,
            )
        )
    return nodes


def build_assignment_map(nodes: Iterable[AssignmentNode]):
    mapping = defaultdict(list)
    for node in nodes:
        for symbol in node.linked_symbols:
            mapping[symbol].append(node)
    return mapping


def build_order_indices(
    orders: list,
) -> tuple[
    dict[str, list[LegRecord]],
    dict[object, list[tuple[str, LegRecord]]],
    dict[int, list[tuple[str, LegRecord]]],
]:
    legs_by_symbol: dict[str, list[LegRecord]] = defaultdict(list)
    complex_leg_map: dict[object, list[tuple[str, LegRecord]]] = defaultdict(list)
    order_leg_map: dict[int, list[tuple[str, LegRecord]]] = defaultdict(list)

    for order in orders:
        status = getattr(order.status, "value", str(order.status))
        received_at = getattr(order, "received_at", None)
        complex_id = getattr(order, "complex_order_id", None)
        for leg in getattr(order, "legs", []) or []:
            symbol = (getattr(leg, "symbol", "") or "").strip()
            if not symbol:
                continue
            action = getattr(leg.action, "value", str(getattr(leg, "action", "")))
            quantity = getattr(leg, "quantity", None)
            try:
                quantity_dec = Decimal(str(quantity)) if quantity is not None else Decimal("0")
            except Exception:
                quantity_dec = Decimal("0")
            order_id = getattr(order, "id", 0)
            record = LegRecord(
                order_id=order_id,
                complex_id=complex_id,
                action=action,
                quantity=quantity_dec,
                status=status,
                received_at=received_at,
                order=order,
            )
            legs_by_symbol[symbol].append(record)
            if complex_id:
                complex_leg_map[complex_id].append((symbol, record))
            order_leg_map[order_id].append((symbol, record))

    return legs_by_symbol, complex_leg_map, order_leg_map


def build_option_lookup(long_puts: list[dict]) -> dict[str, dict]:
    lookup = {}
    for put in long_puts:
        symbol = put.get("symbol")
        if symbol:
            lookup[symbol.strip()] = put
    return lookup


def analyze_assignments(
    assignment_transactions: list,
    legs_by_symbol: dict,
    complex_leg_map: dict,
    order_leg_map: dict,
    open_option_lookup: dict[str, dict],
) -> list[dict]:
    analysis = []
    for tx in assignment_transactions:
        symbol = (getattr(tx, "symbol", "") or "").strip()
        entry = {
            "transaction": tx,
            "symbol": symbol,
            "quantity": getattr(tx, "quantity", None),
            "matched_orders": [],
            "message": None,
        }
        leg_records = legs_by_symbol.get(symbol, [])
        seen_complex_ids = set()
        for leg in leg_records:
            complex_id = leg.complex_id
            if complex_id and complex_id in seen_complex_ids:
                continue
            seen_complex_ids.add(complex_id)
            partners = []
            if complex_id and complex_id in complex_leg_map:
                for partner_symbol, partner_leg in complex_leg_map[complex_id]:
                    if partner_symbol == symbol:
                        continue
                    partners.append(
                        {
                            "symbol": partner_symbol,
                            "action": partner_leg.action,
                            "quantity": partner_leg.quantity,
                            "open": partner_symbol in open_option_lookup,
                        }
                    )
            elif leg.order_id in order_leg_map:
                for partner_symbol, partner_leg in order_leg_map[leg.order_id]:
                    if partner_symbol == symbol:
                        continue
                    partners.append(
                        {
                            "symbol": partner_symbol,
                            "action": partner_leg.action,
                            "quantity": partner_leg.quantity,
                            "open": partner_symbol in open_option_lookup,
                        }
                    )
            entry["matched_orders"].append(
                {
                    "order_id": leg.order_id,
                    "complex_id": complex_id,
                    "partners": partners,
                }
            )
        if not leg_records:
            entry["message"] = "No originating order found for this assignment"
        elif all(not match.get("partners") for match in entry["matched_orders"]):
            entry["message"] = (
                "No partner legs currently linked; protective leg likely closed earlier or executed separately"
            )
        analysis.append(entry)
    return analysis


def print_section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def describe_datetime(value: datetime | None) -> str:
    if not value:
        return "-"
    if value.tzinfo:
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return value.strftime("%Y-%m-%d %H:%M:%S")


def render_report(
    user,
    account,
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    chains,
    assignment_nodes,
    long_stock,
    long_puts,
    assignment_transactions,
    assignment_lookup,
    assignment_analysis: list[dict],
    chain_warning: str | None = None,
    show_all_nodes: bool = False,
):
    print("=" * 80)
    print(f"QQQ Assignment Diagnostic | User={user.email} Account={account.account_number}")
    print("=" * 80)
    print(f"Window: {describe_datetime(start_dt)} -> {describe_datetime(end_dt)}")
    print(f"Symbol: {symbol.upper()}  |  Chains fetched: {len(chains)}")
    if chain_warning:
        print(f"[warning] Order chain data unavailable: {chain_warning}")

    print_section("Current Share/Option Snapshot")
    if long_stock:
        qty = format_quantity(long_stock.quantity)
        basis = format_money(long_stock.average_open_price)
        print(f"- Shares: {qty} {symbol.upper()} @ avg {basis}")
    else:
        print("- Shares: none")

    if long_puts:
        print("- Long puts still open:")
        for put in long_puts:
            expiration = put["expiration"] or "?"
            strike = put["strike"]
            qty = format_quantity(put["quantity"])
            avg = format_money(put["avg_price"])
            mark = format_money(put["mark"])
            symbol_key = put["symbol"].strip()
            match_label = "(linked to assignment)" if assignment_lookup.get(symbol_key) else ""
            print(
                f"  • {qty} x {put['symbol']} exp {expiration} strike {strike} avg {avg} mark {mark} {match_label}"
            )
    else:
        print("- No long puts currently open for this symbol")

    print_section("Assignment / Exercise Nodes")
    if assignment_nodes:
        for node in assignment_nodes:
            print(
                f"Chain #{node.chain_id} :: {node.chain_description}\n"
                f"  Node: {node.node_type or '-'} @ {describe_datetime(node.occurred_at)}\n"
                f"  Detail: {node.description or '-'}"
            )
            if node.option_legs:
                print("  Option legs:")
                for leg in node.option_legs:
                    print(f"    - {leg}")
            if node.equity_legs:
                print("  Equity legs:")
                for leg in node.equity_legs:
                    print(f"    - {leg}")
            if node.raw_node:
                entries = getattr(node.raw_node, "entries", [])
                if entries:
                    print("  Entries:")
                    for entry in entries:
                        print(f"    - {describe_entry(entry)}")
    else:
        print("No assignment-related nodes were detected in the fetched chains.")

    print_section("Residual Legs by Chain")
    any_open = False
    for chain in chains:
        open_entries = getattr(chain.computed_data, "open_entries", None) or []
        if not open_entries:
            continue
        any_open = True
        realized = format_money(chain.computed_data.realized_gain_with_fees)
        net_cost = format_money(chain.computed_data.total_cost)
        print(
            f"Chain #{chain.id} ({chain.description})\n"
            f"  Created: {describe_datetime(chain.created_at)} | Updated: {describe_datetime(chain.updated_at)}\n"
            f"  Realized (with fees): {realized} | Net cost: {net_cost}"
        )
        print("  Open entries:")
        for entry in open_entries:
            print(f"    - {describe_entry(entry)}")
    if not any_open:
        print("All chains are fully closed within the selected window.")

    print_section("Assignment Transactions (Ledger)")
    if assignment_transactions:
        for tx in assignment_transactions:
            print(
                f"- {describe_datetime(tx.executed_at)} | {tx.transaction_type} / {tx.transaction_sub_type} | "
                f"{tx.description} | Qty={format_quantity(tx.quantity)} | Price={format_money(tx.price)} | Symbol={tx.symbol}"
            )
    else:
        print("No transaction-level assignment entries located in the selected window.")

    print_assignment_analysis(assignment_analysis)

    if show_all_nodes:
        print_section("Full Chain Node Listing")
        for chain in chains:
            print(f"Chain #{chain.id} :: {chain.description}")
            for node in chain.lite_nodes or []:
                print(
                    f"  - {node.node_type or '-'} @ {describe_datetime(node.occurred_at)} :: {node.description or '-'}"
                )


def print_assignment_analysis(analysis: list[dict]):
    print_section("Assignment Reconstruction")
    if not analysis:
        print("No assignment events detected in the selected window.")
        return
    for entry in analysis:
        tx = entry["transaction"]
        symbol = entry["symbol"] or "?"
        timestamp = describe_datetime(getattr(tx, "executed_at", None))
        qty = format_quantity(entry["quantity"])
        print(
            f"- {timestamp} :: {symbol} :: qty {qty} :: {tx.transaction_type} / {tx.transaction_sub_type}"
        )
        if entry.get("message"):
            print(f"    {entry['message']}")
        for match in entry.get("matched_orders", []):
            order_id = match.get("order_id")
            complex_id = match.get("complex_id")
            header = "    Matched order"
            if order_id:
                header += f" #{order_id}"
            if complex_id:
                header += f" (complex {complex_id})"
            print(header)
            partners = match.get("partners", [])
            if not partners:
                print("        No partner legs identified for this order")
            for partner in partners:
                status = "OPEN" if partner.get("open") else "closed"
                print(
                    f"        Partner leg: {partner['symbol']} ({partner['action']}) qty {format_quantity(partner['quantity'])} -> {status}"
                )


def main() -> int:
    args = parse_args()
    ensure_field_encryption_key()
    bootstrap_django(args.settings)

    user, account = resolve_user_and_account(args)
    session = build_session(account)

    now_utc = datetime.now(UTC)
    end_dt = now_utc
    start_dt = end_dt - timedelta(days=args.days)

    (
        chains,
        transactions,
        orders,
        equity_positions,
        option_positions,
        chain_warning,
    ) = collect_account_data(account, session, args.symbol.upper(), start_dt, end_dt)

    assignment_transactions = summarize_transactions(transactions)

    assignment_nodes = find_assignment_nodes(chains, args.symbol)
    if not assignment_nodes and assignment_transactions:
        assignment_nodes = synthesize_assignment_nodes_from_transactions(assignment_transactions)
    assignment_lookup = build_assignment_map(assignment_nodes)

    long_stock, long_puts = summarize_positions(equity_positions, option_positions, args.symbol)

    legs_by_symbol, complex_leg_map, order_leg_map = build_order_indices(orders)
    open_option_lookup = build_option_lookup(long_puts)
    assignment_analysis = analyze_assignments(
        assignment_transactions,
        legs_by_symbol,
        complex_leg_map,
        order_leg_map,
        open_option_lookup,
    )

    render_report(
        user,
        account,
        args.symbol,
        start_dt,
        end_dt,
        chains,
        assignment_nodes,
        long_stock,
        long_puts,
        assignment_transactions,
        assignment_lookup,
        assignment_analysis,
        chain_warning=chain_warning,
        show_all_nodes=args.show_all_nodes,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
