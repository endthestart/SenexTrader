#!/usr/bin/env python3
"""
Position Reconciliation via Process of Elimination

Strategy:
1. Load TastyTrade current positions (37 option legs across 6 expirations)
2. Load all database positions with their opening order IDs
3. Match each TastyTrade leg to database positions via order history
4. Use process of elimination to determine which DB positions are actually closed
5. Generate specific correction SQL for each discrepancy

This creates an exact mapping based on transaction evidence.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load the mapping data we generated
with open(PROJECT_ROOT / "position_mapping_data.json") as f:
    data = json.load(f)

print("=" * 80)
print("POSITION RECONCILIATION VIA PROCESS OF ELIMINATION")
print("=" * 80)
print()

# Step 1: Organize TastyTrade current positions by expiration and OCC symbol
print("### STEP 1: Current TastyTrade Positions ###")
print()

tt_legs_by_symbol = {}
tt_by_expiration = data["tastytrade_positions_by_expiration"]

for exp, legs_data in sorted(tt_by_expiration.items()):
    if exp == "equity":
        continue

    print(f"\nExpiration: {exp}")

    # Process puts
    for put_leg in legs_data.get("puts", []):
        symbol = put_leg["symbol"]
        tt_legs_by_symbol[symbol] = {
            "expiration": exp,
            "type": "Put",
            "strike": put_leg["parsed"]["strike"],
            "quantity": put_leg["quantity"],
            "direction": put_leg["quantity_direction"],
        }
        qty = put_leg["quantity"]
        if isinstance(qty, str):
            qty = int(float(qty))
        print(f"  {symbol}: {put_leg['quantity_direction']} x{abs(qty)}")

    # Process calls
    for call_leg in legs_data.get("calls", []):
        symbol = call_leg["symbol"]
        tt_legs_by_symbol[symbol] = {
            "expiration": exp,
            "type": "Call",
            "strike": call_leg["parsed"]["strike"],
            "quantity": call_leg["quantity"],
            "direction": call_leg["quantity_direction"],
        }
        qty = call_leg["quantity"]
        if isinstance(qty, str):
            qty = int(float(qty))
        print(f"  {symbol}: {call_leg['quantity_direction']} x{abs(qty)}")

print(f"\nTotal TastyTrade legs: {len(tt_legs_by_symbol)}")

# Step 2: Organize database positions by state
print()
print("### STEP 2: Database Positions ###")
print()

db_positions = data["database_positions"]
by_state = defaultdict(list)

for pos in db_positions:
    by_state[pos["lifecycle_state"]].append(pos)

for state in ["open_full", "open_partial", "closed"]:
    positions = by_state[state]
    print(f"\n{state.upper()}: {len(positions)} positions")
    for pos in sorted(positions, key=lambda x: x["database_id"]):
        opened = pos["opened_at"][:10] if pos["opened_at"] else "unknown"
        print(
            f"  Position #{pos['database_id']}: opened {opened}, order: {pos['opening_order_id']}"
        )

# Step 3: Match positions to TastyTrade legs via order history
print()
print("### STEP 3: Matching via Order History ###")
print()

# Get order history organized by order ID
tt_orders_by_id = {}
for order in data["tastytrade_order_history"]:
    tt_orders_by_id[str(order["id"])] = order

# Now try to match each database position to current TastyTrade legs
matched_positions = []
unmatched_positions = []

for pos in db_positions:
    pos_id = pos["database_id"]
    state = pos["lifecycle_state"]

    # Get the opening order
    opening_order_id = pos.get("opening_order_id")
    if not opening_order_id:
        print(f"Position #{pos_id}: No opening order ID")
        unmatched_positions.append(
            {
                "position": pos,
                "reason": "No opening order ID",
                "action": "manual_review",
            }
        )
        continue

    opening_order_id = str(opening_order_id)

    # Check if this order is in our 90-day history
    if opening_order_id not in tt_orders_by_id:
        print(
            f"Position #{pos_id}: Order {opening_order_id} not in 90-day history (opened {pos['opened_at'][:10] if pos['opened_at'] else 'unknown'})"
        )

        # For positions older than 90 days, we need to infer from current state
        if state == "closed":
            # If marked closed and order is old, likely truly closed
            unmatched_positions.append(
                {
                    "position": pos,
                    "reason": f"Order {opening_order_id} older than 90 days, position marked closed",
                    "action": "close_trades_keep_closed",
                    "inference": "Position is old and marked closed, likely correct",
                }
            )
        else:
            # If marked open but order is old, need to check if legs exist
            unmatched_positions.append(
                {
                    "position": pos,
                    "reason": f"Order {opening_order_id} older than 90 days, position marked {state}",
                    "action": "manual_review",
                    "inference": "Cannot verify without older order history",
                }
            )
        continue

    # We have the order - extract the leg symbols
    order = tt_orders_by_id[opening_order_id]
    order_leg_symbols = {leg["symbol"] for leg in order["legs"]}

    # Check how many of these legs still exist at TastyTrade
    legs_still_open = [sym for sym in order_leg_symbols if sym in tt_legs_by_symbol]

    match_info = {
        "position_id": pos_id,
        "state": state,
        "opening_order_id": opening_order_id,
        "original_legs": len(order_leg_symbols),
        "legs_still_open": len(legs_still_open),
        "leg_symbols": list(order_leg_symbols),
        "open_symbols": legs_still_open,
        "order_date": order.get("received_at", "unknown")[:10],
    }

    # Determine correct state based on legs
    if len(legs_still_open) == 0:
        correct_state = "closed"
    elif len(legs_still_open) == len(order_leg_symbols):
        correct_state = "open_full"
    else:
        correct_state = "open_partial"

    match_info["correct_state"] = correct_state
    match_info["needs_correction"] = state != correct_state

    if match_info["needs_correction"]:
        print(
            f"Position #{pos_id}: {state} → {correct_state} ({len(legs_still_open)}/{len(order_leg_symbols)} legs at broker)"
        )
    else:
        print(
            f"Position #{pos_id}: {state} PASS: ({len(legs_still_open)}/{len(order_leg_symbols)} legs)"
        )

    matched_positions.append(match_info)

print()
print(f"Matched: {len(matched_positions)} positions")
print(f"Unmatched: {len(unmatched_positions)} positions")

# Step 4: Identify which positions need correction
print()
print("### STEP 4: Positions Needing Correction ###")
print()

corrections_needed = [m for m in matched_positions if m["needs_correction"]]

print(f"Total corrections needed: {len(corrections_needed)}")
print()

for correction in corrections_needed:
    print(f"Position #{correction['position_id']}:")
    print(f"  Current state: {correction['state']}")
    print(f"  Correct state: {correction['correct_state']}")
    print(f"  Legs at broker: {correction['legs_still_open']}/{correction['original_legs']}")
    print(f"  Opening order: {correction['opening_order_id']} ({correction['order_date']})")
    print()

# Step 5: Account for all TastyTrade legs
print("### STEP 5: Accounting for All TastyTrade Legs ###")
print()

# Track which TastyTrade legs have been accounted for
accounted_legs = set()

for match in matched_positions:
    for symbol in match["open_symbols"]:
        accounted_legs.add(symbol)

unaccounted_legs = set(tt_legs_by_symbol.keys()) - accounted_legs

print(f"TastyTrade legs accounted for: {len(accounted_legs)}/{len(tt_legs_by_symbol)}")
print(f"Unaccounted legs: {len(unaccounted_legs)}")

if unaccounted_legs:
    print()
    print("Unaccounted TastyTrade legs (not matched to any DB position):")
    for symbol in sorted(unaccounted_legs):
        leg = tt_legs_by_symbol[symbol]
        print(f"  {symbol}: {leg['type']} ${leg['strike']} exp {leg['expiration']}")
    print()
    print("These may be:")
    print("  - Manual positions (not app-managed)")
    print("  - Positions from old DB records outside our query")
    print("  - Legs from positions we couldn't match (>90 days old)")

# Step 6: Generate correction SQL
print()
print("### STEP 6: Correction Plan ###")
print()

corrections = []

# Group 1: Positions with state mismatch (have order in history)
for correction in corrections_needed:
    pos_id = correction["position_id"]
    current = correction["state"]
    correct = correction["correct_state"]

    # Find the actual position object to get trade info
    pos = next(p for p in db_positions if p["database_id"] == pos_id)

    correction_record = {
        "position_id": pos_id,
        "current_state": current,
        "correct_state": correct,
        "action": None,
        "sql": [],
    }

    if correct == "closed" and current != "closed":
        # Position should be closed but isn't
        correction_record["action"] = "close_position_and_trades"
        correction_record["sql"].append(
            f"UPDATE trading_position SET lifecycle_state = 'closed', closed_at = NOW() WHERE id = {pos_id};"
        )
        # Also close any active trades
        correction_record["sql"].append(
            f"UPDATE trading_trade SET status = 'closed', lifecycle_event = 'close' "
            f"WHERE position_id = {pos_id} AND status IN ('filled', 'submitted', 'live');"
        )

    elif correct != "closed" and current == "closed":
        # Position marked closed but should be open
        correction_record["action"] = "reopen_position"
        correction_record["sql"].append(
            f"UPDATE trading_position SET lifecycle_state = '{correct}', closed_at = NULL WHERE id = {pos_id};"
        )

    elif correct != current:
        # State transition between open_full and open_partial
        correction_record["action"] = "update_state"
        correction_record["sql"].append(
            f"UPDATE trading_position SET lifecycle_state = '{correct}' WHERE id = {pos_id};"
        )

    corrections.append(correction_record)

# Group 2: Unmatched positions (older than 90 days)
for unmatched in unmatched_positions:
    pos = unmatched["position"]
    pos_id = pos["database_id"]

    if unmatched["action"] == "close_trades_keep_closed":
        # Position is closed and old - just need to close the trades
        correction_record = {
            "position_id": pos_id,
            "current_state": pos["lifecycle_state"],
            "correct_state": "closed",
            "action": "close_trades_only",
            "sql": [
                f"UPDATE trading_trade SET status = 'closed', lifecycle_event = 'close' "
                f"WHERE position_id = {pos_id} AND status IN ('filled', 'submitted', 'live');"
            ],
            "note": unmatched["inference"],
        }
        corrections.append(correction_record)

# Print correction summary
print("Correction Summary:")
print(f"  Positions to close: {sum(1 for c in corrections if 'close_position' in c['action'])}")
print(f"  Positions to reopen: {sum(1 for c in corrections if c['action'] == 'reopen_position')}")
print(f"  State updates: {sum(1 for c in corrections if c['action'] == 'update_state')}")
print(f"  Trade cleanups: {sum(1 for c in corrections if c['action'] == 'close_trades_only')}")
print()

# Write detailed correction plan
output_file = PROJECT_ROOT / "position_correction_plan.md"
with open(output_file, "w") as f:
    f.write("# Position Correction Plan\n\n")
    f.write(f"**Generated:** {data['metadata']['generated_at']}\n")
    f.write("**Based on:** Process of elimination using order history\n\n")
    f.write("---\n\n")

    f.write("## Summary\n\n")
    f.write(f"- Total corrections: {len(corrections)}\n")
    f.write(f"- Positions matched via order history: {len(matched_positions)}\n")
    f.write(f"- Positions outside 90-day window: {len(unmatched_positions)}\n")
    f.write(f"- TastyTrade legs accounted for: {len(accounted_legs)}/{len(tt_legs_by_symbol)}\n\n")

    if unaccounted_legs:
        f.write(f"## Unaccounted TastyTrade Legs ({len(unaccounted_legs)})\n\n")
        f.write("These legs exist at TastyTrade but are not matched to any database position:\n\n")
        for symbol in sorted(unaccounted_legs):
            leg = tt_legs_by_symbol[symbol]
            f.write(f"- `{symbol}`: {leg['type']} ${leg['strike']} exp {leg['expiration']}\n")
        f.write("\n**Likely reasons:**\n")
        f.write("- Manual positions (not app-managed) [OK]\n")
        f.write("- Positions older than our database query range\n\n")

    f.write("## Corrections Needed\n\n")

    for i, correction in enumerate(corrections, 1):
        f.write(f"### {i}. Position #{correction['position_id']}\n\n")
        f.write(f"- **Current State:** `{correction['current_state']}`\n")
        f.write(f"- **Correct State:** `{correction['correct_state']}`\n")
        f.write(f"- **Action:** {correction['action']}\n")
        if "note" in correction:
            f.write(f"- **Note:** {correction['note']}\n")
        f.write("\n**SQL:**\n```sql\n")
        for sql in correction["sql"]:
            f.write(sql + "\n")
        f.write("```\n\n")

    f.write("---\n\n")
    f.write("## Execution Plan\n\n")
    f.write("1. Review all corrections above\n")
    f.write("2. Backup production database\n")
    f.write("3. Execute SQL in transaction (with rollback capability)\n")
    f.write("4. Re-run position mapping to verify corrections\n")
    f.write("5. Validate against TastyTrade\n\n")

print(f"Correction plan written to: {output_file}")

# Also save a JSON version for programmatic use
import json

json_file = PROJECT_ROOT / "position_corrections.json"
with open(json_file, "w") as f:
    json.dump(
        {
            "summary": {
                "total_corrections": len(corrections),
                "matched_positions": len(matched_positions),
                "unmatched_positions": len(unmatched_positions),
                "tt_legs_total": len(tt_legs_by_symbol),
                "tt_legs_accounted": len(accounted_legs),
                "tt_legs_unaccounted": len(unaccounted_legs),
            },
            "unaccounted_legs": [
                {"symbol": symbol, **tt_legs_by_symbol[symbol]}
                for symbol in sorted(unaccounted_legs)
            ],
            "corrections": corrections,
        },
        f,
        indent=2,
    )

print(f"Correction data written to: {json_file}")
print()
print("=" * 80)
print("RECONCILIATION COMPLETE")
print("=" * 80)
