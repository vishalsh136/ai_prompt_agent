"""
src/live_auto_runner.py
=======================
Always-on live auto-trader for the Live Algo workflow.

Mirrors the proven paper-trade exit rules (fixed max-loss, profit-target,
time-based exit, daily loss cutoff) but drives the broker adapter to auto-ENTER
and auto-EXIT positions.

SAFETY
------
- Reads a config file (data/live_auto_config.json). If "armed" is false, the
  runner idles and does nothing.
- Real orders are transmitted ONLY when config has dry_run=false AND
  allow_live=true AND valid credentials exist. Default is dry-run simulation.
- One open auto-position per (symbol, strategy) at a time.
- Trading window + daily loss cutoff enforced before any entry.

Valuation reuses auto_trade_engine helpers so live P&L matches paper logic.

Run:
    python -m src.live_auto_runner --once      # single tick (safe to test)
    python -m src.live_auto_runner --loop       # continuous loop
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auto_trade_engine import (
    load_morning_data,
    _ltp_at_strike,
)
from src.live_broker_adapter import (
    StartAlgoRequest,
    get_live_broker_adapter,
    append_journal_event,
    load_live_positions,
    upsert_live_position,
    remove_live_position,
)

logger = logging.getLogger("live_auto_runner")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "data" / "live_auto_config.json"
JOURNAL_PATH = "data/live_algo_journal.jsonl"

DEFAULT_CONFIG = {
    "armed": False,
    "broker": "Groww",
    "symbol": "NIFTY",
    "strategy": "Iron Condor (Defined Risk)",
    "expiry": "",
    "lots": 1,
    "lot_size": 65,
    "legs": [],  # [{"action":"SELL","option_type":"CE","strike":24200}, ...]
    "max_loss_inr": 3000.0,
    "target_profit_inr": 2000.0,
    "time_exit_minutes": 180,
    "daily_max_loss_inr": 6000.0,
    "trade_window_start": "09:20",
    "trade_window_end": "15:20",
    "poll_interval_sec": 30,
    "dry_run": True,
    "allow_live": False,
}


# ── config / state ────────────────────────────────────────────────────────────

def load_config() -> Dict:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(data if isinstance(data, dict) else {})
        return cfg
    except Exception:
        logger.warning("live_auto_config.json unreadable; using defaults.")
        return dict(DEFAULT_CONFIG)


def save_config(cfg: Dict) -> str:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, default=str), encoding="utf-8")
    return str(CONFIG_PATH)


def _position_id(cfg: Dict) -> str:
    today = datetime.now().strftime("%Y%m%d")
    return f"auto_{cfg.get('symbol','NIFTY')}_{cfg.get('strategy','strat')}_{today}".replace(" ", "_")


# ── valuation (reuses paper-trade pricing source) ──────────────────────────────

def _position_value(legs: List[Dict], oc) -> Optional[float]:
    """Net cost-to-close of a credit position = sum(short LTP) - sum(long LTP).

    Returns None if any required leg LTP is unavailable.
    """
    if oc is None or getattr(oc, "empty", True):
        return None
    short_sum = 0.0
    long_sum = 0.0
    for leg in legs:
        strike = int(leg.get("strike", 0))
        opt = str(leg.get("option_type", "")).upper()
        action = str(leg.get("action", "")).upper()
        ltp = _ltp_at_strike(oc, strike, opt)
        if ltp is None or float(ltp) <= 0:
            return None
        if action == "SELL":
            short_sum += float(ltp)
        else:
            long_sum += float(ltp)
    return round(short_sum - long_sum, 2)


def _within_window(cfg: Dict, now: datetime) -> bool:
    try:
        start = datetime.strptime(cfg.get("trade_window_start", "09:20"), "%H:%M").time()
        end = datetime.strptime(cfg.get("trade_window_end", "15:20"), "%H:%M").time()
        return start <= now.time() <= end
    except Exception:
        return True


def _today_realized_pnl() -> float:
    """Sum realized P&L from today's auto_exit journal events."""
    path = Path(JOURNAL_PATH)
    if not path.exists():
        return 0.0
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") == "auto_exit" and str(rec.get("ts_utc", "")).startswith(today):
            total += float(rec.get("pnl_inr", 0) or 0)
    return round(total, 2)


