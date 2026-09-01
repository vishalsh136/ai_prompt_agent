#!/usr/bin/env python
"""Check strikes in option chain"""
import json
from pathlib import Path

oc_file = Path("downloads/option_chain_NIFTY_20260729.json")

with open(oc_file, "r", encoding="utf-8-sig") as f:
    data = json.load(f)

strikes = data.get("strikes", [])
print(f"Total strikes: {len(strikes)}")

if strikes:
    print("\nFirst 3 strikes:")
    for s in strikes[:3]:
        strike_val = s.get('strike')
        ce_ltp = s.get('calls_ltp')
        ce_oi = s.get('calls_oi')
        pe_ltp = s.get('puts_ltp')
        pe_oi = s.get('puts_oi')
        print(f"  {strike_val}: CE={ce_ltp} (OI={ce_oi}), PE={pe_ltp} (OI={pe_oi})")
else:
    print("No strikes found!")
    print(f"Data keys: {list(data.keys())}")
