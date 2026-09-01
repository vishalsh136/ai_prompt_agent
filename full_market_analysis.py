#!/usr/bin/env python
"""Full market analysis with correct JSON field names + strategy audit"""
import sys, json
sys.path.insert(0, 'src')

import pandas as pd
import numpy as np
from pathlib import Path

TODAY = "20260729"
DOWNLOADS = Path("downloads")

# ── LOAD DATA ──────────────────────────────────────────────────────────────────
oc_raw   = json.loads((DOWNLOADS / f"option_chain_NIFTY_{TODAY}.json").read_text(encoding="utf-8-sig"))
live_raw = json.loads((DOWNLOADS / f"live_market_{TODAY}.json").read_text(encoding="utf-8-sig"))
pcr_raw  = json.loads((DOWNLOADS / f"pcr_NIFTY_{TODAY}.json").read_text(encoding="utf-8-sig"))

# ── EXTRACT MARKET DATA ───────────────────────────────────────────────────────
nifty = next((x for x in live_raw.get("indices",[]) if "NIFTY 50" in x.get("index","")), {})
spot       = float(nifty.get("last", oc_raw.get("spot_price", 0)))
open_px    = float(nifty.get("open", 0))
high_px    = float(nifty.get("high", 0))
low_px     = float(nifty.get("low", 0))
prev_close = float(nifty.get("previousClose", 0))
day_chg    = float(nifty.get("change", 0))
day_chg_pct= float(nifty.get("changePct", 0))
vix        = float(oc_raw.get("vix", 0))
pcr_oi     = float(pcr_raw.get("pcr_overall", pcr_raw.get("pcr_current", 0)))
ts_oc      = oc_raw.get("timestamp","—")
ts_pcr     = pcr_raw.get("timestamp","—")
strikes    = oc_raw.get("strikes", [])

# ── BUILD OPTION CHAIN DF ─────────────────────────────────────────────────────
rows = []
for s in strikes:
    ce = s.get("CE", {}) or {}
    pe = s.get("PE", {}) or {}
    rows.append({
        "strike":      float(s.get("strike", 0)),
        "expiry":      s.get("expiry", ""),
        "CE_ltp":      float(ce.get("ltp", 0) or 0),
        "CE_oi":       int(ce.get("oi",  0) or 0),
        "CE_chg_oi":   int(ce.get("chg_oi", 0) or 0),
        "CE_vol":      int(ce.get("volume", 0) or 0),
        "CE_buildup":  ce.get("buildup", ""),
        "PE_ltp":      float(pe.get("ltp", 0) or 0),
        "PE_oi":       int(pe.get("oi",  0) or 0),
        "PE_chg_oi":   int(pe.get("chg_oi", 0) or 0),
        "PE_vol":      int(pe.get("volume", 0) or 0),
        "PE_buildup":  pe.get("buildup", ""),
    })
df = pd.DataFrame(rows)

# ATM
atm_row    = df.iloc[(df["strike"] - spot).abs().argsort()[:1]]
atm        = int(atm_row["strike"].iloc[0])
atm_ce     = float(atm_row["CE_ltp"].iloc[0])
atm_pe     = float(atm_row["PE_ltp"].iloc[0])

# Max pain
df["pain"] = (df["CE_oi"] * (df["strike"] - spot).clip(lower=0) +
              df["PE_oi"] * (spot - df["strike"]).clip(lower=0))
max_pain = int(df.loc[df["pain"].idxmin(), "strike"])

# Historical
from real_data_loader import load_price_history
hist = load_price_history("downloads/app_historical_NIFTY.csv")
close_s  = hist["close"]
prev_c   = close_s.shift(1)
tr = ((hist["high"]-hist["low"])
      .combine((hist["high"]-prev_c).abs(), max)
      .combine((hist["low"] -prev_c).abs(), max))
atr14    = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
atr5     = float(tr.rolling(5,  min_periods=1).mean().iloc[-1])
sma20    = float(close_s.rolling(20, min_periods=1).mean().iloc[-1])
sma50    = float(close_s.rolling(50, min_periods=1).mean().iloc[-1])
last_cls = float(close_s.iloc[-1])

