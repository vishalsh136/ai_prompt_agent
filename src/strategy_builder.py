"""
src/strategy_builder.py — Real-World Strategy Builder (study-only)
===================================================================

This module builds rule-based educational strategies from already loaded data.
It NEVER places orders and NEVER connects to brokers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.strategy_builder")


@dataclass
class StrategyIdea:
    strategy_name: str
    instrument: str
    direction: str
    strike_or_level: str
    premium_or_price: str
    entry_reason: str
    stop_loss_rule: str
    target_rule: str
    risk_level: str
    expected_time_to_target: str
    fit_conditions: str
    main_risks: str
    assumptions: str


class StrategyBuilder:
    """Generate learning-focused rule-based strategy ideas from market features."""

    def __init__(self, config: dict) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nearest_strike(chain_df: pd.DataFrame, value: float) -> int:
        strikes = np.array(sorted(chain_df["strike"].unique()))
        return int(strikes[np.argmin(np.abs(strikes - value))])

    @staticmethod
    def _premium(chain_df: pd.DataFrame, strike: int, opt_type: str) -> float:
        row = chain_df[chain_df["strike"] == strike]
        if row.empty:
            return 0.0
        return float(row["CE_LTP"].iloc[0] if opt_type == "CE" else row["PE_LTP"].iloc[0])

    @staticmethod
    def _format_days(days: float) -> str:
        if days <= 2:
            return "1-2 trading days"
        if days <= 5:
            return "3-5 trading days"
        if days <= 10:
            return "1-2 weeks"
        return "2-4 weeks"

    def _atr_context(self, futures_df: pd.DataFrame) -> Dict:
        df = futures_df.copy()
        prev_close = df["close"].shift(1).fillna(df["close"])
        tr = pd.concat([
            (df["high"] - df["low"]),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
        close = float(df["close"].iloc[-1])
        atr_pct = (atr14 / close) * 100 if close else 0.0
        return {"atr": atr14, "close": close, "atr_pct": atr_pct}

    # ------------------------------------------------------------------
    # A) Option Seller Strategy Engine
    # ------------------------------------------------------------------

    def detect_option_seller_regime(
        self,
        futures_df: pd.DataFrame,
        chain_df: pd.DataFrame,
        pcr_df: pd.DataFrame,
        sentiment: dict,
    ) -> Dict:
        """Detect a practical regime for option selling strategies."""
        close = float(futures_df["close"].iloc[-1])
        sma20 = float(futures_df["close"].rolling(20, min_periods=1).mean().iloc[-1])
        sma50 = float(futures_df["close"].rolling(50, min_periods=1).mean().iloc[-1])
        trend_strength = abs((sma20 - sma50) / close) * 100 if close else 0

        pcr_now = float(pcr_df["pcr_oi"].iloc[-1]) if not pcr_df.empty else 1.0
        ce_wall = sentiment.get("oi_conc", {}).get("ce_wall")
        pe_wall = sentiment.get("oi_conc", {}).get("pe_wall")
        atm_iv = float(chain_df.loc[(chain_df["strike"] - chain_df["spot"].iloc[0]).abs().idxmin(), "CE_IV"])

        atr_ctx = self._atr_context(futures_df)
        vol_regime = "high" if atr_ctx["atr_pct"] > 1.2 else "low"
        iv_regime = "high" if atm_iv > 18 else "low"

        if trend_strength < 0.5 and vol_regime == "low":
            regime = "Range-Bound Low Volatility"
        elif trend_strength < 0.8 and iv_regime == "high":
            regime = "Range-Bound High IV"
        elif sma20 > sma50:
            regime = "Uptrend"
        elif sma20 < sma50:
            regime = "Downtrend"
        else:
            regime = "Transitional"

        return {
            "regime": regime,
            "trend_strength_pct": round(trend_strength, 2),
            "pcr_now": round(pcr_now, 3),
            "atm_iv": round(atm_iv, 2),
            "iv_regime": iv_regime,
            "vol_regime": vol_regime,
            "ce_wall": ce_wall,
            "pe_wall": pe_wall,
            "spot": float(chain_df["spot"].iloc[0]),
            "atr": atr_ctx["atr"],
            "sentiment": sentiment.get("label", "Neutral"),
        }

    def generate_option_seller_strategies(self, chain_df: pd.DataFrame, regime: Dict) -> List[StrategyIdea]:
        """Generate 2-4 educational option-selling strategies based on regime."""
        spot = regime["spot"]
        atr = max(regime["atr"], spot * 0.005)
        s = self._nearest_strike
        p = self._premium

        atm = s(chain_df, spot)
        upper = s(chain_df, spot + 1.0 * atr)
        lower = s(chain_df, spot - 1.0 * atr)
        wing_up = s(chain_df, spot + 2.0 * atr)
        wing_dn = s(chain_df, spot - 2.0 * atr)

        ideas: List[StrategyIdea] = []

        if "Range-Bound" in regime["regime"]:
            # Iron Condor
            net_credit = (p(chain_df, upper, "CE") + p(chain_df, lower, "PE")
                          - p(chain_df, wing_up, "CE") - p(chain_df, wing_dn, "PE"))
            ideas.append(StrategyIdea(
                strategy_name="Iron Condor (Study Setup)",
                instrument="CE/PE",
                direction=f"Sell {lower} PE + Sell {upper} CE; Buy wings {wing_dn} PE/{wing_up} CE",
                strike_or_level=f"Range {lower} - {upper}",
                premium_or_price=f"Approx net credit: ₹{max(net_credit, 0):.2f}",
                entry_reason="Price is range-bound with option OI walls and no strong trend breakout.",
                stop_loss_rule="Exit if spot closes beyond sold strike +/- 0.5 ATR or loss reaches 1.5x credit.",
                target_rule="Book profit at 40-60% of collected premium.",
                risk_level="Medium",
                expected_time_to_target="3-8 trading days",
                fit_conditions="Neutral/range market, stable IV.",
                main_risks="Sudden trend breakout, IV expansion after event risk.",
                assumptions="Liquidity near selected strikes remains healthy.",
            ))

            # Short Strangle
            strangle_credit = p(chain_df, upper, "CE") + p(chain_df, lower, "PE")
            ideas.append(StrategyIdea(
                strategy_name="Short Strangle (Wide)",
                instrument="CE/PE",
                direction=f"Sell {lower} PE and {upper} CE",
                strike_or_level=f"Short volatility around spot {spot:,.0f}",
                premium_or_price=f"Approx total premium: ₹{strangle_credit:.2f}",
                entry_reason="Market is not trending strongly; probability favors time decay capture.",
                stop_loss_rule="Exit side if option premium doubles OR spot breaches strike by 0.3 ATR.",
                target_rule="Take 50% premium decay or close before major event day.",
                risk_level="High",
                expected_time_to_target="2-6 trading days",
                fit_conditions="Low realized volatility, no macro event nearby.",
                main_risks="Gap risk and one-sided trend move.",
                assumptions="Trader can monitor intraday and adjust quickly.",
            ))

        if regime["regime"] in ("Uptrend", "Downtrend", "Transitional", "Range-Bound High IV"):
            # Credit spread directional with regime bias
            if regime["regime"] == "Uptrend":
                sell_k = s(chain_df, spot - 0.8 * atr)
                buy_k = s(chain_df, spot - 1.8 * atr)
                credit = p(chain_df, sell_k, "PE") - p(chain_df, buy_k, "PE")
                direction = "Bull Put Credit Spread"
                fit = "Mild-to-moderate bullish trend with support holding."
            else:
                sell_k = s(chain_df, spot + 0.8 * atr)
                buy_k = s(chain_df, spot + 1.8 * atr)
                credit = p(chain_df, sell_k, "CE") - p(chain_df, buy_k, "CE")
                direction = "Bear Call Credit Spread"
                fit = "Mild-to-moderate bearish/sideways regime with resistance holding."

            ideas.append(StrategyIdea(
                strategy_name=direction,
                instrument="CE/PE",
                direction=(f"Sell {sell_k} PE, Buy {buy_k} PE" if "Put" in direction
                           else f"Sell {sell_k} CE, Buy {buy_k} CE"),
                strike_or_level=f"Spread width: {abs(sell_k - buy_k)} points",
                premium_or_price=f"Approx net credit: ₹{max(credit, 0):.2f}",
                entry_reason="Defined-risk premium selling aligned with regime bias.",
                stop_loss_rule="Exit if short strike is breached with volume expansion or loss reaches 1.7x credit.",
                target_rule="Book 50-65% of max credit.",
                risk_level="Low" if abs(sell_k - buy_k) <= 200 else "Medium",
                expected_time_to_target="4-10 trading days",
                fit_conditions=fit,
                main_risks="Momentum acceleration against the short strike.",
                assumptions="Spread can be executed near quoted mid prices.",
            ))

        # Ratio spread educational idea
        ideas.append(StrategyIdea(
            strategy_name="Call Ratio Spread (1x2) — Study Template",
            instrument="CE",
            direction=f"Buy 1x {atm} CE, Sell 2x {upper} CE",
            strike_or_level=f"ATM to OTM call ratio around spot {spot:,.0f}",
            premium_or_price=f"Premium depends on fill; approx near low-cost to small credit setup",
            entry_reason="Useful when upside is expected to be limited and time decay is favorable.",
            stop_loss_rule="Exit if spot breaks above short call strike by >0.5 ATR with rising IV.",
            target_rule="Capture premium decay as spot stays below upper short strike.",
            risk_level="High",
            expected_time_to_target="3-7 trading days",
            fit_conditions="Mild bullish to sideways regime; capped upside view.",
            main_risks="Sharp upside move creates accelerating losses above breakeven zone.",
            assumptions="Adjustment discipline and position sizing are in place.",
        ))

        return ideas[:4]

    # ------------------------------------------------------------------
    # B) Institutional-style Futures Strategy Engine
    # ------------------------------------------------------------------

    def detect_market_structure(self, futures_df: pd.DataFrame) -> Dict:
        """Detect HH/HL or LL/LH structure with volume and volatility context."""
        df = futures_df.copy().reset_index(drop=True)
        lookback = min(20, len(df))
        recent = df.tail(lookback)

        highs = recent["high"].values
        lows = recent["low"].values
        closes = recent["close"].values

        hh = np.sum(np.diff(highs) > 0)
        hl = np.sum(np.diff(lows) > 0)
        ll = np.sum(np.diff(lows) < 0)
        lh = np.sum(np.diff(highs) < 0)

        if hh > ll and hl > lh:
            structure = "Higher Highs / Higher Lows"
            bias = "Bullish"
        elif ll > hh and lh > hl:
            structure = "Lower Lows / Lower Highs"
            bias = "Bearish"
        else:
            structure = "Mixed / Range"
            bias = "Neutral"

        vol_ma = float(df["volume"].rolling(20, min_periods=1).mean().iloc[-1])
        vol_now = float(df["volume"].iloc[-1])
        volume_confirmation = "Confirmed" if vol_now > 1.1 * vol_ma else "Weak"

        atr_ctx = self._atr_context(df)
        volatility_regime = "High" if atr_ctx["atr_pct"] > 1.2 else "Moderate/Low"

        return {
            "structure": structure,
            "bias": bias,
            "volume_confirmation": volume_confirmation,
            "volatility_regime": volatility_regime,
            "atr": atr_ctx["atr"],
            "close": atr_ctx["close"],
            "swing_high": float(recent["high"].max()),
            "swing_low": float(recent["low"].min()),
        }

    def generate_institutional_strategies(self, structure: Dict, chain_df: pd.DataFrame) -> List[StrategyIdea]:
        """Generate educational futures/instrumental direction strategies."""
        close = structure["close"]
        atr = max(structure["atr"], close * 0.005)
        swing_high = structure["swing_high"]
        swing_low = structure["swing_low"]

        ideas: List[StrategyIdea] = []

        # Trend continuation
        if structure["bias"] == "Bullish":
            entry = close + 0.2 * atr
            sl = close - 1.0 * atr
            tgt = close + 1.8 * atr
            direction = "Long Futures / Buy CE near ATM"
            fit = "Higher-high structure with volume support."
        elif structure["bias"] == "Bearish":
            entry = close - 0.2 * atr
            sl = close + 1.0 * atr
            tgt = close - 1.8 * atr
            direction = "Short Futures / Buy PE near ATM"
            fit = "Lower-low structure with bearish follow-through."
        else:
            entry = close
            sl = close - 0.8 * atr
            tgt = close + 1.2 * atr
            direction = "Range rotation (light size)"
            fit = "Mixed structure with no clean trend edge."

        ideas.append(StrategyIdea(
            strategy_name="Trend Continuation",
            instrument="Futures / CE-PE directional",
            direction=direction,
            strike_or_level=f"Entry zone around ₹{entry:,.0f}",
            premium_or_price=f"Reference: ATR {atr:,.0f} points",
            entry_reason="Price structure and recent impulse favor continuation after pullback/trigger.",
            stop_loss_rule=f"Invalidate if price closes beyond stop zone near ₹{sl:,.0f}",
            target_rule=f"Primary target near ₹{tgt:,.0f} (about 1.8 ATR move)",
            risk_level="Medium",
            expected_time_to_target=self._format_days(abs((tgt - close) / max(atr, 1))),
            fit_conditions=fit,
            main_risks="False continuation after low-liquidity move.",
            assumptions="Trend remains intact and no major gap event occurs.",
        ))

        # Breakout / Breakdown
        ideas.append(StrategyIdea(
            strategy_name="Breakout / Breakdown Trigger",
            instrument="Futures or ATM option",
            direction=(f"Buy breakout above ₹{swing_high:,.0f} / Sell breakdown below ₹{swing_low:,.0f}"),
            strike_or_level=f"Key levels: H={swing_high:,.0f}, L={swing_low:,.0f}",
            premium_or_price="Use nearest ATM option premium at trigger if options chosen",
            entry_reason="Recent range extremes define institutional decision levels.",
            stop_loss_rule="If breakout fails and re-enters prior range, exit immediately.",
            target_rule="Target 1-1.5 ATR from breakout level; trail remainder.",
            risk_level="Medium",
            expected_time_to_target="1-4 trading days",
            fit_conditions="Compression followed by volume expansion.",
            main_risks="Whipsaw in low-participation sessions.",
            assumptions="Breakout candle has above-average volume.",
        ))

        # Reversal zone
        ideas.append(StrategyIdea(
            strategy_name="Reversal Zone Response",
            instrument="Buy CE near support / Buy PE near resistance",
            direction="Mean-reversion setup at OI walls and swing extremes",
            strike_or_level="Use nearest strike to OI wall + confirmation candle",
            premium_or_price="Prefer slightly ITM options for faster delta response",
            entry_reason="When price rejects key zone with momentum divergence, reversal odds improve.",
            stop_loss_rule="Exit if zone breaks by >0.4 ATR on closing basis.",
            target_rule="First target at mid-range; second target at opposite swing.",
            risk_level="High",
            expected_time_to_target="2-6 trading days",
            fit_conditions="Range/mixed regimes, not strong one-way trend days.",
            main_risks="Trying to fade a genuine trend continuation.",
            assumptions="Clear rejection wick/structure shift appears at zone.",
        ))

        # Volume confirmed move
        ideas.append(StrategyIdea(
            strategy_name="Volume-Confirmed Momentum",
            instrument="Futures directional",
            direction="Trade only when volume > 1.2x 20-day avg in breakout direction",
            strike_or_level="Trigger at intraday/previous-day high-low breaks",
            premium_or_price=f"Reference volatility: {structure['volatility_regime']}",
            entry_reason="Institutional participation is more likely when price and volume align.",
            stop_loss_rule="Cut if follow-through fails within 1-2 candles/time blocks.",
            target_rule="Scale out at 1 ATR, trail to 2 ATR.",
            risk_level="Medium",
            expected_time_to_target="1-3 trading days",
            fit_conditions="Momentum sessions and event-driven trend days.",
            main_risks="Late entry after an exhausted move.",
            assumptions="Execution discipline avoids chasing extended candles.",
        ))

        return ideas

    # ------------------------------------------------------------------
    # C) Summary Panel
    # ------------------------------------------------------------------

    def build_strategy_summary(
        self,
        regime: Dict,
        option_ideas: List[StrategyIdea],
        structure: Dict,
        fut_ideas: List[StrategyIdea],
    ) -> Dict:
        """Build compact one-block summary for quick learning review."""
        top_option = option_ideas[0] if option_ideas else None
        top_fut = fut_ideas[0] if fut_ideas else None

        suggested = top_option.strategy_name if top_option else (top_fut.strategy_name if top_fut else "N/A")
        entry = top_option.strike_or_level if top_option else (top_fut.strike_or_level if top_fut else "N/A")
        sl = top_option.stop_loss_rule if top_option else (top_fut.stop_loss_rule if top_fut else "N/A")
        tgt = top_option.target_rule if top_option else (top_fut.target_rule if top_fut else "N/A")

        return {
            "market_regime": f"{regime.get('regime', 'Unknown')} | Structure: {structure.get('structure', 'Unknown')}",
            "suggested_strategy": suggested,
            "entry": entry,
            "stop_loss": sl,
            "target": tgt,
            "risk_note": (
                "Educational rule-set only. Real outcomes depend on execution, costs, slippage, "
                "and event risk. No guarantees."
            ),
        }

    @staticmethod
    def to_dataframe(ideas: List[StrategyIdea]) -> pd.DataFrame:
        return pd.DataFrame([i.__dict__ for i in ideas])
