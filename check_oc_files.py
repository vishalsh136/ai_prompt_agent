#!/usr/bin/env python
"""Check which option chain file is being used"""
import glob
from pathlib import Path

DOWNLOADS = Path('downloads')
SYMBOL = 'NIFTY'

# Show all available option chain files
all_oc_files = sorted(glob.glob(str(DOWNLOADS / f"app_option_chain_{SYMBOL}-*.csv")))
print("Option chain files with dates in name:")
for f in all_oc_files:
    print(f"  {Path(f).name}")

generic_oc_file = DOWNLOADS / f"app_option_chain_{SYMBOL}.csv"
print(f"\nGeneric option chain file:")
print(f"  {generic_oc_file.name} exists: {generic_oc_file.exists()}")

# Check which one load_morning_data() would use
selected = generic_oc_file
print(f"\nload_morning_data() selects: {selected.name}")
if all_oc_files:
    print("Note: dated app_option_chain files are kept for reference and should not be used for live valuation.")