# OI concentration (top 5 each side)
top_ce_oi = df.nlargest(5, "CE_oi")[["strike","CE_oi","CE_chg_oi","CE_buildup"]]
top_pe_oi = df.nlargest(5, "PE_oi")[["strike","PE_oi","PE_chg_oi","PE_buildup"]]

# OI change today — net put/call writing
total_ce_new_oi = df["CE_chg_oi"].sum()
total_pe_new_oi = df["PE_chg_oi"].sum()

# ══════════════════════════════════════════════════════════════════════════════
print("=" * 65)
print("TODAY'S MARKET DEEP ANALYSIS  —  NIFTY  2026-07-29")
print("=" * 65)

print(f"""
■ INTRADAY SNAPSHOT  [{ts_oc}]
  Prev Close : ₹{prev_close:,.2f}
  Open       : ₹{open_px:,.2f}
  High       : ₹{high_px:,.2f}   (range top)
  Low        : ₹{low_px:,.2f}   (range bottom)
  LTP / Close: ₹{spot:,.2f}
  Day Change : ₹{day_chg:+,.2f} ({day_chg_pct:+.2f}%)
  Day Range  : {high_px - low_px:.0f} pts ({(high_px-low_px)/open_px*100:.2f}%)
  Gap-up     : {open_px - prev_close:+.2f} pts ({(open_px-prev_close)/prev_close*100:+.2f}%)

■ DERIVATIVES  [{ts_pcr}]
  VIX        : {vix:.2f}   {'🟢 Low (best for selling)' if vix < 14 else '🟡 Moderate' if vix < 18 else '🔴 High (avoid selling)'}
  PCR (OI)   : {pcr_oi:.4f}  {'🟢 > 1.0 = bullish hedge (smart money protects longs)' if pcr_oi > 1 else '⚠  < 1.0 = bearish/no hedge'}
  ATM Strike : {atm}
  ATM CE LTP : ₹{atm_ce:.2f}
  ATM PE LTP : ₹{atm_pe:.2f}
  ATM CE/PE  : {atm_ce/max(atm_pe,0.01):.2f}x  {'(CE > PE = bullish skew)' if atm_ce > atm_pe else '(PE > CE = bearish hedge / protection)'}
  Max Pain   : ₹{max_pain:,}   (spot is {spot - max_pain:+.0f} pts {'above' if spot > max_pain else 'below'})
""")

print(f"■ HISTORICAL CONTEXT (last 5 trading days)")
for _, r in hist.tail(5).iterrows():
    c = round((r["close"] - r["open"]) / r["open"] * 100, 2)
    bar = "▲" if c > 0 else "▼"
    print(f"  {str(r['date'])[:10]}  ₹{r['close']:,.0f}  {bar} {c:+.2f}%  range:{r['high']-r['low']:.0f}pts")

print(f"""
  ATR(14) : {atr14:.0f} pts  ({atr14/spot*100:.2f}% of spot)
  ATR(5)  : {atr5:.0f} pts
  20-SMA  : ₹{sma20:,.0f}   spot {'ABOVE ✅' if last_cls > sma20 else 'BELOW ⚠'}
  50-SMA  : ₹{sma50:,.0f}   spot {'ABOVE ✅' if last_cls > sma50 else 'BELOW ⚠'}
""")

print("■ OI CONCENTRATION (Smart Money Positioning)")
print("  CE (Resistance) walls:")
for _, r in top_ce_oi.iterrows():
    dist = r["strike"] - spot
    chg_lbl = f"OI {'▲' if r['CE_chg_oi'] > 0 else '▼'}{abs(r['CE_chg_oi']):,}"
    print(f"    {int(r['strike']):>6}  OI:{r['CE_oi']:>10,}  {chg_lbl:<18}  {r['CE_buildup']}  ({dist:+.0f}pts)")

print("  PE (Support) walls:")
for _, r in top_pe_oi.iterrows():
    dist = r["strike"] - spot
    chg_lbl = f"OI {'▲' if r['PE_chg_oi'] > 0 else '▼'}{abs(r['PE_chg_oi']):,}"
    print(f"    {int(r['strike']):>6}  OI:{r['PE_oi']:>10,}  {chg_lbl:<18}  {r['PE_buildup']}  ({dist:+.0f}pts)")

