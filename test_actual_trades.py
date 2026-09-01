"""
Test the winner function with actual NIFTY trades from the log
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import json
from pathlib import Path
from src.market_microstructure import (
    detect_crowd_bias, find_smart_entry_zones, calculate_iv_rank
)
import re

# Load actual trades
trades_data = json.loads(Path('data/auto_trade_log.json').read_text())

print("=" * 100)
print("TESTING LIKELY WINNER WITH ACTUAL TRADES FROM LOG")
print("=" * 100)

# Test function (exact copy from app.py with trade symbol)
def analyze_winner(trade, symbol):
    """Determine likely winner - uses TRADE's symbol, not function parameter."""
    try:
        # Use symbol from trade (not the function parameter)
        trade_symbol = trade.get("symbol", symbol)
        
        # Get trade strike
        trade_strike_str = str(trade.get("strike", "")).strip()
        if not trade_strike_str or trade_strike_str == "" or trade_strike_str == "—":
            return "—"
        
        # Parse strike(s)
        strikes_nums = re.findall(r'\d+', trade_strike_str)
        trade_strikes_set = set()
        
        for s in strikes_nums:
            try:
                strike_int = int(s)
                # Accept any 4-5 digit strike (works for both NIFTY and BANKNIFTY)
                if 1000 <= strike_int <= 100000:
                    trade_strikes_set.add(strike_int)
            except:
                pass
        
        if not trade_strikes_set:
            return "—"
        
        # Load option chain for TRADE's symbol (not app symbol)
        import glob
        oc_files = sorted(
            glob.glob(str(Path("data") / f"option_chain_{trade_symbol}.csv")),
            key=lambda p: Path(p).stat().st_mtime, reverse=True,
        )
        if not oc_files:
            return f"— (no {trade_symbol} data)"
        
        oc_df = pd.read_csv(oc_files[0])
        if oc_df.empty:
            return "—"
        
        # Get available strikes
        available_strikes = set(int(s) for s in oc_df['strike'].unique() if int(s) > 0)
        if not available_strikes:
            return "—"
        
        # Get crowd and smart zones
        crowd_data = detect_crowd_bias(oc_df)
        crowd_strikes = set()
        if crowd_data:
            for c in crowd_data:
                if isinstance(c, dict):
                    try:
                        cs = int(float(c.get("strike", -1)))
                        if cs > 0:
                            crowd_strikes.add(cs)
                    except:
                        pass
        
        smart_df = find_smart_entry_zones(oc_df, calculate_iv_rank(oc_df))
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
            smart_strikes = available_strikes.copy()
        
        # Check positioning
        crowd_count = sum(1 for s in trade_strikes_set if s in crowd_strikes)
        smart_count = sum(1 for s in trade_strikes_set if s in smart_strikes)
        
        direction = str(trade.get("direction", "")).lower().strip()
        instrument = str(trade.get("instrument", "")).lower().strip()
        
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
        
        # Predict winner
        if positioning == "👥 Crowd":
            if "buy" in direction or "ce" in instrument:
                return "👥 Crowd (Lose)"
            else:
                return "🧠 Smart (Win)"
        elif positioning == "🧠 Smart":
            if "sell" in direction or "spread" in instrument:
                return "🧠 Smart (Win)"
            else:
                return "👥 Crowd (Lose)"
        else:
            return positioning
            
    except Exception as e:
        return f"— (Error: {str(e)[:20]})"

print(f"\nTesting {len(trades_data)} trades from log:\n")
print(f"{'Trade ID':<30} {'Symbol':<10} {'Strike':<20} {'Direction':<10} {'Prediction':<30}")
print("-" * 100)

for trade in trades_data:
    trade_id = trade.get("id", "?")
    trade_sym = trade.get("symbol", "?")
    strike = str(trade.get("strike", ""))
    direction = trade.get("direction", "?")
    prediction = analyze_winner(trade, "BANKNIFTY")  # App symbol won't matter now
    
    print(f"{trade_id:<30} {trade_sym:<10} {strike:<20} {direction:<10} {prediction:<30}")

print("\n" + "=" * 100)
print("✅ Testing complete!")
print("=" * 100)
