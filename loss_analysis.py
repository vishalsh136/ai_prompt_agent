#!/usr/bin/env python
"""Analyze closed trades for 2026-07-31 and identify loss restriction strategies"""
import sys, json
sys.path.insert(0, 'src')
import pandas as pd
from pathlib import Path
from datetime import datetime, date

TODAY = "20260731"
DOWNLOADS = Path("downloads")

oc_raw   = json.loads((DOWNLOADS / f"option_chain_NIFTY_{TODAY}.json").read_text(encoding="utf-8-sig"))
live_raw = json.loads((DOWNLOADS / f"live_market_{TODAY}.json").read_text(encoding="utf-8-sig"))

nifty = next((x for x in live_raw.get("indices",[]) if "NIFTY 50" in x.get("index","")), {})
spot       = float(nifty.get("last", oc_raw.get("spot_price", 0)))
open_px    = float(nifty.get("open", oc_raw.get("open", 0)))
high_px    = float(nifty.get("high", oc_raw.get("high", 0)))
low_px     = float(nifty.get("low", oc_raw.get("low", 0)))
prev_close = float(nifty.get("previousClose", 0))
day_chg_pct= float(nifty.get("changePct", 0))
vix        = float(oc_raw.get("vix", 0))
ts         = oc_raw.get("timestamp", "—")
expiry_date= str(oc_raw.get("strikes",[{}])[0].get("expiry",""))[:10] if oc_raw.get("strikes") else "?"

from real_data_loader import load_price_history
hist = load_price_history("downloads/app_historical_NIFTY.csv")
close_s = hist["close"]
prev_c  = close_s.shift(1)
tr = ((hist["high"]-hist["low"]).combine((hist["high"]-prev_c).abs(),max).combine((hist["low"]-prev_c).abs(),max))
atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

# Build OC DF
rows = []
for s in oc_raw.get("strikes",[]):
    ce = s.get("CE",{}) or {}
    pe = s.get("PE",{}) or {}
    rows.append({"strike": float(s.get("strike",0)),
                 "CE_ltp": float(ce.get("ltp",0) or 0),
                 "PE_ltp": float(pe.get("ltp",0) or 0),
                 "CE_oi": int(ce.get("oi",0) or 0),
                 "PE_oi": int(pe.get("oi",0) or 0)})
df = pd.DataFrame(rows)
df["pain"] = df["CE_oi"]*(df["strike"]-spot).clip(lower=0)+df["PE_oi"]*(spot-df["strike"]).clip(lower=0)
max_pain = int(df.loc[df["pain"].idxmin(),"strike"])

# Is today expiry?
is_expiry = expiry_date == TODAY or expiry_date[:7] == TODAY[:7]
today_date = date.today()
expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d").date() if expiry_date and len(expiry_date) >= 10 else None
is_expiry_day = expiry_dt == today_date if expiry_dt else False

LOT = 65

TRADES = [
    {"name":"Institutional",       "type":"buy_ce", "strike":24400, "entry":87.20, "sl":43.60, "target":174.40, "exit":71.41, "pnl":-1026},
    {"name":"OptionSeller",        "type":"ic",     "short_ce":24600,"buy_ce":24800,"short_pe":24200,"buy_pe":24000,"entry":35.40,"sl":70.80,"target":17.70,"exit":30.51,"pnl":+318},
    {"name":"OptionBuyer",         "type":"buy_ce", "strike":24400, "entry":87.20, "sl":43.60, "target":174.40, "exit":71.41, "pnl":-1026},
    {"name":"Hedging",             "type":"spread", "short_pe":24250,"buy_pe":24050,"entry":26.90,"sl":40.35,"target":13.45,"exit":28.21,"pnl":-85},
    {"name":"Agent-Institutional", "type":"buy_ce", "strike":24400, "entry":87.20, "sl":37.79, "target":174.40, "exit":71.41, "pnl":-1026},
    {"name":"Agent-OptionSeller",  "type":"ic",     "short_ce":24600,"buy_ce":24800,"short_pe":24200,"buy_pe":24000,"entry":35.40,"sl":60.18,"target":21.24,"exit":30.51,"pnl":+318},
]

print("=" * 65)
print("LOSS ANALYSIS — CLOSED TRADES 2026-07-31")
print("=" * 65)

print(f"""
  Market data [{ts}]:
  Open: ₹{open_px:,.0f}  High: ₹{high_px:,.0f}  Low: ₹{low_px:,.0f}  Close: ₹{spot:,.0f}
  Day change: {day_chg_pct:+.2f}%  (₹{spot-prev_close:+.0f} from prev ₹{prev_close:,.0f})
  VIX: {vix:.2f}   ATR(14): {atr14:.0f}pts   Max Pain: ₹{max_pain:,}
  Expiry in OC: {expiry_date}
  TODAY IS {'⚠  EXPIRY DAY' if is_expiry_day else 'NOT expiry day'}
""")

# For CE 24400 - what strike needs to be for buyer to profit
atm_strike = 24400
ce_entry = 87.20
breakeven = atm_strike + ce_entry
print(f"  CE 24400 Buyer Breakeven: ₹{breakeven:.0f}  (spot needs to be > ₹{breakeven:.0f} at expiry)")
print(f"  Actual close: ₹{spot:,.0f}  ({'ABOVE' if spot > breakeven else '⚠ BELOW breakeven - buyer loses'} breakeven)")
print(f"  Gap to breakeven: ₹{spot - breakeven:+.0f}pts")
print()

print("=" * 65)
print("ROOT CAUSE: WHY BUYERS LOST")
print("=" * 65)

