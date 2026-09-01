#!/usr/bin/env python
"""Unit-style checks for stale position reconciliation toggle behavior."""
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.algo_auto_trader import AlgoAutoTrader


class _DummyAdapter:
    def square_off_all(self, symbol: str, strategy: str = "") -> dict:
        return {
            "ok": True,
            "status": "scaffold_squareoff_intent",
            "symbol": symbol,
            "strategy": strategy,
        }


def _base_config(enabled: bool) -> dict:
    return {
        "active_broker": "Groww",
        "brokers": {"Groww": {"api_key": "", "api_secret": "", "access_token": "", "totp": "", "auth_flow": "approval"}},
        "trading": {
            "symbol": "NIFTY",
            "strategy": "Iron Condor (Defined Risk)",
            "selection_mode": "manual",
            "enabled_strategies": ["OptionSeller"],
            "lots": 1,
            "lot_size": 65,
            "expiry": "",
            "strikes": {"buy_pe": 0, "sell_pe": 0, "sell_ce": 0, "buy_ce": 0},
            "legs": [
                {"action": "SELL", "option_type": "CE", "strike": 24500},
                {"action": "SELL", "option_type": "PE", "strike": 24200},
                {"action": "BUY", "option_type": "CE", "strike": 24700},
                {"action": "BUY", "option_type": "PE", "strike": 24000},
            ],
            "trade_window_start": "23:58",
            "trade_window_end": "23:59",
            "hard_squareoff_time": "15:20",
            "poll_interval_sec": 30,
            "value_from_snapshot": False,
            "value_from_broker": False,
        },
        "risk": {
            "target_profit_inr": 3000.0,
            "per_trade_max_loss_inr": 3000.0,
            "time_exit_minutes": 180,
            "max_trade_amount_inr": 150000.0,
            "max_lots_per_trade": 5,
            "max_open_positions": 2,
            "max_orders_per_day": 6,
            "daily_max_loss_inr": 15000.0,
            "daily_profit_target_inr": 4000.0,
            "crash_guard_pct": 1.5,
            "rally_guard_pct": 1.5,
            "gap_guard_pct": 1.2,
            "cooloff_after_loss_min": 30,
            "exit_on_guard_breach": True,
            "exit_on_stale_data": False,
        },
        "controls": {
            "armed": True,
            "dry_run": True,
            "allow_live": False,
            "auto_regenerate_token": False,
            "stale_reconciliation_enabled": enabled,
        },
    }


class TestStaleReconciliation(unittest.TestCase):
    def _run_tick_with_store(self, enabled: bool):
        now = datetime.now()
        stale_pid = f"algo_NIFTY_OptionSeller_{(now - timedelta(days=1)).strftime('%Y%m%d')}"
        store = {
            stale_pid: {
                "status": "open",
                "symbol": "NIFTY",
                "strategy": "OptionSeller",
                "entry_time": (now - timedelta(days=1, minutes=5)).isoformat(),
                "entry_value": 20.0,
                "units_per_leg": 65,
                "legs": [
                    {"action": "SELL", "option_type": "CE", "strike": 24500},
                    {"action": "SELL", "option_type": "PE", "strike": 24200},
                ],
            }
        }
        journal = []

        hist = pd.DataFrame(
            {
                "high": [24320.0, 24340.0, 24310.0],
                "low": [24220.0, 24210.0, 24190.0],
                "close": [24280.0, 24300.0, 24270.0],
            }
        )
        oc = pd.DataFrame(
            {
                "strike": [24200, 24300, 24500],
                "CE_LTP": [100.0, 80.0, 55.0],
                "PE_LTP": [25.0, 40.0, 90.0],
                "spot": [24287.65, 24287.65, 24287.65],
            }
        )

        def _load_positions():
            return dict(store)

        def _upsert(intent_id, record):
            existing = store.get(intent_id, {})
            merged = {**existing, **record, "intent_id": intent_id}
            store[intent_id] = merged
            return dict(store)

        def _remove(intent_id):
            store.pop(intent_id, None)
            return dict(store)

        def _append(event):
            journal.append(event)
            return "mock-journal"

        trader = AlgoAutoTrader()

        with patch("src.algo_auto_trader.load_algo_config", return_value=_base_config(enabled)), \
             patch("src.algo_auto_trader.refresh_realtime", return_value={"ok": True, "spot": 24287.65, "day_move_pct": -0.2, "vix": 11.3, "pcr": 0.92}), \
             patch("src.algo_auto_trader.load_morning_data", return_value=(hist, oc, pd.DataFrame(), 11.3, Path("downloads/option_chain_NIFTY_20260817.json"))), \
             patch("src.algo_auto_trader._today_realized_pnl", return_value=0.0), \
             patch("src.algo_auto_trader._position_value", return_value=20.0), \
             patch("src.algo_auto_trader.load_live_positions", side_effect=_load_positions), \
             patch("src.algo_auto_trader.upsert_live_position", side_effect=_upsert), \
             patch("src.algo_auto_trader.remove_live_position", side_effect=_remove), \
             patch("src.algo_auto_trader.append_journal_event", side_effect=_append), \
             patch.object(AlgoAutoTrader, "_adapter", return_value=_DummyAdapter()):
            res = trader.tick()

        return stale_pid, res, store, journal

    def test_reconciliation_enabled(self):
        stale_pid, res, store, journal = self._run_tick_with_store(enabled=True)
        self.assertNotIn(stale_pid, store)
        self.assertIn("stale_positions_reconciled", res)
        self.assertIn(stale_pid, res["stale_positions_reconciled"])
        self.assertTrue(any(j.get("trigger") == "STALE_CARRYFORWARD" for j in journal))

    def test_reconciliation_disabled(self):
        stale_pid, res, store, journal = self._run_tick_with_store(enabled=False)
        self.assertIn(stale_pid, store)
        self.assertNotIn("stale_positions_reconciled", res)
        self.assertFalse(any(j.get("trigger") == "STALE_CARRYFORWARD" for j in journal))


if __name__ == "__main__":
    unittest.main(verbosity=2)
