import json
from pathlib import Path
from datetime import datetime as dt

# Load latest option chain JSON
with open('downloads/option_chain_NIFTY_20260717.json', encoding='utf-8-sig') as f:
    data = json.load(f)

cron_t = data.get('cron_run_time', '')
mkt_t = data.get('timestamp', '')
spot_v = float(data.get('spot_price', 0) or 0)
vix_v = float(data.get('vix', 0) or 0)
pcr_v = float(data.get('pcr', 0) or 0)

# Format times
cron_fmt = dt.fromisoformat(cron_t[:19]).strftime('%d-%b %H:%M') if cron_t else '—'
mkt_fmt = dt.fromisoformat(mkt_t[:19]).strftime('%d-%b %H:%M') if mkt_t else '—'

print('\n' + '='*60)
print('SIDEBAR DATA DISPLAY OUTPUT')
print('='*60 + '\n')
print('📡 **Last data refresh**')
print(f'Cron run : `{cron_fmt}`')
print(f'Market ts: `{mkt_fmt}`')
print(f'NIFTY ₹{spot_v:,.1f}  VIX {vix_v:.2f}  PCR {pcr_v:.4f}')
print('\n' + '='*60)
print('✅ This data will appear in the app sidebar!')
print('='*60 + '\n')
