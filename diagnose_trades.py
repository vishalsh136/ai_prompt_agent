#!/usr/bin/env python
"""Diagnose auto trade log issues"""
import json
from pathlib import Path
from datetime import date

log_path = Path("data/auto_trade_log.json")

if not log_path.exists():
    print("❌ Auto trade log file does not exist")
    exit(1)

with open(log_path, "r", encoding="utf-8") as f:
    trades = json.load(f)

print(f"📊 AUTO TRADE LOG ANALYSIS")
print("=" * 60)
print(f"Total trades: {len(trades)}")
print()

today = date.today().isoformat()
today_trades = [t for t in trades if t.get("date") == today]
open_trades = [t for t in today_trades if t.get("status") == "Open"]

print(f"Today's trades ({today}): {len(today_trades)}")
print(f"Open trades today: {len(open_trades)}")
print()

if open_trades:
    print("🔍 OPEN TRADES DETAIL:")
    for i, t in enumerate(open_trades, 1):
        print(f"\n  [{i}] {t.get('strategy_type', 'Unknown')}")
        print(f"      Entry: ₹{t.get('entry_price', 'N/A')}")
        print(f"      Current LTP: ₹{t.get('current_ltp', 'N/A')}")
        print(f"      Current P&L: ₹{t.get('current_pnl', 'N/A')} ({t.get('current_pnl_pct', 'N/A')}%)")
        print(f"      Last Updated: {t.get('last_updated', 'N/A')}")
        print(f"      Status: {t.get('status', 'N/A')}")
        
        # Check for missing critical fields
        required = ['entry_price', 'qty_lots', 'lot_size', 'investment_amount', 'direction']
        missing = [f for f in required if f not in t or t[f] is None]
        if missing:
            print(f"      ⚠️  Missing fields: {missing}")
else:
    print("❌ No open trades found for today")
    if today_trades:
        print("\nRecent trades:")
        for t in today_trades[-3:]:
            print(f"  - {t.get('strategy_type')}: {t.get('status')} | {t.get('instrument')}")