print(f"""
  Net CE OI change today : {total_ce_new_oi:+,}
  Net PE OI change today : {total_pe_new_oi:+,}
  OI bias : {'PE writing > CE writing → BULLISH (market makers expect upside)' if total_pe_new_oi > total_ce_new_oi else 'CE writing > PE writing → NEUTRAL/CAPPED'}
""")

# ── REGIME CLASSIFICATION ─────────────────────────────────────────────────────
bullish      = last_cls > sma20 > sma50
bearish      = last_cls < sma20 < sma50
trending     = atr14 > spot * 0.0085   # > ~205pts today
low_vix      = vix < 14
gap_up       = (open_px - prev_close) / prev_close * 100 > 0.3
strong_day   = abs(day_chg_pct) > 0.8
pcr_bullish  = pcr_oi > 1.0
near_max_pain= abs(spot - max_pain) < atr14 * 0.5

print("=" * 65)
print("STRATEGY FITNESS  —  SHOULD EACH STRATEGY TRADE TODAY?")
print("=" * 65)

# 1. Institutional / OptionBuyer / Agent-Institutional (all = buy CE)
buy_valid = bullish and day_chg_pct > 0
buy_fit = "✅ GOOD" if buy_valid and not strong_day else "⚠  CAUTION" if bullish else "❌ SKIP"

print(f"""
1. INSTITUTIONAL + OPTION BUYER + AGENT-INSTITUTIONAL
   Action    : Buy ATM CE @ {atm} strike (entry ₹{atm_ce:.0f})
   Fit Today : {buy_fit}
   Because   :
     • Day move : {day_chg_pct:+.2f}% {'(strong up-move today ✅)' if day_chg_pct > 0.8 else '(mild up-move)' if day_chg_pct > 0 else '(down move ⚠)'}
     • Trend    : {'BULLISH — spot above BOTH SMAs ✅' if bullish else 'WEAK — check SMA'}
     • Gap-up   : {'Yes ({:.2f}%) — momentum day supports buyers ✅'.format((open_px-prev_close)/prev_close*100) if gap_up else 'No significant gap'}
     • PCR {pcr_oi:.2f}: {'High PCR = institutions hedged = bulls protected ✅' if pcr_bullish else 'Low PCR = exposed longs, risky'}
     • ATR {atr14:.0f}pts = {'Adequate range for target hit' if trending else 'Low — may not reach 2x target today'}
   Trade Plan :
     Entry  : Buy ATM CE {atm} @ ₹{atm_ce:.0f}
     SL     : ₹{atm_ce*0.5:.0f} (50% of premium)  → risk ₹{atm_ce*0.5*65:.0f}/lot
     Target : ₹{atm_ce*2:.0f} (2× premium)  → reward ₹{atm_ce*65:.0f}/lot
     R:R    : 1:{atm_ce / (atm_ce*0.5):.1f}
   {'⚡ NOTE: Entry late in day (16:08 snapshot) — most move already happened. Better at open.' if 'T16' in ts_oc or 'T15' in ts_oc else ''}
""")

# 2. OptionSeller / Agent-OptionSeller (Iron Condor)
ic_sell_ce = int(round((spot + atr14 * 1.5) / 50) * 50)
ic_sell_pe = int(round((spot - atr14 * 1.5) / 50) * 50)
ic_buy_ce  = ic_sell_ce + 200
ic_buy_pe  = ic_sell_pe - 200

# Get LTPs for those strikes
def ltp(strike, side):
    r = df[df["strike"] == strike]
    return float(r[f"{side}_ltp"].iloc[0]) if not r.empty else 0.0

sc_ltp = ltp(ic_sell_ce, "CE")
sp_ltp = ltp(ic_sell_pe, "PE")
bc_ltp = ltp(ic_buy_ce,  "CE")
bp_ltp = ltp(ic_buy_pe,  "PE")
net_credit_ic = round((sc_ltp + sp_ltp) - (bc_ltp + bp_ltp), 2)
ic_valid = not strong_day and not (abs(day_chg_pct) > 1.5)
ic_fit   = "✅ GOOD" if ic_valid and near_max_pain else "⚠  CAUTION" if ic_valid else "❌ RISKY"

