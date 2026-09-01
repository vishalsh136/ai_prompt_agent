"""
src/auto_trade_engine.py
========================
Automatic daily paper-trade logger.

Runs after the 2nd cron (10:15 AM) to:
  1. Validate data quality (trading day, data freshness, VIX, liquidity)
  2. Run all 4 strategy engines with the morning snapshot
  3. Log one trade per strategy into data/auto_trade_log.json
  4. At 15:30 / 18:30 runs: update open positions with exit prices & P&L

Usage (called by download_nse_data.ps1):
    python src/auto_trade_engine.py --mode=entry   # 10:15 run
    python src/auto_trade_engine.py --mode=update  # 15:30 / 18:30 run

All trades are paper-trades only. No broker connectivity.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import re
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ── project imports ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_provider import DataProvider
from src.final_trade_decision import institutional_trade, option_seller_trade
from src.institutional_view import InstitutionalAnalyzer
from src.option_buyer_strategies import (
    assess_buyer_regime,
    generate_buyer_strategies,
    generate_hedging_strategies,
)
from src.real_data_loader import load_option_chain, load_pcr_data, load_price_history
from src.strategy_builder import StrategyBuilder
from src.utils import get_config
from src.agent_logic import DecisionOptimizerAgent

logger = logging.getLogger("auto_trade_engine")

# Use a stdout handler that replaces unencodable characters (e.g. Rs symbol)
# so PowerShell capture (2>&1) doesn't crash the logger.
_stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(_stream)],
)

# ── paths ────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent
DOWNLOADS   = ROOT / "downloads"
LOG_PATH    = ROOT / "data" / "auto_trade_log.json"
SYMBOL      = "NIFTY"
LOT_SIZE    = 65
BUDGET      = 150_000
# NSE NIFTY F&O expiry weekday (0=Mon … 6=Sun). Moved Thu -> Tue.
# Used only as a fallback when the option-chain feed is unavailable; the live
# path reads the real expiry from the option-chain JSON (source of truth).
NIFTY_EXPIRY_WEEKDAY = 1  # Tuesday

# ── safety thresholds ────────────────────────────────────────────────────────
VIX_SELL_MAX    = 25.0   # skip option-selling above this VIX
MIN_OI_ATM      = 100_000  # ATM OI < this = stale chain
# Minimum credit as a fraction of the spread's max defined risk (credit / (width - credit)).
# Blocks defined-risk sellers whose reward is too thin for the risk taken.
MIN_CREDIT_TO_RISK = 0.15
DATA_FRESH_HRS  = 3.0    # cron JSON must be within this many hours
AUTO_EXIT_SLIPPAGE_PCT = 0.20  # conservative fill adjustment (%) for auto exits

# Optional time-based auto exit (minutes) for open trades during update mode.
# Keeps intraday risk bounded even when SL/Target are not touched.
AUTO_TIME_EXIT_MIN_DEFAULT = 180
AUTO_TIME_EXIT_MIN_BY_STRATEGY = {
    "Hedging": 120,
}

STRATEGY_TYPES = ["Institutional", "OptionSeller", "OptionBuyer", "Hedging", "Agent-Institutional", "Agent-OptionSeller"]


# ── persistence ──────────────────────────────────────────────────────────────

def _load_log() -> List[dict]:
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("auto_trade_log.json corrupt — starting fresh.")
        return []


def _save_log(trades: List[dict]) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    LOG_PATH.write_text(
        json.dumps(trades, indent=2, default=str), encoding="utf-8"
    )


def _trade_id(trade_date: str, strategy: str) -> str:
    return f"{trade_date.replace('-', '')}_{SYMBOL}_{strategy}"


# ── validation ───────────────────────────────────────────────────────────────

def validate_conditions(oc_df: pd.DataFrame, json_path: Path, vix: float,
                        require_cron_run: str = "12:00") -> dict:
    """
    Run all pre-trade safety checks.
    Returns dict with 'ok', 'flags', 'data_timestamp', 'cron_run_time'.

    require_cron_run: HH:MM label — if set, verifies the downloaded JSON was
                      produced by THIS specific cron run (not an older snapshot).
                      NOTE: Changed from 10:15 to 12:00 for better mid-day entry quality
    """
    flags = []
    today = date.today()
    data_timestamp  = None
    cron_run_time   = None
    cron_run_label  = None

    # 1. Trading day
    if today.weekday() >= 5:
        flags.append("HOLIDAY")

    # 2. Data freshness + cron run verification
    try:
        raw = json.loads(json_path.read_bytes().decode("utf-8-sig"))

        # Embedded market data timestamp (from niftytrader.in)
        data_timestamp = raw.get("timestamp", "")

        # Cron run time (added by our download script)
        cron_run_time  = raw.get("cron_run_time", "")
        cron_run_label = raw.get("cron_run_label", "")

        # Check file age
        mtime = datetime.fromtimestamp(json_path.stat().st_mtime)
        age_h = (datetime.now() - mtime).total_seconds() / 3600
        if age_h > DATA_FRESH_HRS:
            flags.append(f"STALE_DATA({age_h:.1f}h old)")

        # Verify the data_timestamp is from today
        if data_timestamp:
            try:
                dt_data = datetime.fromisoformat(data_timestamp[:19])
                if dt_data.date() != today:
                    flags.append(f"DATA_FROM_WRONG_DATE({dt_data.date()})")
                else:
                    # For 12:00 entry run: data should be from >= 09:00 today
                    if require_cron_run and dt_data.hour < 9:
                        flags.append(f"DATA_TOO_EARLY({dt_data.strftime('%H:%M')})")
            except Exception:
                pass

        # If cron_run_label present, verify it matches the expected run
        if cron_run_label and require_cron_run:
            # Allow ±5 min tolerance  (e.g. 12:00 run might be tagged 12:01)
            req_h, req_m = map(int, require_cron_run.split(":"))
            lbl_h, lbl_m = map(int, cron_run_label.split(":")) if ":" in cron_run_label else (0, 0)
            diff_min = abs((lbl_h * 60 + lbl_m) - (req_h * 60 + req_m))
            if diff_min > 65:   # allow up to 65 min gap (covers 11:15 run data used at 12:00)
                flags.append(f"WRONG_CRON_RUN(data={cron_run_label}, expected~{require_cron_run})")
        elif not cron_run_label:
            # Old format — no cron_run_label embedded (first few days of use)
            flags.append("CRON_LABEL_MISSING(using file mtime)")

    except Exception:
        flags.append("STALE_DATA(unknown)")

    # 3. Option chain health
    if oc_df is None or oc_df.empty:
        flags.append("NO_OC")
    else:
        # Check ATM liquidity
        try:
            spot  = float(oc_df["spot"].iloc[0])
            atm_k = int(round(spot / 50) * 50)
            atm_row = oc_df[oc_df["strike"] == atm_k]
            if atm_row.empty or int(atm_row["CE_OI"].iloc[0]) < MIN_OI_ATM:
                flags.append("LOW_LIQUIDITY")
        except Exception:
            flags.append("LOW_LIQUIDITY")

    # 4. VIX
    if vix > VIX_SELL_MAX:
        flags.append(f"HIGH_VIX({vix:.1f})")

    ok = "HOLIDAY" not in flags and "NO_OC" not in flags and "STALE_DATA" not in flags[0:1] if flags else True
    return {
        "ok":              not bool([f for f in flags if f in ("HOLIDAY", "NO_OC")]),
        "flags":           flags,
        "vix_safe_to_sell": vix <= VIX_SELL_MAX,
        "data_timestamp":  data_timestamp,
        "cron_run_time":   cron_run_time,
        "cron_run_label":  cron_run_label,
    }


# ── data loader ──────────────────────────────────────────────────────────────

def load_morning_data():
    """Load the latest cron-converted CSV files. Returns (hist, oc, pcr, vix, json_path)."""
    hist_csv = DOWNLOADS / f"app_historical_{SYMBOL}.csv"
    pcr_csv  = DOWNLOADS / f"app_pcr_{SYMBOL}.csv"

    # Use the generic app_option_chain_NIFTY.csv which is updated with current day's data.
    # (Dated files like app_option_chain_NIFTY-28-Jul-2026.csv are for specific expirations
    #  and may contain stale/expired data)
    oc_csv   = DOWNLOADS / f"app_option_chain_{SYMBOL}.csv"

    oc_json  = max(
        glob.glob(str(DOWNLOADS / f"option_chain_{SYMBOL}_*.json")),
        key=lambda p: Path(p).stat().st_mtime,
        default=str(DOWNLOADS / f"option_chain_{SYMBOL}_20000101.json"),
    )

    hist = load_price_history(str(hist_csv)) if hist_csv.exists() else pd.DataFrame()
    oc   = load_option_chain(str(oc_csv))    if oc_csv.exists()   else pd.DataFrame()
    pcr  = load_pcr_data(str(pcr_csv), oc)  if pcr_csv.exists()  else pd.DataFrame()

    # VIX from the option chain JSON (not in CSV)
    vix = 0.0
    try:
        raw = json.loads(Path(oc_json).read_bytes().decode("utf-8-sig"))
        vix = float(raw.get("vix", 0) or 0)
    except Exception:
        pass

    return hist, oc, pcr, vix, Path(oc_json)


# ── helper ───────────────────────────────────────────────────────────────────

def _safe_float(v, default=0.0) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _investment(entry: float, lot_size: int, qty: int, margin_type: str,
                margin_pct: float = 0.21) -> float:
    """Approximate investment / margin required."""
    if margin_type == "Premium":
        return round(entry * lot_size * qty, 0)
    else:
        return round(entry * lot_size * qty * margin_pct, -2)


MAX_QTY_LOTS    = 50    # hard safety cap — prevents runaway qty from zero entry price


def _days_to_active_expiry() -> int:
    """Return non-negative days to current active weekly expiry."""
    try:
        exp = _nifty_weekly_expiry()
        return max(0, (exp - date.today()).days)
    except Exception:
        return 2


def _adaptive_credit_ratio(vix: float, days_to_expiry: int, base_ratio: float = 0.15) -> float:
    """Adaptive minimum credit ratio for spread sellers."""
    ratio = float(base_ratio)
    if vix < 12.0:
        ratio -= 0.04
    elif vix < 14.0:
        ratio -= 0.02
    elif vix > 20.0:
        ratio += 0.01

    if days_to_expiry <= 1:
        ratio += 0.02
    elif days_to_expiry >= 3:
        ratio -= 0.01

    return max(0.10, min(0.18, ratio))


def _latest_intraday_context() -> Dict[str, float]:
    """Load intraday spot/open/high/low/vix from latest option-chain JSON."""
    try:
        oc_json = max(
            glob.glob(str(DOWNLOADS / f"option_chain_{SYMBOL}_*.json")),
            key=lambda p: Path(p).stat().st_mtime,
        )
        raw = json.loads(Path(oc_json).read_bytes().decode("utf-8-sig"))
        spot = float(raw.get("spot_price", 0) or 0)
        opn = float(raw.get("open", 0) or 0)
        high = float(raw.get("high", 0) or 0)
        low = float(raw.get("low", 0) or 0)
        vix = float(raw.get("vix", 0) or 0)
        day_move_pct = ((spot - opn) / opn * 100.0) if opn > 0 else 0.0
        day_range_pct = ((high - low) / opn * 100.0) if opn > 0 else 0.0
        return {
            "spot": spot,
            "open": opn,
            "high": high,
            "low": low,
            "vix": vix,
            "day_move_pct": day_move_pct,
            "day_range_pct": day_range_pct,
        }
    except Exception:
        return {
            "spot": 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "vix": 0.0,
            "day_move_pct": 0.0,
            "day_range_pct": 0.0,
        }


# ── NSE expiry calendar ───────────────────────────────────────────────────────

def _load_nse_holidays() -> set:
    """
    Load NSE market holidays from nse_holidays.json (project root).
    Returns a set of ISO date strings e.g. {"2026-08-15", ...}.
    File can be edited without code changes — just add/remove dates.
    """
    try:
        _hpath = ROOT / "nse_holidays.json"
        if _hpath.exists():
            _data = json.loads(_hpath.read_text(encoding="utf-8"))
            return set(_data.get("holidays", []))
    except Exception:
        pass
    return set()


def _active_expiry_from_oc(for_date: date = None) -> Optional[date]:
    """
    Source-of-truth expiry: read the nearest active NIFTY option expiry directly
    from the latest option-chain JSON (downloads/option_chain_NIFTY_*.json).

    NSE has moved the NIFTY weekly expiry weekday over time (Thu -> Tue), so
    computing it from a hardcoded weekday is unreliable. The option-chain feed
    carries the real expiry per strike, so we use that instead.

    Returns the earliest expiry date that is >= for_date (today), or None if no
    option-chain file / expiry data is available (caller falls back to weekday calc).
    """
    ref = for_date or date.today()
    try:
        oc_json = max(
            glob.glob(str(DOWNLOADS / f"option_chain_{SYMBOL}_*.json")),
            key=lambda p: Path(p).stat().st_mtime,
        )
        raw = json.loads(Path(oc_json).read_bytes().decode("utf-8-sig"))
        expiries: set = set()
        for s in raw.get("strikes", []) or []:
            exp_raw = s.get("expiry")
            if not exp_raw:
                continue
            try:
                exp_d = datetime.fromisoformat(str(exp_raw).replace("Z", "")).date()
                expiries.add(exp_d)
            except Exception:
                continue
        future = sorted(e for e in expiries if e >= ref)
        if future:
            return future[0]
    except Exception:
        pass
    return None


def _shift_back_if_holiday(d: date, holidays: set = None) -> date:
    """
    NSE moves an expiry that lands on a weekend/holiday to the PREVIOUS trading
    day. Walk backwards over weekends and holidays until a trading day is found.
    """
    from datetime import timedelta as _td
    holidays = holidays if holidays is not None else _load_nse_holidays()
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d = d - _td(days=1)
    return d


def _nifty_monthly_expiry(year: int, month: int, holidays: set = None) -> date:
    """
    Last NIFTY-expiry-weekday (Tuesday) of the given month = NIFTY monthly F&O
    expiry. Shifted to the previous trading day when it is a weekend/holiday.
    """
    import calendar as _cal
    from datetime import timedelta as _td
    holidays = holidays if holidays is not None else _load_nse_holidays()
    last_day = date(year, month, _cal.monthrange(year, month)[1])
    # Walk back to the last expiry-weekday (Tuesday)
    days_back = (last_day.weekday() - NIFTY_EXPIRY_WEEKDAY) % 7
    last_exp = last_day - _td(days=days_back)
    return _shift_back_if_holiday(last_exp, holidays)


def _nifty_weekly_expiry(for_date: date = None) -> date:
    """
    Returns the CURRENT active NIFTY option expiry for the given date.

    Primary source: the actual expiry read from the latest option-chain JSON
    (`_active_expiry_from_oc`), which reflects NSE's real expiry weekday
    (currently Tuesday) including any exchange changes automatically.

    Fallback (only when no option-chain data is available): compute from the
    NIFTY expiry weekday (NIFTY_EXPIRY_WEEKDAY = Tuesday):
      on/before expiry weekday  →  this week's expiry (still ahead or is today)
      after expiry weekday       →  NEXT week's expiry (this week's already passed)
    Holiday adjustment: if the computed day is a weekend/NSE holiday, expiry
    shifts to the previous trading day (loaded from nse_holidays.json).
    """
    from datetime import timedelta as _td
    d = for_date or date.today()

    # Source-of-truth: real expiry from the option-chain feed.
    oc_expiry = _active_expiry_from_oc(d)
    if oc_expiry is not None:
        return oc_expiry

    # Fallback: compute from the NIFTY expiry weekday (no live option-chain available).
    weekday = d.weekday()            # 0=Mon … 6=Sun
    if weekday <= NIFTY_EXPIRY_WEEKDAY:      # this week's expiry still ahead or today
        days_ahead = NIFTY_EXPIRY_WEEKDAY - weekday
    else:                                    # this week's expiry passed → next week
        days_ahead = 7 - weekday + NIFTY_EXPIRY_WEEKDAY
    exp = d + _td(days=days_ahead)
    return _shift_back_if_holiday(exp)


def _is_nifty_expiry_day(for_date: date = None) -> bool:
    """True only on the actual NIFTY expiry day (from option-chain feed, else weekday calc)."""
    d = for_date or date.today()
    return _nifty_weekly_expiry(d) == d


def _expiry_type(expiry_date: date) -> str:
    """
    Returns 'monthly' when expiry_date is the last NIFTY expiry-weekday (Tuesday)
    of its month (NIFTY monthly F&O series), otherwise 'weekly'.
    """
    monthly = _nifty_monthly_expiry(expiry_date.year, expiry_date.month)
    return "monthly" if expiry_date == monthly else "weekly"


# ── profit banking & dynamic SL helpers ──────────────────────────────────────

def _calculate_dynamic_sl_atr(entry_price: float, hist: pd.DataFrame, 
                               cfg: dict, base_multiplier: float = 1.5) -> float:
    """
    Calculate dynamic stop loss based on ATR and market volatility.
    
    Formula: SL = entry_price × (1.0 + base_multiplier × (current_atr / baseline_atr))
    
    This adapts to market conditions:
    - High volatility (high ATR) → wider SL (avoid whipsaw exits)
    - Low volatility (low ATR) → tighter SL (protect capital)
    """
    if hist is None or hist.empty or entry_price <= 0:
        return round(entry_price * base_multiplier, 2)
    
    try:
        # Calculate current 14-period ATR
        _prev_c = hist["close"].shift(1).fillna(hist["close"])
        _tr = ((hist["high"]-hist["low"]).combine((hist["high"]-_prev_c).abs(),max)
               .combine((hist["low"]-_prev_c).abs(),max))
        _atr = float(_tr.rolling(14, min_periods=1).mean().iloc[-1])
        
        # Baseline ATR from config (typical 14-period ATR for the market)
        baseline_atr = float(cfg.get("risk", {}).get("baseline_atr", 100))
        if baseline_atr <= 0:
            baseline_atr = max(_atr * 0.8, 50)  # fallback: estimate from current
        
        # ATR multiplier from config (default 1.5 for 15% volatility adjustment)
        atr_mult = float(cfg.get("risk", {}).get("dynamic_sl", {}).get("atr_multiplier", 1.5))
        
        # Dynamic SL: wider in high vol, tighter in low vol
        sl_multiplier = base_multiplier * (1.0 + atr_mult * (_atr / baseline_atr) - atr_mult)
        
        # Hard caps: prevent runaway SL
        sl_multiplier = max(sl_multiplier, base_multiplier * 0.8)  # not more than 20% tighter
        sl_multiplier = min(sl_multiplier, base_multiplier * 2.0)  # not more than 2x wider
        
        return round(entry_price * sl_multiplier, 2)
    except Exception as e:
        logger.warning(f"Dynamic SL calculation failed: {e}, using base multiplier")
        return round(entry_price * base_multiplier, 2)


def _check_partial_exit_level(entry_price: float, current_price: float, 
                               direction: str = "sell", cfg: dict = None) -> Optional[dict]:
    """
    Check if current profit level matches any partial exit thresholds.
    
    Returns dict with:
      - level_hit: which profit level (1, 2, or 3)
      - profit_pct: current profit percentage
      - should_exit_pct: what percentage of position to exit
    Or None if no level hit.
    
    For sellers: profit = (entry - current) / entry × 100
    For buyers: profit = (current - entry) / entry × 100
    """
    if not cfg or entry_price <= 0:
        return None
    
    try:
        partial_exits = cfg.get("risk", {}).get("partial_exits", {})
        if not partial_exits.get("enabled", False):
            return None
        
        # Calculate current profit percentage
        if "sell" in direction.lower():
            profit_pct = ((entry_price - current_price) / entry_price) * 100 if entry_price > 0 else 0
        else:
            profit_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        
        # Check each exit level
        for level in [1, 2, 3]:
            level_key = f"exit_{level}_profit_pct"
            size_key = f"exit_{level}_size_pct"
            
            if level_key not in partial_exits:
                continue
            
            target_pct = float(partial_exits[level_key])
            exit_size = float(partial_exits.get(size_key, 0))
            
            if profit_pct >= target_pct and exit_size > 0:
                return {
                    "level_hit": level,
                    "profit_pct": round(profit_pct, 2),
                    "should_exit_pct": exit_size,
                    "target_pct": target_pct,
                }
        
        return None
    except Exception as e:
        logger.warning(f"Partial exit check failed: {e}")
        return None


def _calculate_adaptive_strikes(oc: pd.DataFrame, current_spreads: dict, 
                                 target_credit: float, max_spread_width: int = 600) -> Optional[dict]:
    """
    When credit threshold breached, adjust strikes to widen the spread.
    Returns new strike configuration or None if cannot achieve target.
    
    Algorithm:
    1. Start with current spreads
    2. If credit < target: widen outer strikes by +50pts each iteration
    3. Retry until credit >= target or max_width exceeded
    """
    if oc is None or oc.empty or not current_spreads:
        return None
    
    try:
        spot = float(oc["spot"].iloc[0])
        current_sell_pe = int(current_spreads.get("sell_pe", spot - 100))
        current_buy_pe = int(current_spreads.get("buy_pe", spot - 200))
        current_sell_ce = int(current_spreads.get("sell_ce", spot + 100))
        current_buy_ce = int(current_spreads.get("buy_ce", spot + 200))
        
        # Calculate current credit
        def get_spread_credit():
            sell_pe_ltp = float(oc[oc["strike"] == current_sell_pe]["PE_LTP"].iloc[0]) if not oc[oc["strike"] == current_sell_pe].empty else 0
            buy_pe_ltp = float(oc[oc["strike"] == current_buy_pe]["PE_LTP"].iloc[0]) if not oc[oc["strike"] == current_buy_pe].empty else 0
            return max(sell_pe_ltp - buy_pe_ltp, 0)
        
        current_credit = get_spread_credit()
        
        # If already at target, return current
        if current_credit >= target_credit:
            return None  # No adjustment needed
        
        # Try widening by 50pts at a time
        for iteration in range(6):  # max 6 iterations = 300pts wider
            width = abs(current_sell_pe - current_buy_pe)
            if width > max_spread_width:
                return None  # Cannot widen further
            
            # Widen the spread by moving outer strike further
            current_buy_pe = current_sell_pe - (width + 50)
            new_credit = get_spread_credit()
            
            if new_credit >= target_credit:
                return {
                    "sell_pe": current_sell_pe,
                    "buy_pe": current_buy_pe,
                    "sell_ce": current_sell_ce,
                    "buy_ce": current_buy_ce,
                    "new_credit": new_credit,
                    "iterations": iteration + 1,
                }
        
        return None
    except Exception as e:
        logger.warning(f"Adaptive strike calculation failed: {e}")
        return None


# ── strategy runners ─────────────────────────────────────────────────────────

def _run_institutional(hist, oc, sent, cfg, vix: float = 0.0) -> dict:
    # Expiry day guard: block directional buyers on expiry — premium crushes to zero by EOD
    # Expiry date is read from the option-chain feed (source of truth), else weekday fallback.
    if _is_nifty_expiry_day():
        return {"skip_reason": f"EXPIRY_DAY({date.today()}) - buyers blocked on expiry, premium decays to zero"}

    # Time-of-day guard: block buyers after 14:30 IST — theta decay accelerates near close
    _now_time = datetime.now().strftime("%H:%M")
    if _now_time >= "14:30":
        return {"skip_reason": f"LATE_ENTRY({_now_time}) - buyer entries blocked after 14:30 IST"}

    result = institutional_trade(hist, oc, sent, LOT_SIZE, cfg, BUDGET)
    if "error" in result:
        return {"skip_reason": result["error"]}

    entry  = _safe_float(result.get("_entry_price"))
    strike = int(result.get("_strike", 0) or 0)
    opt_type = str(result.get("_opt_type", "CE"))

    # Low-range guard for buyers: in very low VIX and low intraday movement,
    # avoid long premium entries where theta decay dominates.
    _ctx = _latest_intraday_context()
    _vix = float(vix or 0.0)
    _move_abs = abs(float(_ctx.get("day_move_pct", 0) or 0))
    _range_pct = float(_ctx.get("day_range_pct", 0) or 0)
    if _vix < 12.5 and _move_abs < 0.18 and _range_pct < 0.35:
        return {
            "skip_reason": (
                f"LOW_RANGE_NO_MOMENTUM(vix={_vix:.1f},move={_move_abs:.2f}%,range={_range_pct:.2f}%)"
            )
        }

    # Breakeven distance guard: skip if required move > ATR threshold.
    # Threshold is VIX-adaptive: tighter in high-vol (expensive premium, big ATR),
    # looser in low-vol (VIX < 14) because ATR itself is smaller in calm markets.
    if not oc.empty and entry > 0 and strike > 0:
        _spot_now = float(oc["spot"].iloc[0])
        _prev_c   = hist["close"].shift(1).fillna(hist["close"])
        _tr = ((hist["high"]-hist["low"]).combine((hist["high"]-_prev_c).abs(),max)
               .combine((hist["low"]-_prev_c).abs(),max))
        _atr = float(_tr.rolling(14, min_periods=1).mean().iloc[-1])
        # Loosen threshold in low-volatility: 60% ATR when VIX < 14, else 40% ATR
        _vix = float(vix or 0.0)
        _atr_threshold = 0.60 if _vix < 14.0 else 0.40
        _breakeven = strike + entry if opt_type == "CE" else strike - entry
        _move_needed = abs(_breakeven - _spot_now)
        if _move_needed > _atr * _atr_threshold:
            return {"skip_reason": f"BREAKEVEN_TOO_FAR(need={_move_needed:.0f}pts > {int(_atr_threshold*100)}%ATR={_atr*_atr_threshold:.0f}pts, VIX={_vix:.1f})"}
        if entry > _atr * _atr_threshold:
            return {"skip_reason": f"EXPENSIVE_PREMIUM(entry={entry:.0f} > {int(_atr_threshold*100)}%ATR={_atr*_atr_threshold:.0f}, VIX={_vix:.1f})"}

    # Tighter SL: 25% of premium (was 50% from institutional_trade — too loose)
    sl  = round(entry * 0.75, 2)   # exit when premium drops 25%
    tgt = _safe_float(result.get("_target_price"))

    return {
        "instrument":      opt_type,
        "direction":       result.get("_direction", "buy"),
        "strike":          strike,
        "entry_price":     entry,
        "stop_loss":       sl,
        "target":          tgt,
        "qty_lots":        1,
        "investment_amount": _investment(entry, LOT_SIZE, 1, "Premium"),
        "margin_type":     "Premium",
        "regime":          sent.get("label", ""),
        "reason":          result.get("reason", "")[:200],
        "skip_reason":     None if sent.get("score", 0) != 0 else "NEUTRAL_SIGNAL",
    }


def _run_option_seller(hist, oc, sent, cfg, sb, vix_safe) -> dict:
    if not vix_safe:
        return {"skip_reason": f"HIGH_VIX({round(0, 1)}) - seller skipped"}

    opt_regime  = sb.detect_option_seller_regime(hist, oc, pd.DataFrame(), sent)
    opt_ideas   = sb.generate_option_seller_strategies(oc, opt_regime)
    result      = option_seller_trade(hist, oc, sent, opt_ideas, LOT_SIZE, cfg, BUDGET)

    if "error" in result:
        return {"skip_reason": result["error"]}

    entry = _safe_float(result.get("_entry_price"))
    sl    = _safe_float(result.get("_sl_price"))
    tgt   = _safe_float(result.get("_target_price"))

    # Minimum credit check (adaptive): relax slightly in low VIX, tighten near expiry.
    spread_width = _safe_float(result.get("spread_width", 200))
    _ctx = _latest_intraday_context()
    _vix_now = float(_ctx.get("vix", 0) or 0)
    _dte = _days_to_active_expiry()
    _ratio = _adaptive_credit_ratio(_vix_now, _dte, base_ratio=0.15)
    min_credit = spread_width * _ratio
    if spread_width > 0 and entry < min_credit:
        # IMPROVEMENT: Agent adaptive strikes - try to widen spread if credit insufficient
        adaptive = _calculate_adaptive_strikes(oc, {
            "sell_pe": int(result.get("_strike_pe", 0) or 0),
            "buy_pe": int(result.get("buy_pe_strike", 0) or 0),
            "sell_ce": int(result.get("_strike_ce", 0) or 0),
            "buy_ce": int(result.get("buy_ce_strike", 0) or 0),
        }, min_credit, max_spread_width=600)
        
        if adaptive:
            # Successfully found wider strikes with better credit
            new_credit = adaptive.get("new_credit", entry)
            logger.info(f"Agent adapted strikes (widened {adaptive['iterations']} times): "
                       f"credit improved from {entry:.1f} to {new_credit:.1f}")
            # Note: Full implementation would regenerate strikes here
            # For now, we log the adaptation and still skip with note
            return {"skip_reason": f"THIN_CREDIT(adapted_credit={new_credit:.1f}<{min_credit:.1f}={int(_ratio*100)}%x{spread_width:.0f}pts,dte={_dte})"}
        else:
            return {"skip_reason": f"THIN_CREDIT(credit={entry:.1f}<{min_credit:.1f}={int(_ratio*100)}%x{spread_width:.0f}pts,dte={_dte})"}

    # SL based on max defined risk, not a simple premium multiple.
    # For a defined-risk spread (Iron Condor): max loss = spread_width - credit.
    # Exit when loss reaches 50% of max defined risk to preserve capital.
    # If spread_width is unknown (naked strategies), fall back to 1.5× premium.
    _max_defined_risk = (spread_width - entry) if spread_width > entry else 0
    if _max_defined_risk > 0:
        # Credit-to-max-risk floor: reject setups whose reward is too thin for the
        # defined risk (e.g. tiny credit on a wide spread). Complements the
        # width-based min_credit check above.
        _credit_to_risk = entry / _max_defined_risk if _max_defined_risk > 0 else 0
        if _credit_to_risk < MIN_CREDIT_TO_RISK:
            return {"skip_reason": (f"THIN_REWARD(credit/risk={_credit_to_risk:.2f}<"
                                    f"{MIN_CREDIT_TO_RISK:.2f}; credit={entry:.1f},"
                                    f"max_risk={_max_defined_risk:.1f})")}
        # SL = entry + 50% of max loss  (i.e. close position when debit-to-close = entry + 0.5×max_risk)
        sl = round(entry + _max_defined_risk * 0.50, 2)
    else:
        sl = round(entry * 1.5, 2)   # fallback for naked strategies

    return {
        "instrument":      result.get("strategy", "Straddle"),
        "direction":       "sell",
        "strike":          f"CE:{result.get('_strike_ce', 0)}/PE:{result.get('_strike_pe', 0)}",
        "short_ce_strike": result.get("_strike_ce"),
        "short_pe_strike": result.get("_strike_pe"),
        "buy_ce_strike":   result.get("buy_ce_strike"),
        "buy_pe_strike":   result.get("buy_pe_strike"),
        "spread_width":    spread_width,
        "entry_price":     entry,
        "stop_loss":       sl,
        "target":          tgt,
        "qty_lots":        1,
        "investment_amount": _safe_float(result.get("_margin_per_lot", 0)) * 1,
        "margin_type":     "SPAN",
        "regime":          opt_regime.get("regime", ""),
        "reason":          result.get("reason", "")[:200],
        "skip_reason":     None,
    }


def _run_option_buyer(hist, oc, sent, cfg, vix: float = 0.0) -> dict:
    score = sent.get("score", 0)
    if score == 0:
        return {"skip_reason": "NEUTRAL_SIGNAL"}

    # Expiry day guard: block directional buyers on expiry — premium crushes to zero by EOD
    # Expiry date is read from the option-chain feed (source of truth), else weekday fallback.
    if _is_nifty_expiry_day():
        return {"skip_reason": f"EXPIRY_DAY({date.today()}) - buyers blocked on expiry, premium decays to zero"}

    # Time-of-day guard: block buyers after 14:30 IST — theta decay accelerates near close
    _now_time = datetime.now().strftime("%H:%M")
    if _now_time >= "14:30":
        return {"skip_reason": f"LATE_ENTRY({_now_time}) - buyer entries blocked after 14:30 IST"}

    buyer_ideas = generate_buyer_strategies(oc, hist, sent, LOT_SIZE, cfg)
    if not buyer_ideas:
        return {"skip_reason": "NO_BUYER_SETUP"}

    # Pick best match for direction
    idea = None
    for i in buyer_ideas:
        if score >= 1 and "Bullish" in i.direction:
            idea = i; break
        if score <= -1 and "Bearish" in i.direction:
            idea = i; break
    idea = idea or buyer_ideas[0]

    entry = _safe_float(idea._entry)
    if entry <= 0:
        return {"skip_reason": "ZERO_ENTRY_PRICE"}

    strike   = int(idea._strike)
    opt_type = str(idea._opt_type)

    # Low-range guard for buyers: in very low VIX and low intraday movement,
    # avoid long premium entries where theta decay dominates.
    _ctx = _latest_intraday_context()
    _vix = float(vix or 0.0)
    _move_abs = abs(float(_ctx.get("day_move_pct", 0) or 0))
    _range_pct = float(_ctx.get("day_range_pct", 0) or 0)
    if _vix < 12.5 and _move_abs < 0.18 and _range_pct < 0.35:
        return {
            "skip_reason": (
                f"LOW_RANGE_NO_MOMENTUM(vix={_vix:.1f},move={_move_abs:.2f}%,range={_range_pct:.2f}%)"
            )
        }

    # Breakeven distance guard: VIX-adaptive threshold.
    # Loose in low-vol (VIX < 14 → 60% ATR), tighter in high-vol (40% ATR).
    if not oc.empty and entry > 0 and strike > 0:
        _spot_now = float(oc["spot"].iloc[0])
        _prev_c   = hist["close"].shift(1).fillna(hist["close"])
        _tr = ((hist["high"]-hist["low"]).combine((hist["high"]-_prev_c).abs(),max)
               .combine((hist["low"]-_prev_c).abs(),max))
        _atr = float(_tr.rolling(14, min_periods=1).mean().iloc[-1])
        _vix = float(vix or 0.0)
        _atr_threshold = 0.60 if _vix < 14.0 else 0.40
        _breakeven = strike + entry if opt_type == "CE" else strike - entry
        _move_needed = abs(_breakeven - _spot_now)
        if _move_needed > _atr * _atr_threshold:
            return {"skip_reason": f"BREAKEVEN_TOO_FAR(need={_move_needed:.0f}pts > {int(_atr_threshold*100)}%ATR={_atr*_atr_threshold:.0f}pts, VIX={_vix:.1f})"}
        if entry > _atr * _atr_threshold:
            return {"skip_reason": f"EXPENSIVE_PREMIUM(entry={entry:.0f} > {int(_atr_threshold*100)}%ATR={_atr*_atr_threshold:.0f}, VIX={_vix:.1f})"}

    # Tighter SL: 25% of premium (fixed 50% SL is too loose for directional buys)
    sl_tight = round(entry * 0.75, 2)

    return {
        "instrument":      opt_type,
        "direction":       idea._direction_code,
        "strike":          strike,
        "entry_price":     entry,
        "stop_loss":       sl_tight,
        "target":          _safe_float(idea._target),
        "qty_lots":        1,
        "investment_amount": round(entry * LOT_SIZE, 0),
        "margin_type":     "Premium",
        "regime":          sent.get("label", ""),
        "reason":          idea.when_to_use[:200],
        "skip_reason":     None,
    }


def _run_hedging(hist, oc, sent, cfg) -> dict:
    """
    Re-computes entry/SL/target directly from the option chain because
    HedgingStrategyIdea does NOT store private _entry/_sl/_target attributes.
    Uses the same strike selection logic as generate_hedging_strategies.
    """
    if oc is None or oc.empty:
        return {"skip_reason": "NO_OC"}

    hedge_ideas = generate_hedging_strategies(oc, hist, sent, LOT_SIZE, cfg)
    idea = next((h for h in hedge_ideas if "⭐" in h.strategy_name), None)
    idea = idea or (hedge_ideas[0] if hedge_ideas else None)
    if not idea:
        return {"skip_reason": "NO_HEDGE_SETUP"}

    # ── Recompute numeric values directly from chain ──────────────────
    import numpy as np

    def _near(df, v):
        arr = np.array(sorted(df["strike"].unique()))
        return int(arr[np.argmin(np.abs(arr - v))])

    def _ltp_local(df, strike, opt):
        row = df[df["strike"] == strike]
        if row.empty: return 0.05
        return max(float(row["CE_LTP"].iloc[0] if opt == "CE" else row["PE_LTP"].iloc[0]), 0.05)

    def _atr_local(df, period=14):
        prev = df["close"].shift(1).fillna(df["close"])
        tr = (df["high"] - df["low"]).combine(
            (df["high"] - prev).abs(), max).combine(
            (df["low"]  - prev).abs(), max)
        return float(tr.rolling(period, min_periods=1).mean().iloc[-1])

    spot  = float(oc["spot"].iloc[0])
    atr   = _atr_local(hist)
    score = sent.get("score", 0)

    # Determine which spread to use based on the idea's strategy name
    if "Bull Put" in idea.strategy_name or score >= 0:
        # Bull Put Credit Spread: sell OTM put, buy lower put
        # FIX: Use 1.5× ATR distance for short leg (was 1.0×) to reduce breach probability
        # At 1.0× ATR, spot routinely hits the short strike on volatile days → losses
        # At 1.5× ATR, short strike is safer but credit is slightly lower — acceptable tradeoff
        sell_s = _near(oc, spot - 1.5 * atr)
        buy_s  = _near(oc, spot - 2.5 * atr)
        sell_p = _ltp_local(oc, sell_s, "PE")
        buy_p  = _ltp_local(oc, buy_s,  "PE")
        net_credit    = round(sell_p - buy_p, 2)
        spread_width  = abs(sell_s - buy_s)
        instrument    = f"Bull Put Spread (Sell {sell_s}PE / Buy {buy_s}PE)"
        direction     = "sell"
        strike_label  = f"PE:{sell_s}/PE:{buy_s}"
    else:
        # Bear Call Credit Spread: sell OTM call, buy higher call
        # FIX: Use 1.5× ATR distance for short leg (was 1.0×)
        sell_s = _near(oc, spot + 1.5 * atr)
        buy_s  = _near(oc, spot + 2.5 * atr)
        sell_p = _ltp_local(oc, sell_s, "CE")
        buy_p  = _ltp_local(oc, buy_s,  "CE")
        net_credit    = round(sell_p - buy_p, 2)
        spread_width  = abs(sell_s - buy_s)
        instrument    = f"Bear Call Spread (Sell {sell_s}CE / Buy {buy_s}CE)"
        direction     = "sell"
        strike_label  = f"CE:{sell_s}/CE:{buy_s}"

    if net_credit <= 0:
        return {"skip_reason": f"NO_CREDIT(sell={sell_p:.2f} buy={buy_p:.2f})"}

    # Minimum credit check (adaptive): align with OptionSeller and account for low VIX / DTE.
    _ctx = _latest_intraday_context()
    _vix_now = float(_ctx.get("vix", 0) or 0)
    _dte = _days_to_active_expiry()
    _ratio = _adaptive_credit_ratio(_vix_now, _dte, base_ratio=0.15)
    _min_hedge_credit = spread_width * _ratio
    if net_credit < _min_hedge_credit:
        return {"skip_reason": f"THIN_CREDIT(credit={net_credit:.2f}<{_min_hedge_credit:.2f}={int(_ratio*100)}%x{spread_width:.0f}pts,dte={_dte})"}

    # IMPROVEMENT: Use dynamic SL based on ATR instead of fixed 1.5x multiplier
    # High volatility → wider SL (avoid whipsaw exits)
    # Low volatility → tighter SL (protect capital)
    dynamic_sl = _calculate_dynamic_sl_atr(net_credit, hist, cfg, base_multiplier=1.5)
    sl_price = dynamic_sl  # dynamic SL in place of fixed 1.5× rule
    
    # Target remains 50% profit on collected credit (this is profitable enough)
    tgt_price = round(net_credit * 0.50, 2)  # 50% profit target (close at half value)

    # Margin = spread width × lot_size (max risk per lot)
    margin_per_lot = spread_width * LOT_SIZE
    qty = 1  # always 1 lot minimum for auto trade
    investment = round(margin_per_lot * qty, 0)

    return {
        "instrument":       instrument,
        "direction":        direction,
        "strike":           strike_label,
        "entry_price":      net_credit,        # net credit received per unit
        "stop_loss":        sl_price,          # debit to close = SL trigger
        "target":           tgt_price,         # debit to close = Target trigger (50% profit)
        "qty_lots":         qty,
        "investment_amount": investment,        # margin required
        "margin_type":      "SPAN",
        "regime":           sent.get("label", ""),
        "reason":           f"Credit spread: collect {net_credit:.2f}. Win if spot stays "
                            f"{'above ' + str(sell_s) if 'PE' in strike_label else 'below ' + str(sell_s)} at expiry.",
        "skip_reason":      None,
    }


def _run_institutional_agent(hist, oc, sent, cfg, opts, vix: float = 0.0) -> dict:
    standard = _run_institutional(hist, oc, sent, cfg, vix=vix)
    if "skip_reason" in standard and standard["skip_reason"]:
        return standard

    entry = standard["entry_price"]

    # FIX: SL is a fraction of premium remaining, not subtracted from entry.
    # For buyers: SL = entry × sl_retention_pct  (e.g. 0.65 = exit when 35% of premium is lost)
    # A value of 1.5 / 1.5 = 1.0 ratio means normal, below 1 means tighter.
    atr_ratio_sl  = opts.get("optimal_sl_atr_multiplier", 1.5) / 1.5   # 0.8–1.2 range typical
    atr_ratio_tgt = opts.get("optimal_target_atr_multiplier", 2.5) / 2.5

    # SL: retain at least (1 - sl_loss_pct) of premium. Base loss tolerance = 25%.
    # In low vol (atr_ratio < 1): tighten slightly. In high vol (atr_ratio > 1): loosen slightly.
    # FLOOR at 55% retained (max 45% loss) to avoid premature exits on volatile days.
    sl_retention = max(0.55, min(0.85, 0.75 * atr_ratio_sl))  # 55–85% retention
    sl  = round(entry * sl_retention, 2)

    # Target: 2× entry is standard (100% return on premium), scale with agent ratio
    tgt_multiplier = max(1.5, min(3.0, 2.0 * atr_ratio_tgt))
    tgt = round(entry * tgt_multiplier, 2)

    standard["stop_loss"] = max(sl, 0.05)
    standard["target"]    = max(tgt, 0.05)
    
    # RISK CONTROL: Add hard caps on position sizing and SL scaling
    qty_lots = standard.get("qty_lots", 1)
    qty_lots = max(1, int(round(qty_lots * opts.get("risk_allocation_multiplier", 1.0))))
    qty_lots = min(qty_lots, 5)  # HARD CAP: Never exceed 5 lots per trade
    standard["qty_lots"] = qty_lots
    
    standard["investment_amount"] = _investment(entry, LOT_SIZE, qty_lots, "Premium")
    standard["reason"] = f"[Agent Optimized (SL Mult: {atr_ratio_sl:.1f}x, Size Cap: {qty_lots})] " + standard["reason"]
    return standard


def _run_option_seller_agent(hist, oc, sent, cfg, sb, vix_safe, opts) -> dict:
    standard = _run_option_seller(hist, oc, sent, cfg, sb, vix_safe)
    if "skip_reason" in standard and standard["skip_reason"]:
        return standard
    
    # FIXED: Use premium-based targeting for option selling (not percentage haircut)
    # For short strangles/condors, target should be profit % of collected premium
    entry = standard["entry_price"]
    
    # Stop Loss: Allow 1.5-2.0x the collected premium before exiting
    atr_ratio_sl = opts.get("optimal_sl_atr_multiplier", 1.5) / 1.5
    base_sl_mult = max(1.5, 1.5 * atr_ratio_sl)  # 1.5x-2.25x premium loss tolerance
    base_sl_mult = min(base_sl_mult, 3.0)  # HARD CAP: Never exceed 3.0x SL expansion
    
    # IMPROVEMENT: Use dynamic SL based on ATR volatility adjustment
    dynamic_sl = _calculate_dynamic_sl_atr(entry, hist, cfg, base_multiplier=base_sl_mult)
    sl_price = dynamic_sl  # Use ATR-adjusted SL instead of fixed multiplier
    
    # Target: Aim for 40-60% profit on collected premium
    # Narrower spreads (Iron Condor) → 60% profit, wider (naked strangle) → 50% profit
    spread_width = standard.get("spread_width", 100)  # points
    if spread_width > 0 and spread_width <= 200:
        profit_target_pct = 0.60  # Iron Condor: 60% profit target
    else:
        profit_target_pct = 0.50  # Naked Strangle: 50% profit target
    
    tgt_price = round(entry * profit_target_pct, 2)
    
    standard["stop_loss"] = sl_price
    standard["target"] = tgt_price
    
    # RISK CONTROL: Add hard caps on position sizing
    qty_lots = standard.get("qty_lots", 1)
    qty_lots = max(1, int(round(qty_lots * opts.get("risk_allocation_multiplier", 1.0))))
    qty_lots = min(qty_lots, 5)  # HARD CAP: Never exceed 5 lots per trade
    standard["qty_lots"] = qty_lots
    
    standard["investment_amount"] = round(standard.get("investment_amount", 0) * qty_lots, 0)
    standard["reason"] = f"[Agent Optimized - {profit_target_pct*100:.0f}% Target ({spread_width}pt spread) Size Cap: {qty_lots}] " + standard["reason"]
    return standard


# ── P&L updater ──────────────────────────────────────────────────────────────

def _current_ltp(oc: pd.DataFrame, strike, opt_type: str) -> float:
    """Fetch current LTP from option chain for a given strike and type."""
    if oc is None or oc.empty:
        return 0.0
    try:
        strike = int(float(str(strike).split("/")[0].replace("CE:", "").replace("PE:", "")))
        row = oc[oc["strike"] == strike]
        if row.empty:
            return 0.0
        return float(row["CE_LTP"].iloc[0] if opt_type in ("CE", "buy") else row["PE_LTP"].iloc[0])
    except Exception:
        return 0.0


def _ltp_at_strike(oc: pd.DataFrame, strike: int, opt_type: str) -> float:
    """Fetch CE/PE LTP for an exact strike, 0.0 if unavailable."""
    if oc is None or oc.empty or strike <= 0:
        return 0.0
    row = oc[oc["strike"] == int(strike)]
    if row.empty:
        return 0.0
    return float(row["CE_LTP"].iloc[0] if opt_type == "CE" else row["PE_LTP"].iloc[0])


def _parse_short_strikes_from_text(strike_str: str) -> tuple[int, int]:
    """Parse short CE/PE strikes from compact text like CE:24050/PE:23600."""
    short_ce = 0
    short_pe = 0
    if not strike_str:
        return short_ce, short_pe

    # Token-wise parse to tolerate variants like PE:S23600 or CE:B24300.
    for token in re.split(r"[/|]", str(strike_str)):
        t = token.strip().upper()
        m = re.search(r"(CE|PE)[^0-9]*([0-9]{4,6})", t)
        if not m:
            continue
        opt, strike_num = m.group(1), int(m.group(2))
        if opt == "CE" and short_ce == 0:
            short_ce = strike_num
        if opt == "PE" and short_pe == 0:
            short_pe = strike_num
    return short_ce, short_pe


def _current_spread_value(
    oc: pd.DataFrame,
    strike_str: str,
    trade: Optional[dict] = None,
    return_trace: bool = False,
):
    """
    Calculate current spread value for credit spreads.
    Format: "PE:24000/PE:23800" → returns (PE_24000_LTP - PE_23800_LTP)
    Format: "CE:25000/CE:26000" → returns (CE_25000_LTP - CE_26000_LTP)
    For credit spreads, lower spread value = good (we collected premium, closing cheaper)
    """
    if oc is None or oc.empty:
        if return_trace:
            return 0.0, {"method": "no_oc", "legs": []}
        return 0.0
    
    try:
        trade = trade or {}
        instr = str(trade.get("instrument", "")).lower()
        trace = {"method": "unknown", "legs": []}

        # Iron condor: value must be 4-leg net debit to close:
        # (short CE + short PE) - (long CE wing + long PE wing)
        if "iron condor" in instr or (
            trade.get("short_ce_strike") or trade.get("short_pe_strike") or
            trade.get("buy_ce_strike") or trade.get("buy_pe_strike")
        ):
            short_ce = int(trade.get("short_ce_strike", 0) or 0)
            short_pe = int(trade.get("short_pe_strike", 0) or 0)
            buy_ce = int(trade.get("buy_ce_strike", 0) or 0)
            buy_pe = int(trade.get("buy_pe_strike", 0) or 0)

            if short_ce <= 0 or short_pe <= 0:
                parsed_ce, parsed_pe = _parse_short_strikes_from_text(strike_str)
                short_ce = short_ce or parsed_ce
                short_pe = short_pe or parsed_pe

            if short_ce <= 0 or short_pe <= 0:
                return 0.0

            sc = _ltp_at_strike(oc, short_ce, "CE")
            sp = _ltp_at_strike(oc, short_pe, "PE")
            trace["legs"].append({"role": "short_ce", "strike": short_ce, "ltp": sc})
            trace["legs"].append({"role": "short_pe", "strike": short_pe, "ltp": sp})

            # If wings are unavailable in older rows, fall back to short strangle value
            # rather than CE-PE subtraction, which is invalid for condor pricing.
            if buy_ce > 0 and buy_pe > 0:
                bc = _ltp_at_strike(oc, buy_ce, "CE")
                bp = _ltp_at_strike(oc, buy_pe, "PE")
                trace["legs"].append({"role": "long_ce", "strike": buy_ce, "ltp": bc})
                trace["legs"].append({"role": "long_pe", "strike": buy_pe, "ltp": bp})
                if min(sc, sp, bc, bp) <= 0:
                    if return_trace:
                        trace["method"] = "iron_condor_4leg"
                        trace["error"] = "one_or_more_ltp_missing"
                        return 0.0, trace
                    return 0.0
                spread_value = (sc + sp) - (bc + bp)
                trace["method"] = "iron_condor_4leg"
            else:
                if min(sc, sp) <= 0:
                    if return_trace:
                        trace["method"] = "iron_condor_short_pair_fallback"
                        trace["error"] = "short_ltp_missing"
                        return 0.0, trace
                    return 0.0
                spread_value = sc + sp
                trace["method"] = "iron_condor_short_pair_fallback"

            out = max(spread_value, 0.05)
            if return_trace:
                trace["value"] = out
                return out, trace
            return out

        if "/" not in strike_str:
            if return_trace:
                return 0.0, {"method": "not_spread", "legs": []}
            return 0.0

        parts = strike_str.split("/")
        leg1_raw = parts[0].strip()  # e.g., "PE:24000"
        leg2_raw = parts[1].strip() if len(parts) > 1 else None
        
        if not leg2_raw:
            val = _current_ltp(oc, leg1_raw, "CE")
            if return_trace:
                return val, {"method": "single_leg_fallback", "legs": [{"raw": leg1_raw, "ltp": val}], "value": val}
            return val
        
        # Extract strike number and type
        leg1_type = "CE" if "CE" in leg1_raw else "PE"
        leg2_type = "CE" if "CE" in leg2_raw else "PE"
        
        leg1_strike = int(float(leg1_raw.replace("CE:", "").replace("PE:", "")))
        leg2_strike = int(float(leg2_raw.replace("CE:", "").replace("PE:", "")))
        
        # Fetch LTPs
        row1 = oc[oc["strike"] == leg1_strike]
        row2 = oc[oc["strike"] == leg2_strike]
        
        if row1.empty or row2.empty:
            if return_trace:
                return 0.0, {"method": "two_leg", "error": "row_missing", "legs": []}
            return 0.0
        
        ltp1 = float(row1["CE_LTP"].iloc[0] if leg1_type == "CE" else row1["PE_LTP"].iloc[0])
        ltp2 = float(row2["CE_LTP"].iloc[0] if leg2_type == "CE" else row2["PE_LTP"].iloc[0])
        
        # Same-type legs (CE/CE or PE/PE): treat as vertical spread value.
        # Mixed-type legs (CE/PE): treat as strangle/straddle short basket value.
        if leg1_type == leg2_type:
            # Credit spread value = sold leg - bought leg (assuming stored leg order).
            spread_value = ltp1 - ltp2
            method = "vertical_spread"
        else:
            # Short strangle/straddle close value = CE short + PE short.
            spread_value = ltp1 + ltp2
            method = "short_strangle_or_straddle"
        out = max(spread_value, 0.05)
        if return_trace:
            return out, {
                "method": method,
                "legs": [
                    {"role": "leg1", "raw": leg1_raw, "type": leg1_type, "strike": leg1_strike, "ltp": ltp1},
                    {"role": "leg2", "raw": leg2_raw, "type": leg2_type, "strike": leg2_strike, "ltp": ltp2},
                ],
                "value": out,
            }
        return out  # min 0.05 to avoid zero
    except Exception as e:
        logger.debug(f"Error calculating spread value for {strike_str}: {e}")
        if return_trace:
            return 0.0, {"method": "error", "error": str(e), "legs": []}
        return 0.0


def _apply_exit_slippage(trade: dict, base_exit_px: float, trigger: str) -> float:
    """Apply conservative slippage to auto-exit fills.

    SELL positions are closed by buying back premium/debit; worse fill = higher exit price.
    BUY positions are closed by selling premium; worse fill = lower exit price.
    """
    px = max(_safe_float(base_exit_px), 0.05)
    direction = str(trade.get("direction", "buy")).lower()
    s = AUTO_EXIT_SLIPPAGE_PCT / 100.0

    if "sell" in direction:
        return round(max(px * (1.0 + s), 0.05), 2)
    return round(max(px * (1.0 - s), 0.05), 2)


def _minutes_since_entry(trade: dict, now_dt: datetime) -> Optional[int]:
    """Return minutes elapsed since entry, or None if parsing fails."""
    try:
        d = str(trade.get("date", "")).strip()
        t = str(trade.get("entry_time", "")).strip()
        if not d or not t:
            return None
        entry_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
        return int((now_dt - entry_dt).total_seconds() // 60)
    except Exception:
        return None


def _strategy_time_exit_limit_minutes(trade: dict) -> int:
    """Pick configured time-exit limit for the trade's strategy type."""
    st = str(trade.get("strategy_type", "")).strip()
    if st in AUTO_TIME_EXIT_MIN_BY_STRATEGY:
        return int(AUTO_TIME_EXIT_MIN_BY_STRATEGY[st])
    return int(AUTO_TIME_EXIT_MIN_DEFAULT)


