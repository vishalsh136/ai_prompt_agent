"""
Market Microstructure Analysis
Identifies who wins/loses in options trading by analyzing:
- OI Heatmap (accumulation vs distribution)
- IV Rank (premium expensive/cheap)
- Options Flow (buying pressure)
- Crowd Bias Detector
- Smart Entry Zones
- Realistic P&L with hidden costs
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

def get_oi_heatmap(current_option_chain, prev_option_chain=None):
    """
    Analyze OI changes by strike to identify accumulation vs distribution zones.
    Returns dataframe with OI change analysis.
    Format: date, strike, CE_LTP, CE_IV, CE_OI, CE_Volume, PE_LTP, PE_IV, PE_OI, PE_Volume, spot
    """
    if current_option_chain is None or current_option_chain.empty:
        return pd.DataFrame()
    
    df = current_option_chain.copy()
    result = []
    
    for _, row in df.iterrows():
        try:
            strike = str(row.get('strike', ''))
            
            # CE side
            ce_oi = float(row.get('CE_OI', 0))
            ce_volume = float(row.get('CE_Volume', 0))
            ce_iv = float(row.get('CE_IV', 50))
            ce_ltp = float(row.get('CE_LTP', 0))
            
            # PE side
            pe_oi = float(row.get('PE_OI', 0))
            pe_volume = float(row.get('PE_Volume', 0))
            pe_iv = float(row.get('PE_IV', 50))
            pe_ltp = float(row.get('PE_LTP', 0))
            
            # CE analysis
            ce_pressure = ce_volume * (ce_iv / 100) * 100
            result.append({
                'strike': strike,
                'opt_type': 'CE',
                'oi': ce_oi,
                'volume': ce_volume,
                'iv': ce_iv,
                'ltp': ce_ltp,
                'bid_ask_spread': 0,  # not available in this format
                'buying_pressure': ce_pressure,
                'iv_level': 'High' if ce_iv > 60 else 'Medium' if ce_iv > 40 else 'Low'
            })
            
            # PE analysis
            pe_pressure = pe_volume * (pe_iv / 100) * 100
            result.append({
                'strike': strike,
                'opt_type': 'PE',
                'oi': pe_oi,
                'volume': pe_volume,
                'iv': pe_iv,
                'ltp': pe_ltp,
                'bid_ask_spread': 0,
                'buying_pressure': pe_pressure,
                'iv_level': 'High' if pe_iv > 60 else 'Medium' if pe_iv > 40 else 'Low'
            })
        except (ValueError, TypeError):
            continue
    
    return pd.DataFrame(result)


def calculate_iv_rank(option_chain, symbol='BANKNIFTY', window_days=252):
    """
    Calculate IV Rank (percentile of current IV vs 52-week history).
    Returns IV Rank % (0-100, where 100 = highest in 52 weeks).
    """
    try:
        if option_chain is None or option_chain.empty:
            return 50  # neutral if no data
        
        # Get average IV from current option chain (CE and PE)
        df = option_chain.copy()
        ce_ivs = pd.to_numeric(df.get('CE_IV', []), errors='coerce')
        pe_ivs = pd.to_numeric(df.get('PE_IV', []), errors='coerce')
        
        all_ivs = pd.concat([ce_ivs, pe_ivs], ignore_index=True)
        current_iv = all_ivs.mean() if len(all_ivs) > 0 else 50
        
        # Load historical option chain data to get IV history
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        
        # For now, use a simple approximation:
        # If IV > 60 = high (75th percentile)
        # If IV 40-60 = medium (50th)
        # If IV < 40 = low (25th)
        if current_iv > 65:
            iv_rank = 75
        elif current_iv > 55:
            iv_rank = 60
        elif current_iv > 45:
            iv_rank = 50
        elif current_iv > 35:
            iv_rank = 40
        else:
            iv_rank = 25
        
        return iv_rank
    except Exception as e:
        print(f"Error calculating IV Rank: {e}")
        return 50


def analyze_options_flow(option_chain):
    """
    Analyze options flow to detect aggressive buying/selling pressure.
    Format: date, strike, CE_LTP, CE_IV, CE_OI, CE_Volume, PE_LTP, PE_IV, PE_OI, PE_Volume, spot
    Returns summary of call vs put buying, implied direction.
    """
    if option_chain is None or option_chain.empty:
        return {}
    
    df = option_chain.copy()
    
    ce_volume = pd.to_numeric(df.get('CE_Volume', []), errors='coerce').sum()
    pe_volume = pd.to_numeric(df.get('PE_Volume', []), errors='coerce').sum()
    
    ce_oi = pd.to_numeric(df.get('CE_OI', []), errors='coerce').sum()
    pe_oi = pd.to_numeric(df.get('PE_OI', []), errors='coerce').sum()
    
    ce_iv = pd.to_numeric(df.get('CE_IV', []), errors='coerce').mean()
    pe_iv = pd.to_numeric(df.get('PE_IV', []), errors='coerce').mean()
    
    total_volume = ce_volume + pe_volume
    call_ratio = ce_volume / total_volume if total_volume > 0 else 0.5
    
    total_oi = ce_oi + pe_oi
    call_oi_ratio = ce_oi / total_oi if total_oi > 0 else 0.5
    
    # Determine sentiment
    if call_ratio > 0.65 and ce_iv > pe_iv:
        sentiment = "🔴 EXTREMELY BULLISH (Overheated)"
    elif call_ratio > 0.60:
        sentiment = "🟠 STRONGLY BULLISH"
    elif call_ratio > 0.55:
        sentiment = "🟡 MODERATELY BULLISH"
    elif call_ratio < 0.40:
        sentiment = "🔵 STRONGLY BEARISH"
    else:
        sentiment = "⚪ NEUTRAL"
    
    return {
        'call_volume_ratio': round(call_ratio * 100, 1),
        'put_volume_ratio': round((1 - call_ratio) * 100, 1),
        'call_oi_ratio': round(call_oi_ratio * 100, 1),
        'put_oi_ratio': round((1 - call_oi_ratio) * 100, 1),
        'call_avg_iv': round(ce_iv, 2),
        'put_avg_iv': round(pe_iv, 2),
        'sentiment': sentiment,
        'crowd_conviction': 'EXTREME' if abs(call_ratio - 0.5) > 0.15 else 'STRONG' if abs(call_ratio - 0.5) > 0.10 else 'MODERATE'
    }


def detect_crowd_bias(option_chain):
    """
    Identify which strikes have highest crowd concentration.
    Format: date, strike, CE_LTP, CE_IV, CE_OI, CE_Volume, PE_LTP, PE_IV, PE_OI, PE_Volume, spot
    High concentration = crowd gathered here = likely to lose (they're the "dumb money").
    """
    if option_chain is None or option_chain.empty:
        return []
    
    df = option_chain.copy()
    results = []
    
    # Calculate total volume
    df['CE_Volume_num'] = pd.to_numeric(df.get('CE_Volume', []), errors='coerce').fillna(0)
    df['PE_Volume_num'] = pd.to_numeric(df.get('PE_Volume', []), errors='coerce').fillna(0)
    df['CE_IV_num'] = pd.to_numeric(df.get('CE_IV', []), errors='coerce').fillna(50)
    df['PE_IV_num'] = pd.to_numeric(df.get('PE_IV', []), errors='coerce').fillna(50)
    df['CE_OI_num'] = pd.to_numeric(df.get('CE_OI', []), errors='coerce').fillna(0)
    df['PE_OI_num'] = pd.to_numeric(df.get('PE_OI', []), errors='coerce').fillna(0)
    df['CE_LTP_num'] = pd.to_numeric(df.get('CE_LTP', []), errors='coerce').fillna(0)
    df['PE_LTP_num'] = pd.to_numeric(df.get('PE_LTP', []), errors='coerce').fillna(0)
    
    ce_total = df['CE_Volume_num'].sum()
    pe_total = df['PE_Volume_num'].sum()
    
    # Analyze CE
    if ce_total > 0:
        for _, row in df.iterrows():
            crowd_pct = (row['CE_Volume_num'] / ce_total) * 100
            if crowd_pct > 0.3:  # More than 0.3% of CE volume (adjusted for many strikes)
                crowd_level = "🔴 EXTREME" if crowd_pct > 15 else "🟠 HIGH" if crowd_pct > 8 else "🟡 MODERATE"
                results.append({
                    'strike': str(row['strike']),
                    'opt_type': 'CE',
                    'crowd_pct': round(crowd_pct, 1),
                    'crowd_level': crowd_level,
                    'volume': int(row['CE_Volume_num']),
                    'oi': int(row['CE_OI_num']),
                    'iv': round(row['CE_IV_num'], 2),
                    'ltp': round(row['CE_LTP_num'], 2),
                    'risk_level': 'HIGH' if crowd_pct > 1.2 else 'MODERATE' if crowd_pct > 0.6 else 'LOW'
                })
    
    # Analyze PE
    if pe_total > 0:
        for _, row in df.iterrows():
            crowd_pct = (row['PE_Volume_num'] / pe_total) * 100
            if crowd_pct > 2:
                crowd_level = "🔴 EXTREME" if crowd_pct > 15 else "🟠 HIGH" if crowd_pct > 8 else "🟡 MODERATE"
                results.append({
                    'strike': str(row['strike']),
                    'opt_type': 'PE',
                    'crowd_pct': round(crowd_pct, 1),
                    'crowd_level': crowd_level,
                    'volume': int(row['PE_Volume_num']),
                    'oi': int(row['PE_OI_num']),
                    'iv': round(row['PE_IV_num'], 2),
                    'ltp': round(row['PE_LTP_num'], 2),
                    'risk_level': 'HIGH' if crowd_pct > 12 else 'MODERATE' if crowd_pct > 8 else 'LOW'
                })
    
    return sorted(results, key=lambda x: x['crowd_pct'], reverse=True)[:10]


def find_smart_entry_zones(option_chain, iv_rank_pct=50):
    """
    Identify strikes where IV Rank is low (< 40th percentile) = better value entry.
    Format: date, strike, CE_LTP, CE_IV, CE_OI, CE_Volume, PE_LTP, PE_IV, PE_OI, PE_Volume, spot
    """
    if option_chain is None or option_chain.empty:
        return pd.DataFrame()
    
    df = option_chain.copy()
    smart_zones = []
    
    df['CE_IV_num'] = pd.to_numeric(df.get('CE_IV', []), errors='coerce').fillna(50)
    df['PE_IV_num'] = pd.to_numeric(df.get('PE_IV', []), errors='coerce').fillna(50)
    df['CE_Volume_num'] = pd.to_numeric(df.get('CE_Volume', []), errors='coerce').fillna(0)
    df['PE_Volume_num'] = pd.to_numeric(df.get('PE_Volume', []), errors='coerce').fillna(0)
    df['CE_LTP_num'] = pd.to_numeric(df.get('CE_LTP', []), errors='coerce').fillna(0)
    df['PE_LTP_num'] = pd.to_numeric(df.get('PE_LTP', []), errors='coerce').fillna(0)
    # Find median IV to use as benchmark
    ce_iv_median = df['CE_IV_num'].median()
    pe_iv_median = df['PE_IV_num'].median()
    
    # Low IV = below 75% of median (value entry)
    ce_low_threshold = max(ce_iv_median * 0.75, 15)
    pe_low_threshold = max(pe_iv_median * 0.75, 15)
    
    # Find low IV strikes in CE
    for _, row in df[df['CE_IV_num'] <= ce_low_threshold].iterrows():
        smart_zones.append({
            'strike': str(row['strike']),
            'opt_type': 'CE',
            'iv': round(row['CE_IV_num'], 2),
            'iv_percentile': round(iv_rank_pct, 1),
            'ltp': round(row['CE_LTP_num'], 2),
            'volume': int(row['CE_Volume_num']),
            'entry_quality': '⭐⭐⭐ EXCELLENT' if row['CE_IV_num'] < 15 else '⭐⭐ GOOD' if row['CE_IV_num'] <= ce_low_threshold else '⭐ FAIR'
        })
    
    # Find low IV strikes in PE
    for _, row in df[df['PE_IV_num'] <= pe_low_threshold].iterrows():
        smart_zones.append({
            'strike': str(row['strike']),
            'opt_type': 'PE',
            'iv': round(row['PE_IV_num'], 2),
            'iv_percentile': round(iv_rank_pct, 1),
            'ltp': round(row['PE_LTP_num'], 2),
            'volume': int(row['PE_Volume_num']),
            'entry_quality': '⭐⭐⭐ EXCELLENT' if row['PE_IV_num'] < 15 else '⭐⭐ GOOD' if row['PE_IV_num'] <= pe_low_threshold else '⭐ FAIR'
        })
    
    return pd.DataFrame(smart_zones)


def calculate_realistic_pnl(entry_price, exit_price, quantity, 
                            brokerage_pct=0.03, slippage_pct=0.5, tax_rate=0.20):
    """
    Calculate realistic P&L accounting for:
    - Slippage (entry + exit)
    - Brokerage fees
    - Short-term capital gains tax
    
    Returns dict with gross, costs, and net P&L.
    """
    if entry_price <= 0 or exit_price <= 0:
        return {}
    
    # Gross profit/loss
    gross_pnl_per_unit = exit_price - entry_price
    gross_pnl = gross_pnl_per_unit * quantity
    
    # Slippage (assuming 0.5% on entry, 0.5% on exit)
    slippage_cost = (entry_price * slippage_pct / 100 + exit_price * slippage_pct / 100) * quantity
    
    # Brokerage (0.03% of turnover)
    turnover = (entry_price + exit_price) * quantity
    brokerage_cost = turnover * brokerage_pct / 100
    
    # Taxes (20% STCG on profits only, if profitable)
    taxable_profit = max(0, gross_pnl)
    tax_cost = taxable_profit * tax_rate / 100
    
    # Net P&L
    total_costs = slippage_cost + brokerage_cost + tax_cost
    net_pnl = gross_pnl - total_costs
    
    # Win/lose classification
    result_quality = '✅ WINNER' if net_pnl > gross_pnl * 0.5 else '⚠️  BREAKEVEN' if net_pnl > 0 else '❌ LOSER'
    
    return {
        'entry_price': round(entry_price, 2),
        'exit_price': round(exit_price, 2),
        'quantity': quantity,
        'gross_pnl': round(gross_pnl, 2),
        'slippage_cost': round(slippage_cost, 2),
        'brokerage_cost': round(brokerage_cost, 2),
        'tax_cost': round(tax_cost, 2),
        'total_costs': round(total_costs, 2),
        'net_pnl': round(net_pnl, 2),
        'net_pnl_pct': round((net_pnl / (entry_price * quantity)) * 100, 2) if entry_price * quantity > 0 else 0,
        'result_quality': result_quality,
        'cost_as_pct_of_gross': round((total_costs / abs(gross_pnl)) * 100, 1) if gross_pnl != 0 else 0
    }


def crowd_vs_smart_analysis(option_chain, crowd_bias_strikes):
    """
    Compare crowd-gathered strikes vs smart entry zones to predict winners.
    """
    if not crowd_bias_strikes:
        return {}
    
    # Find highest crowd concentration strike
    crowd_strike = crowd_bias_strikes[0] if crowd_bias_strikes else None
    
    # Find smart entry zone (lowest IV)
    smart_zones = find_smart_entry_zones(option_chain)
    
    analysis = {
        'crowd_gathered_at': crowd_strike['strike'] if crowd_strike else 'N/A',
        'crowd_iv': crowd_strike['iv'] if crowd_strike else 'N/A',
        'crowd_crowd_pct': crowd_strike['crowd_pct'] if crowd_strike else 'N/A',
        'smart_entry_at': smart_zones.iloc[0]['strike'] if not smart_zones.empty else 'N/A',
        'smart_iv': smart_zones.iloc[0]['iv'] if not smart_zones.empty else 'N/A',
        'probability_prediction': 'Crowd likely to lose (expensive entry), Smart money positioned better'
    }
    
    return analysis
