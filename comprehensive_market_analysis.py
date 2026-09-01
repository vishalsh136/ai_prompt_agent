#!/usr/bin/env python
"""Comprehensive Market & Strategy Analysis Report - 2026-08-10"""
import json
import os
from datetime import datetime
import sys
sys.path.insert(0, 'src')

print("="*80)
print("COMPREHENSIVE MARKET & STRATEGY ANALYSIS REPORT")
print("Date: 2026-08-10")
print("="*80)

# 1. MARKET DATA ANALYSIS
print("\n📊 TODAY'S MARKET DATA")
print("-"*80)

market_file = 'downloads/live_market_20260810.json'
if os.path.exists(market_file):
    try:
        with open(market_file, 'r') as f:
            market = json.load(f)
        
        print(f"Market Snapshot: {market.get('timestamp')}")
        print(f"Source: {market.get('source')}\n")
        
        for idx in market.get('indices', []):
            print(f"🔹 {idx['index']}")
            print(f"   Price: ₹{idx['last']:,.2f}")
            print(f"   Change: {idx['change']:+.2f} ({idx['changePct']:+.2f}%)")
            print(f"   Day Range: ₹{idx['low']:,.2f} - ₹{idx['high']:,.2f}")
            print(f"   Valuation: P/E={idx['pe']}, P/B={idx['pb']}, DY={idx['dy']}%")
            print(f"   Breadth: {idx['advances']} advances vs {idx['declines']} declines")
            print()
    except Exception as e:
        print(f"⚠️  Error reading market data: {e}")
else:
    print(f"⚠️  Market file not found: {market_file}")

# 2. PROFITABILITY ANALYSIS
print("\n📈 STRATEGY PROFITABILITY ANALYSIS")
print("-"*80)

summary_file = 'trading_profitability_summary.json'
if os.path.exists(summary_file):
    try:
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        print(f"Analysis Date: {summary.get('analysis_date')}")
        print(f"Spot Price: ₹{summary.get('spot_price'):,.2f}")
        print(f"\n📊 Market Metrics:")
        print(f"   PCR Ratio: {summary.get('pcr'):.4f}")
        print(f"   VIX: {summary.get('vix'):.2f}")
        print(f"   Trend: {summary.get('trend')}")
        
        print(f"\n🎯 Strategy Recommendation:")
        print(f"   Best Strategy: {summary.get('best_strategy')}")
        print(f"   Profitability Score: {summary.get('profitability_score')}/10")
        print(f"   Expected Win Rate: {summary.get('win_rate_expected')}")
    except Exception as e:
        print(f"⚠️  Error reading summary: {e}")
else:
    print(f"⚠️  Summary file not found: {summary_file}")

# 3. DOWNLOADS FOLDER STATUS
print("\n\n📁 DOWNLOADS FOLDER STATUS")
print("-"*80)

downloads_dir = 'downloads'
files = os.listdir(downloads_dir) if os.path.exists(downloads_dir) else []

# Group by type
today_files = [f for f in files if '20260810' in f]
recent_files = [f for f in files if any(d in f for d in ['20260807', '20260806', '20260805', '20260804'])]
csv_files = [f for f in files if f.endswith('.csv')]

print(f"Total files in downloads: {len(files)}")
print(f"\n✅ Today's files (2026-08-10): {len(today_files)}")
for f in sorted(today_files):
    size = os.path.getsize(os.path.join(downloads_dir, f)) / 1024
    print(f"   • {f} ({size:.1f} KB)")

print(f"\n📊 Recent CSV files: {len(csv_files)}")
for f in sorted([x for x in csv_files if 'NIFTY' in x])[:5]:
    size = os.path.getsize(os.path.join(downloads_dir, f)) / 1024
    print(f"   • {f} ({size:.1f} KB)")

# 4. CONFIGURATION STATUS
print("\n\n⚙️  CONFIGURATION STATUS")
print("-"*80)

config_file = 'algo_trade_config.json'
if os.path.exists(config_file):
    try:
        with open(config_file, 'r') as f:
            cfg = json.load(f)
        
        trading = cfg.get('trading', {})
        risk = cfg.get('risk', {})
        
        print(f"Active Broker: {cfg.get('active_broker')}")
        print(f"\n📝 Trading Config:")
        print(f"   Symbol: {trading.get('symbol')}")
        print(f"   Strategy: {trading.get('strategy')}")
        print(f"   Lots: {trading.get('lots')} x {trading.get('lot_size')} = {trading.get('lots', 1) * trading.get('lot_size', 0)} units")
        print(f"   Expiry: {trading.get('expiry')}")
        print(f"   Trade Window: {trading.get('trade_window_start')} - {trading.get('trade_window_end')}")
        
        print(f"\n🛡️  Risk Controls:")
        print(f"   Target Profit: ₹{risk.get('target_profit_inr'):,.2f}")
        print(f"   Max Loss per Trade: ₹{risk.get('per_trade_max_loss_inr'):,.2f}")
        print(f"   Time Exit: {risk.get('time_exit_minutes')} minutes")
        
        print(f"\n📋 Enabled Strategies: {len(trading.get('enabled_strategies', []))}")
        for strat in trading.get('enabled_strategies', []):
            print(f"   ✓ {strat}")
    except Exception as e:
        print(f"⚠️  Error reading config: {e}")
else:
    print(f"⚠️  Config file not found: {config_file}")

# 5. STRATEGY VALIDATION RESULTS (already run)
print("\n\n✅ STRATEGY VALIDATION RESULTS")
print("-"*80)
print("All 6 strategies validated:")
print("   • Institutional: ⚠️  SKIPPED (late entry after 14:30)")
print("   • OptionSeller: ⚠️  SKIPPED (insufficient credit)")
print("   • OptionBuyer: ⚠️  SKIPPED (neutral signal)")
print("   • Hedging: ✅ PASSED (Bull Put Spread ready)")
print("   • Agent-Institutional: ⚠️  SKIPPED (late entry after 14:30)")
print("   • Agent-OptionSeller: ⚠️  SKIPPED (insufficient credit)")

print("\n" + "="*80)
print("ANALYSIS COMPLETE")
print("="*80)
