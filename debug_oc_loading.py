#!/usr/bin/env python
"""Debug the option chain loading pipeline"""
import pandas as pd
import sys
sys.path.insert(0, 'src')

from real_data_loader import load_option_chain

# Load the option chain CSV
oc = load_option_chain('downloads/app_option_chain_NIFTY.csv')

print("=" * 60)
print("OPTION CHAIN DATAFRAME DEBUG")
print("=" * 60)
print(f"\nDataFrame shape: {oc.shape}")
print(f"DataFrame columns: {list(oc.columns)}")
print(f"\nFirst 3 rows:")
print(oc.head(3))
print(f"\nData types:")
print(oc.dtypes)
print(f"\nCE_LTP statistics:")
print(f"  Min: {oc['CE_LTP'].min()}")
print(f"  Max: {oc['CE_LTP'].max()}")
print(f"  Mean: {oc['CE_LTP'].mean():.2f}")
print(f"  NaN count: {oc['CE_LTP'].isna().sum()}")
print(f"\nPE_LTP statistics:")
print(f"  Min: {oc['PE_LTP'].min()}")
print(f"  Max: {oc['PE_LTP'].max()}")
print(f"  Mean: {oc['PE_LTP'].mean():.2f}")
print(f"  NaN count: {oc['PE_LTP'].isna().sum()}")
print(f"\nStrike 24000 lookup:")
strike_24k = oc[oc['strike'] == 24000]
if not strike_24k.empty:
    print(f"  CE_LTP: ₹{strike_24k['CE_LTP'].iloc[0]}")
    print(f"  PE_LTP: ₹{strike_24k['PE_LTP'].iloc[0]}")
else:
    print(f"  Not found!")
print(f"\nStrike 24200 lookup:")
strike_24k2 = oc[oc['strike'] == 24200]
if not strike_24k2.empty:
    print(f"  CE_LTP: ₹{strike_24k2['CE_LTP'].iloc[0]}")
    print(f"  PE_LTP: ₹{strike_24k2['PE_LTP'].iloc[0]}")
else:
    print(f"  Not found!")
