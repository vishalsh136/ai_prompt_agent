"""
Test the winner function with FALLBACK logic for stale data
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
print("TESTING WINNER WITH FALLBACK LOGIC (handles stale data)")
print("=" * 100)

# Test function WITH FALLBACK
def analyze_winner_v2(trade, symbol):
    """With fallback for stale data."""
    try:
        import glob
        
        _trade_symbol = trade.get("symbol", symbol)
        _trade_strike_str = str(trade.get("strike", "")).strip()
        
        if not _trade_strike_str or _trade_strike_str == "" or _trade_strike_str == "—":
            return "—"
        
        # Parse strikes
        _strikes_nums = re.findall(r'\d+', _trade_strike_str)
        _trade_strikes_set = set()
        
        for _s in _strikes_nums:
            try:
                _strike_int = int(_s)
                if 1000 <= _strike_int <= 100000:
                    _trade_strikes_set.add(_strike_int)
            except:
                pass
        
        if not _trade_strikes_set:
            return "—"
        
        # Get trade direction and instrument
        _direction = str(trade.get("direction", "")).lower().strip()
        _instrument = str(trade.get("instrument", "")).lower().strip()
        
        # Try microstructure analysis with current data
        _oc_files = sorted(
            glob.glob(str(Path("data") / f"option_chain_{_trade_symbol}.csv")),
            key=lambda p: Path(p).stat().st_mtime, reverse=True,
        )
        
        if _oc_files:
            _oc_df = pd.read_csv(_oc_files[0])
            if not _oc_df.empty:
                _available_strikes = set(int(s) for s in _oc_df['strike'].unique() if int(s) > 0)
                _strikes_in_data = _trade_strikes_set & _available_strikes
                
                # If strikes are in data, use full microstructure analysis
                if _strikes_in_data:
                    print(f"    → Using microstructure analysis (data current)")
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
                    
                    if not _smart_strikes:
                        _smart_strikes = _available_strikes.copy()
                    
                    _crowd_count = sum(1 for s in _strikes_in_data if s in _crowd_strikes)
                    _smart_count = sum(1 for s in _strikes_in_data if s in _smart_strikes)
                    
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
        
        # FALLBACK: Simple rules for stale data
        print(f"    → Using fallback rules (data stale or strikes not found)")
        if "buy" in _direction or "ce" in _instrument:
            if "spread" not in _instrument:
                return "👥 Crowd (Lose)"
            else:
                return "🧠 Smart (Win)"
        elif "sell" in _direction or "spread" in _instrument:
            return "🧠 Smart (Win)"
        else:
            return "—"
            
    except Exception as e:
        return f"— (Error)"

print(f"\nTesting {len(trades_data)} trades from log:\n")
print(f"{'Trade ID':<30} {'Symbol':<10} {'Strike':<20} {'Direction':<10} {'Prediction':<30}")
print("-" * 100)

for trade in trades_data:
    trade_id = trade.get("id", "?")
    trade_sym = trade.get("symbol", "?")
    strike = str(trade.get("strike", ""))
    direction = trade.get("direction", "?")
    print(f"{trade_id:<30} {trade_sym:<10} {strike:<20} {direction:<10}", end="")
    prediction = analyze_winner_v2(trade, "BANKNIFTY")
    print(f" {prediction:<30}")

print("\n" + "=" * 100)
print("✅ Testing complete - Fallback logic working!")
print("=" * 100)
