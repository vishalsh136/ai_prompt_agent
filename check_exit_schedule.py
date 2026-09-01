#!/usr/bin/env python
import json
from pathlib import Path
from datetime import datetime, timedelta

cfg = json.loads(Path('algo_trade_config.json').read_text(encoding='utf-8'))
risk = cfg.get('risk', {})
trading = cfg.get('trading', {})

print("Auto-exit settings:")
print(f"  time_exit_minutes : {risk.get('time_exit_minutes')}")
print(f"  target_profit_inr : {risk.get('target_profit_inr')}")
print(f"  per_trade_max_loss: {risk.get('per_trade_max_loss_inr')}")
print(f"  hard_squareoff    : {trading.get('hard_squareoff_time')}")
print()

pos = json.loads(Path('data/live_algo_positions.json').read_text(encoding='utf-8'))
for pid, p in pos.items():
    entry = p.get('entry_time', '')
    strategy = p.get('strategy', '')
    print(f"Position: {pid}")
    print(f"  Entry   : {entry[:16]}")
    base_mins = int(risk.get('time_exit_minutes', 180) or 180)
    time_cap = min(base_mins, 120) if strategy in ('Institutional', 'OptionBuyer') else base_mins
    try:
        entry_dt = datetime.fromisoformat(entry)
        auto_exit_dt = entry_dt + timedelta(minutes=time_cap)
        print(f"  Auto-exit: {auto_exit_dt.strftime('%H:%M')} IST (TIME_EXIT after {time_cap}min)")
    except Exception as e:
        print(f"  Auto-exit: could not compute ({e})")
    print(f"  Hard squareoff: {trading.get('hard_squareoff_time', '15:20')} IST (hard deadline)")
    print(f"  SL trigger    : loss >= Rs.{risk.get('per_trade_max_loss_inr')}")
    print(f"  Target trigger: profit >= Rs.{risk.get('target_profit_inr')}")