def _compute_pnl(trade: dict, exit_price: float, is_spread: bool = False) -> dict:
    """
    Compute P&L for a trade given the exit price.
    
    For single-leg trades:
      - Buy: pnl = (exit - entry) × qty × lot_size
      - Sell: pnl = (entry - exit) × qty × lot_size
    
    For spread trades:
      - exit_price should be the current spread value
      - pnl = (entry - exit_price) × qty × lot_size (seller collects more when spread narrows)
    """
    entry    = _safe_float(trade.get("entry_price"))
    qty      = int(trade.get("qty_lots", 1))
    lot_size = int(trade.get("lot_size", LOT_SIZE) or LOT_SIZE)
    invest   = _safe_float(trade.get("investment_amount", 1))
    direction = str(trade.get("direction", "buy")).lower()

    if "sell" in direction:
        # Credit trade: profit = premium collected - premium paid to close
        # This works for both single leg and spread (exit_price should be spread value for spreads)
        pnl = (entry - exit_price) * lot_size * qty
    else:
        # Debit trade: profit = exit - entry
        pnl = (exit_price - entry) * lot_size * qty

    pnl_pct = round(pnl / invest * 100, 2) if invest > 0 else 0.0
    return {"pnl_amount": round(pnl, 2), "pnl_pct": pnl_pct}


