#!/usr/bin/env python
"""Comprehensive diagnostic of P&L calculation issue"""
import json
import pandas as pd
from pathlib import Path
from datetime import date

# 1. Load the auto trade log
log_path = Path("data/auto_trade_log.json")
with open(log_path, "r", encoding="utf-8") as f:
    trades = json.load(f)

today = date.today().isoformat()
today_trades = [t for t in trades if t.get("date") == today]
open_trades = [t for t in today_trades if t.get("status") == "Open"]

print("=" * 60)
print("TRADE P&L DIAGNOSTIC")
print("=" * 60)

# 2. Load the option chain CSV
oc_csv = Path("downloads/app_option_chain_NIFTY.csv")
print(f"\n1. Option Chain CSV: {oc_csv.name}")
print(f"   File exists: {oc_csv.exists()}")
print(f"   File size: {oc_csv.stat().st_size} bytes")

if oc_csv.exists():
    with open(oc_csv, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()
    print(f"   Total lines: {len(lines)}")
    print(f"   Data rows: {len(lines) - 2}")  # Exclude header rows

# 3. Load the JSON option chain
oc_json = Path("downloads/option_chain_NIFTY_20260729.json")
print(f"\n2. Option Chain JSON: {oc_json.name}")
if oc_json.exists():
    with open(oc_json, "r", encoding="utf-8-sig") as f:
        json_data = json.load(f)
    strikes = json_data.get("strikes", [])
    print(f"   Spot price: ₹{json_data.get('spot_price')}")
    print(f"   Total strikes: {len(strikes)}")
    if strikes:
        print(f"   Sample strike 24000:")
        strike_24k = next((s for s in strikes if abs(s.get("strike", 0) - 24000) < 1), None)
        if strike_24k:
            print(f"     CE LTP: ₹{strike_24k.get('CE', {}).get('ltp')}")
            print(f"     PE LTP: ₹{strike_24k.get('PE', {}).get('ltp')}")

# 4. Check open trades
print(f"\n3. Open Trades: {len(open_trades)}")
for i, t in enumerate(open_trades, 1):
    print(f"\n   Trade {i}: {t.get('strategy_type')}")
    print(f"     Instrument: {t.get('instrument')}")
    print(f"     Strike: {t.get('strike')}")
    print(f"     Direction: {t.get('direction')}")
    print(f"     Entry Price: ₹{t.get('entry_price')}")
    print(f"     Current LTP: ₹{t.get('current_ltp')}")
    print(f"     Qty Lots: {t.get('qty_lots')}")
    print(f"     Lot Size: {t.get('lot_size')}")
    print(f"     Investment: ₹{t.get('investment_amount')}")
    print(f"     Current P&L: ₹{t.get('current_pnl')} ({t.get('current_pnl_pct')}%)")

# 5. Try to replicate P&L calculation
print(f"\n4. Manual P&L Calculation Check:")
if open_trades:
    t = open_trades[0]
    entry = float(t.get("entry_price", 0))
    current = float(t.get("current_ltp", 0))
    qty = int(t.get("qty_lots", 1))
    lot_size = int(t.get("lot_size", 65) or 65)
    direction = str(t.get("direction", "buy")).lower()
    
    if "sell" in direction:
        pnl = (entry - current) * lot_size * qty
    else:
        pnl = (current - entry) * lot_size * qty
    
    print(f"   Trade: {t.get('strategy_type')}")
    print(f"   Entry: ₹{entry}, Current: ₹{current}")
    print(f"   Direction: {direction}")
    print(f"   P&L Calc: ({entry} - {current}) * {lot_size} * {qty} = ₹{pnl}")