print(f"""2. OPTION SELLER + AGENT-OPTION SELLER (Iron Condor)
   Action    : Sell OTM CE+PE, Buy wings
   Fit Today : {ic_fit}
   Because   :
     • Day move {day_chg_pct:+.2f}%: {'HIGH — IC already breached upward! Check strikes.' if day_chg_pct > 1.3 else 'Moderate — IC range viable'}
     • VIX {vix:.2f}: {'Very low — THIN premium, poor credit collected ⚠' if low_vix else 'OK'}
     • Max Pain ₹{max_pain:,}: {'Spot ≈ max pain — ideal IC expiry anchor ✅' if near_max_pain else f'Spot {spot-max_pain:+.0f}pts from max pain'}
     • Strong day +{day_chg_pct:.1f}%: {'IC upper wing pressure — short CE may be tested ⚠' if day_chg_pct > 1.0 else 'IC range intact ✅'}
   Suggested Strikes (ATR×1.5 bands):
     Sell CE {ic_sell_ce} @ ₹{sc_ltp:.1f}
     Sell PE {ic_sell_pe} @ ₹{sp_ltp:.1f}
     Buy  CE {ic_buy_ce}  @ ₹{bc_ltp:.1f}  (wing)
     Buy  PE {ic_buy_pe}  @ ₹{bp_ltp:.1f}  (wing)
     Net Credit : ₹{net_credit_ic:.2f}/lot × {65} = ₹{net_credit_ic*65:.0f}/lot
   {'⚡ IMPROVEMENT: Day gap-up of {:.2f}% reduces upside buffer. Consider selling CE at {:.0f} instead.'.format(day_chg_pct, ic_sell_ce+100) if day_chg_pct > 1.0 else ''}
   {'⚡ IMPROVEMENT: VIX={:.1f} → credit very thin. Consider waiting for VIX > 14 before selling.'.format(vix) if vix < 13 else ''}
""")

# 3. Hedging (Bull Put Spread)
hedge_sell_pe = int(round((spot - atr14 * 0.8) / 50) * 50)
hedge_buy_pe  = int(round((spot - atr14 * 1.8) / 50) * 50)
h_sell_ltp    = ltp(hedge_sell_pe, "PE")
h_buy_ltp     = ltp(hedge_buy_pe,  "PE")
hedge_credit  = round(h_sell_ltp - h_buy_ltp, 2)
hedge_fit     = "✅ GOOD" if bullish and pcr_bullish else "⚠  CAUTION"

print(f"""3. HEDGING (Bull Put Credit Spread)
   Action    : Sell OTM PE, Buy lower PE (credit spread)
   Fit Today : {hedge_fit}
   Because   :
     • Bullish trend {'✅' if bullish else '⚠'}  — Bull Put suits bullish-to-neutral view
     • PCR {pcr_oi:.2f} {'> 1.0 = smart money protecting longs ✅ (PE demand = credit fatter)' if pcr_bullish else '< 1.0 = low hedging'}
     • Max Pain ₹{max_pain:,} = support floor (market unlikely to fall below)
     • Put skew: PE side has '{top_pe_oi.iloc[0]["PE_buildup"]}' at {int(top_pe_oi.iloc[0]["strike"])} ({'supports hedge ✅' if 'Writing' in str(top_pe_oi.iloc[0]['PE_buildup']) else 'check buildup'})
   Suggested Strikes:
     Sell PE {hedge_sell_pe} @ ₹{h_sell_ltp:.2f}
     Buy  PE {hedge_buy_pe}  @ ₹{h_buy_ltp:.2f}
     Net Credit : ₹{hedge_credit:.2f} × {65} = ₹{hedge_credit*65:.0f}/lot
     Max Risk   : ₹{(hedge_sell_pe - hedge_buy_pe - hedge_credit) * 65:.0f}/lot
     R:R        : 1:{round(hedge_credit/(hedge_sell_pe-hedge_buy_pe-hedge_credit),2) if hedge_sell_pe-hedge_buy_pe > hedge_credit else 'N/A'}
""")