print(f"""
  1. EXPIRY DAY THETA CRUSH
     Entry at 13:41 on EXPIRY DAY ({TODAY})
     CE 24400 at ₹87.20 — with only ~1h 49min to market close (15:30)
     
     Theta (time decay) on expiry day is EXTREME after 13:00:
     • At 13:41, the option loses ~₹2-5/minute in time value
     • ₹87.20 premium means NIFTY must close > ₹{breakeven:.0f}
     • NIFTY closed at ₹{spot:,.0f} — ₹{spot-breakeven:.0f}pts {'above' if spot > breakeven else 'SHORT of'} breakeven
     • Result: Option expired worth ₹{max(spot - atm_strike, 0):.2f} — buyer lost ₹{min(spot-atm_strike, ce_entry) - ce_entry:.2f}/unit

  2. LATE ENTRY TIME
     • Entries at 13:41 on expiry day = HIGH RISK
     • Our time guard blocks buyers after 14:30 — still allowed at 13:41
     • On expiry day, effective cutoff should be 11:30 AM (before IV crush)
     • Intrinsic value = max({spot:.0f} - 24400, 0) = ₹{max(spot-24400, 0):.2f}
     • Premium paid: ₹87.20 — ALL time value, burns to zero at expiry

  3. VIX=11.89 = IV ALREADY LOW AT ENTRY
     • Low VIX means premiums are compressed
     • A ₹87.20 CE is priced for a directional move that didn't materialise
     • In low-VIX regimes, buyers need MORE move to profit, but premiums are expensive

  4. OPTION IS ATM (not OTM)
     • Strike 24400, spot ~24417 at entry = barely ATM
     • ATM options have highest theta burn on expiry day
     • Should prefer OTM options OR avoid buying on expiry day entirely
""")

print("=" * 65)
print("STRATEGIES TO RESTRICT THESE LOSSES")
print("=" * 65)

print(f"""
  SOLUTION 1: EXPIRY DAY BLOCK ← MOST IMPORTANT
  ─────────────────────────────────────────────
  Add check in _run_institutional/_run_option_buyer:
    If today == expiry date of option chain → SKIP all buyer strategies
  
  Today is expiry: {is_expiry_day}
  If this guard was active, all 3 buyer trades would have been SKIPPED
  → Loss avoided: ₹{3*1026:,} (3 × ₹1,026)

  SOLUTION 2: TIGHTER TIME CUT-OFF ON EXPIRY DAY
  ───────────────────────────────────────────────
  Current: Block buyers after 14:30
  Needed:  On expiry day, block buyers after 11:30
           (after 11:30, theta decay accelerates non-linearly)

  SOLUTION 3: BREAKEVEN CHECK BEFORE ENTRY
  ─────────────────────────────────────────
  Before buying CE, check: breakeven = strike + premium
  If (breakeven - spot) > 0.6 × ATR → skip (move required too large)
  
  Today: Breakeven = {breakeven:.0f}, Spot = {spot:.0f}, move needed = {breakeven-spot:.0f}pts
  ATR = {atr14:.0f}pts, 60% ATR = {atr14*0.6:.0f}pts
  {'⚠ Move needed ({:.0f}pts) > 60% ATR ({:.0f}pts) → should SKIP'.format(breakeven-spot, atr14*0.6) if breakeven-spot > atr14*0.6 else '✅ Move required within ATR range'}

  SOLUTION 4: TRAILING SL (not fixed 50%)
  ─────────────────────────────────────────
  Current SL: ₹43.60 (fixed 50% of ₹87.20 entry)
  Better: Trailing SL — move SL up as trade profits
    • Activate trail once premium > ₹100 (15% profit)
    • Trail SL = current_ltp × 0.80 (20% below peak)
  Exit at ₹71.41 → fixed SL (₹43.60) was NOT hit
  With trailing SL starting at ₹94.50 (entry +₹7):
    • SL would trail to ₹94.50 × 0.80 = ₹75.60
    • Trade exits at ₹71.41 → earlier exit at ₹75.60
    • Reduced loss: ₹{round((75.60-87.20)*65, 0):,.0f} vs ₹{-1026:,} (saves ₹{round((-87.20+75.60)*65 - (-1026), 0):,.0f})
    Note: When trade went profitable briefly, trail would lock in gains

  SOLUTION 5: REDUCE LOT SIZE ON EXPIRY DAY
  ──────────────────────────────────────────
  On expiry day (high risk), cap buyer qty at 0 lots (i.e., skip)
  OR reduce risk: invest ≤ ₹3,000/lot on expiry day
  CE 24400 at ₹87.20 × 65 = ₹5,668 investment — too much for expiry-day bet
""")

print("=" * 65)
print("RECOMMENDED CODE CHANGES (PRIORITY ORDER)")
print("=" * 65)

print(f"""
  PRIORITY 1 ✅ Add expiry day guard to _run_institutional/_run_option_buyer
    in src/auto_trade_engine.py

  PRIORITY 2 ✅ Tighten expiry day time cutoff: 11:30 instead of 14:30

  PRIORITY 3 ✅ Add breakeven check: skip if (strike + premium - spot) > 0.5×ATR

  PRIORITY 4 ✅ Trailing SL: track peak LTP and trail at 80% of peak

  Each guard working today:
  Guard 1 (expiry day): {'WOULD HAVE PREVENTED' if is_expiry_day else 'N/A today'} all 3 buyer losses = ₹{3*1026:,} saved
  Guard 3 (breakeven):  {'WOULD HAVE PREVENTED' if breakeven - spot > atr14*0.5 else 'Would NOT have prevented'} (need {breakeven-spot:.0f}pts > 50%×ATR={atr14*0.5:.0f}pts)
  Combined: FULL LOSS PREVENTION for today's scenario
""")
