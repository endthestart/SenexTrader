#!/usr/bin/env python
"""
Quick test to verify volatility display issue.
Tests the market_conditions building logic.
"""

# Test case 1: current_iv = 0.2122 (21.22%)
current_iv = 0.2122
current_iv_pct = round(current_iv * 100, 1)
print(f"Test 1: current_iv={current_iv} → current_iv_pct={current_iv_pct}")
print(f"Expected: 21.2, Got: {current_iv_pct}")
print()

# Test case 2: What if it's already a percentage (2122)?
already_percentage = 2122.0
result_if_multiply = round(already_percentage * 100, 1)
print(f"Test 2: If current_iv was already {already_percentage}")
print(f"Then current_iv * 100 = {result_if_multiply}")
print(f"This would display as {result_if_multiply}%")
print()

# Test case 3: Confirm the JavaScript display
volatility_value = 2122.0
display = f"{volatility_value:.1f}%"
print(f"Test 3: JS displays volatility value {volatility_value}")
print(f"Result: '{display}'")
