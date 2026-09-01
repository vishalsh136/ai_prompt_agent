#!/usr/bin/env python
import json
from pathlib import Path

cfg = json.loads(Path('algo_trade_config.json').read_text(encoding='utf-8'))
risk = cfg.get('risk', {})
trading = cfg.get('trading', {})
print("=== CONFIG ===")
print(f"max_open_positions : {risk.get('max_open_positions')}")
print(f"max_orders_per_day : {risk.get('max_orders_per_day')}")
print(f"selection_mode     : {trading.get('selection_mode')}")
print(f"strategy           : {trading.get('strategy')}")  # config strategy (for manual pid)

print()
print("=== LIVE POSITIONS ===")
pos = json.loads(Path('data/live_algo_positions.json').read_text(encoding='utf-8'))
print(f"Total positions: {len(pos)}")
for k, v in pos.items():
    print(f"  pid    : {k}")
    print(f"  status : {v.get('status')}")
    print(f"  entry  : {v.get('entry_time')}")
    print(f"  legs   : {v.get('legs')}")