# ── runner ──────────────────────────────────────────────────────────────────

class LiveAutoTrader:
    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or load_config()

    def _adapter(self):
        cfg = self.cfg
        broker = cfg.get("broker", "Groww")
        api_key = os.getenv("GROWW_API_KEY", "") or cfg.get("api_key", "")
        api_secret = os.getenv("GROWW_API_SECRET", "") or cfg.get("api_secret", "")
        access_token = os.getenv("GROWW_ACCESS_TOKEN", "") or cfg.get("access_token", "")
        allow_live = bool(cfg.get("allow_live", False)) and not bool(cfg.get("dry_run", True))
        return get_live_broker_adapter(
            broker, api_key=api_key, api_secret=api_secret,
            access_token=access_token, allow_live=allow_live,
        )

    def tick(self) -> Dict:
        cfg = self.cfg = load_config()
        now = datetime.now()
        result = {"ts": now.isoformat(), "action": "idle"}

        if not cfg.get("armed"):
            result["reason"] = "not_armed"
            return result

        legs = cfg.get("legs") or []
        if not legs:
            result["action"] = "error"
            result["reason"] = "no_legs_configured"
            return result

        pid = _position_id(cfg)
        positions = load_live_positions()
        pos = positions.get(pid)

        # Daily loss cutoff check.
        realized = _today_realized_pnl()
        if realized <= -abs(float(cfg.get("daily_max_loss_inr", 0) or 0)) and float(cfg.get("daily_max_loss_inr", 0) or 0) > 0:
            result["action"] = "halted"
            result["reason"] = "daily_max_loss_reached"
            result["realized_pnl"] = realized
            return result

        # Load latest market data for valuation.
        try:
            _hist, oc, _pcr, _vix, _ocjson = load_morning_data()
        except Exception as exc:
            result["action"] = "error"
            result["reason"] = f"market_data_error: {exc}"
            return result

        cur_val = _position_value(legs, oc)

        adapter = self._adapter()
        lots = int(cfg.get("lots", 1))
        lot_size = int(cfg.get("lot_size", 65))
        units = lots * lot_size

        # ── MANAGE OPEN POSITION → auto-exit checks ──
        if pos and pos.get("status") == "open":
            if cur_val is None:
                result["action"] = "hold"
                result["reason"] = "valuation_unavailable"
                return result
            entry_val = float(pos.get("entry_value", 0) or 0)
            # Credit position: profit when current value < entry value.
            pnl = round((entry_val - cur_val) * units, 2)
            mins = None
            try:
                entry_dt = datetime.fromisoformat(pos.get("entry_time"))
                mins = int((now - entry_dt).total_seconds() // 60)
            except Exception:
                mins = None

            trigger = None
            if float(cfg.get("target_profit_inr", 0) or 0) > 0 and pnl >= float(cfg["target_profit_inr"]):
                trigger = "TARGET_PROFIT"
            elif float(cfg.get("max_loss_inr", 0) or 0) > 0 and pnl <= -abs(float(cfg["max_loss_inr"])):
                trigger = "MAX_LOSS"
            elif mins is not None and int(cfg.get("time_exit_minutes", 0) or 0) > 0 and mins >= int(cfg["time_exit_minutes"]):
                trigger = "TIME_EXIT"

            if trigger:
                sq = adapter.square_off_all(cfg.get("symbol", "NIFTY"), cfg.get("strategy", ""))
                upsert_live_position(pid, {
                    "status": "closed",
                    "exit_value": cur_val,
                    "exit_time": now.isoformat(),
                    "pnl_inr": pnl,
                    "exit_trigger": trigger,
                })
                remove_live_position(pid)
                append_journal_event({
                    "event": "auto_exit",
                    "position_id": pid,
                    "symbol": cfg.get("symbol"),
                    "strategy": cfg.get("strategy"),
                    "trigger": trigger,
                    "entry_value": entry_val,
                    "exit_value": cur_val,
                    "pnl_inr": pnl,
                    "minutes_open": mins,
                    "dry_run": bool(cfg.get("dry_run", True)),
                    "squareoff": sq,
                })
                result.update({"action": "exit", "trigger": trigger, "pnl_inr": pnl})
                return result

            result.update({"action": "hold", "pnl_inr": pnl, "current_value": cur_val, "minutes_open": mins})
            return result

        # ── NO OPEN POSITION → auto-entry ──
        if not _within_window(cfg, now):
            result["action"] = "idle"
            result["reason"] = "outside_trade_window"
            return result

        if cur_val is None:
            result["action"] = "wait_entry"
            result["reason"] = "entry_valuation_unavailable"
            return result

        req = StartAlgoRequest(
            broker=cfg.get("broker", "Groww"),
            symbol=cfg.get("symbol", "NIFTY"),
            strategy=cfg.get("strategy", ""),
            lots=lots,
            lot_size=lot_size,
            expiry=str(cfg.get("expiry", "")),
            legs=legs,
            stop_loss=float(cfg.get("max_loss_inr", 0) or 0),
            target=float(cfg.get("target_profit_inr", 0) or 0),
            time_exit_minutes=int(cfg.get("time_exit_minutes", 0) or 0),
            daily_max_loss_inr=float(cfg.get("daily_max_loss_inr", 0) or 0),
        )
        placed = adapter.place_basket_order(req, dry_run=bool(cfg.get("dry_run", True)))
        if not placed.get("ok"):
            result.update({"action": "entry_failed", "reason": placed.get("message")})
            append_journal_event({
                "event": "auto_entry_failed",
                "position_id": pid,
                "symbol": cfg.get("symbol"),
                "strategy": cfg.get("strategy"),
                "reason": placed.get("message"),
            })
            return result

        upsert_live_position(pid, {
            "broker": cfg.get("broker"),
            "symbol": cfg.get("symbol"),
            "strategy": cfg.get("strategy"),
            "lots": lots,
            "units_per_leg": units,
            "expiry": cfg.get("expiry"),
            "legs": legs,
            "entry_value": cur_val,
            "entry_time": now.isoformat(),
            "status": "open",
            "dry_run": bool(cfg.get("dry_run", True)),
            "intent_id": placed.get("intent_id"),
            "leg_refs": placed.get("leg_refs", []),
        })
        append_journal_event({
            "event": "auto_entry",
            "position_id": pid,
            "symbol": cfg.get("symbol"),
            "strategy": cfg.get("strategy"),
            "entry_value": cur_val,
            "lots": lots,
            "units_per_leg": units,
            "dry_run": bool(cfg.get("dry_run", True)),
            "intent_id": placed.get("intent_id"),
        })
        result.update({"action": "entry", "entry_value": cur_val, "intent_id": placed.get("intent_id")})
        return result

    def run_forever(self, interval_sec: Optional[int] = None):
        interval = int(interval_sec or self.cfg.get("poll_interval_sec", 30) or 30)
        logger.info("Live auto-runner started (interval=%ss, dry_run=%s).",
                    interval, self.cfg.get("dry_run", True))
        while True:
            try:
                res = self.tick()
                logger.info("tick: %s", {k: v for k, v in res.items() if k != "squareoff"})
            except Exception as exc:
                logger.exception("tick error: %s", exc)
            time.sleep(max(5, interval))


def main():
    ap = argparse.ArgumentParser(description="Live auto-trader runner")
    ap.add_argument("--once", action="store_true", help="Run a single tick and exit.")
    ap.add_argument("--loop", action="store_true", help="Run continuously.")
    ap.add_argument("--interval", type=int, default=0, help="Override poll interval seconds.")
    args = ap.parse_args()

    trader = LiveAutoTrader()
    if args.loop:
        trader.run_forever(args.interval or None)
    else:
        res = trader.tick()
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
