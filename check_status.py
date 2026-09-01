import json
with open('data/live_algo_positions.json') as f:
    positions = json.load(f)

print("=== POSITION STATUS ===")
for pid, p in positions.items():
    if pid.startswith('algo_'):
        status = p.get('status', 'UNKNOWN').upper()
        entry_value = p.get('entry_value', 0)
        est_amount = p.get('est_amount', 0)
        entry_time = p.get('entry_time', '—')
        legs = p.get('legs', [])
        print(f"\nPosition: {pid}")
        print(f"  Status: {status}")
        print(f"  Entry Value (Premium Paid): ₹{entry_value:,.2f}")
        print(f"  Est. Amount (Margin): ₹{est_amount:,.0f}")
        print(f"  Entry Time: {entry_time}")
        print(f"  Legs: {legs}")
