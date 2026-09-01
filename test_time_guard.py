#!/usr/bin/env python
"""Test time-of-day guard: buyers allowed at 09:30, blocked after 14:30"""
import sys; sys.path.insert(0, 'src')
from unittest.mock import patch
from datetime import datetime

from auto_trade_engine import load_morning_data, _run_institutional, _run_option_seller
from institutional_view import InstitutionalAnalyzer
from strategy_builder import StrategyBuilder
from utils import get_config

hist, oc, pcr, vix, _ = load_morning_data()
cfg = get_config('config.yaml')
ia = InstitutionalAnalyzer(cfg)
sb = StrategyBuilder(cfg)
sent = ia.generate_sentiment(hist, oc, pcr)
vix_safe = vix < 20

print("Time-of-Day Guard Test")
print("=" * 45)

for time_str in ["09:30", "10:15", "14:29", "14:31", "16:00"]:
    with patch('auto_trade_engine.datetime') as mock_dt:
        mock_dt.now.return_value = datetime.strptime(f"2026-07-29 {time_str}", "%Y-%m-%d %H:%M")
        mock_dt.strptime = datetime.strptime

        r_inst   = _run_institutional(hist, oc, sent, cfg)
        r_seller = _run_option_seller(hist, oc, sent, cfg, sb, vix_safe)

    inst_status   = f"ACTIVE CE@{r_inst.get('strike')} ₹{r_inst.get('entry_price',0):.0f}" if not r_inst.get("skip_reason") else f"SKIP ({r_inst['skip_reason'][:50]})"
    seller_status = f"ACTIVE entry ₹{r_seller.get('entry_price',0):.0f}" if not r_seller.get("skip_reason") else f"SKIP ({r_seller['skip_reason'][:50]})"
    print(f"  {time_str}  Institutional: {inst_status}")
    print(f"         OptionSeller : {seller_status}")
    print()
