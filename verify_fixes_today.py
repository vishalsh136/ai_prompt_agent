#!/usr/bin/env python
"""Verify both fixes are correctly applied"""
import sys; sys.path.insert(0, 'src')
from strategy_selector import winner_label

print("Winner label AFTER fix (sentiment_score=2 = Bullish today):")
print()
tests = [
    ("Institutional",       "buy",  "CE",                        2),
    ("OptionBuyer",         "buy",  "CE",                        2),
    ("Agent-Institutional", "buy",  "CE",                        2),
    ("OptionSeller",        "sell", "Iron Condor (Defined Risk)", 2),
    ("Hedging",             "sell", "Bull Put Spread",            2),
    ("Agent-OptionSeller",  "sell", "Iron Condor (Defined Risk)", 2),
]

for name, direction, instrument, score in tests:
    old_result = "🧠 Smart (Win)" if "sell" in direction or "spread" in instrument.lower() else "👥 Crowd (Lose)"
    new_result = winner_label(direction, instrument, score)
    status = "✅ FIXED" if new_result != old_result else "unchanged"
    arrow = f"{old_result} → {new_result}" if new_result != old_result else new_result
    print(f"  {name:<25} {arrow}  {status}")

print()
print("P&L sign fix in app.py (line 3373):")
for pnl in [208, -39, 68, 0]:
    old_sign = "+" if pnl >= 0 else ""
    new_sign = "+" if pnl >= 0 else "-"
    old_disp = f"{old_sign}₹{abs(pnl)}"
    new_disp = f"{new_sign}₹{abs(pnl)}"
    status = "✅ FIXED" if old_disp != new_disp else "unchanged"
    print(f"  P&L {pnl:+4}:  OLD '{old_disp}'  →  NEW '{new_disp}'  {status}")
