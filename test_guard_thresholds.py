#!/usr/bin/env python
"""Test which guard thresholds would have blocked today's losing trades"""
import sys; sys.path.insert(0, 'src')
from pathlib import Path
from real_data_loader import load_price_history

hist = load_price_history("downloads/app_historical_NIFTY.csv")
close_s = hist["close"]
prev_c  = close_s.shift(1).fillna(close_s)
tr = ((hist["high"]-hist["low"]).combine((hist["high"]-prev_c).abs(),max)
      .combine((hist["low"]-prev_c).abs(),max))
atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

# TODAY'S FAILING TRADE PARAMS
entry_premium  = 87.20    # CE 24400 at entry (13:41)
strike         = 24400
spot_at_entry  = 24417.0  # approximate spot when trade entered
opt_type       = "CE"
breakeven      = strike + entry_premium  # 24487
move_needed    = breakeven - spot_at_entry  # 70pts

print(f"ATR(14): {atr14:.1f}pts")
print(f"Entry premium: ₹{entry_premium}")
print(f"Breakeven: ₹{breakeven:.0f} (need spot > this to profit)")
print(f"Spot at entry: ₹{spot_at_entry:.0f}")
print(f"Move needed: {move_needed:.0f}pts")
print()
print("Guard threshold analysis:")
print(f"{'ATR% Threshold':<20} {'Breakeven Guard':<25} {'Premium Guard':<25} {'WOULD BLOCK?'}")
print("─" * 80)

for pct in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]:
    atr_threshold = atr14 * pct
    breakeven_blocks = move_needed > atr_threshold
    premium_blocks   = entry_premium > atr_threshold
    either_blocks    = breakeven_blocks or premium_blocks
    
    marker = "← BLOCKS ✅" if either_blocks else "passes ❌"
    print(f"{pct*100:.0f}% = {atr_threshold:.0f}pts  "
          f"  breakeven({move_needed:.0f}>{atr_threshold:.0f}): {'BLOCK' if breakeven_blocks else 'pass':<6}"
          f"  premium({entry_premium:.0f}>{atr_threshold:.0f}): {'BLOCK' if premium_blocks else 'pass':<6}"
          f"  {marker}")

print()
print(f"✅ Setting both guards at 45% of ATR = {atr14*0.45:.0f}pts would block this trade:")
print(f"   Premium ₹{entry_premium} > 45%×ATR ₹{atr14*0.45:.0f} → EXPENSIVE_PREMIUM → SKIP")
print()

# Also test valid entries that should NOT be blocked
print("Checking valid entries that should NOT be blocked at 45% ATR threshold:")
valid_entries = [
    ("Low vol entry",    24400, 65.0,  24380.0, "CE"),  # smaller premium
    ("OTM entry",        24500, 50.0,  24400.0, "CE"),  # OTM - cheaper
    ("Bullish strong",   24400, 75.0,  24420.0, "CE"),  # tight breakeven
]
for label, stk, prem, spot_e, otp in valid_entries:
    be = stk + prem if otp == "CE" else stk - prem
    mn = abs(be - spot_e)
    threshold = atr14 * 0.45
    b1 = mn > threshold; b2 = prem > threshold
    result = "BLOCKED ⚠" if (b1 or b2) else "ALLOWED ✅"
    print(f"  {label:<22} premium={prem:<6} need={mn:.0f}pts  threshold={threshold:.0f}pts  → {result}")
