#!/usr/bin/env python
"""Today's Market Analysis & Strategy Validation Report"""
import json
import sys
sys.path.insert(0, 'src')

# Load market data
with open('downloads/live_market_20260810.json', 'r') as f:
    market = json.load(f)

with open('trading_profitability_summary.json', 'r') as f:
    summary = json.load(f)

print('='*70)
print('TODAY\'S MARKET ANALYSIS (2026-08-10)')
print('='*70)

for idx in market.get('indices', []):
    name = idx['index']
    last = idx['last']
    change = idx['change']
    pct = idx['changePct']
    pe = idx['pe']
    pb = idx['pb']
    dy = idx['dy']
    
    print(f'\n{name}:')
    print(f'  Price: ₹{last:,.2f} | Change: {change:+.2f} ({pct:+.2f}%)')
    print(f'  P/E: {pe} | P/B: {pb} | Dividend Yield: {dy}%')
    print(f'  Advances: {idx["advances"]} | Declines: {idx["declines"]}')

print(f'\n{"="*70}')
print(f'PROFITABILITY METRICS:')
print(f'  Best Strategy: {summary.get("best_strategy")}')
print(f'  Trend: {summary.get("trend")}')
print(f'  PCR Ratio: {summary.get("pcr"):.4f}')
print(f'  VIX: {summary.get("vix"):.2f}')
print(f'  Profitability Score: {summary.get("profitability_score")}/10')
print(f'  Expected Win Rate: {summary.get("win_rate_expected")}')
print('='*70)
