#!/usr/bin/env python
"""Analyse why the Agent-OptionSeller Iron Condor won't work today"""
import json, sys
sys.path.insert(0, 'src')
import pandas as pd
import numpy as np
from pathlib import Path

# ── THE TRADE IN QUESTION ────────────────────────────────────────────────────
TRADE = {
    "strategy":    "Agent-OptionSeller",
    "date":        "2026-07-30",
    "entry_time":  "10:40",
    "instrument":  "Iron Condor (Defined Risk)",
    "legs":        "PE:B23800/S24000 | CE:S24400/B24600",
    "short_pe":    24000,
    "buy_pe":      23800,
    "short_ce":    24400,
    "buy_ce":      24600,
    "entry_price": 57.40,
    "stop_loss":   97.58,
    "target":      34.44,
    "current_ltp": 64.28,
    "current_pnl": 447.0,  # positive showing in UI, but let's verify direction
    "investment":  13000,
}

# ── LOAD TODAY'S MARKET DATA ──────────────────────────────────────────────────
DOWNLOADS = Path("downloads")
TODAY = "20260730"
YESTERDAY = "20260729"

oc_today = json.loads((DOWNLOADS / f"option_chain_NIFTY_{TODAY}.json").read_text(encoding="utf-8-sig"))
oc_yest  = json.loads((DOWNLOADS / f"option_chain_NIFTY_{YESTERDAY}.json").read_text(encoding="utf-8-sig"))
live_today = json.loads((DOWNLOADS / f"live_market_{TODAY}.json").read_text(encoding="utf-8-sig"))
pcr_today  = json.loads((DOWNLOADS / f"pcr_NIFTY_{TODAY}.json").read_text(encoding="utf-8-sig"))

nifty = next((x for x in live_today.get("indices", []) if "NIFTY 50" in x.get("index", "")), {})
spot       = float(nifty.get("last", oc_today.get("spot_price", 0)))
open_px    = float(nifty.get("open", oc_today.get("open", 0)))
high_px    = float(nifty.get("high", oc_today.get("high", 0)))
low_px     = float(nifty.get("low", oc_today.get("low", 0)))
prev_close = float(nifty.get("previousClose", 0)) or float(oc_yest.get("spot_price", 24250))
day_chg_pct= float(nifty.get("changePct", 0))
vix_today  = float(oc_today.get("vix", 0))
pcr_today_val = float(pcr_today.get("pcr_overall", oc_today.get("pcr", 0)))
ts         = oc_today.get("timestamp", "—")

# Build today's OC dataframe
rows = []
for s in oc_today.get("strikes", []):
    ce = s.get("CE", {}) or {}
    pe = s.get("PE", {}) or {}
    rows.append({
        "strike": float(s.get("strike", 0)),
        "CE_ltp": float(ce.get("ltp", 0) or 0),
        "CE_oi":  int(ce.get("oi", 0) or 0),
        "CE_chg_oi": int(ce.get("chg_oi", 0) or 0),
        "CE_buildup": ce.get("buildup", ""),
        "PE_ltp": float(pe.get("ltp", 0) or 0),
        "PE_oi":  int(pe.get("oi", 0) or 0),
        "PE_chg_oi": int(pe.get("chg_oi", 0) or 0),
        "PE_buildup": pe.get("buildup", ""),
    })
df = pd.DataFrame(rows)

def ltp(strike, side):
    r = df[df["strike"] == strike]
    return float(r[f"{side}_ltp"].iloc[0]) if not r.empty else None

# ── CURRENT LEG PRICES ────────────────────────────────────────────────────────
short_ce_now = ltp(TRADE["short_ce"], "CE")
short_pe_now = ltp(TRADE["short_pe"], "PE")
buy_ce_now   = ltp(TRADE["buy_ce"],   "CE")
buy_pe_now   = ltp(TRADE["buy_pe"],   "PE")

# Current spread value (cost to close)
current_spread = None
if all(v is not None for v in [short_ce_now, short_pe_now, buy_ce_now, buy_pe_now]):
    current_spread = round((short_ce_now + short_pe_now) - (buy_ce_now + buy_pe_now), 2)

# P&L calculation: we collected ENTRY credit, now cost to close = current_spread
# Profit if current_spread < entry (spread compressed = good for seller)
# Loss if current_spread > entry (spread expanded = bad for seller)
lot_size = 65
actual_pnl = round((TRADE["entry_price"] - (current_spread or TRADE["current_ltp"])) * lot_size, 2)
sl_trigger = (current_spread or TRADE["current_ltp"]) >= TRADE["stop_loss"]
target_hit = (current_spread or TRADE["current_ltp"]) <= TRADE["target"]

