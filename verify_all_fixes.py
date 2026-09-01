#!/usr/bin/env python
"""Verify all fixes are in place"""
from pathlib import Path

# Check datetime fix
app_file = Path('app.py')
content = app_file.read_text(encoding='utf-8', errors='ignore')

# Check 1: datetime import has timezone
if 'from datetime import datetime as _dt_p, timezone as _tz_p' in content:
    print('✓ Datetime fix: import statement correct')
else:
    print('✗ Datetime fix: import statement MISSING')

# Check 2: timezone usage
if '_dt_p.now(_tz_p.utc).isoformat()' in content:
    print('✓ Datetime fix: timezone usage correct')
else:
    print('✗ Datetime fix: timezone usage INCORRECT')

# Check 3: No use_container_width
if 'use_container_width' not in content:
    print('✓ Deprecation fix: use_container_width removed')
else:
    print('✗ Deprecation fix: use_container_width STILL PRESENT')

# Check auto_trade_engine fix
engine_file = Path('src/auto_trade_engine.py')
engine_content = engine_file.read_text(encoding='utf-8', errors='ignore')

# Look for the fixed code pattern
if '# Use the generic app_option_chain_NIFTY.csv' in engine_content:
    print('✓ Data loading fix: using generic CSV file (FIXED)')
elif 'oc_files = sorted(glob.glob' in engine_content:
    print('✗ Data loading fix: STILL using old file selection logic')
else:
    print('? Data loading fix: Cannot determine status')
