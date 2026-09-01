#!/usr/bin/env python
from src.live_broker_adapter import load_live_positions

def fmt_legs(legs_raw):
    if not legs_raw or not isinstance(legs_raw, list): return "—"
    parts = []
    for leg in legs_raw:
        parts.append(f"{leg.get('action','').upper()} {leg.get('option_type','').upper()} {leg.get('strike','')}")
    return " | ".join(parts)

pos = load_live_positions()
aopen = {k: v for k, v in pos.items() if str(k).startswith("algo_")}
print(f"Open positions: {len(aopen)}")
for pid, p in aopen.items():
    print()
    print(f"  Position ID  : {pid}")
    print(f"  Broker       : {p.get('broker')}")
    print(f"  Symbol       : {p.get('symbol')}")
    print(f"  Strategy     : {p.get('strategy')}")
    print(f"  Legs         : {fmt_legs(p.get('legs'))}")
    print(f"  Lots         : {p.get('lots')}")
    print(f"  Expiry       : {p.get('expiry')}")
    print(f"  Entry Value  : ₹{float(p.get('entry_value', 0) or 0):,.2f}")
    print(f"  Est. Amount  : ₹{float(p.get('est_amount', 0) or 0):,.0f}")
    print(f"  Entry Time   : {str(p.get('entry_time',''))[:16]}")
    print(f"  Status       : {str(p.get('status','')).upper()}")
    print(f"  Dry Run      : {'Yes (paper)' if p.get('dry_run') else '🔴 LIVE'}")
    print(f"  Selection    : {p.get('selection_mode')}")
    print(f"  Updated      : {str(p.get('updated_utc',''))[:16]}")