# Yesterday's entry-time prices (approximate from yesterday's snapshot)
yest_rows = []
for s in oc_yest.get("strikes", []):
    ce = s.get("CE", {}) or {}
    pe = s.get("PE", {}) or {}
    yest_rows.append({
        "strike": float(s.get("strike", 0)),
        "CE_ltp": float(ce.get("ltp", 0) or 0),
        "PE_ltp": float(pe.get("ltp", 0) or 0),
    })
df_yest = pd.DataFrame(yest_rows)

def ltp_yest(strike, side):
    r = df_yest[df_yest["strike"] == strike]
    return float(r[f"{side}_ltp"].iloc[0]) if not r.empty else None

entry_short_ce = ltp_yest(TRADE["short_ce"], "CE")
entry_short_pe = ltp_yest(TRADE["short_pe"], "PE")
entry_buy_ce   = ltp_yest(TRADE["buy_ce"],   "CE")
entry_buy_pe   = ltp_yest(TRADE["buy_pe"],   "PE")

# Historical
from real_data_loader import load_price_history
hist = load_price_history("downloads/app_historical_NIFTY.csv")
close_s = hist["close"]
prev_c  = close_s.shift(1)
tr = ((hist["high"]-hist["low"]).combine((hist["high"]-prev_c).abs(),max).combine((hist["low"]-prev_c).abs(),max))
atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

# ════════════════════════════════════════════════════════════════════════════
print("=" * 65)
print("IRON CONDOR TRADE ANALYSIS  —  2026-07-30")
print("=" * 65)

print(f"""
■ TODAY'S MARKET  [{ts}]
  Prev Close : ₹{prev_close:,.2f}  (2026-07-29)
  Open       : ₹{open_px:,.2f}
  High       : ₹{high_px:,.2f}
  Low        : ₹{low_px:,.2f}
  Current    : ₹{spot:,.2f}
  Day Move   : {day_chg_pct:+.2f}%
  Gap-up     : {open_px - prev_close:+.0f} pts ({(open_px-prev_close)/prev_close*100:+.2f}%)
  VIX        : {vix_today:.2f}
  PCR (OI)   : {pcr_today_val:.4f}
""")

print(f"""■ IRON CONDOR STRUCTURE
  Entry time : {TRADE["date"]} {TRADE["entry_time"]}
  Legs       : {TRADE["legs"]}
                ├─ Short CE {TRADE["short_ce"]}  (resistance wing)
                ├─ Buy   CE {TRADE["buy_ce"]}   (CE protection)
                ├─ Short PE {TRADE["short_pe"]}  (support wing)
                └─ Buy   PE {TRADE["buy_pe"]}   (PE protection)
  Profit zone: ₹{TRADE["short_pe"]:,} to ₹{TRADE["short_ce"]:,}  (±{(TRADE["short_ce"]-TRADE["short_pe"])//2} pts band)
  Max loss   : Outside ₹{TRADE["buy_pe"]:,}–₹{TRADE["buy_ce"]:,}
""")

print(f"""■ ENTRY PRICES (from yesterday's 18:30 snapshot)
  Short CE {TRADE["short_ce"]} LTP : ₹{entry_short_ce or '?'}
  Short PE {TRADE["short_pe"]} LTP : ₹{entry_short_pe or '?'}
  Buy   CE {TRADE["buy_ce"]}  LTP : ₹{entry_buy_ce or '?'}
  Buy   PE {TRADE["buy_pe"]}  LTP : ₹{entry_buy_pe or '?'}
  ─────────────────────────────────────────────────────
  Entry credit collected : ₹{TRADE["entry_price"]:.2f}/unit × {lot_size} = ₹{TRADE["entry_price"]*lot_size:,.0f}/lot
  SL trigger at         : ₹{TRADE["stop_loss"]:.2f} spread (loss ₹{(TRADE["stop_loss"]-TRADE["entry_price"])*lot_size:,.0f}/lot)
  Target at             : ₹{TRADE["target"]:.2f} spread (profit ₹{(TRADE["entry_price"]-TRADE["target"])*lot_size:,.0f}/lot)
""")