def _determine_exit_trigger(trade: dict, current_ltp: float, strike_raw: str = "", cfg: dict = None) -> str:
    """
    Decide if SL / Target is hit or still open.
    Handles both single-leg and spread trades.
    For spreads, current_ltp should be the spread value (sell - buy).
    
    IMPROVEMENT: Also checks for partial exit profit levels for profit banking.
    """
    sl     = _safe_float(trade.get("stop_loss"))
    target = _safe_float(trade.get("target"))
    entry  = _safe_float(trade.get("entry_price"))
    direction = str(trade.get("direction", "buy")).lower()

    # Check for partial exit profit levels (NEW - Profit Banking)
    if cfg and entry > 0:
        partial_exit = _check_partial_exit_level(entry, current_ltp, direction, cfg)
        if partial_exit:
            level = partial_exit.get("level_hit", 0)
            exit_pct = partial_exit.get("should_exit_pct", 0)
            return f"Partial_Exit_{level}({exit_pct}%)"

    # Standard exit triggers (unchanged)
    if "sell" in direction:
        # For sellers: SL = premium rises above entry; target = premium falls
        # For spreads: current_ltp is the spread value; lower = good for seller
        if sl > 0 and current_ltp >= sl:
            return "SL_Hit"
        if target > 0 and current_ltp <= target:
            return "Target_Hit"
    else:
        # For buyers: SL = price falls below; target = price rises above
        if sl > 0 and current_ltp <= sl:
            return "SL_Hit"
        if target > 0 and current_ltp >= target:
            return "Target_Hit"
    return "EOD_Close"


