import json
from pathlib import Path

# Check correct log location
log_path = Path('data/auto_trade_log.json')
print(f'Log file exists: {log_path.exists()}')

if log_path.exists():
    data = json.loads(log_path.read_text())
    print(f'Total trades: {len(data)}')
    
    if data:
        print('\n=== FIRST 3 TRADES ===')
        for idx, t in enumerate(data[:3]):
            print(f'\nTrade {idx+1}:')
            print(f'  strike: {repr(t.get("strike"))}')
            print(f'  direction: {repr(t.get("direction"))}')
            print(f'  instrument: {repr(t.get("instrument"))}')
            print(f'  status: {repr(t.get("status"))}')
else:
    print('data/auto_trade_log.json NOT FOUND')
    # Check what files exist
    print('\nFiles in data/:')
    for f in Path('data').glob('*.json'):
        print(f'  - {f.name}')
