#!/usr/bin/env python
"""Check current market prices from option chain (schema-aware)."""
import json
from pathlib import Path


downloads = Path("downloads")

# Find the most recent option chain file
oc_files = sorted(downloads.glob("option_chain_NIFTY_*.json"))
if not oc_files:
    print("No option chain files found")
    raise SystemExit(1)

oc_file = oc_files[-1]
print(f"Reading option chain from: {oc_file.name}\n")

with open(oc_file, "r", encoding="utf-8-sig") as f:
    oc_data = json.load(f)

print("Market Data:")
print(f"  Spot Price: {oc_data.get('spot_price', 'N/A')}")
print(f"  VIX: {oc_data.get('vix', 'N/A')}")
print(f"  PCR: {oc_data.get('pcr', 'N/A')}")
print(f"  Timestamp: {oc_data.get('timestamp', 'N/A')}")
print(f"  Cron Run Time: {oc_data.get('cron_run_time', 'N/A')}")
print(f"  Data Age: {oc_data.get('cron_run_label', 'N/A')}\n")

strikes = oc_data.get("strikes", [])
if not strikes:
    print("No strikes found in option chain JSON")
    raise SystemExit(0)

spot = float(oc_data.get("spot_price", 0) or 0)
strikes_sorted = sorted(strikes, key=lambda s: abs(float(s.get("strike", 0) or 0) - spot))

print("Sample ATM-near strikes:")
for row in strikes_sorted[:3]:
    strike = int(float(row.get("strike", 0) or 0))
    ce = row.get("CE", {}) or {}
    pe = row.get("PE", {}) or {}
    print(
        f"  Strike {strike}: "
        f"CE LTP={ce.get('ltp', 'N/A')} OI={ce.get('oi', 'N/A')} | "
        f"PE LTP={pe.get('ltp', 'N/A')} OI={pe.get('oi', 'N/A')}"
    )
