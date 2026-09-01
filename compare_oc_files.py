#!/usr/bin/env python
"""Load both files and compare"""
import sys
sys.path.insert(0, 'src')
from real_data_loader import load_option_chain

# Load the old file
print("=" * 60)
print("JULY 28 FILE (app_option_chain_NIFTY-28-Jul-2026.csv)")
print("=" * 60)
try:
    oc_old = load_option_chain('downloads/app_option_chain_NIFTY-28-Jul-2026.csv')
    print(f"Loaded: {len(oc_old)} strikes")
    strike_24k = oc_old[oc_old['strike'] == 24000]
    if not strike_24k.empty:
        print(f"Strike 24000:")
        print(f"  CE_LTP: ₹{strike_24k['CE_LTP'].iloc[0]}")
        print(f"  PE_LTP: ₹{strike_24k['PE_LTP'].iloc[0]}")
except Exception as e:
    print(f"Error: {e}")

# Load the current file
print("\n" + "=" * 60)
print("JULY 29 FILE (app_option_chain_NIFTY.csv)")
print("=" * 60)
try:
    oc_new = load_option_chain('downloads/app_option_chain_NIFTY.csv')
    print(f"Loaded: {len(oc_new)} strikes")
    strike_24k = oc_new[oc_new['strike'] == 24000]
    if not strike_24k.empty:
        print(f"Strike 24000:")
        print(f"  CE_LTP: ₹{strike_24k['CE_LTP'].iloc[0]}")
        print(f"  PE_LTP: ₹{strike_24k['PE_LTP'].iloc[0]}")
except Exception as e:
    print(f"Error: {e}")
