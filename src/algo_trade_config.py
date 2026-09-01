"""
src/algo_trade_config.py
========================
Single source of truth for the Auto Algo Trader.

Stores broker credentials, risk controls, and trading parameters in a
human-editable JSON file (``algo_trade_config.json`` at the repo root) so the
whole app + the background runner read the same settings.

SECURITY
--------
This file can hold API keys / secrets / access tokens. It is git-ignored by
default (see .gitignore). Never commit real secrets. Values fall back to
environment variables when left blank in the file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "algo_trade_config.json"

# Env-var names each broker reads from when the config value is blank.
BROKER_ENV_MAP: Dict[str, Dict[str, str]] = {
    "Groww":     {"api_key": "GROWW_API_KEY",   "api_secret": "GROWW_API_SECRET",   "access_token": "GROWW_ACCESS_TOKEN"},
    "Zerodha":   {"api_key": "ZERODHA_API_KEY", "api_secret": "ZERODHA_API_SECRET", "access_token": "ZERODHA_ACCESS_TOKEN"},
    "Upstox":    {"api_key": "UPSTOX_API_KEY",  "api_secret": "UPSTOX_API_SECRET",  "access_token": "UPSTOX_ACCESS_TOKEN"},
    "Angel One": {"api_key": "ANGEL_API_KEY",   "api_secret": "ANGEL_API_SECRET",   "access_token": "ANGEL_ACCESS_TOKEN"},
    "Dhan":      {"api_key": "DHAN_API_KEY",    "api_secret": "DHAN_API_SECRET",    "access_token": "DHAN_ACCESS_TOKEN"},
    "Other":     {"api_key": "BROKER_API_KEY",  "api_secret": "BROKER_API_SECRET",  "access_token": "BROKER_ACCESS_TOKEN"},
}

SUPPORTED_BROKERS: List[str] = list(BROKER_ENV_MAP.keys())

DEFAULT_ALGO_CONFIG: Dict = {
    "active_broker": "Groww",
    "brokers": {
        name: {"api_key": "", "api_secret": "", "access_token": "", "totp": "", "auth_flow": "approval"}
        for name in SUPPORTED_BROKERS
    },
    "trading": {
        "symbol": "NIFTY",
        "strategy": "Iron Condor (Defined Risk)",
        "selection_mode": "auto_winner",   # "manual" (fixed strategy+strikes) or "auto_winner"
        "enabled_strategies": ["Institutional", "OptionSeller", "OptionBuyer", "Hedging", "Agent-Institutional", "Agent-OptionSeller"],
        "lots": 1,
        "lot_size": 65,
        "expiry": "",
        "strikes": {"buy_pe": 23500, "sell_pe": 23800, "sell_ce": 24200, "buy_ce": 24500},
        "legs": [],
        "trade_window_start": "09:20",
        "trade_window_end": "15:20",
        "hard_squareoff_time": "15:20",
        "poll_interval_sec": 30,
        # New-entry hygiene.
        "entry_cutoff_before_squareoff_min": 45,  # no NEW entry within N min of hard squareoff
        "startup_grace_sec": 120,                  # ignore entries for first N sec after process start
        "reentry_cooldown_min": 20,                # wait N min after ANY exit before re-entering
        "momentum_selection_enabled": True,        # prefer aligned directional buyer on strong trend days
        "momentum_trend_move_pct": 0.50,           # |day_move%| threshold that defines a "strong trend"
        "value_from_snapshot": False,  # value legs from fresh in-memory snapshot (no shared-CSV round-trip)
        "value_from_broker": False,    # value legs from broker live LTP API (live sessions only; falls back)
    },
    "risk": {
        # Position-level exits (rupees).
        "target_profit_inr": 2000.0,
        "per_trade_max_loss_inr": 3000.0,
        "time_exit_minutes": 180,          # overridden to 120 min for buyer strategies in auto trader
        # Capital / sizing caps.
        "max_trade_amount_inr": 150000.0,
        "max_lots_per_trade": 5,
        "max_open_positions": 2,           # allow 2 concurrent positions (e.g. Hedging + Seller)
        "max_orders_per_day": 6,
        # Daily circuit breakers.
        "daily_max_loss_inr": 15000.0,
        "daily_profit_target_inr": 4000.0, # lock profits after ₹4,000 daily gain
        # Sudden-move guards (percent move of spot vs day-open).
        "crash_guard_pct": 1.5,           # halt/exit if spot falls this % intraday
        "rally_guard_pct": 1.5,           # halt/exit if spot rises this % intraday
        "gap_guard_pct": 1.2,             # skip new entries if day gapped this %
        "cooloff_after_loss_min": 30,     # wait after a losing exit before re-entry
        "exit_on_guard_breach": True,     # square off open positions on crash/rally breach
        "exit_on_stale_data": False,      # if data feed fails, square off open positions (protective; default off)
    },
    "controls": {
        "armed": False,
        "dry_run": True,       # simulate; no real orders
        "allow_live": False,   # must be True (and dry_run False) to transmit
        "auto_regenerate_token": True,
        "stale_reconciliation_enabled": True,
    },
}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_algo_config() -> Dict:
    """Load config merged over defaults so new keys always exist."""
    if not CONFIG_PATH.exists():
        return json.loads(json.dumps(DEFAULT_ALGO_CONFIG))
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return json.loads(json.dumps(DEFAULT_ALGO_CONFIG))
        return _deep_merge(DEFAULT_ALGO_CONFIG, data)
    except Exception:
        return json.loads(json.dumps(DEFAULT_ALGO_CONFIG))


def save_algo_config(cfg: Dict) -> str:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, default=str), encoding="utf-8")
    return str(CONFIG_PATH)


def resolve_broker_creds(cfg: Dict, broker: str) -> Dict[str, str]:
    """Return {api_key, api_secret, access_token, totp, auth_flow} using
    config values first, then environment variables as fallback."""
    broker_cfg = (cfg.get("brokers", {}) or {}).get(broker, {}) or {}
    env_map = BROKER_ENV_MAP.get(broker, BROKER_ENV_MAP["Other"])
    return {
        "api_key": broker_cfg.get("api_key") or os.getenv(env_map["api_key"], ""),
        "api_secret": broker_cfg.get("api_secret") or os.getenv(env_map["api_secret"], ""),
        "access_token": broker_cfg.get("access_token") or os.getenv(env_map["access_token"], ""),
        "totp": broker_cfg.get("totp", ""),
        "auth_flow": broker_cfg.get("auth_flow", "approval"),
    }


def build_legs(strategy: str, strikes: Dict) -> List[Dict]:
    """Build option legs from a strategy name + strike map.

    Mirrors the leg construction used by the Live Algo Trade tab.
    """
    def _s(key: str) -> int:
        return int(strikes.get(key, 0) or 0)

    if strategy == "Iron Condor (Defined Risk)":
        return [
            {"action": "BUY", "option_type": "PE", "strike": _s("buy_pe")},
            {"action": "SELL", "option_type": "PE", "strike": _s("sell_pe")},
            {"action": "SELL", "option_type": "CE", "strike": _s("sell_ce")},
            {"action": "BUY", "option_type": "CE", "strike": _s("buy_ce")},
        ]
    if strategy == "Bull Put Spread":
        return [
            {"action": "SELL", "option_type": "PE", "strike": _s("sell_pe")},
            {"action": "BUY", "option_type": "PE", "strike": _s("buy_pe")},
        ]
    if strategy == "Bear Call Spread":
        return [
            {"action": "SELL", "option_type": "CE", "strike": _s("sell_ce")},
            {"action": "BUY", "option_type": "CE", "strike": _s("buy_ce")},
        ]
    if strategy == "Short Strangle":
        return [
            {"action": "SELL", "option_type": "PE", "strike": _s("sell_pe")},
            {"action": "SELL", "option_type": "CE", "strike": _s("sell_ce")},
        ]
    if strategy == "Long Call":
        return [{"action": "BUY", "option_type": "CE", "strike": _s("buy_ce")}]
    return [{"action": "BUY", "option_type": "PE", "strike": _s("buy_pe")}]


def mask_secret(val: str) -> str:
    if not val:
        return "— not set —"
    if len(val) <= 6:
        return "******"
    return f"{val[:3]}…{val[-2:]}"