def _resolve_opt_type(instr: str, strike_raw: str) -> str:
    """
    Determine the option type (CE/PE) from the instrument and strike fields.
    Uses instrument field as primary source, strike string as fallback.
    Does NOT use direction — a PE buyer has direction='buy' but opt_type='PE'.
    """
    instr_up = instr.strip().upper()

    # Exact single-type instruments
    if instr_up == "CE":
        return "CE"
    if instr_up == "PE":
        return "PE"

    # Spread / condor strikes like "CE:24450/PE:23950" or "PE:24000/PE:23800"
    if "CE" in strike_raw and "PE" in strike_raw:
        # Use the PUT leg for put spreads, CE leg for call spreads
        if "put" in instr.lower() or instr_up.startswith("PE"):
            return "PE"
        return "CE"

    if "PE" in strike_raw:
        return "PE"
    if "CE" in strike_raw:
        return "CE"

    # Instrument name hints
    if "put" in instr.lower() or " PE" in instr:
        return "PE"
    if "call" in instr.lower() or " CE" in instr:
        return "CE"

    return "CE"  # safe default


def update_open_trades(mode: str = "update"):
    """Update all open trades from today with latest prices and P&L."""
    logger.info("=== Auto Trade Updater (%s) ===", mode)
    hist, oc, pcr, vix, oc_json = load_morning_data()

    # Load configuration for partial exits and dynamic adjustments
    cfg = get_config()

    # Stale-data kill switch for update/eod cycles.
    validation = validate_conditions(oc, oc_json, vix, require_cron_run=None)
    flags = validation.get("flags", [])
    critical = any(
        str(f).startswith(("HOLIDAY", "NO_OC", "STALE_DATA", "DATA_FROM_WRONG_DATE"))
        for f in flags
    )
    if critical:
        logger.warning("Update skipped due to safety flags: %s", flags)
        return

    trades   = _load_log()
    today    = date.today().isoformat()
    now_dt   = datetime.now()
    now_time = datetime.now().strftime("%H:%M")
    updated  = 0

    for t in trades:
        if t.get("status") != "Open" or t.get("date") != today:
            continue

        instr      = str(t.get("instrument", ""))
        strike_raw = str(t.get("strike", "0"))
        opt_type   = _resolve_opt_type(instr, strike_raw)
        
        # Check if this is a spread trade or condor-like multi-leg setup.
        is_spread = ("/" in strike_raw) or ("iron condor" in instr.lower())
        
        if is_spread:
            # For spreads: get spread value (sell leg - buy leg)
            current, trace = _current_spread_value(oc, strike_raw, t, return_trace=True)
        else:
            # For single-leg: get option LTP
            current = _current_ltp(oc, strike_raw, opt_type)
            trace = {
                "method": "single_leg",
                "legs": [{"role": "single", "type": opt_type, "strike": str(strike_raw), "ltp": current}],
                "value": current,
            }

        if current <= 0 and not hist.empty:
            current = float(hist["close"].iloc[-1])
            trace["fallback"] = "hist_close"
            trace["value"] = current

        # Pass cfg for partial exit checking (Profit Banking improvement)
        trigger = _determine_exit_trigger(t, current, strike_raw, cfg=cfg)

        # Time-based auto exit when trade remains open beyond configured limit.
        if mode == "update" and trigger == "EOD_Close":
            elapsed_min = _minutes_since_entry(t, now_dt)
            exit_limit = _strategy_time_exit_limit_minutes(t)
            t["elapsed_minutes"] = elapsed_min
            t["time_exit_limit_minutes"] = exit_limit
            if elapsed_min is not None and elapsed_min >= exit_limit:
                trigger = "TIME_EXIT"

        pnl     = _compute_pnl(t, current, is_spread=is_spread)

        t["current_ltp"]     = round(current, 2)
        t["current_pnl"]     = pnl["pnl_amount"]
        t["current_pnl_pct"] = pnl["pnl_pct"]
        t["last_updated"]    = now_time
        t["pricing_trace"]   = trace
        t["update_flags"]    = flags

        logger.info("  %s: opt=%s strike=%s ltp=%.2f pnl=%.2f (%s%%)",
                    t.get("strategy_type",""), opt_type, strike_raw,
                    current, pnl["pnl_amount"], pnl["pnl_pct"])

        if mode == "eod" or trigger in ("SL_Hit", "Target_Hit", "TIME_EXIT"):
            base_exit_px = current if trigger == "EOD_Close" else (
                t.get("stop_loss") if trigger == "SL_Hit" else t.get("target")
            )
            if trigger == "TIME_EXIT":
                base_exit_px = current
            exit_px = _apply_exit_slippage(t, _safe_float(base_exit_px), trigger)
            final_pnl = _compute_pnl(t, _safe_float(exit_px))

            if trigger in ("SL_Hit", "Target_Hit"):
                status = trigger
            else:
                status = "Closed"

            t.update({
                "status":       status,
                "exit_price":   round(_safe_float(exit_px), 2),
                "exit_time":    now_time,
                "exit_trigger": trigger,
                "pnl_amount":   final_pnl["pnl_amount"],
                "pnl_pct":      final_pnl["pnl_pct"],
                "exit_price_raw": round(_safe_float(base_exit_px), 2),
                "exit_slippage_pct": AUTO_EXIT_SLIPPAGE_PCT,
            })
        updated += 1

    _save_log(trades)
    logger.info("Updated %d open trade(s).", updated)


