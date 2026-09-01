"""
Test the "Likely Winner" column logic for auto trade log
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
from pathlib import Path
from src.market_microstructure import (
    detect_crowd_bias, find_smart_entry_zones, calculate_iv_rank
)

print("=" * 80)
print("MARKET MICROSTRUCTURE - LIKELY WINNER PREDICTION")
print("=" * 80)

# Load option chain data
oc = pd.read_csv('data/option_chain_BANKNIFTY.csv')

# Get crowd and smart zones (extract strikes properly from their return types)
crowd_data = detect_crowd_bias(oc)
crowd_strikes = {int(c.get("strike", -1)) for c in crowd_data if isinstance(c, dict)}

smart_df = find_smart_entry_zones(oc, calculate_iv_rank(oc))
smart_strikes = set()
if isinstance(smart_df, pd.DataFrame) and not smart_df.empty:
    smart_strikes = {int(float(s)) for s in smart_df.get("strike", []) if str(s).replace(".", "", 1).isdigit()}

iv_rank = calculate_iv_rank(oc)

print(f"\n📊 Market Analysis (BANKNIFTY):")
print(f"  Crowd bias strikes: {len(crowd_strikes)} (e.g., {list(crowd_strikes)[:5] if crowd_strikes else 'None'})")
print(f"  Smart entry zones: {len(smart_strikes)} (e.g., {list(smart_strikes)[:5] if smart_strikes else 'None'})")
print(f"  IV Rank: {iv_rank:.1f}%")

# Simulate different trade scenarios
trades = [
    {"id": "T1", "direction": "buy", "instrument": "CE", "strike": "CE:40600", "strategy": "OptionBuyer"},
    {"id": "T2", "direction": "sell", "instrument": "PE", "strike": "PE:40000", "strategy": "OptionSeller"},
    {"id": "T3", "direction": "sell", "instrument": "Bull Put Spread", "strike": "PE:40000/PE:39800", "strategy": "Hedging"},
    {"id": "T4", "direction": "buy", "instrument": "CE", "strike": "CE:41000", "strategy": "Institutional"},
]

print(f"\n{'Trade':<8} {'Direction':<10} {'Strike':<18} {'Strategy':<15} {'Prediction':<30}")
print("-" * 80)

for trade in trades:
    trade_strike_str = str(trade.get("strike", ""))
    
    # Parse strikes
    if "/" in trade_strike_str:
        import re
        strikes_nums = re.findall(r'\d{5}', trade_strike_str)
        trade_strikes_set = {int(s) for s in strikes_nums if s}
    else:
        import re
        match = re.search(r'\d{5}', trade_strike_str)
        trade_strikes_set = {int(match.group())} if match else set()
    
    if not trade_strikes_set:
        prediction = "—"
    else:
        crowd_count = sum(1 for s in trade_strikes_set if s in crowd_strikes)
        smart_count = sum(1 for s in trade_strikes_set if s in smart_strikes)
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
    
    print(f"{trade['id']:<8} {trade['direction']:<10} {trade_strike_str:<18} {trade['strategy']:<15} {prediction:<30}")

print("\n" + "=" * 80)
print("INTERPRETATION")
print("=" * 80)
print("""
👥 Crowd (Likely Lose):
  - When crowd gathers at high volume/OI strikes
  - Buyers get trapped (high premium sellers exit)
  - Prediction: Likely loses money

🧠 Smart (Likely Win):
  - When positioned at low IV zones (smart entry levels)
  - Sellers at these levels get good credit
  - Prediction: Likely makes money

🤝 Both:
  - Trade spans both crowd and smart zones
  - Mixed outcome, depends on execution

— (Unknown):
  - Data not available or strike not found
  - Cannot predict
""")

print("=" * 80)
