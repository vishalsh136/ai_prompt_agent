#!/usr/bin/env python
"""Verify that both fixes have been applied correctly"""

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

print('FIX VERIFICATION REPORT')
print('=' * 50)

checks = [
    ('datetime import fixed', 'from datetime import datetime as _dt_p, timezone as _tz_p' in content),
    ('timezone usage fixed', '_tz_p.utc' in content),
    ('use_container_width removed', 'use_container_width' not in content),
]

for label, passed in checks:
    symbol = 'OK' if passed else 'FAIL'
    print(f"[{symbol}] {label}")

print('\nPARAMETER COUNTS:')
print("  - width='stretch':", content.count("width='stretch'"))
print("  - width='content':", content.count("width='content'"))
print("  - use_container_width:", content.count('use_container_width'))

if all(c[1] for c in checks):
    print('\n*** ALL FIXES VERIFIED SUCCESSFULLY! ***')
else:
    print('\n*** SOME FIXES FAILED! ***')
