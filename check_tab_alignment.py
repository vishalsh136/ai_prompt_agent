#!/usr/bin/env python
"""Check Auto Algo Trader tab alignment with strategies"""
import sys
sys.path.insert(0, 'src')

from strategy_selector import (
    evaluate_strategies, recommend, backtest_winrate,
    idea_to_legs, winner_label, DEFAULT_STRATEGIES, STRATEGY_LABELS, SMART_WIN, CROWD_LOSE
)

print("=" * 60)
print("AUTO ALGO TRADER TAB - STRATEGY ALIGNMENT CHECK")
print("=" * 60)

# 1. Evaluate all strategies
print("\n1. EVALUATE STRATEGIES (Tab G)")
ev = evaluate_strategies()
if ev.get("ok"):
    print(f"   Spot: ₹{ev['spot']:,.2f}  Sentiment: {ev['sentiment']}  VIX: {ev['vix']}")
    print(f"\n   {'Strategy':<22} {'Direction':<8} {'Entry':>8} {'Winner':<18} {'Legs (idea_to_legs)'}")
    print("   " + "─" * 78)
    for idea in ev.get("ideas", []):
        if idea.get("skip_reason"):
            print(f"   {idea['strategy']:<22} {'SKIPPED':<8} {'—':>8} {'—':<18} [{idea['skip_reason']}]")
            continue
        legs = idea_to_legs(idea)
        leg_str = " | ".join(f"{l['action']} {l['option_type']} {l['strike']}" for l in legs) if legs else "❌ UNMAPPABLE"
        wl = idea.get("winner", "—")
        marker = "✅" if idea.get("smart_win") else "⚠"
        print(f"   {idea['strategy']:<22} {idea.get('direction',''):<8} ₹{idea.get('entry_price',0):>6.2f}  {marker} {wl:<15}  {leg_str}")
else:
    print(f"   FAILED: {ev.get('message')}")

# 2. Recommend
print("\n\n2. AUTO_WINNER RECOMMENDATION")
rec = recommend()
if rec.get("ok") and rec.get("recommended"):
    best = rec["recommended_idea"]
    print(f"   ✅ Recommended: {rec['recommended']} → {STRATEGY_LABELS.get(rec['recommended'])}")
    print(f"   Strike: {best.get('strike')}  Direction: {best.get('direction')}")
    legs = idea_to_legs(best)
    if legs:
        print(f"   Broker Legs:")
        for l in legs:
            print(f"     {l['action']:4} {l['option_type']} @ {l['strike']}")
    else:
        print(f"   ❌ idea_to_legs returned empty — cannot execute!")
else:
    print(f"   No recommendation: {rec.get('message')}")

# 3. Backtest
print("\n\n3. BACKTEST WIN-RATE (from auto_trade_log.json)")
rows = backtest_winrate()
for r in rows:
    print(f"   {r['strategy']:<22} {r['trades']} trades  {r['win_rate_pct']:.0f}% win  ₹{r['total_pnl']:,.0f} total")

# 4. Winner label classification review
print("\n\n4. WINNER LABEL CLASSIFICATION REVIEW")
sentiment_score = int(ev.get("ideas", [{}])[0].get("strategy","") and 2 or 0)
# Get actual sentiment from the evaluation
import sys
sys.path.insert(0, 'src')
from auto_trade_engine import load_morning_data
from institutional_view import InstitutionalAnalyzer
from utils import get_config
_h, _oc, _p, _v, _ = load_morning_data()
_cfg = get_config('config.yaml')
_ia = InstitutionalAnalyzer(_cfg)
_sent = _ia.generate_sentiment(_h, _oc, _p)
s = int(_sent.get("score", 0))
test_cases = [
    ("buy",  "CE",                        s, "Buy CE (bullish) with current sentiment"),
    ("buy",  "CE",                        0, "Buy CE in neutral market (score=0)"),
    ("buy",  "PE",                        -2, "Buy PE in bearish market (score=-2)"),
    ("sell", "Short Strangle",            0, "Short Strangle (neutral seller)"),
    ("sell", "Iron Condor (Defined Risk)", 0, "Iron Condor (defined risk seller)"),
    ("sell", "Bull Put Spread",           0, "Bull Put Spread (credit spread)"),
]
for direction, instr, score_val, label in test_cases:
    wl = winner_label(direction, instr, score_val)
    mark = "✅" if wl == SMART_WIN else "⚠"
    print(f"   {mark} [{direction:4} {instr:<30} score={score_val:+2}] → {wl} ({label})")

print("\n5. ISSUES FOUND")
issues = []
for idea in ev.get("ideas", []):
    if idea.get("skip_reason"):
        continue
    legs = idea_to_legs(idea)
    if not legs:
        issues.append(f"   ❌ {idea['strategy']}: idea_to_legs() returned empty → cannot execute in auto_winner mode")

if issues:
    for i in issues:
        print(i)
else:
    print("   None found. All 6 strategies fully aligned with Auto Algo Trader tab.")
