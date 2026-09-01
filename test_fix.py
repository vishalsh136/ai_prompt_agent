#!/usr/bin/env python
"""Test that the fix works"""
import sys
sys.path.insert(0, 'src')

from auto_trade_engine import load_morning_data

hist, oc, pcr, vix, oc_json = load_morning_data()

print("=" * 60)
print("FIXED load_morning_data() TEST")
print("=" * 60)
print(f"\nOption Chain DataFrame:")
print(f"  Shape: {oc.shape}")
print(f"  File date (inferred): {oc['date'].iloc[0] if not oc.empty else 'N/A'}")
if not oc.empty:
    print(f"\nStrike 24000 prices:")
    strike_24k = oc[oc['strike'] == 24000]
    if not strike_24k.empty:
        print(f"  CE_LTP: ₹{strike_24k['CE_LTP'].iloc[0]}")
        print(f"  PE_LTP: ₹{strike_24k['PE_LTP'].iloc[0]}")
    else:
        print(f"  Strike not found!")
    
    print(f"\nStrike 24200 prices:")
    strike_24k2 = oc[oc['strike'] == 24200]
    if not strike_24k2.empty:
        print(f"  CE_LTP: ₹{strike_24k2['CE_LTP'].iloc[0]}")
        print(f"  PE_LTP: ₹{strike_24k2['PE_LTP'].iloc[0]}")
    else:
        print(f"  Strike not found!")

print(f"\nVIX: {vix}")
print(f"Historical data shape: {hist.shape}")
print(f"PCR data shape: {pcr.shape}")
print(f"JSON path: {oc_json}")
