import json

data = json.loads(open('data/auto_trade_log.json').read())
if data:
    t = data[0]
    print('All keys in first trade:')
    for key in sorted(t.keys()):
        val = str(t[key])[:80]
        print(f'  {key}: {val}')
