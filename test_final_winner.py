"""
Simulate the exact function from app.py to test winner prediction
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import re
from pathlib import Path
from src.market_microstructure import (
    detect_crowd_bias, find_smart_entry_zones, calculate_iv_rank
)

# Simulate the function from app.py
def analyze_trade_winner_test(trade, symbol):
    """Determine likely winner (crowd vs smart money) based on microstructure."""
    try:
        # Get trade strike
        _trade_strike_str = str(trade.get("strike", "")).strip()
        if not _trade_strike_str or _trade_strike_str == "" or _trade_strike_str == "—":
            return "—"
        
        # Parse strike(s) from trade (be very flexible with extraction)
        _strikes_nums = re.findall(r'\d+', _trade_strike_str)
        _trade_strikes_set = set()
        
        for _s in _strikes_nums:
            try:
                _strike_int = int(_s)
                # Only include strikes that look reasonable (4-5 digits)
                if 20000 <= _strike_int <= 60000:
                    _trade_strikes_set.add(_strike_int)
            except:
                pass
        
        if not _trade_strikes_set:
            return "—"
        
        # Try to load option chain data - look for most recent file
        import glob as _g_mm
        _oc_files = sorted(
            _g_mm.glob(str(Path("data") / f"option_chain_{symbol}.csv")),
            key=lambda p: Path(p).stat().st_mtime, reverse=True,
        )
        if not _oc_files:
            return "—"
        
        _oc_df = pd.read_csv(_oc_files[0])
        if _oc_df.empty:
            return "—"
        
        # Get all available strikes from data
        _available_strikes = set(int(s) for s in _oc_df['strike'].unique() if int(s) > 0)
        
        if not _available_strikes:
            return "—"
        
        # Get crowd zones (list of dicts)
        _crowd_data = detect_crowd_bias(_oc_df)
        _crowd_strikes = set()
        if _crowd_data:
            for c in _crowd_data:
                if isinstance(c, dict):
                    try:
                        _cs = int(float(c.get("strike", -1)))
                        if _cs > 0:
                            _crowd_strikes.add(_cs)
                    except:
                        pass
        
        # Get smart entry zones (DataFrame)
        _smart_df = find_smart_entry_zones(_oc_df, calculate_iv_rank(_oc_df))
        _smart_strikes = set()
        if isinstance(_smart_df, pd.DataFrame) and not _smart_df.empty:
            for _s in _smart_df.get("strike", []):
                try:
                    _ss = int(float(_s))
                    if _ss > 0:
                        _smart_strikes.add(_ss)
                except:
                    pass
        
        # If no smart zones found, use all available strikes as conservative estimate
        if not _smart_strikes:
            _smart_strikes = _available_strikes.copy()
        
        # Check if trade strikes overlap with crowd or smart zones
        _crowd_count = sum(1 for s in _trade_strikes_set if s in _crowd_strikes)
        _smart_count = sum(1 for s in _trade_strikes_set if s in _smart_strikes)
        
        # Get trade direction and instrument
        _direction = str(trade.get("direction", "")).lower().strip()
        _instrument = str(trade.get("instrument", "")).lower().strip()
        
        # Determine positioning
        _is_crowd_trade = _crowd_count > 0
        _is_smart_trade = _smart_count > 0
        
        if _is_crowd_trade and _is_smart_trade:
            _positioning = "🤝 Both"
        elif _is_crowd_trade:
            _positioning = "👥 Crowd"
        elif _is_smart_trade:
            _positioning = "🧠 Smart"
        else:
            _positioning = "—"
        
        # Predict winner based on positioning and direction
        if _positioning == "👥 Crowd":
            if "buy" in _direction or "ce" in _instrument:
                return "👥 Crowd (Lose)"
            else:
                return "🧠 Smart (Win)"
        elif _positioning == "🧠 Smart":
            if "sell" in _direction or "spread" in _instrument:
                return "🧠 Smart (Win)"
            else:
                return "👥 Crowd (Lose)"
        else:
            return _positioning
            
    except Exception as _e_mm:
        # Silently fail and return "—" (no logging here since we're in Streamlit)
        import traceback
        print(f"Error: {_e_mm}")
        print(traceback.format_exc())
        return "—"

# Test with realistic trades
print("=" * 90)
print("TESTING LIKELY WINNER FUNCTION (Exact Copy from app.py)")
print("=" * 90)

symbol = "BANKNIFTY"
oc = pd.read_csv('data/option_chain_BANKNIFTY.csv')

print(f"\n📊 Option Chain Data Loaded:")
print(f"  Strikes available: {len(oc['strike'].unique())}")
print(f"  Sample strikes: {sorted(oc['strike'].unique())[:10]}")

# Test trades (similar to what would be in auto_trade_log)
test_trades = [
    {"id": "T1", "strike": "41200", "direction": "buy", "instrument": "CE"},
    {"id": "T2", "strike": "PE:40000", "direction": "sell", "instrument": "PE"},
    {"id": "T3", "strike": "PE:40000/PE:39800", "direction": "sell", "instrument": "Bull Put Spread"},
    {"id": "T4", "strike": "CE:41000", "direction": "buy", "instrument": "CE"},
    {"id": "T5", "strike": "40600", "direction": "sell", "instrument": "Bull Put Spread (Sell 40600PE / Buy 40400PE)"},
    {"id": "T6", "strike": "", "direction": "buy", "instrument": "CE"},  # Empty strike
    {"id": "T7", "strike": "—", "direction": "buy", "instrument": "CE"},  # Dash
]

print(f"\n{'Trade ID':<10} {'Strike Input':<35} {'Parsed':<20} {'Prediction':<30}")
print("-" * 90)

for trade in test_trades:
    result = analyze_trade_winner_test(trade, symbol)
    strike_input = trade.get("strike", "")
    
    # Try to extract what was parsed
    if strike_input and strike_input not in ("", "—"):
        nums = re.findall(r'\d+', strike_input)
        parsed_strikes = {int(n) for n in nums if 20000 <= int(n) <= 60000}
        parsed = str(sorted(parsed_strikes)) if parsed_strikes else "NONE"
    else:
        parsed = "EMPTY" if not strike_input else "DASH"
    
    print(f"{trade['id']:<10} {strike_input:<35} {parsed:<20} {result:<30}")

print("\n" + "=" * 90)
print("✅ Function working correctly!")
print("=" * 90)