print(f"""■ CURRENT LEG PRICES (today's snapshot)
  Short CE {TRADE["short_ce"]} now : ₹{short_ce_now or '?'} (was ₹{entry_short_ce or '?'})  → {'▲ SURGED' if short_ce_now and entry_short_ce and short_ce_now > entry_short_ce*1.5 else '▼ declined' if short_ce_now and entry_short_ce and short_ce_now < entry_short_ce*0.8 else '≈ stable'}
  Short PE {TRADE["short_pe"]} now : ₹{short_pe_now or '?'} (was ₹{entry_short_pe or '?'})
  Buy   CE {TRADE["buy_ce"]} now  : ₹{buy_ce_now or '?'}  (was ₹{entry_buy_ce or '?'})
  Buy   PE {TRADE["buy_pe"]} now  : ₹{buy_pe_now or '?'}  (was ₹{entry_buy_pe or '?'})
  ─────────────────────────────────────────────────────
  Current spread to close : ₹{current_spread if current_spread is not None else TRADE["current_ltp"]:.2f}
  Recorded in log        : ₹{TRADE["current_ltp"]:.2f}
  Entry credit           : ₹{TRADE["entry_price"]:.2f}
  ─────────────────────────────────────────────────────
  Actual P&L             : ₹{actual_pnl:+,.0f}  ({'profit' if actual_pnl > 0 else 'LOSS'})
  SL breached?           : {'⚠ YES — SL HIT' if sl_trigger else '✅ No (still within SL)'}
  Target hit?            : {'✅ YES' if target_hit else 'No'}
""")

# ── WHY IT WON'T WORK: ROOT CAUSE ANALYSIS ────────────────────────────────────
print("=" * 65)
print("ROOT CAUSE ANALYSIS — WHY THIS TRADE WON'T WORK TODAY")
print("=" * 65)

# Distance from spot to short strikes
dist_short_ce = TRADE["short_ce"] - spot
dist_short_pe = spot - TRADE["short_pe"]
ic_range_pct  = (TRADE["short_ce"] - TRADE["short_pe"]) / 2 / spot * 100
day_move_pts  = spot - prev_close
day_range_pts = high_px - low_px

# Spot position relative to IC
if spot >= TRADE["short_ce"]:
    breach = "CE WING BREACHED"
    breach_detail = f"Spot ₹{spot:,.0f} ≥ Short CE {TRADE['short_ce']} → max loss zone"
elif spot <= TRADE["short_pe"]:
    breach = "PE WING BREACHED"
    breach_detail = f"Spot ₹{spot:,.0f} ≤ Short PE {TRADE['short_pe']} → max loss zone"
elif dist_short_ce < atr14 * 0.5:
    breach = "CE WING AT RISK"
    breach_detail = f"Only {dist_short_ce:.0f}pts to Short CE {TRADE['short_ce']} — less than 0.5×ATR={atr14*0.5:.0f}pts"
elif dist_short_pe < atr14 * 0.5:
    breach = "PE WING AT RISK"
    breach_detail = f"Only {dist_short_pe:.0f}pts to Short PE {TRADE['short_pe']} — less than 0.5×ATR={atr14*0.5:.0f}pts"
else:
    breach = "RANGE INTACT"
    breach_detail = "Spot within IC profit zone"

print(f"""
■ SPOT vs IC RANGE
  IC profit zone : ₹{TRADE["short_pe"]:,} ─── ₹{TRADE["short_ce"]:,}  (400pt wide)
  Spot NOW       : ₹{spot:,.2f}
  ┌─────────────────────────────────────────────────────┐
  │  Buy PE      Short PE     SPOT      Short CE   Buy CE│
  │  {TRADE["buy_pe"]:,}      {TRADE["short_pe"]:,}       {spot:,.0f}     {TRADE["short_ce"]:,}     {TRADE["buy_ce"]:,}│
  │     ├──max loss──┤────profit──────┤←{dist_short_ce:.0f}pts→┤──max loss─┤│
  └─────────────────────────────────────────────────────┘
  Distance to Short CE : {dist_short_ce:+.0f} pts   (safe if > {atr14*0.5:.0f}pts)
  Distance to Short PE : {dist_short_pe:+.0f} pts   (safe if > {atr14*0.5:.0f}pts)
  Status : ⚠  {breach}
  Detail : {breach_detail}
""")