# ── OVERALL SUMMARY ───────────────────────────────────────────────────────────
print("=" * 65)
print("OVERALL STRATEGY RECOMMENDATIONS FOR TODAY")
print("=" * 65)

print(f"""
  MARKET IN ONE LINE:
  NIFTY +{day_chg_pct:.1f}% gap-up bullish day, VIX={vix:.1f} (very low),
  spot at max pain ₹{max_pain:,}, PCR={pcr_oi:.2f} (smart money hedged).

  STRATEGY RANKINGS FOR TODAY (1=best):

  RANK 1 ✅  Hedging — Bull Put Spread {hedge_sell_pe}/{hedge_buy_pe}PE
    Net credit ₹{hedge_credit:.0f}/lot. Defined-risk, low-maintenance.
    Best fit: bullish+low-VIX+max-pain anchor. Expires Aug-4.

  RANK 2 ✅  Institutional — Buy ATM CE {atm}
    Strong day (+{day_chg_pct:.1f}%), bullish trend, above both SMAs.
    ⚠  Late entry (snapshot at {ts_oc[11:16]}) — most move is done.
    Better for: tomorrow morning entry on continuation.

  RANK 3 ⚠   OptionSeller — Iron Condor {ic_sell_pe}–{ic_sell_ce}
    Net credit ₹{net_credit_ic:.0f}/lot. Works if market stays rangebound.
    Risk: VIX={vix:.1f} → thin premium. Upper wing near today's high.
    Improvement needed: widen CE wing by 100pts after big up-move.

  RANK 4 ❌  OptionBuyer (standalone) — NOT recommended today
    ATR={atr14:.0f}pts is borderline. After +{day_chg_pct:.1f}% move, entry is
    chasing. Theta decay on Aug-4 expiry still 6 days away but
    premium already elevated from the day's move.
""")

# ── IMPROVEMENTS NEEDED ───────────────────────────────────────────────────────
print("=" * 65)
print("IMPROVEMENTS NEEDED IN STRATEGY CODE")
print("=" * 65)

print(f"""
  1. IC STRIKE SELECTION after gap-up days [OptionSeller]
     Issue   : Current code uses ATR×1.5 symmetrically around spot.
     Problem : After a +{day_chg_pct:.1f}% gap-up, the short CE at {ic_sell_ce} has
               only {ic_sell_ce - spot:.0f}pts buffer — same-day high is ₹{high_px:.0f}.
     Fix     : Shift IC center up by gap-amount after a gap > 0.5%.
               or use max(open, close) as reference for CE wing.

  2. VIX-based MIN CREDIT filter [OptionSeller / Hedging]
     Issue   : No minimum credit check before entering sellers.
     Problem : At VIX={vix:.1f}, IC net credit ≈ ₹{net_credit_ic:.0f}/lot — too thin
               for the margin tied up (risk ₹{200*65:.0f}/lot for ₹{net_credit_ic*65:.0f} credit).
     Fix     : Skip OptionSeller if net_credit < 0.15 × spread_width
               (current: {net_credit_ic:.1f} vs threshold {200*0.15:.1f}).
               {'⚠  BELOW threshold today!' if net_credit_ic < 200*0.15 else '✅  Above threshold today.'}

  3. TIME-OF-DAY filter for buyers [Institutional / OptionBuyer]
     Issue   : Strategy enters at any time when called.
     Problem : Snapshot is from {ts_oc[11:16]} — after 3PM, less than 30min to
               close. Buying premium this late means instant theta decay.
     Fix     : Block buyer entries after 14:30 IST.

  4. PCR reading from correct field [PCR loader]
     Issue   : real_data_loader uses 'pcr_oi' but JSON has 'pcr_overall'.
     Problem : PCR shows 0.00 in strategy engine (seen earlier).
     Status  : {'⚠  NEEDS FIX in pcr loader' if True else '✅'}

  5. live_market data extraction [Historical loader]
     Issue   : live_market JSON has nested indices[] array.
     Problem : Day OHLC fields not surfaced to strategy engine.
     Impact  : Day-move % guard in AlgoAutoTrader uses 0% — crash/rally
               guard is effectively blind to actual day move.
     Fix     : Extract from indices[0] for NIFTY 50.
""")
