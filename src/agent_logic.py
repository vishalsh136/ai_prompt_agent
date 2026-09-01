"""
src/agent_logic.py — Intelligent Optimization and Decision Agent Layer
========================================================================

What this module does
---------------------
Acts as an autonomous intelligence agent layer. It:
1. Monitors past trade performance (win rates, drawdowns, loss sequences) in the local trade journal.
2. Evaluates the current market environment (volatility regimes, sentiment strength, IV rank, and volume/OI signals).
3. Analyzes rule-based strategies and suggests concrete code or parameter shifts to improve edge (e.g., adaptive SL multiples, dynamic ATR factors, VIX caps).
4. Recommends dynamic target, stop-loss, and capital allocation size shifts based on recent logic success rates (expected value optimization).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Any
import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.agent_logic")


class DecisionOptimizerAgent:
    """
    Agent layer that audits trading performance, evaluates current market state,
    and dynamically refines execution parameters to maximize edge/profitability.
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    def analyze_journal_metrics(self, trades: List[dict]) -> Dict[str, Any]:
        """
        Analyze trade history from the journal to identify performance patterns.
        """
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_profit_factor": 1.0,
                "consecutive_losses": 0,
                "underperforming_strategies": [],
                "best_performing_strategies": [],
            }

        df = pd.DataFrame(trades)
        if "total_pnl" not in df.columns or df.empty:
            return {"total_trades": 0, "win_rate": 0.0, "avg_profit_factor": 1.0}

        # Essential metrics
        total_trades = len(df)
        completed = df[df["status"] == "Closed"]
        
        if completed.empty:
            return {
                "total_trades": total_trades,
                "completed_trades": 0,
                "win_rate": 0.0,
                "avg_profit_factor": 1.0,
                "streak_alert": False,
            }

        completed = completed.copy()
        completed["is_win"] = completed["total_pnl"] > 0
        win_rate = float(completed["is_win"].mean() * 100)

        # Profit / Loss stats
        wins = completed[completed["total_pnl"] > 0]["total_pnl"]
        losses = completed[completed["total_pnl"] < 0]["total_pnl"].abs()

        sum_wins = float(wins.sum())
        sum_losses = float(losses.sum())
        profit_factor = sum_wins / sum_losses if sum_losses > 0 else (sum_wins or 1.0)

        # Performance by strategy
        strategy_stats = []
        if "strategy_type" in completed.columns:
            for strat, group in completed.groupby("strategy_type"):
                pnl = group["total_pnl"].sum()
                wr = group["is_win"].mean() * 100
                strategy_stats.append({
                    "strategy": strat,
                    "total_pnl": float(pnl),
                    "win_rate": float(wr),
                    "count": len(group)
                })

        underperforming = [s["strategy"] for s in strategy_stats if s["win_rate"] < 40 or s["total_pnl"] < 0]
        best_performing = [s["strategy"] for s in strategy_stats if s["win_rate"] >= 55 and s["total_pnl"] > 0]

        # Consecutive losing streak calculation
        consecutive_losses = 0
        current_streak = 0
        pnl_sequence = completed.sort_values("timestamp")["total_pnl"].values
        for p in pnl_sequence:
            if p < 0:
                current_streak += 1
                consecutive_losses = max(consecutive_losses, current_streak)
            else:
                current_streak = 0

        return {
            "total_trades": total_trades,
            "completed_trades": len(completed),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "consecutive_losses": consecutive_losses,
            "streak_alert": consecutive_losses >= 3,
            "underperforming_strategies": underperforming,
            "best_performing_strategies": best_performing,
            "strategy_stats": strategy_stats
        }

    def evaluate_market_regime(
        self,
        futures_df: pd.DataFrame,
        chain_df: pd.DataFrame,
        vix: float
    ) -> Dict[str, Any]:
        """
        Evaluate current market state and high-level option properties
        to determine risk-adjusted volatility levels and structural regimes.
        """
        if futures_df.empty:
            return {"regime": "Unknown", "vix_regime": "Normal", "volatility_premium_factor": 1.0}

        close = float(futures_df["close"].iloc[-1])
        sma_200 = float(futures_df["close"].rolling(200, min_periods=1).mean().iloc[-1])
        sma_50 = float(futures_df["close"].rolling(50, min_periods=1).mean().iloc[-1])

        # Trend and distance metrics
        distance_to_sma200 = (close - sma_200) / sma_200 * 100
        trend = "Bullish" if close > sma_200 and close > sma_50 else ("Bearish" if close < sma_200 else "Sideways/Range")

        # Volatility assessment
        vix_regime = "NORMAL (12-18)"
        iv_multiplier = 1.0
        if vix > 18:
            vix_regime = "HIGH (>18) ⚠️ Expect wide swings"
            iv_multiplier = 1.25
        elif vix < 12:
            vix_regime = "LOW (<12) 📉 Low premiums, option-buying favored"
            iv_multiplier = 0.85

        # ATR percentage check
        high = futures_df["high"].tail(14)
        low = futures_df["low"].tail(14)
        tr = np.maximum(high - low, np.abs(high - futures_df["close"].shift(1).tail(14)))
        atr_14 = float(tr.mean()) if not tr.empty else 0.0
        atr_pct = (atr_14 / close) * 100 if close > 0 else 0.0

        market_vol = "High" if atr_pct > 1.2 or vix > 18 else ("Low" if atr_pct < 0.6 else "Normal")

        return {
            "trend": trend,
            "distance_to_sma200": round(distance_to_sma200, 2),
            "vix_regime": vix_regime,
            "market_volatility_label": market_vol,
            "atr_pct_of_price": round(atr_pct, 2),
            "iv_multiplier": iv_multiplier,
            "spot_price": close
        }

    def optimize_logic_parameters(
        self,
        performance: Dict[str, Any],
        regime: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Dynamically calculates optimal parameters (Stop-Loss factor, Target factor, Margin reserve)
        by joining trading metrics and market context, attempting to maximize profit factor.
        """
        # Baseline multipliers
        sl_factor = 1.5
        target_factor = 2.5
        allocation_pct = 1.0  # Multiplier for recommended lot sizing
        reasons = []

        # 1. Volatility adjustment
        mkt_vol = regime.get("market_volatility_label", "Normal")
        vix_regime = regime.get("vix_regime", "NORMAL")
        
        if mkt_vol == "High":
            sl_factor = 1.8
            target_factor = 3.0
            reasons.append("High volatility detected: widening SL and targets to avoid premature exits.")
        elif mkt_vol == "Low":
            sl_factor = 1.2
            target_factor = 2.0
            reasons.append("Low volatility regime: tightening SL and targets to protect returns.")

        # 2. Performance Feedback (Reinforcement)
        streak_alert = performance.get("streak_alert", False)
        pf = performance.get("profit_factor", 1.0)
        wr = performance.get("win_rate", 50.0)

        if streak_alert:
            allocation_pct = 0.5
            reasons.append("Recent losing sequence (>= 3): scaling down lot size risk by 50% to conserve capital.")
        elif wr < 45.0:
            sl_factor += 0.2
            reasons.append("Win rate sub-45%: increasing target and slightly widening SL to optimize Risk-to-Reward ratio.")
        elif wr >= 55.0 and pf >= 1.5:
            allocation_pct = 1.25
            reasons.append("High-conviction streak: extending position capacity allocations by 25%.")

        return {
            "optimal_sl_atr_multiplier": round(sl_factor, 2),
            "optimal_target_atr_multiplier": round(target_factor, 2),
            "risk_allocation_multiplier": allocation_pct,
            "logic_explanations": reasons,
            "recommended_regime_focus": "Option Selling / Hedging" if mkt_vol in ("Low", "Normal") else "Option Buying / Spread Protection"
        }
