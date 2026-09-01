import json
from pathlib import Path

# Check if log exists
log_path = Path('logs/auto_trade_log.json')
print(f'Log file exists: {log_path.exists()}')

if log_path.exists():
    try:
        data = json.loads(log_path.read_text())
        print(f'Trades in log: {len(data)}')
        if data:
            print('\nFirst 2 trades:')
            for idx, t in enumerate(data[:2]):
                print(f'\nTrade {idx+1}:')
                print(f'  strike: {repr(t.get("strike", "MISSING"))}')
                print(f'  direction: {repr(t.get("direction", "MISSING"))}')
                print(f'  instrument: {repr(t.get("instrument", "MISSING"))}')
                print(f'  status: {repr(t.get("status", "MISSING"))}')
    except Exception as e:
        print(f'Error reading: {e}')
else:
    print('No log file found')
