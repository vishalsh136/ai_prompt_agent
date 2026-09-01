#!/usr/bin/env python
"""Deep analysis of latest market data and strategy fitness (dynamic date)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from real_data_loader import load_price_history


DOWNLOADS = Path("downloads")


def _latest(pattern: str) -> Path:
    files = sorted(DOWNLOADS.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files found for pattern: {pattern}")
    return files[-1]


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


oc_path = _latest("option_chain_NIFTY_*.json")
pcr_path = _latest("pcr_NIFTY_*.json")
live_path = _latest("live_market_*.json")

oc_raw = _load_json(oc_path)
pcr_raw = _load_json(pcr_path)
live_raw = _load_json(live_path)

print("=" * 65)
print(f"TODAY'S MARKET DATA ANALYSIS — {oc_path.stem.split('_')[-1]}")
print("=" * 65)

spot = float(oc_raw.get("spot_price", 0) or 0)
vix = float(oc_raw.get("vix", 0) or 0)
pcr_oi = float(pcr_raw.get("pcr_overall", oc_raw.get("pcr", 0)) or 0)
ts = oc_raw.get("timestamp", "-")
strikes = oc_raw.get("strikes", [])

indices = live_raw.get("indices", [])
nifty = next((x for x in indices if "NIFTY 50" in str(x.get("index", ""))), {})
open_px = float(nifty.get("open", oc_raw.get("open", 0)) or 0)
high_px = float(nifty.get("high", oc_raw.get("high", 0)) or 0)
low_px = float(nifty.get("low", oc_raw.get("low", 0)) or 0)
close_px = float(nifty.get("last", spot) or spot)
day_move = round((close_px - open_px) / open_px * 100, 2) if open_px else 0

print("\nMarket Snapshot")
print(f"  Source files: {oc_path.name}, {pcr_path.name}, {live_path.name}")
print(f"  Timestamp: {ts}")
print(f"  Spot: {spot:,.2f} | Open: {open_px:,.2f} | High: {high_px:,.2f} | Low: {low_px:,.2f}")
print(f"  Day move: {day_move:+.2f}% | VIX: {vix:.2f} | PCR(OI): {pcr_oi:.3f}")
print(f"  Strikes loaded: {len(strikes)}")

rows = []
for s in strikes:
    ce = s.get("CE", {}) or {}
    pe = s.get("PE", {}) or {}
    rows.append(
        {
            "strike": float(s.get("strike", 0) or 0),
            "CE_ltp": float(ce.get("ltp", 0) or 0),
            "PE_ltp": float(pe.get("ltp", 0) or 0),
            "CE_oi": int(ce.get("oi", 0) or 0),
            "PE_oi": int(pe.get("oi", 0) or 0),
            "CE_iv": float(ce.get("iv", 0) or 0),
            "PE_iv": float(pe.get("iv", 0) or 0),
        }
    )
df = pd.DataFrame(rows)
if df.empty:
    print("\nOption chain is empty. Cannot compute strategy fitness.")
    raise SystemExit(0)

atm_row = df.iloc[(df["strike"] - spot).abs().argsort()[:1]]
atm = int(atm_row["strike"].iloc[0])
atm_ce = float(atm_row["CE_ltp"].iloc[0])
atm_pe = float(atm_row["PE_ltp"].iloc[0])

df["pain"] = df["CE_oi"] * (df["strike"] - spot).clip(lower=0) + df["PE_oi"] * (spot - df["strike"]).clip(lower=0)
_calc_max_pain = int(df.loc[df["pain"].idxmin(), "strike"])
max_pain = int(float(oc_raw.get("max_pain", _calc_max_pain) or _calc_max_pain))

print("\nOption Chain Structure")
print(f"  ATM strike: {atm} | ATM CE: {atm_ce:.2f} | ATM PE: {atm_pe:.2f}")
print(f"  Max pain: {max_pain} | Spot-MaxPain: {spot - max_pain:+.0f} pts")
if max_pain != _calc_max_pain:
    print(f"  Note: source max_pain differs from local calc ({_calc_max_pain}); using source for consistency.")

print("  Top CE OI (resistance):")
for _, r in df.nlargest(3, "CE_oi").iterrows():
    print(f"    {int(r['strike'])}: {int(r['CE_oi']):,} ({r['strike'] - spot:+.0f} pts)")
print("  Top PE OI (support):")
for _, r in df.nlargest(3, "PE_oi").iterrows():
    print(f"    {int(r['strike'])}: {int(r['PE_oi']):,} ({r['strike'] - spot:+.0f} pts)")

hist_df = load_price_history("downloads/app_historical_NIFTY.csv")
close_s = hist_df["close"]
prev_c = close_s.shift(1)
tr = (hist_df["high"] - hist_df["low"]).combine((hist_df["high"] - prev_c).abs(), max).combine((hist_df["low"] - prev_c).abs(), max)
atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
sma20 = float(close_s.rolling(20, min_periods=1).mean().iloc[-1])
sma50 = float(close_s.rolling(50, min_periods=1).mean().iloc[-1])
last_close = float(close_s.iloc[-1])

bullish = last_close > sma20 > sma50
bearish = last_close < sma20 < sma50
trending = atr14 > spot * 0.01
low_vix = vix < 14

print("\nRegime")
print(f"  ATR(14): {atr14:.1f} pts ({atr14 / max(spot, 1) * 100:.2f}% of spot)")
print(f"  Price vs SMA: {'ABOVE' if last_close > sma20 else 'BELOW'} 20SMA, {'ABOVE' if last_close > sma50 else 'BELOW'} 50SMA")
print(f"  Trend: {'BULLISH' if bullish else 'BEARISH' if bearish else 'MIXED'}")

print("\nStrategy Fitness")
print(f"  Institutional/OptionBuyer: {'GOOD' if bullish and trending else 'POOR' if not trending else 'NEUTRAL'}")
print(f"  OptionSeller/Agent-OptionSeller: {'GOOD' if low_vix and abs(day_move) < 0.6 else 'NEUTRAL'}")
print(f"  Hedging: {'GOOD' if (bullish or pcr_oi >= 1.0) else 'NEUTRAL'}")

if low_vix:
    print("  Improvement: Premium is thin in low VIX. Keep strict credit filters and consider wider wings.")
if not trending:
    print("  Improvement: Avoid long-premium buys unless trend/ATR expands.")
