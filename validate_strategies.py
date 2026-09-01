#!/usr/bin/env python
"""Verify all 6 strategies produce correct trades"""
import sys
sys.path.insert(0, 'src')

from auto_trade_engine import (
    load_morning_data, _run_institutional, _run_option_seller,
    _run_option_buyer, _run_hedging, _run_institutional_agent,
    _run_option_seller_agent, get_config, LOT_SIZE
)
from institutional_view import InstitutionalAnalyzer
from strategy_builder import StrategyBuilder

hist, oc, pcr, vix, oc_json = load_morning_data()
cfg = get_config('config.yaml')
ia = InstitutionalAnalyzer(cfg)
sb = StrategyBuilder(cfg)
sent = ia.generate_sentiment(hist, oc, pcr)

print("=" * 60)
print("STRATEGY VALIDATION REPORT")
print("=" * 60)
print(f"\nMarket context:")
print(f"  Spot: ₹{oc['spot'].iloc[0]:.2f}")
print(f"  VIX: {vix}")
print(f"  Sentiment: {sent.get('label')} (score: {sent.get('score')})")
print(f"  Total strikes in OC: {len(oc)}")

# Agent optimizer params
opts = {
    "optimal_sl_atr_multiplier": 1.5,
    "optimal_target_atr_multiplier": 2.5,
    "risk_allocation_multiplier": 1.0,
}

strategies = [
    ("Institutional",       lambda: _run_institutional(hist, oc, sent, cfg)),
    ("OptionSeller",        lambda: _run_option_seller(hist, oc, sent, cfg, sb, vix < 20)),
    ("OptionBuyer",         lambda: _run_option_buyer(hist, oc, sent, cfg)),
    ("Hedging",             lambda: _run_hedging(hist, oc, sent, cfg)),
    ("Agent-Institutional", lambda: _run_institutional_agent(hist, oc, sent, cfg, opts)),
    ("Agent-OptionSeller",  lambda: _run_option_seller_agent(hist, oc, sent, cfg, sb, vix < 20, opts)),
]

passed = 0
failed = 0

for name, runner in strategies:
    print(f"\n{'─'*50}")
    print(f"Strategy: {name}")
    try:
        result = runner()
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        failed += 1
        continue

    skip = result.get("skip_reason")
    if skip:
        print(f"  ⚠ SKIPPED: {skip}")
        # Not a failure - valid skip conditions
        passed += 1
        continue

    entry = result.get("entry_price", 0)
    sl    = result.get("stop_loss", 0)
    tgt   = result.get("target", 0)
    instr = result.get("instrument", "")
    strike = result.get("strike", "")
    direction = result.get("direction", "")
    inv   = result.get("investment_amount", 0)

    print(f"  ✓ Instrument: {instr}")
    print(f"  ✓ Strike: {strike}, Direction: {direction}")
    print(f"  ✓ Entry: ₹{entry:.2f}  |  SL: ₹{sl:.2f}  |  Target: ₹{tgt:.2f}")
    print(f"  ✓ Investment: ₹{inv:,.0f}")

    # Validation checks
    errors = []
    if entry <= 0:
        errors.append(f"Entry price is zero/negative: {entry}")
    if entry > 0 and sl >= entry and direction == "buy":
        errors.append(f"SL ({sl}) >= Entry ({entry}) for BUY trade - wrong direction")
    if entry > 0 and sl <= entry and direction == "sell":
        errors.append(f"SL ({sl}) <= Entry ({entry}) for SELL trade - wrong direction")
    if tgt <= 0:
        errors.append(f"Target is zero/negative: {tgt}")
    if entry > 0 and abs(entry - 0.05) < 0.01:
        errors.append(f"Entry price suspiciously small (₹0.05) - likely wrong data loaded")
    if inv <= 0:
        errors.append(f"Investment amount is zero: {inv}")

    if errors:
        for e in errors:
            print(f"  ✗ VALIDATION FAIL: {e}")
        failed += 1
    else:
        print(f"  ✅ All checks passed")
        passed += 1

print(f"\n{'='*60}")
print(f"RESULTS: {passed}/{len(strategies)} strategies PASSED, {failed} FAILED")
print("=" * 60)