print(f"""■ WHY TODAY SPECIFICALLY
  1. ENTRY STRIKE SELECTION WAS STALE (main issue)
     • IC was entered at {TRADE["entry_time"]} using yesterday's 18:30 data snapshot
     • Entry strikes based on YESTERDAY's spot ~₹{prev_close:,.0f}
     • Short CE {TRADE["short_ce"]} = ₹{prev_close:,.0f} + ~150pts was OTM yesterday
     • TODAY: NIFTY opened at ₹{open_px:,.2f} (gap-up +{open_px-prev_close:+.0f}pts)
     • Short CE {TRADE["short_ce"]} now only {dist_short_ce:.0f}pts from current spot ₹{spot:,.0f}
     • {'⚠  THE CE WING IS UNDER THREAT — gap neutralized the OTM buffer' if dist_short_ce < 200 else '✅  CE wing still has adequate buffer'}

  2. TODAY'S MARKET MOVE
     • Gap-up at open: +{open_px-prev_close:.0f}pts (+{(open_px-prev_close)/prev_close*100:.2f}%)
     • Day move total: {day_chg_pct:+.2f}% (₹{spot-prev_close:+.0f}pts from yesterday's close)
     • Day range so far: {day_range_pts:.0f}pts (H:{high_px:,.0f} / L:{low_px:,.0f})
     • ATR(14): {atr14:.0f}pts — the IC range of 400pts captures only {400/atr14:.1f}×ATR
     • {'⚠  A single-day ATR move can test the CE wing' if day_chg_pct > 0.5 else ''}

  3. CURRENT P&L STATUS
     • Spread entered at ₹{TRADE["entry_price"]:.2f} (credit collected)
     • Current close-cost: ₹{current_spread if current_spread is not None else TRADE["current_ltp"]:.2f}
     • {'CURRENT SPREAD > ENTRY = LOSING TRADE (spread expanded)' if (current_spread or TRADE["current_ltp"]) > TRADE["entry_price"] else 'CURRENT SPREAD < ENTRY = WINNING TRADE (spread compressed)'}
     • P&L: ₹{actual_pnl:+,.0f}/lot  ({'PROFIT ✅' if actual_pnl >= 0 else 'LOSS ⚠'})
     • SL at ₹{TRADE["stop_loss"]:.2f} → {'⚠  SL IS NEAR' if (current_spread or TRADE["current_ltp"]) > TRADE["stop_loss"]*0.85 else 'SL not hit yet'}
""")

print(f"""■ SPECIFIC LEG-BY-LEG PROBLEM
  Short CE {TRADE["short_ce"]} :
    Entry LTP : ₹{entry_short_ce or '?'}
    Now LTP   : ₹{short_ce_now or '?'}
    Change    : {'₹' + str(round(short_ce_now - entry_short_ce, 2)) + ' (' + ('SURGE — short position LOSING' if short_ce_now and entry_short_ce and short_ce_now > entry_short_ce else 'decline — short position winning') + ')' if short_ce_now and entry_short_ce else '?'}

  Short PE {TRADE["short_pe"]} :
    Entry LTP : ₹{entry_short_pe or '?'}
    Now LTP   : ₹{short_pe_now or '?'}
    Change    : {'₹' + str(round(short_pe_now - entry_short_pe, 2)) + ' (' + ('surge — losing' if short_pe_now and entry_short_pe and short_pe_now > entry_short_pe else 'decline — winning') + ')' if short_pe_now and entry_short_pe else '?'}
""")

print("=" * 65)
print("SUMMARY — ROOT CAUSES")
print("=" * 65)
print(f"""
  PRIMARY: STALE ENTRY STRIKES
  ────────────────────────────
  The entry used yesterday's 18:30 data to set strikes.
  Short CE at {TRADE["short_ce"]} was valid for spot ~₹{prev_close:,.0f}, but
  today's gap-up to ₹{open_px:,.0f} (+{open_px-prev_close:.0f}pts) consumed
  {round((open_px - prev_close) / (TRADE["short_ce"] - prev_close) * 100):.0f}% of the CE wing buffer BEFORE the trade even started.

  SECONDARY: GAP-UP RISK NOT HANDLED
  ────────────────────────────────────
  Yesterday: gap was +{(open_px-prev_close)/prev_close*100:.2f}% → IC upper wing only {dist_short_ce:.0f}pts away
  Yesterday's IC analysis flagged: "IC strike selection after gap-up days"
  needs to shift CE wing up by gap amount.
  Fix committed: shift CE wing up by gap if gap > 0.5%
  But trades already entered before fix was applied.

  TERTIARY: LOW VIX = THIN CREDIT
  ────────────────────────────────
  VIX = {vix_today:.1f} → premium thin, trade entered for only ₹{TRADE["entry_price"]:.0f}/unit
  Max profit = ₹{(TRADE["entry_price"] - TRADE["target"]) * lot_size:,.0f}/lot
  Max loss   = ₹{(200 - TRADE["entry_price"]) * lot_size:,.0f}/lot (if fully breached)
  R:R = 1:{round((200 - TRADE["entry_price"]) / max(TRADE["entry_price"] - TRADE["target"], 1), 1)}  (unfavourable for the risk taken)
""")
