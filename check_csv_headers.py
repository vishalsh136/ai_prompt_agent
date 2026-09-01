#!/usr/bin/env python
import csv
from pathlib import Path

csv_file = Path('downloads/app_option_chain_NIFTY.csv')
with open(csv_file, 'r', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    rows = list(reader)

header = rows[1]
print('Full CSV Header (23 columns):')
for i, col in enumerate(header):
    print(f'  Col {i:2d}: "{col}"')
