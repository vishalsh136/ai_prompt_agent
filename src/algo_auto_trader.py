"""
src/algo_auto_trader.py
=======================
Unified automated options algo-trader.

Combines the *paper-trade decision logic* (Auto Trade Log) with *live broker
execution* (Live Algo Trade) into one always-on loop that reads market data in
real time (no cron) and manages entry + exit automatically under strict risk
controls.

Every tick:
  1. Pull a fresh real-time option-chain snapshot.
  2. Evaluate circuit breakers (crash / rally / gap / daily loss / daily profit
     / max orders / cool-off).
  3. If a position is open  -> value it and auto-EXIT on target / max-loss /
     time / guard-breach / hard square-off.
  4. If flat & armed & clear -> size within caps and auto-ENTER.

Real orders transmit ONLY when controls.dry_run is False AND controls.allow_live
is True. Otherwise everything is simulated.

Run:
    python -m src.algo_auto_trader --once
    python -m src.algo_auto_trader --loop
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.algo_trade_config import (
    load_algo_config,
    resolve_broker_creds,
    build_legs,
)
from src.realtime_data import refresh_realtime, value_legs_from_snapshot
from src.auto_trade_engine import (
    load_morning_data, _nifty_weekly_expiry, _nifty_monthly_expiry,
    _is_nifty_expiry_day, _expiry_type,
)
from src.live_auto_runner import _position_value, _today_realized_pnl
from src.live_broker_adapter import (
    StartAlgoRequest,
    get_live_broker_adapter,
    append_journal_event,
    load_live_positions,
    upsert_live_position,
    remove_live_position,
)
from src.token_manager import regenerate_token

logger = logging.getLogger("algo_auto_trader")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

JOURNAL_PATH = Path("data/live_algo_journal.jsonl")


def _parse_hhmm(text: str, default: str) -> datetime.time:
    try:
        return datetime.strptime(str(text or default), "%H:%M").time()
    except Exception:
        return datetime.strptime(default, "%H:%M").time()


def _evaluate_opportunity(rt: dict, oc, hist, cfg: dict, now: datetime) -> dict:
    """
    Score the current market setup for trade entry quality.

    Evaluates 6 independent signals, each contributing to a 0-100 score:
      1. Opening range confirmed  (time > 10:15 IST)
      2. Directional clarity      (day_move_pct magnitude)
      3. VIX in sweet spot        (11–18 = normal, outside = risk)
      4. PCR alignment            (PCR confirms directional bias)
      5. Move not extended        (price not already >60% of ATR from prior close)
      6. ATM premium available    (straddle >= meaningful threshold)

    Returns dict with:
      score        : int 0-100
      grade        : "A" / "B" / "C" / "D" / "F"
      signals      : list of human-readable signal strings
      should_enter : bool (score >= min_opportunity_score from config)
      reason       : aggregated skip reason if should_enter=False
    """
    import math

    score = 0
    signals = []
    trading = cfg.get("trading", {})
    min_score = int(trading.get("min_opportunity_score", 55))

    vix      = float(rt.get("vix", 0) or 0)
    pcr      = float(rt.get("pcr", 1.0) or 1.0)
    day_move = float(rt.get("day_move_pct", 0) or 0)
    spot     = float(rt.get("spot", 0) or 0)

    # ── Signal 1: Opening range confirmed (20 pts) ────────────────────────
    # Market needs at least 60 min to establish a trend / flush opening orders
    _or_time = _parse_hhmm(trading.get("opening_range_confirmed_time", "10:15"), "10:15")
    if now.time() >= _or_time:
        score += 20
        signals.append(f"✅ Opening range confirmed (>{_or_time.strftime('%H:%M')} IST)")
    else:
        signals.append(f"❌ Too early — opening range not confirmed yet (wait till {_or_time.strftime('%H:%M')})")

    # ── Signal 2: Directional clarity (15 pts) ───────────────────────────
    # Context matters:
    #   - BUYERS need clear direction (strong move confirms their bet)
    #   - SELLERS (credit spreads) actually PREFER flat/ranging markets — no move = full profit
    # Determine likely strategy type from VIX + PCR to adjust scoring.
    _seller_mode = (vix < 18) and (0.7 <= pcr <= 1.3)  # flat VIX + neutral PCR = seller market

    if _seller_mode:
        # For sellers: flat market is ideal (15 pts), strong move is risky (fewer pts)
        if abs(day_move) < 0.20:
            score += 15
            signals.append(f"✅ Flat/ranging market ({day_move:+.2f}%) — ideal for credit sellers")
        elif abs(day_move) < 0.40:
            score += 10
            signals.append(f"🟡 Mild move ({day_move:+.2f}%) — OK for sellers, watch direction")
        elif abs(day_move) < 0.80:
            score += 5
            signals.append(f"⚠️ Moderate move ({day_move:+.2f}%) — credit spread strikes may be tested")
        else:
            score += 2
            signals.append(f"❌ Strong move ({day_move:+.2f}%) — high risk for credit sellers")
    else:
        # For buyers: need clear directional move
        if abs(day_move) >= 0.40:
            score += 15
            signals.append(f"✅ Strong direction ({'bearish' if day_move < 0 else 'bullish'}: {day_move:+.2f}%)")
        elif abs(day_move) >= 0.20:
            score += 8
            signals.append(f"🟡 Mild direction ({day_move:+.2f}%) — moderate confidence")
        elif abs(day_move) >= 0.10:
            score += 3
            signals.append(f"⚠️ Weak direction ({day_move:+.2f}%) — choppy conditions")
        else:
            signals.append(f"❌ No direction ({day_move:+.2f}%) — flat/indecisive market")

    # ── Signal 3: VIX sweet spot (20 pts) ────────────────────────────────
    # 11–18 = normal; >20 = panic (risky for sellers); <10 = complacent (premiums too thin)
    if 11 <= vix <= 18:
        score += 20
        signals.append(f"✅ VIX in optimal range ({vix:.1f})")
    elif 18 < vix <= 22:
        score += 10
        signals.append(f"🟡 VIX slightly elevated ({vix:.1f}) — wider spreads needed")
    elif vix > 22:
        score += 3
        signals.append(f"❌ VIX too high ({vix:.1f}) — dangerous for sellers")
    elif vix > 0:
        score += 8
        signals.append(f"🟡 VIX very low ({vix:.1f}) — premiums thin, buyer edge poor")
    else:
        score += 10   # VIX unavailable — don't penalise heavily
        signals.append("⚠️ VIX unavailable — assuming neutral")

    # ── Signal 4: PCR alignment with day bias (15 pts) ───────────────────
    # PCR < 0.8 = bearish (more CE writing); PCR > 1.2 = bullish (more PE writing)
    # Best when PCR direction matches day_move direction
    if pcr < 0.8 and day_move < 0:
        score += 15
        signals.append(f"✅ PCR confirms bearish bias (PCR={pcr:.2f}, move={day_move:+.2f}%)")
    elif pcr > 1.2 and day_move > 0:
        score += 15
        signals.append(f"✅ PCR confirms bullish bias (PCR={pcr:.2f}, move={day_move:+.2f}%)")
    elif 0.8 <= pcr <= 1.2:
        score += 8
        signals.append(f"🟡 PCR neutral ({pcr:.2f}) — market indecision")
    else:
        score += 5
        signals.append(f"⚠️ PCR diverges from price ({pcr:.2f}, move={day_move:+.2f}%)")

    # ── Signal 5: Move not extended vs ATR (15 pts) ───────────────────────
    # Don't enter when price has already moved >60% of expected daily range
    # (chasing extended moves = high reversal risk)
    if not hist.empty and spot > 0:
        try:
            _prev = hist["close"].shift(1).fillna(hist["close"])
            _tr   = ((hist["high"] - hist["low"])
                     .combine((hist["high"] - _prev).abs(), max)
                     .combine((hist["low"]  - _prev).abs(), max))
            _atr  = float(_tr.rolling(14, min_periods=1).mean().iloc[-1])
            _prev_close = float(hist["close"].iloc[-2]) if len(hist) > 1 else spot
            _move_pts   = abs(spot - _prev_close)
            _pct_of_atr = _move_pts / _atr if _atr > 0 else 0

            if _pct_of_atr < 0.40:
                score += 15
                signals.append(f"✅ Move not extended ({_move_pts:.0f} pts = {_pct_of_atr*100:.0f}% of ATR)")
            elif _pct_of_atr < 0.65:
                score += 8
                signals.append(f"🟡 Moderately extended ({_pct_of_atr*100:.0f}% of ATR)")
            elif _pct_of_atr < 0.85:
                score += 3
                signals.append(f"⚠️ Extended move ({_pct_of_atr*100:.0f}% of ATR) — reversal risk")
            else:
                signals.append(f"❌ Overextended ({_pct_of_atr*100:.0f}% of ATR) — do NOT chase")
        except Exception:
            score += 8
            signals.append("⚠️ ATR check failed — skipping extension check")
    else:
        score += 8
        signals.append("⚠️ History unavailable — skipping extension check")

    # ── Signal 6: ATM straddle premium adequate (15 pts) ─────────────────
    # Minimum premium ensures strategies can collect meaningful credit
    # and that bid-ask spread isn't too wide relative to profit target
    if not oc.empty and spot > 0:
        try:
            _atm   = int(round(spot / 50) * 50)
            _row   = oc[oc["strike"] == _atm]
            if not _row.empty:
                _ce = float(_row["CE_LTP"].iloc[0])
                _pe = float(_row["PE_LTP"].iloc[0])
                _straddle = _ce + _pe
                min_straddle = float(trading.get("min_atm_straddle", 40))
                if _straddle >= min_straddle * 1.5:
                    score += 15
                    signals.append(f"✅ Rich premium (ATM straddle ₹{_straddle:.0f})")
                elif _straddle >= min_straddle:
                    score += 8
                    signals.append(f"🟡 Adequate premium (ATM straddle ₹{_straddle:.0f})")
                else:
                    signals.append(f"❌ Thin premium (ATM straddle ₹{_straddle:.0f} < ₹{min_straddle:.0f} min)")
            else:
                score += 8
                signals.append("⚠️ ATM row not found in option chain")
        except Exception:
            score += 8
            signals.append("⚠️ Premium check failed")
    else:
        score += 8
        signals.append("⚠️ Option chain unavailable — skipping premium check")

    # ── Grade & decision ─────────────────────────────────────────────────
    grade = "F"
    if score >= 80:   grade = "A"
    elif score >= 65: grade = "B"
    elif score >= 50: grade = "C"
    elif score >= 35: grade = "D"

    should_enter = score >= min_score
    reason = None if should_enter else (
        f"LOW_OPPORTUNITY_SCORE({score}/{min_score}) — "
        + "; ".join(s for s in signals if s.startswith(("❌", "⚠️")))
    )

    return {
        "score":        score,
        "max_score":    100,
        "grade":        grade,
        "signals":      signals,
        "should_enter": should_enter,
        "min_score":    min_score,
        "reason":       reason,
    }


def _count_today_entries() -> int:
    if not JOURNAL_PATH.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    n = 0
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") == "auto_entry" and str(rec.get("ts_utc", "")).startswith(today):
            n += 1
    return n


def _last_loss_exit_dt() -> Optional[datetime]:
    """Most recent losing auto_exit today (for cool-off)."""
    if not JOURNAL_PATH.exists():
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    latest = None
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") == "auto_exit" and str(rec.get("ts_utc", "")).startswith(today):
            if float(rec.get("pnl_inr", 0) or 0) < 0:
                try:
                    _dt = datetime.fromisoformat(str(rec.get("ts_utc")).replace("Z", "+00:00"))
                    # Normalize to naive local datetime for comparison with datetime.now()
                    if _dt.tzinfo is not None:
                        from datetime import timezone
                        _dt = _dt.astimezone(timezone.utc).replace(tzinfo=None)
                    latest = _dt
                except Exception:
                    pass
    return latest


def _last_exit_dt() -> Optional[datetime]:
    """Most recent auto_exit today (any outcome) — for the re-entry cooldown."""
    if not JOURNAL_PATH.exists():
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    latest = None
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") == "auto_exit" and str(rec.get("ts_utc", "")).startswith(today):
            try:
                _dt = datetime.fromisoformat(str(rec.get("ts_utc")).replace("Z", "+00:00"))
                if _dt.tzinfo is not None:
                    from datetime import timezone
                    _dt = _dt.astimezone(timezone.utc).replace(tzinfo=None)
                if latest is None or _dt > latest:
                    latest = _dt
            except Exception:
                pass
    return latest


class AlgoAutoTrader:
    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or load_algo_config()
        # Process start time — used for the startup grace guard so that merely
        # (re)starting the service does not trigger an immediate entry.
        self._started_at = datetime.now()

    # ── helpers ──
    def _broker(self) -> str:
        return self.cfg.get("active_broker", "Groww")

    def _legs(self) -> List[Dict]:
        trading = self.cfg.get("trading", {})
        legs = trading.get("legs") or []
        if legs:
            return legs
        return build_legs(trading.get("strategy", ""), trading.get("strikes", {}))

    def _adapter(self):
        cfg = self.cfg
        broker = self._broker()
        creds = resolve_broker_creds(cfg, broker)
        controls = cfg.get("controls", {})
        allow_live = bool(controls.get("allow_live")) and not bool(controls.get("dry_run", True))
        return get_live_broker_adapter(
            broker,
            api_key=creds["api_key"],
            api_secret=creds["api_secret"],
            access_token=creds["access_token"],
            allow_live=allow_live,
        )

    def _position_id(self) -> str:
        t = self.cfg.get("trading", {})
        today = datetime.now().strftime("%Y%m%d")
        return f"algo_{t.get('symbol','NIFTY')}_{t.get('strategy','strat')}_{today}".replace(" ", "_")

    # ── main tick ──
    def tick(self) -> Dict:
        self.cfg = load_algo_config()
        cfg = self.cfg
        controls = cfg.get("controls", {})
        trading = cfg.get("trading", {})
        risk = cfg.get("risk", {})
        now = datetime.now()
        result: Dict = {"ts": now.isoformat(), "action": "idle"}

        if not controls.get("armed"):
            result["reason"] = "not_armed"
            return result

        legs = self._legs()
        if trading.get("selection_mode", "manual") != "auto_winner":
            if not legs or any(int(l.get("strike", 0) or 0) <= 0 for l in legs):
                result.update({"action": "error", "reason": "legs_not_configured"})
                return result

        symbol = trading.get("symbol", "NIFTY")
        lots = min(int(trading.get("lots", 1)), int(risk.get("max_lots_per_trade", 5) or 5))
        lot_size = int(trading.get("lot_size", 65))
        units = lots * lot_size

        # 1) Real-time data refresh.
        use_snapshot = bool(trading.get("value_from_snapshot", False))
        rt = refresh_realtime(symbol, return_snapshot=use_snapshot)
        result["realtime"] = {k: rt.get(k) for k in ("ok", "spot", "day_move_pct", "vix", "pcr")}
        # Fail-safe: if the feed failed, treat data as stale. Do NOT silently assume
        # day_move=0 for decisions -- block new entries and (optionally) protect open ones.
        data_stale = not bool(rt.get("ok"))
        result["data_stale"] = data_stale
        if data_stale:
            result["data_stale_reason"] = rt.get("message", "realtime_fetch_failed")
        day_move = float(rt.get("day_move_pct", 0) or 0) if not data_stale else 0.0
        snap = rt.get("snapshot") if use_snapshot else None

        # 2) Load valuation data.
        try:
            _hist, oc, _pcr, _vix, _ocjson = load_morning_data()
        except Exception as exc:
            result.update({"action": "error", "reason": f"market_data_error: {exc}"})
            return result

        adapter = self._adapter()
        use_broker = bool(trading.get("value_from_broker", False))

        # Derive expiry dynamically: always use the real NIFTY Thursday expiry,
        # not the OC CSV date which defaults to today for the generic filename.
        expiry = _nifty_weekly_expiry().isoformat()
        result["expiry"] = expiry

        def _value_from_broker(leg_list):
            """Value legs from broker live LTP; None if unavailable (e.g. dry-run)."""
            try:
                res = adapter.get_leg_ltps(symbol, expiry, leg_list)
            except Exception:
                return None
            if not res.get("ok"):
                return None
            ltps = res.get("ltps", {})
            short_sum = 0.0
            long_sum = 0.0
            for leg in leg_list:
                key = f"{int(leg.get('strike', 0) or 0)}{str(leg.get('option_type', '')).upper()}"
                ltp = ltps.get(key)
                if ltp is None or float(ltp) <= 0:
                    return None
                if str(leg.get("action", "")).upper() == "SELL":
                    short_sum += float(ltp)
                else:
                    long_sum += float(ltp)
            return round(short_sum - long_sum, 2)

        def _value(leg_list):
            """Value legs: broker LTP > in-memory snapshot > shared-CSV (in priority)."""
            if use_broker:
                val = _value_from_broker(leg_list)
                if val is not None:
                    return val
            if use_snapshot and snap:
                val = value_legs_from_snapshot(snap, leg_list)
                if val is not None:
                    return val
            return _position_value(leg_list, oc)

        cur_val = _value(legs)
        realized = _today_realized_pnl()
        result["realized_pnl"] = realized

        positions = load_live_positions()
        pid = self._position_id()
        pos = positions.get(pid)

        # ── ROBUST PID RESOLUTION ──────────────────────────────────────────
        # In auto_winner mode the config strategy (used by _position_id) may
        # differ from the actually-selected strategy, so the pid lookup above
        # returns None even when a position IS open.
        # Fall back to scanning all positions for any OPEN one from today.
        if pos is None:
            today_str = now.strftime("%Y%m%d")
            for _scan_pid, _scan_pos in positions.items():
                if (_scan_pid.endswith(f"_{today_str}")
                        and _scan_pos.get("status") == "open"):
                    pos = _scan_pos
                    pid = _scan_pid
                    break

        # Reconcile stale carry-forward open positions from prior dates.
        # These can block new entries if a previous session did not clean up state.
        stale_reconciled: List[str] = []
        reconcile_stale = bool(controls.get("stale_reconciliation_enabled", True))
        if reconcile_stale:
            for stale_pid, stale_pos in list(positions.items()):
                if stale_pos.get("status") != "open":
                    continue
                entry_time_raw = str(stale_pos.get("entry_time", "") or "")
                if not entry_time_raw:
                    continue
                try:
                    entry_dt = datetime.fromisoformat(entry_time_raw)
                except Exception:
                    continue
                if entry_dt.date() >= now.date():
                    continue

                stale_symbol = str(stale_pos.get("symbol") or symbol)
                stale_strategy = str(stale_pos.get("strategy") or "")
                sq = adapter.square_off_all(stale_symbol, stale_strategy)

                upsert_live_position(stale_pid, {
                    "status": "closed",
                    "exit_time": now.isoformat(),
                    "exit_trigger": "STALE_CARRYFORWARD",
                    "exit_value": stale_pos.get("entry_value"),
                    "pnl_inr": stale_pos.get("pnl_inr", 0),
                })
                remove_live_position(stale_pid)
                append_journal_event({
                    "event": "auto_exit",
                    "position_id": stale_pid,
                    "symbol": stale_symbol,
                    "strategy": stale_strategy,
                    "trigger": "STALE_CARRYFORWARD",
                    "entry_value": stale_pos.get("entry_value", 0),
                    "exit_value": stale_pos.get("entry_value", 0),
                    "pnl_inr": stale_pos.get("pnl_inr", 0),
                    "minutes_open": None,
                    "day_move_pct": day_move,
                    "dry_run": bool(controls.get("dry_run", True)),
                    "squareoff": sq,
                })
                stale_reconciled.append(stale_pid)

        if stale_reconciled:
            positions = load_live_positions()
            if pid in stale_reconciled:
                pos = None
            result["stale_positions_reconciled"] = stale_reconciled

        # ── Circuit breakers ──
        crash = float(risk.get("crash_guard_pct", 0) or 0) > 0 and day_move <= -abs(float(risk["crash_guard_pct"]))
        rally = float(risk.get("rally_guard_pct", 0) or 0) > 0 and day_move >= abs(float(risk["rally_guard_pct"]))
        daily_loss_hit = float(risk.get("daily_max_loss_inr", 0) or 0) > 0 and realized <= -abs(float(risk["daily_max_loss_inr"]))
        daily_profit_hit = float(risk.get("daily_profit_target_inr", 0) or 0) > 0 and realized >= abs(float(risk["daily_profit_target_inr"]))
        hard_sq_time = _parse_hhmm(trading.get("hard_squareoff_time", "15:20"), "15:20")
        past_squareoff = now.time() >= hard_sq_time

        # ── MANAGE OPEN POSITION ──
        if pos and pos.get("status") == "open":
            pos_legs = pos.get("legs") or legs
            cur_val = _value(pos_legs)
            if cur_val is None:
                result.update({"action": "hold", "reason": "valuation_unavailable"})
                return result
            units_pos = int(pos.get("units_per_leg", units) or units)
            pos_strategy = pos.get("strategy") or trading.get("strategy", "")
            entry_val = float(pos.get("entry_value", 0) or 0)
            pnl = round((entry_val - cur_val) * units_pos, 2)
            mins = None
            try:
                mins = int((now - datetime.fromisoformat(pos.get("entry_time"))).total_seconds() // 60)
            except Exception:
                mins = None

            # Compute effective time-exit threshold from the SAVED strategy type:
            # buyers: cap at 120 min (theta destroys value fast)
            # credit sellers: minimum 240 min (theta IS the profit)
            _base_te = int(risk.get("time_exit_minutes", 180) or 180)
            if pos_strategy in ("OptionBuyer", "Institutional"):
                _eff_te = min(_base_te, 120)
            elif pos_strategy in ("Hedging", "OptionSeller", "Iron Condor (Defined Risk)",
                                  "Bull Put Spread", "Bear Call Spread", "Short Strangle"):
                _eff_te = max(_base_te, 240)
            else:
                _eff_te = _base_te

            trigger = None
            if float(risk.get("target_profit_inr", 0) or 0) > 0 and pnl >= float(risk["target_profit_inr"]):
                trigger = "TARGET_PROFIT"
            elif float(risk.get("per_trade_max_loss_inr", 0) or 0) > 0 and pnl <= -abs(float(risk["per_trade_max_loss_inr"])):
                trigger = "MAX_LOSS"
            elif mins is not None and _eff_te > 0 and mins >= _eff_te:
                trigger = "TIME_EXIT"
            elif past_squareoff:
                trigger = "HARD_SQUAREOFF"
            elif daily_loss_hit:
                trigger = "DAILY_LOSS_CUTOFF"
            elif daily_profit_hit:
                trigger = "DAILY_PROFIT_LOCK"
            elif data_stale and bool(risk.get("exit_on_stale_data", False)):
                trigger = "STALE_DATA_GUARD"
            elif risk.get("exit_on_guard_breach", True) and (crash or rally):
                trigger = "CRASH_GUARD" if crash else "RALLY_GUARD"

            if trigger:
                sq = adapter.square_off_all(symbol, pos_strategy)
                upsert_live_position(pid, {
                    "status": "closed", "exit_value": cur_val,
                    "exit_time": now.isoformat(), "pnl_inr": pnl, "exit_trigger": trigger,
                })
                remove_live_position(pid)
                append_journal_event({
                    "event": "auto_exit", "position_id": pid, "symbol": symbol,
                    "strategy": pos_strategy, "trigger": trigger,
                    "entry_value": entry_val, "exit_value": cur_val, "pnl_inr": pnl,
                    "minutes_open": mins, "day_move_pct": day_move,
                    "dry_run": bool(controls.get("dry_run", True)), "squareoff": sq,
                })
                result.update({"action": "exit", "trigger": trigger, "pnl_inr": pnl})
                return result

            append_journal_event({
                "event": "auto_mark_to_market",
                "position_id": pid,
                "symbol": symbol,
                "strategy": pos_strategy,
                "current_value": cur_val,
                "entry_value": entry_val,
                "pnl_inr": pnl,
                "minutes_open": mins,
                "day_move_pct": day_move,
                "dry_run": bool(controls.get("dry_run", True)),
            })

            result.update({"action": "hold", "pnl_inr": pnl, "current_value": cur_val, "minutes_open": mins})
            if data_stale:
                result["warning"] = "data_stale: crash/rally guard blind this tick"
            return result

        # ── NO OPEN POSITION -> consider entry ──
        # Entry blockers (ordered).
        if data_stale:
            # Never open a new position on a failed/stale data feed.
            result.update({"action": "blocked", "reason": "data_stale_no_entry"}); return result
        if daily_loss_hit:
            result.update({"action": "halted", "reason": "daily_max_loss_reached"}); return result
        if daily_profit_hit:
            result.update({"action": "halted", "reason": "daily_profit_target_reached"}); return result
        if past_squareoff:
            result.update({"action": "idle", "reason": "past_hard_squareoff_time"}); return result
        if crash or rally:
            result.update({"action": "blocked", "reason": "crash_guard" if crash else "rally_guard", "day_move_pct": day_move}); return result
        if float(risk.get("gap_guard_pct", 0) or 0) > 0 and abs(day_move) >= abs(float(risk["gap_guard_pct"])) and _count_today_entries() == 0:
            # Large open-move before first trade = skip (treated as gap risk).
            result.update({"action": "blocked", "reason": "gap_guard", "day_move_pct": day_move}); return result

        win_start = _parse_hhmm(trading.get("trade_window_start", "09:20"), "09:20")
        win_end = _parse_hhmm(trading.get("trade_window_end", "15:20"), "15:20")
        if not (win_start <= now.time() <= win_end):
            result.update({"action": "idle", "reason": "outside_trade_window"}); return result

        # Startup grace: merely (re)starting the service must NOT trigger an instant
        # entry. Skip new entries for the first N seconds so at least one fresh data
        # cycle + opportunity re-evaluation happens before committing capital.
        _grace_sec = int(trading.get("startup_grace_sec", 120) or 0)
        if _grace_sec > 0:
            _since_start = (now - self._started_at).total_seconds()
            if _since_start < _grace_sec:
                result.update({"action": "idle",
                               "reason": f"startup_grace: warming_up ({int(_since_start)}s < {_grace_sec}s)"})
                return result

        # Re-entry cooldown: wait N min after ANY exit today before opening a fresh
        # position. Prevents same-day churn (exit → immediate re-enter for a few min).
        _reentry_min = int(trading.get("reentry_cooldown_min", 20) or 0)
        if _reentry_min > 0:
            _last_exit = _last_exit_dt()
            if _last_exit and (now - _last_exit).total_seconds() < _reentry_min * 60:
                result.update({"action": "cooloff",
                               "reason": f"reentry_cooldown: waiting {_reentry_min}min after last exit"})
                return result

        # Block new entries within N min of hard-squareoff (too little time for credit strategies to profit)
        _entry_cutoff_min = int(trading.get("entry_cutoff_before_squareoff_min", 45) or 45)
        _cutoff_dt = (datetime.combine(now.date(), hard_sq_time)
                      - __import__("datetime").timedelta(minutes=_entry_cutoff_min))
        if now.time() >= _cutoff_dt.time():
            result.update({"action": "idle",
                           "reason": f"entry_cutoff: too_close_to_squareoff (< {_entry_cutoff_min} min)"})
            return result

        if _count_today_entries() >= int(risk.get("max_orders_per_day", 6) or 6):
            result.update({"action": "halted", "reason": "max_orders_per_day_reached"}); return result

        # Count only currently-open positions toward the cap.
        open_count = sum(1 for p in positions.values() if p.get("status") == "open")
        if open_count >= int(risk.get("max_open_positions", 1) or 1):
            result.update({"action": "idle", "reason": "max_open_positions_reached"}); return result

        # Race-condition guard: re-read positions immediately before placing order.
        # Prevents duplicate entries when two loop instances run simultaneously.
        _fresh_positions = load_live_positions()
        _fresh_open = sum(1 for p in _fresh_positions.values() if p.get("status") == "open")
        if _fresh_open >= int(risk.get("max_open_positions", 1) or 1):
            result.update({"action": "idle", "reason": "max_open_positions_reached_recheck"}); return result

        # Cool-off after a losing exit.
        cool = int(risk.get("cooloff_after_loss_min", 0) or 0)
        if cool > 0:
            last_loss = _last_loss_exit_dt()
            if last_loss and (now - last_loss).total_seconds() < cool * 60:
                result.update({"action": "cooloff", "reason": "cooling_off_after_loss"}); return result

        # ── Opportunity quality gate ──────────────────────────────────────
        # Evaluate 6 market signals (time, direction, VIX, PCR, extension, premium).
        # Only enter when the combined score >= min_opportunity_score (default 55/100).
        opp = _evaluate_opportunity(rt, oc, _hist, cfg, now)
        result["opportunity"] = {
            "score": opp["score"],
            "grade": opp["grade"],
            "signals": opp["signals"],
        }
        if not opp["should_enter"]:
            result.update({"action": "no_trade", "reason": opp["reason"]}); return result

        # ── Strategy selection ──
        selection_mode = trading.get("selection_mode", "manual")
        entry_strategy = trading.get("strategy", "")
        entry_legs = legs
        selection_info = None
        if selection_mode == "auto_winner":
            from src.strategy_selector import recommend, idea_to_legs
            # Momentum hint: on a strong, PCR-confirmed trend day, prefer a directional
            # buyer aligned with the trend over a neutral seller (sellers underperform
            # when the market trends hard).
            _mom = None
            if bool(trading.get("momentum_selection_enabled", True)):
                _pcr_now = float(rt.get("pcr", 0) or 0)
                _mv = float(rt.get("day_move_pct", 0) or 0)
                _mv_th = float(trading.get("momentum_trend_move_pct", 0.50) or 0.50)
                _strong = abs(_mv) >= _mv_th and (
                    (_mv < 0 and 0 < _pcr_now < 0.8) or (_mv > 0 and _pcr_now > 1.2)
                )
                if _strong:
                    _mom = {"strong_trend": True,
                            "direction": "bearish" if _mv < 0 else "bullish"}
            rec = recommend(trading.get("enabled_strategies") or None, momentum=_mom)
            selection_info = {"recommended": rec.get("recommended"), "message": rec.get("message")}
            result["selection"] = selection_info
            if not rec.get("ok") or not rec.get("recommended"):
                result.update({"action": "no_trade", "reason": rec.get("message", "no_smart_win_candidate")})
                return result
            idea = rec.get("recommended_idea", {})
            entry_strategy = rec.get("recommended")
            # Pre-entry regime guard: block buyer strategies in neutral market
            idea_skip = idea.get("skip_reason")
            if idea_skip:
                result.update({"action": "no_trade", "reason": f"strategy_skipped: {idea_skip}"})
                return result
            # Pre-entry regime guards based on live PCR + VIX
            pcr_val = float(rt.get("pcr", 0) or 0)
            vix_val = float(rt.get("vix", 0) or 0)

            # Guard 1: Block OptionBuyer/Institutional in neutral market (PCR 0.8-1.2, VIX<16)
            if entry_strategy in ("OptionBuyer", "Institutional") and 0.8 <= pcr_val <= 1.2 and vix_val < 16:
                result.update({"action": "no_trade",
                               "reason": f"regime_mismatch: {entry_strategy} skipped in neutral PCR={pcr_val:.2f}/VIX={vix_val:.1f}"})
                return result

            # Guard 2: VIX override — when VIX>20 force premium-selling strategies only
            if vix_val > 20 and entry_strategy in ("OptionBuyer", "Institutional"):
                result.update({"action": "no_trade",
                               "reason": f"vix_override: {entry_strategy} blocked at VIX={vix_val:.1f}>20; prefer sellers"})
                return result
            entry_legs = idea_to_legs(idea)
            if not entry_legs:
                result.update({"action": "no_trade", "reason": "idea_not_mappable_to_legs"})
                return result
            cur_val = _value(entry_legs)
            pid = f"algo_{symbol}_{entry_strategy}_{now.strftime('%Y%m%d')}".replace(" ", "_")

            # ── BUG FIX: re-check the auto_winner pid BEFORE entering ──────────
            # _position_id() above used the config's strategy (not the auto-selected one).
            # After resolving the real strategy, check if this specific position is already open.
            _existing = positions.get(pid)
            if _existing and _existing.get("status") == "open":
                units_e = int(_existing.get("units_per_leg", units) or units)
                entry_v = float(_existing.get("entry_value", 0) or 0)
                pnl_e   = round((entry_v - (_value(_existing.get("legs") or entry_legs) or entry_v)) * units_e, 2)
                result.update({"action": "hold", "pnl_inr": pnl_e, "reason": "auto_winner_position_already_open"})
                return result

        if cur_val is None:
            result.update({"action": "wait_entry", "reason": "entry_valuation_unavailable"}); return result

        # Capital / margin cap.
        try:
            margin = adapter.estimate_margin_proxy(
                entry_strategy, entry_legs, lot_size, lots, abs(cur_val))
            est_amount = float(margin.get("proxy_margin", 0) or 0)
        except Exception:
            est_amount = abs(cur_val) * units
        if float(risk.get("max_trade_amount_inr", 0) or 0) > 0 and est_amount > float(risk["max_trade_amount_inr"]):
            result.update({"action": "blocked", "reason": "trade_amount_exceeds_cap", "est_amount": est_amount})
            return result

        # Auto-regenerate token if going live without one.
        controls_live = bool(controls.get("allow_live")) and not bool(controls.get("dry_run", True))
        if controls_live and controls.get("auto_regenerate_token", True):
            creds = resolve_broker_creds(cfg, self._broker())
            if not creds.get("access_token"):
                tok = regenerate_token(self._broker(), allow_live=True, cfg=cfg)
                result["token_regen"] = tok.get("message")
                self.cfg = cfg = load_algo_config()
                adapter = self._adapter()

        # Time-exit logic differs by strategy type:
        # - Buyers (long premium): exit fast, theta decay destroys value → cap at 120 min
        # - Sellers/Hedging (credit spreads): time HELPS them, theta decay is profit → min 240 min
        #   These strategies rely on HARD_SQUAREOFF (15:20) or MAX_LOSS as primary exits.
        base_time_exit = int(risk.get("time_exit_minutes", 180) or 180)
        if entry_strategy in ("OptionBuyer", "Institutional"):
            effective_time_exit = min(base_time_exit, 120)   # cap at 120 min for buyers
        elif entry_strategy in ("Hedging", "OptionSeller", "Iron Condor (Defined Risk)",
                                 "Bull Put Spread", "Bear Call Spread", "Short Strangle"):
            effective_time_exit = max(base_time_exit, 240)   # minimum 240 min for credit sellers
        else:
            effective_time_exit = base_time_exit

        # ── GUARD: Block BUYER strategies on expiry day (gamma crushes premium) ──
        # Expiry date is read from the option-chain feed (source of truth), else weekday fallback.
        _is_expiry_day = _is_nifty_expiry_day()
        _buyer_strategies = {"OptionBuyer", "Institutional", "Agent-Institutional"}
        if _is_expiry_day and entry_strategy in _buyer_strategies:
            result.update({"action": "no_trade",
                           "reason": f"expiry_day_guard: {entry_strategy} blocked on expiry ({expiry}). Use seller strategies instead."})
            return result

        req = StartAlgoRequest(
            broker=self._broker(), symbol=symbol, strategy=entry_strategy,
            lots=lots, lot_size=lot_size,
            expiry=expiry,
            legs=entry_legs, stop_loss=float(risk.get("per_trade_max_loss_inr", 0) or 0),
            target=float(risk.get("target_profit_inr", 0) or 0),
            time_exit_minutes=effective_time_exit,
            daily_max_loss_inr=float(risk.get("daily_max_loss_inr", 0) or 0),
        )
        placed = adapter.place_basket_order(req, dry_run=bool(controls.get("dry_run", True)))
        if not placed.get("ok"):
            append_journal_event({
                "event": "auto_entry_failed", "position_id": pid, "symbol": symbol,
                "strategy": entry_strategy, "reason": placed.get("message"),
            })
            result.update({"action": "entry_failed", "reason": placed.get("message")})
            return result

        upsert_live_position(pid, {
            "broker": self._broker(), "symbol": symbol, "strategy": entry_strategy,
            "lots": lots, "units_per_leg": units, "expiry": expiry,
            "legs": entry_legs, "entry_value": cur_val, "entry_time": now.isoformat(),
            "status": "open", "dry_run": bool(controls.get("dry_run", True)),
            "intent_id": placed.get("intent_id"), "leg_refs": placed.get("leg_refs", []),
            "est_amount": est_amount, "selection_mode": selection_mode,
        })
        append_journal_event({
            "event": "auto_entry", "position_id": pid, "symbol": symbol,
            "strategy": entry_strategy, "entry_value": cur_val, "lots": lots,
            "units_per_leg": units, "est_amount": est_amount, "day_move_pct": day_move,
            "selection_mode": selection_mode,
            "dry_run": bool(controls.get("dry_run", True)), "intent_id": placed.get("intent_id"),
        })
        result.update({"action": "entry", "strategy": entry_strategy, "entry_value": cur_val,
                       "intent_id": placed.get("intent_id"), "est_amount": est_amount})
        return result

    def run_forever(self, interval_sec: Optional[int] = None):
        interval = int(interval_sec or self.cfg.get("trading", {}).get("poll_interval_sec", 30) or 30)
        logger.info("Algo auto-trader started (interval=%ss).", interval)
        while True:
            try:
                res = self.tick()
                logger.info("tick: %s", {k: v for k, v in res.items() if k not in ("squareoff",)})
            except Exception as exc:
                logger.exception("tick error: %s", exc)
            time.sleep(max(5, interval))


def main():
    ap = argparse.ArgumentParser(description="Unified automated algo-trader")
    ap.add_argument("--once", action="store_true", help="Run a single tick and exit.")
    ap.add_argument("--loop", action="store_true", help="Run continuously.")
    ap.add_argument("--interval", type=int, default=0, help="Override poll interval seconds.")
    args = ap.parse_args()

    trader = AlgoAutoTrader()
    if args.loop:
        trader.run_forever(args.interval or None)
    else:
        print(json.dumps(trader.tick(), indent=2, default=str))


if __name__ == "__main__":
    main()
