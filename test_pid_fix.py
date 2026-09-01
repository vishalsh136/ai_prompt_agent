#!/usr/bin/env python
"""Simulate what the next tick will do with the existing open position"""
import sys; sys.path.insert(0, 'src')
from datetime import datetime
from src.live_broker_adapter import load_live_positions

positions = load_live_positions()
now = datetime.now()
today_str = now.strftime("%Y%m%d")

# Simulate _position_id() for config strategy = "Iron Condor (Defined Risk)"
config_strategy = "Iron Condor (Defined Risk)"
config_pid = f"algo_NIFTY_{config_strategy}_{today_str}".replace(" ", "_")

print("=== PID RESOLUTION SIMULATION ===")
print(f"Config strategy   : {config_strategy}")
print(f"Config-based pid  : {config_pid}")
pos = positions.get(config_pid)
print(f"Config pid found? : {pos is not None}")

print()
print("--- NEW: Scan all today's positions ---")
resolved_pos = None
resolved_pid = None
for scan_pid, scan_pos in positions.items():
    if scan_pid.endswith(f"_{today_str}") and scan_pos.get("status") == "open":
        resolved_pos = scan_pos
        resolved_pid = scan_pid
        print(f"  Found open position: {scan_pid}")
        print(f"  Status: {scan_pos.get('status')}")
        print(f"  Legs  : {scan_pos.get('legs')}")
        print(f"  Action: MANAGE OPEN POSITION block will now run correctly ✅")
        break

if not resolved_pos:
    print("  No open positions found for today → entry would be allowed")
    print("  (This is expected if position was exited or doesn't exist yet)")
