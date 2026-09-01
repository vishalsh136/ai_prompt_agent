"""
Test the improved "Likely Winner" logic with actual trade data
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import re
from pathlib import Path
from src.market_microstructure import (
    detect_crowd_bias, find_smart_entry_zones, calculate_iv_rank
)

print("=" * 80)
print("TESTING IMPROVED LIKELY WINNER LOGIC")
print("=" * 80)

# Load option chain data
oc = pd.read_csv('data/option_chain_BANKNIFTY.csv')

# Get crowd and smart zones (improved parsing)
crowd_data = detect_crowd_bias(oc)
crowd_strikes = set()
for c in crowd_data:
    if isinstance(c, dict):
        try:
            cs = int(float(c.get("strike", -1)))
            if cs > 0:
                crowd_strikes.add(cs)
        except:
            pass

smart_df = find_smart_entry_zones(oc, calculate_iv_rank(oc))
smart_strikes = set()
if isinstance(smart_df, pd.DataFrame) and not smart_df.empty:
    for s in smart_df.get("strike", []):
        try:
            ss = int(float(s))
            if ss > 0:
                smart_strikes.add(ss)
        except:
            pass

if not smart_strikes:
    smart_strikes = set(int(s) for s in oc['strike'].unique() if int(s) > 0)

print(f"\n📊 Market Analysis (BANKNIFTY):")
print(f"  Crowd bias strikes: {len(crowd_strikes)} (e.g., {list(crowd_strikes)[:5] if crowd_strikes else 'None'})")
print(f"  Smart entry zones: {len(smart_strikes)} (e.g., {list(smart_strikes)[:5] if smart_strikes else 'None'})")
print(f"  Total strikes in data: {len(oc['strike'].unique())}")

# Simulate different trade scenarios
trades = [
    {"id": "T1", "strike": "CE:40600", "direction": "buy", "instrument": "CE"},
    {"id": "T2", "strike": "PE:40000", "direction": "sell", "instrument": "PE"},
    {"id": "T3", "strike": "PE:40000/PE:39800", "direction": "sell", "instrument": "Bull Put Spread"},
    {"id": "T4", "strike": "CE:41000", "direction": "buy", "instrument": "CE"},
    {"id": "T5", "strike": "40600", "direction": "sell", "instrument": "PE"},  # No prefix
]

print(f"\n{'Trade':<8} {'Strike':<18} {'Parsed Strikes':<20} {'Crowd?':<10} {'Smart?':<10} {'Prediction':<30}")
print("-" * 110)

for trade in trades:
    trade_strike_str = str(trade.get("strike", ""))
    
    # Parse strikes (improved method)
    strikes_nums = re.findall(r'\d+', trade_strike_str)
    trade_strikes_set = set()
    
    for s in strikes_nums:
        try:
            strike_int = int(s)
            if 20000 <= strike_int <= 60000:
                trade_strikes_set.add(strike_int)
        except:
            pass
    
    if not trade_strikes_set:
        prediction = "—"
        crowd_q = "—"
        smart_q = "—"
        parsed = "FAILED"
    else:
        parsed = str(sorted(trade_strikes_set))
        
        crowd_count = sum(1 for s in trade_strikes_set if s in crowd_strikes)
        smart_count = sum(1 for s in trade_strikes_set if s in smart_strikes)
        
        crowd_q = "✓" if crowd_count > 0 else "✗"
        smart_q = "✓" if smart_count > 0 else "✗"
        
        direction = str(trade.get("direction", "")).lower()
        instrument = str(trade.get("instrument", "")).lower()
        
        is_crowd_trade = crowd_count > 0
        is_smart_trade = smart_count > 0
        
        if is_crowd_trade and is_smart_trade:
            positioning = "🤝 Both"
        elif is_crowd_trade:
            positioning = "👥 Crowd"
        elif is_smart_trade:
            positioning = "🧠 Smart"
        else:
            positioning = "—"
        
        if positioning == "👥 Crowd":
            if "buy" in direction or "ce" in instrument.lower():
                prediction = "👥 Crowd (Lose)"
            else:
                prediction = "🧠 Smart (Win)"
        elif positioning == "🧠 Smart":
            if "sell" in direction or "spread" in instrument.lower():
                prediction = "🧠 Smart (Win)"
            else:
                prediction = "👥 Crowd (Lose)"
        else:
            prediction = positioning
    
    print(f"{trade['id']:<8} {trade_strike_str:<18} {parsed:<20} {crowd_q:<10} {smart_q:<10} {prediction:<30}")

print("\n" + "=" * 80)
print("✅ All trades processed successfully!")
print("=" * 80)
