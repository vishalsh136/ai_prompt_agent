import json
from pathlib import Path

log_candidates = [
    Path('data/auto_trade_log.json'),
    Path('logs/auto_trade_log.json'),
]
log_file = next((p for p in log_candidates if p.exists()), None)

if log_file is not None:
    with open(log_file) as f:
        trades = json.load(f)
    
    print(f'Total trades: {len(trades)}')
    print()
    
    # Show first 3 trades
    for i, t in enumerate(trades[:3]):
        print(f"Trade {i+1}:")
        print(f"  Strike: {t.get('strike', 'N/A')}")
        print(f"  Direction: {t.get('direction', 'N/A')}")
        print(f"  Instrument: {t.get('instrument', 'N/A')}")
        print()
else:
    print('No auto_trade_log.json found')
