"""
src/trade_tracker.py — Paper-Trade Journal & P&L Tracker
=========================================================

Stores every logged trade to  data/trade_journal.json  and provides:

  • add_trade(...)       — log a new paper trade
  • load_trades()        — return all trades as a list of dicts
  • update_all_open(...) — recalculate P&L against latest chain/futures data
                           and generate HOLD / EXIT / REVERSE suggestions
  • close_trade(...)     — mark a trade closed with exit price & final P&L
  • get_history_df()     — return trade history as a tidy DataFrame

No brokers, no real orders. All P&L is hypothetical.

Daily workflow
--------------
Morning   : upload 3 files → Final Trade Decision tab → click "Log Trade"
After 2-3h: upload updated files → Trade Journal tab auto-recalculates P&L
End of day: Trade History section shows all trades with final status
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re

import pandas as pd

logger = logging.getLogger("market_study_tool.trade_tracker")

JOURNAL_PATH = Path("data/trade_journal.json")

# ---------------------------------------------------------------------------
# Risk controls for sudden market changes (paper-trade approximation)
# ---------------------------------------------------------------------------
GAP_SHOCK_PCT = 1.2
BASE_STOP_SLIPPAGE_PCT = 0.20
EXTRA_SLIPPAGE_PER_GAP_PCT = 0.25
MAX_STOP_SLIPPAGE_PCT = 3.00
TRAILING_LOCK_PCT = 0.35
TRAILING_ACTIVATION_PCT_TO_TARGET = 40
DAILY_MAX_LOSS_INR = -15000


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_raw() -> List[dict]:
    """Load trades from JSON file. Returns [] if file is missing or corrupt."""
    if not JOURNAL_PATH.exists():
        return []
    try:
        with open(JOURNAL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        logger.warning("Trade journal corrupt or unreadable — starting fresh.")
        return []


def _save_raw(trades: List[dict]) -> None:
    JOURNAL_PATH.parent.mkdir(exist_ok=True)
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, default=str)


def _is_today_trade(trade: dict, today_str: str) -> bool:
    ts = str(trade.get("timestamp", "")).strip()
    return ts.startswith(today_str)


def _calc_gap_info(futures_df: pd.DataFrame) -> dict:
    if futures_df is None or futures_df.empty or len(futures_df) < 2:
        return {"gap_pct": 0.0, "is_shock": False}

    prev_close = float(futures_df["close"].iloc[-2])
    curr_open = float(futures_df["open"].iloc[-1]) if "open" in futures_df.columns else float(futures_df["close"].iloc[-1])
    if prev_close <= 0:
        return {"gap_pct": 0.0, "is_shock": False}

    gap_pct = abs((curr_open - prev_close) / prev_close) * 100
    return {"gap_pct": gap_pct, "is_shock": gap_pct >= GAP_SHOCK_PCT}


def _stop_slippage_pct(gap_pct: float, is_shock: bool) -> float:
    shock_extra = gap_pct * EXTRA_SLIPPAGE_PER_GAP_PCT if is_shock else 0.0
    slip = BASE_STOP_SLIPPAGE_PCT + shock_extra
    return min(slip, MAX_STOP_SLIPPAGE_PCT)


def _apply_stop_slippage(direction: str, sl: float, current_price: float, gap_pct: float, is_shock: bool) -> float:
    slip_pct = _stop_slippage_pct(gap_pct, is_shock) / 100.0
    if direction == "buy":
        # Long option/futures stop can fill lower during fast selloffs.
        slipped = sl * (1.0 - slip_pct)
        return round(min(current_price, slipped), 2)

    # Short stop can fill higher during fast up-moves.
    slipped = sl * (1.0 + slip_pct)
    return round(max(current_price, slipped), 2)


# ---------------------------------------------------------------------------
# Core TradeTracker class
# ---------------------------------------------------------------------------

class TradeTracker:
    """
    Manages the paper-trade journal stored in data/trade_journal.json.

    Each trade record
    -----------------
    id               : Unique ID  (timestamp string)
    timestamp        : When the trade was logged
    symbol           : NIFTY / BANKNIFTY / RELIANCE etc.
    instrument       : "CE" / "PE" / "Futures" / "CE+PE"
    direction        : "buy" / "sell"
    strike           : strike price (int) or futures entry level
    entry_price      : option LTP or futures price at entry
    stop_loss        : initial SL price
    target           : initial target price
    qty_lots         : number of lots
    lot_size         : exchange lot size
    strategy_type    : "Institutional" / "Option Seller"
    regime           : market regime at entry
    structure        : market structure at entry
    reason           : entry reason (string)
    expected_time    : rough time estimate
    margin_approx    : approx margin in ₹
    status           : "Open" / "Closed"
    exit_price       : filled when closed
    pnl_per_lot      : ₹ P&L per lot (filled when closed or updated)
    total_pnl        : ₹ total P&L
    suggestion       : last auto-generated suggestion (HOLD/EXIT/REVERSE)
    suggestion_reason: explanation for the suggestion
    notes            : free-text notes added by user
    """

    def __init__(self, cfg: Optional[dict] = None) -> None:
        JOURNAL_PATH.parent.mkdir(exist_ok=True)
        self._apply_risk_config(cfg or {})

    @staticmethod
    def get_risk_controls() -> dict:
        """Return currently active risk-control values."""
        return {
            "gap_shock_pct": float(GAP_SHOCK_PCT),
            "base_stop_slippage_pct": float(BASE_STOP_SLIPPAGE_PCT),
            "extra_slippage_per_gap_pct": float(EXTRA_SLIPPAGE_PER_GAP_PCT),
            "max_stop_slippage_pct": float(MAX_STOP_SLIPPAGE_PCT),
            "trailing_lock_pct": float(TRAILING_LOCK_PCT),
            "trailing_activation_pct_to_target": float(TRAILING_ACTIVATION_PCT_TO_TARGET),
            "daily_max_loss_inr": float(DAILY_MAX_LOSS_INR),
        }

    def set_risk_controls(self, overrides: dict) -> None:
        """Apply runtime risk-control overrides (does not edit config.yaml)."""
        merged = self.get_risk_controls()
        merged.update(overrides or {})
        self._apply_risk_config({"risk_controls": merged})

    @staticmethod
    def _apply_risk_config(cfg: dict) -> None:
        """Apply optional risk-control overrides from config.yaml."""
        global GAP_SHOCK_PCT
        global BASE_STOP_SLIPPAGE_PCT
        global EXTRA_SLIPPAGE_PER_GAP_PCT
        global MAX_STOP_SLIPPAGE_PCT
        global TRAILING_LOCK_PCT
        global TRAILING_ACTIVATION_PCT_TO_TARGET
        global DAILY_MAX_LOSS_INR

        rc = cfg.get("risk_controls", {}) if isinstance(cfg, dict) else {}
        GAP_SHOCK_PCT = float(rc.get("gap_shock_pct", GAP_SHOCK_PCT))
        BASE_STOP_SLIPPAGE_PCT = float(rc.get("base_stop_slippage_pct", BASE_STOP_SLIPPAGE_PCT))
        EXTRA_SLIPPAGE_PER_GAP_PCT = float(rc.get("extra_slippage_per_gap_pct", EXTRA_SLIPPAGE_PER_GAP_PCT))
        MAX_STOP_SLIPPAGE_PCT = float(rc.get("max_stop_slippage_pct", MAX_STOP_SLIPPAGE_PCT))
        TRAILING_LOCK_PCT = float(rc.get("trailing_lock_pct", TRAILING_LOCK_PCT))
        TRAILING_ACTIVATION_PCT_TO_TARGET = float(
            rc.get("trailing_activation_pct_to_target", TRAILING_ACTIVATION_PCT_TO_TARGET)
        )
        DAILY_MAX_LOSS_INR = float(rc.get("daily_max_loss_inr", DAILY_MAX_LOSS_INR))

    # ------------------------------------------------------------------
    # Add a new trade
    # ------------------------------------------------------------------

    def add_trade(
        self,
        symbol: str,
        instrument: str,
        direction: str,
        strike,
        entry_price: float,
        stop_loss: float,
        target: float,
        qty_lots: int,
        lot_size: int,
        strategy_type: str,
        regime: str,
        structure: str,
        reason: str,
        expected_time: str,
        margin_approx: str = "N/A",
        notes: str = "",
    ) -> str:
        """
        Log a new paper trade. Returns the trade ID.

        All parameters are stored as-is — no validation beyond type coercion.
        """
        trade_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        trade = {
            "id":               trade_id,
            "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol":           symbol,
            "instrument":       instrument,
            "direction":        direction,
            "strike":           strike,
            "entry_price":      float(entry_price),
            "stop_loss":        float(stop_loss),
            "target":           float(target),
            "qty_lots":         int(qty_lots),
            "lot_size":         int(lot_size),
            "strategy_type":    strategy_type,
            "regime":           regime,
            "structure":        structure,
            "reason":           reason,
            "expected_time":    expected_time,
            "margin_approx":    margin_approx,
            "status":           "Open",
            "exit_price":       None,
            "pnl_per_lot":      None,
            "total_pnl":        None,
            "suggestion":       "HOLD",
            "suggestion_reason":"Trade just entered — monitor for first checkpoint.",
            "notes":            notes,
        }
        trades = _load_raw()
        trades.append(trade)
        _save_raw(trades)
        logger.info("Trade logged: %s | %s | %s | ₹%.2f", trade_id, symbol, instrument, entry_price)
        return trade_id

    # ------------------------------------------------------------------
    # Load & query
    # ------------------------------------------------------------------

    def load_trades(self, symbol_filter: Optional[str] = None) -> List[dict]:
        """Return all trades, optionally filtered by symbol."""
        trades = _load_raw()
        if symbol_filter:
            trades = [t for t in trades if t.get("symbol") == symbol_filter]
        return trades

    def get_open_trades(self, symbol: Optional[str] = None) -> List[dict]:
        """Return only open (active) trades."""
        return [t for t in self.load_trades(symbol) if t.get("status") == "Open"]

    def get_history_df(self, symbol: Optional[str] = None) -> pd.DataFrame:
        """Return all trades as a tidy DataFrame."""
        trades = self.load_trades(symbol)
        if not trades:
            return pd.DataFrame()
        df = pd.DataFrame(trades)
        # Human-readable columns for display
        display_cols = [
            "id", "timestamp", "symbol", "instrument", "strike",
            "entry_price", "stop_loss", "target", "qty_lots",
            "strategy_type", "status", "exit_price", "total_pnl",
            "suggestion", "notes",
        ]
        present = [c for c in display_cols if c in df.columns]
        return df[present]

    # ------------------------------------------------------------------
    # Update open trades against current market data
    # ------------------------------------------------------------------

    def update_all_open(
        self,
        chain_df: pd.DataFrame,
        futures_df: pd.DataFrame,
        symbol: Optional[str] = None,
    ) -> List[dict]:
        """
        Recalculate P&L and generate HOLD/EXIT/REVERSE for every open trade.

        Called automatically when new data is loaded in the app.

        Price lookup
        ------------
        • CE/PE trades: look up current LTP from chain_df by strike.
        • CE+PE trades: use combined premium (CE_LTP + PE_LTP) from chain_df.
        • Futures trades: use latest close from futures_df.
        • If option strike is missing in chain_df, trade is skipped for that refresh cycle.

        P&L calculation
        ---------------
        For a BUY trade:  P&L per unit = current_price - entry_price
        For a SELL trade: P&L per unit = entry_price   - current_price
        P&L per lot  = P&L per unit × lot_size
        Total P&L    = P&L per lot   × qty_lots

        Suggestion logic
        ----------------
        • % to target  = (current_pnl_per_unit / (target - entry)) × 100
        • % to SL      = (current_pnl_per_unit / (sl    - entry)) × 100  (sign flipped for sells)
        • EXIT         : ≥ 70% of target reached, or ≥ 90% of SL reached
        • HOLD         : between 0% and 70% of target
        • REVIEW       : P&L between -40% and -90% of SL
        • EXIT (SL)    : ≥ 90% of SL reached — close the position
        • REVERSE      : market structure reversed vs entry (structural opposite)
        """
        trades   = _load_raw()
        updated  = []

        cur_close = float(futures_df["close"].iloc[-1]) if not futures_df.empty else None
        gap_info = _calc_gap_info(futures_df)
        gap_pct = gap_info["gap_pct"]
        is_gap_shock = gap_info["is_shock"]

        today_str = datetime.now().strftime("%Y-%m-%d")
        closed_today_pnl = sum(
            float(t.get("total_pnl") or 0)
            for t in trades
            if t.get("status") == "Closed" and _is_today_trade(t, today_str)
        )
        open_today_running_pnl = 0.0

        for trade in trades:
            if trade.get("status") != "Open":
                updated.append(trade)
                continue

            if symbol and trade.get("symbol") != symbol:
                updated.append(trade)
                continue

            current_price = self._get_current_price(trade, chain_df, cur_close)
            if current_price is None:
                updated.append(trade)
                continue

            entry  = float(trade["entry_price"])
            sl     = float(trade["stop_loss"])
            tgt    = float(trade["target"])
            qty    = int(trade.get("qty_lots", 1))
            ls     = int(trade.get("lot_size", 25))
            direct = trade.get("direction", "buy")

            if direct == "buy":
                pnl_unit = current_price - entry
                pct_tgt  = ((current_price - entry) / (tgt  - entry)) * 100 if (tgt  - entry) != 0 else 0
                pct_sl   = ((entry - current_price) / (entry - sl   )) * 100 if (entry - sl   ) != 0 else 0
            else:  # sell
                pnl_unit = entry - current_price
                pct_tgt  = ((entry - current_price) / (entry - tgt  )) * 100 if (entry - tgt  ) != 0 else 0
                pct_sl   = ((current_price - entry) / (sl    - entry )) * 100 if (sl    - entry ) != 0 else 0

            pnl_lot   = pnl_unit * ls
            total_pnl = pnl_lot  * qty
            open_today_running_pnl += total_pnl if _is_today_trade(trade, today_str) else 0.0

            trade["pnl_per_lot"] = round(pnl_lot, 2)
            trade["total_pnl"]   = round(total_pnl, 2)

            # Trail a protective stop after progress toward target to lock profits.
            if direct == "buy" and current_price > entry and pct_tgt >= TRAILING_ACTIVATION_PCT_TO_TARGET:
                prev_anchor = float(trade.get("trailing_anchor_price") or entry)
                anchor = max(prev_anchor, current_price)
                trail = round(entry + (anchor - entry) * TRAILING_LOCK_PCT, 2)
                trade["trailing_anchor_price"] = round(anchor, 2)
                trade["trailing_stop"] = trail
                if current_price <= trail:
                    trade["status"] = "Closed"
                    trade["exit_price"] = current_price
                    trade["suggestion"] = "EXIT — Trailing Stop"
                    trade["suggestion_reason"] = (
                        f"Price retraced to trailing stop ₹{trail:.2f} after favorable move. "
                        "Trade closed to protect gains."
                    )
                    updated.append(trade)
                    continue
            elif direct == "sell" and current_price < entry and pct_tgt >= TRAILING_ACTIVATION_PCT_TO_TARGET:
                prev_anchor = float(trade.get("trailing_anchor_price") or entry)
                anchor = min(prev_anchor, current_price)
                trail = round(entry - (entry - anchor) * TRAILING_LOCK_PCT, 2)
                trade["trailing_anchor_price"] = round(anchor, 2)
                trade["trailing_stop"] = trail
                if current_price >= trail:
                    trade["status"] = "Closed"
                    trade["exit_price"] = current_price
                    trade["suggestion"] = "EXIT — Trailing Stop"
                    trade["suggestion_reason"] = (
                        f"Price bounced back to trailing stop ₹{trail:.2f} after favorable move. "
                        "Trade closed to protect gains."
                    )
                    updated.append(trade)
                    continue

            # Auto-close if SL or target hit
            if pct_sl >= 100:
                slipped_exit = _apply_stop_slippage(direct, sl, current_price, gap_pct, is_gap_shock)
                trade["status"]            = "Closed"
                trade["exit_price"]        = slipped_exit
                exit_pnl_unit = (slipped_exit - entry) if direct == "buy" else (entry - slipped_exit)
                trade["pnl_per_lot"] = round(exit_pnl_unit * ls, 2)
                trade["total_pnl"] = round(exit_pnl_unit * ls * qty, 2)
                trade["suggestion"]        = "EXIT — Stop-Loss Hit"
                if is_gap_shock:
                    trade["suggestion_reason"] = (
                        f"Stop-loss triggered during gap/sudden move (gap {gap_pct:.2f}%). "
                        f"Applied slippage-aware exit at ₹{slipped_exit:.2f}."
                    )
                else:
                    trade["suggestion_reason"] = (
                        f"Current ₹{current_price:.2f} reached stop-loss (₹{sl:.2f}). "
                        f"Slippage-aware exit applied at ₹{slipped_exit:.2f}."
                    )
                logger.info("Auto-closed (SL): trade %s | PnL ₹%.0f", trade["id"], trade["total_pnl"])

            elif pct_tgt >= 100:
                trade["status"]            = "Closed"
                trade["exit_price"]        = current_price
                trade["suggestion"]        = "EXIT — Target Reached"
                trade["suggestion_reason"] = f"Target ₹{tgt:.2f} reached. Position closed automatically. Final PnL: ₹{total_pnl:,.0f}"
                logger.info("Auto-closed (Target): trade %s | PnL ₹%.0f", trade["id"], total_pnl)

            # HOLD / EXIT / REVIEW suggestions
            elif pct_tgt >= 70:
                trade["suggestion"]        = "EXIT (partial/full)"
                trade["suggestion_reason"] = (f"₹{current_price:.2f} is {pct_tgt:.0f}% of the way to target. "
                                               "Consider booking partial profits to protect gains.")
            elif pct_sl >= 70:
                trade["suggestion"]        = "REVIEW — Near Stop-Loss"
                trade["suggestion_reason"] = (f"Loss is {pct_sl:.0f}% of max allowed risk. "
                                               "Review whether original thesis still holds. "
                                               "Tighten SL or close to avoid full stop-out.")
            elif is_gap_shock and pct_tgt < 30 and pct_sl >= 40:
                trade["suggestion"]        = "REVIEW — Gap Shock"
                trade["suggestion_reason"] = (
                    f"Market opened with a {gap_pct:.2f}% gap. Position is vulnerable to sudden volatility. "
                    "Consider reducing size or closing if thesis weakens."
                )
            elif pct_tgt >= 30:
                trade["suggestion"]        = "HOLD"
                trade["suggestion_reason"] = f"Trade is {pct_tgt:.0f}% to target. Thesis intact — hold with discipline."
            elif pnl_unit >= 0:
                trade["suggestion"]        = "HOLD"
                trade["suggestion_reason"] = "In profit but early stage. Monitor price action near key levels."
            else:
                trade["suggestion"]        = "MONITOR"
                trade["suggestion_reason"] = (f"Trade is ₹{abs(pnl_unit):.2f} against entry. "
                                               "Revisit entry logic if market structure changes.")

            updated.append(trade)

        # Portfolio kill-switch: if today's aggregate paper P&L breaches daily max loss,
        # close remaining open trades to avoid compounding drawdown.
        day_total = closed_today_pnl + open_today_running_pnl
        if day_total <= DAILY_MAX_LOSS_INR:
            for trade in updated:
                if trade.get("status") != "Open":
                    continue
                if not _is_today_trade(trade, today_str):
                    continue

                current_price = self._get_current_price(trade, chain_df, cur_close)
                if current_price is None:
                    continue

                entry = float(trade["entry_price"])
                ls = int(trade.get("lot_size", 25))
                qty = int(trade.get("qty_lots", 1))
                direct = trade.get("direction", "buy")
                pnl_unit = (current_price - entry) if direct == "buy" else (entry - current_price)

                trade["status"] = "Closed"
                trade["exit_price"] = round(current_price, 2)
                trade["pnl_per_lot"] = round(pnl_unit * ls, 2)
                trade["total_pnl"] = round(pnl_unit * ls * qty, 2)
                trade["suggestion"] = "EXIT — Daily Risk Limit"
                trade["suggestion_reason"] = (
                    f"Daily portfolio P&L reached ₹{day_total:,.0f}, below limit ₹{DAILY_MAX_LOSS_INR:,.0f}. "
                    "All open trades closed to prevent deeper drawdown."
                )

        _save_raw(updated)
        return [t for t in updated if t.get("status") == "Open"]

    @staticmethod
    def _get_current_price(trade: dict, chain_df: pd.DataFrame, cur_close: Optional[float]) -> Optional[float]:
        """Look up the current price for a trade from chain or futures data."""
        instrument = trade.get("instrument", "")
        strike     = trade.get("strike")

        if instrument in ("CE", "PE") and not chain_df.empty and strike:
            col = "CE_LTP" if instrument == "CE" else "PE_LTP"
            row = chain_df[chain_df["strike"] == int(strike)]
            if not row.empty:
                return float(row[col].iloc[0])

        if instrument == "CE+PE" and not chain_df.empty:
            ce_strike = None
            pe_strike = None

            # Newer logs store both strikes as: "CE:24200/PE:23700"
            if isinstance(strike, str):
                m = re.match(r"^CE:(\d+)\/PE:(\d+)$", strike.strip())
                if m:
                    ce_strike = int(m.group(1))
                    pe_strike = int(m.group(2))
            # Older logs may store a single ATM strike for both CE and PE.
            elif strike is not None:
                try:
                    ce_strike = int(strike)
                    pe_strike = int(strike)
                except (TypeError, ValueError):
                    ce_strike = None
                    pe_strike = None

            if ce_strike is not None and pe_strike is not None:
                ce_row = chain_df[chain_df["strike"] == ce_strike]
                pe_row = chain_df[chain_df["strike"] == pe_strike]
                if not ce_row.empty and not pe_row.empty:
                    return float(ce_row["CE_LTP"].iloc[0] + pe_row["PE_LTP"].iloc[0])

            return None

        if instrument == "Futures":
            return cur_close

        # Fallback: use futures close
        return None

    # ------------------------------------------------------------------
    # Manual close
    # ------------------------------------------------------------------

    def close_trade(self, trade_id: str, exit_price: float, notes: str = "") -> bool:
        """
        Manually close a trade at exit_price.

        Returns True if the trade was found and closed; False otherwise.
        """
        trades = _load_raw()
        found  = False
        for trade in trades:
            if trade["id"] == trade_id and trade["status"] == "Open":
                entry = float(trade["entry_price"])
                ls    = int(trade.get("lot_size", 25))
                qty   = int(trade.get("qty_lots", 1))
                direct = trade.get("direction", "buy")

                pnl_unit = (exit_price - entry) if direct == "buy" else (entry - exit_price)
                trade["status"]     = "Closed"
                trade["exit_price"] = exit_price
                trade["pnl_per_lot"]= round(pnl_unit * ls, 2)
                trade["total_pnl"]  = round(pnl_unit * ls * qty, 2)
                if notes:
                    trade["notes"] = notes
                trade["suggestion"]        = "CLOSED (Manual)"
                trade["suggestion_reason"] = f"Manually closed at ₹{exit_price:.2f}."
                found = True
                logger.info("Trade %s manually closed | PnL ₹%.0f", trade_id, trade["total_pnl"])
                break

        if found:
            _save_raw(trades)
        return found

    def delete_trade(self, trade_id: str) -> bool:
        """Remove a trade from the journal (use carefully)."""
        trades = _load_raw()
        before = len(trades)
        trades = [t for t in trades if t["id"] != trade_id]
        _save_raw(trades)
        return len(trades) < before