# ── main entry function ───────────────────────────────────────────────────────

def run_auto_trade_entry():
    """Run at 10:15 (expiry day) or 12:00 (normal day) — log today's auto-trade entries."""

    # Determine entry mode BEFORE loading data so we use the correct cron label
    _is_expiry = _is_nifty_expiry_day()
    _entry_cron_label = "10:15" if _is_expiry else "12:00"
    _entry_desc = f"10:15 (expiry day — early theta entry)" if _is_expiry else "12:00 (normal day)"
    logger.info("=== Auto Trade Entry [%s] ===", _entry_desc)

    # Always fetch a LIVE snapshot before entry so strikes are based on TODAY's spot,
    # not yesterday's EOD data.  Stale strikes are the #1 cause of IC wing breaches.
    try:
        from src.realtime_data import refresh_realtime
        snap_result = refresh_realtime(SYMBOL)
        if snap_result.get("ok"):
            logger.info("Live snapshot refreshed at entry: spot=₹%s  VIX=%s",
                        snap_result.get("spot"), snap_result.get("vix"))
        else:
            logger.warning("Live snapshot failed (%s) — proceeding with cached data.",
                           snap_result.get("message"))
    except Exception as exc:
        logger.warning("Could not refresh live snapshot before entry: %s", exc)

    hist, oc, pcr, vix, oc_json = load_morning_data()
    if hist.empty:
        logger.error("Historical data not available. Aborting.")
        return

    cfg  = get_config(str(ROOT / "config.yaml"))
    ia   = InstitutionalAnalyzer(cfg)
    sb   = StrategyBuilder(cfg)
    sent = ia.generate_sentiment(hist, oc, pcr)

    # Validate — use expiry-aware cron label
    validation = validate_conditions(oc, oc_json, vix, require_cron_run=_entry_cron_label)
    global_flags    = validation["flags"]
    vix_safe        = validation["vix_safe_to_sell"]
    data_timestamp  = validation["data_timestamp"]   # market snapshot time
    cron_run_label  = validation["cron_run_label"]   # which cron run produced this data

    logger.info("Data snapshot: market_time=%s  cron_run=%s  flags=%s",
                data_timestamp, cron_run_label, global_flags)

    today      = date.today().isoformat()
    entry_time = datetime.now().strftime("%H:%M")
    trades     = _load_log()
    existing   = {t["id"] for t in trades}

    spot = float(oc["spot"].iloc[0]) if not oc.empty else (
        float(hist["close"].iloc[-1]) if not hist.empty else 0.0
    )
    expiry = str(oc["date"].iloc[0].date()) if not oc.empty else today
    # Correct if the generic CSV defaulted to today (non-expiry day): use the real Thursday expiry
    _real_expiry = _nifty_weekly_expiry().isoformat()
    if expiry == today and expiry != _real_expiry:
        expiry = _real_expiry

    # ── Optimizer Agent Parameters ──
    try:
        agent_opt = DecisionOptimizerAgent(cfg)
        perf_data = agent_opt.analyze_journal_metrics(trades)
        reg_data = agent_opt.evaluate_market_regime(hist, oc, vix)
        opts = agent_opt.optimize_logic_parameters(perf_data, reg_data)
    except Exception as exc:
        logger.warning("Could not calculate agent parameters: %s", exc)
        opts = {
            "optimal_sl_atr_multiplier": 1.5,
            "optimal_target_atr_multiplier": 2.5,
            "risk_allocation_multiplier": 1.0,
        }

    strategy_runners = {
        "Institutional": lambda: _run_institutional(hist, oc, sent, cfg, vix=vix),
        "OptionSeller":  lambda: _run_option_seller(hist, oc, sent, cfg, sb, vix_safe),
        "OptionBuyer":   lambda: _run_option_buyer(hist, oc, sent, cfg, vix=vix),
        "Hedging":       lambda: _run_hedging(hist, oc, sent, cfg),
        "Agent-Institutional": lambda: _run_institutional_agent(hist, oc, sent, cfg, opts, vix=vix),
        "Agent-OptionSeller":  lambda: _run_option_seller_agent(hist, oc, sent, cfg, sb, vix_safe, opts),
    }

    added = 0
    # Track which (strike, instrument) pairs have already been entered today
    # to prevent multiple strategies from duplicating the exact same position.
    entered_strike_keys: set = set()

    for stype, runner in strategy_runners.items():
        trade_id = _trade_id(today, stype)

        # Skip duplicates
        if trade_id in existing:
            logger.info("  [SKIP] %s — already logged today.", stype)
            continue

        # Global safety block for holidays
        if "HOLIDAY" in global_flags:
            entry = {
                "id": trade_id, "date": today, "entry_time": entry_time,
                "symbol": SYMBOL, "strategy_type": stype,
                "status": "Skipped", "skip_reason": "HOLIDAY",
            }
            trades.append(entry)
            logger.info("  [SKIP] %s — HOLIDAY.", stype)
            continue

        try:
            result = runner()
        except Exception as exc:
            logger.warning("  [ERROR] %s — %s", stype, exc)
            result = {"skip_reason": f"ERROR: {exc}"}

        skip = result.get("skip_reason")

        # Duplicate strike guard: block entry if same strike+direction already entered
        # by a different strategy today (prevents 3x loss on same position).
        if not skip:
            _strike_key = f"{result.get('instrument','')}:{result.get('strike','')}:{result.get('direction','')}"
            if _strike_key and _strike_key in entered_strike_keys:
                skip = f"DUPLICATE_STRIKE({result.get('strike','')}) - already entered by earlier strategy"
                logger.info("  [SKIP] %s — %s", stype, skip)
            else:
                entered_strike_keys.add(_strike_key)

        entry = {
            "id":               trade_id,
            "date":             today,
            "entry_time":       entry_time,
            "cron_run":         _entry_cron_label,
            "symbol":           SYMBOL,
            "strategy_type":    stype,
            "instrument":       result.get("instrument", ""),
            "direction":        result.get("direction", ""),
            "strike":           str(result.get("strike", "")),
            "expiry":           expiry,
            "entry_price":      result.get("entry_price", 0.0),
            "stop_loss":        result.get("stop_loss", 0.0),
            "target":           result.get("target", 0.0),
            "qty_lots":         result.get("qty_lots", 1),
            "lot_size":         LOT_SIZE,
            "investment_amount": result.get("investment_amount", 0.0),
            "margin_type":      result.get("margin_type", "Premium"),
            "spot_at_entry":    spot,
            "sentiment_score":  sent.get("score", 0),
            "sentiment_label":  sent.get("label", ""),
            "pcr":              float(pcr["pcr_oi"].iloc[-1]) if not pcr.empty else 0.0,
            "vix":              vix,
            "max_pain":         0.0,
            "regime":           result.get("regime", ""),
            "reason":           result.get("reason", ""),
            "validation_flags": global_flags,
            "data_timestamp":   data_timestamp,   # when market data was captured (niftytrader.in)
            "cron_run_label":   cron_run_label,   # which cron run: "09:15" / "10:15" etc.
            "status":           "Skipped" if skip else "Open",
            "skip_reason":      skip,
            "current_ltp":      result.get("entry_price", 0.0),
            "current_pnl":      0.0,
            "current_pnl_pct":  0.0,
            "last_updated":     entry_time,
            "exit_price":       None,
            "exit_time":        None,
            "exit_trigger":     None,
            "pnl_amount":       None,
            "pnl_pct":          None,
            # Optional full-leg metadata (for multi-leg broker guides).
            "short_ce_strike":  result.get("short_ce_strike"),
            "short_pe_strike":  result.get("short_pe_strike"),
            "buy_ce_strike":    result.get("buy_ce_strike"),
            "buy_pe_strike":    result.get("buy_pe_strike"),
        }

        # Try to pull max_pain from OC JSON
        try:
            raw = json.loads(oc_json.read_bytes().decode("utf-8-sig"))
            entry["max_pain"] = float(raw.get("max_pain", 0) or 0)
        except Exception:
            pass

        trades.append(entry)
        added += 1
        status = f"SKIP({skip})" if skip else "OPEN"
        logger.info("  [%s] %s — strike=%s entry=%.2f sl=%.2f tgt=%.2f invest=₹%.0f",
                    status, stype,
                    entry["strike"], entry["entry_price"],
                    entry["stop_loss"], entry["target"],
                    entry["investment_amount"])

    _save_log(trades)
    logger.info("Auto trade entry complete. Added %d record(s) to %s", added, LOG_PATH)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Trade Engine")
    parser.add_argument(
        "--mode",
        choices=["entry", "update", "eod"],
        default="entry",
        help="entry=log new trades (10:15), update=refresh P&L (intraday), eod=close trades (15:30/18:30)",
    )
    args = parser.parse_args()

    if args.mode == "entry":
        run_auto_trade_entry()
    else:
        update_open_trades(mode=args.mode)
