"""
src/options_view.py — Options strategy analytics for the Study Tool
====================================================================

What this module does
---------------------
Provides payoff diagrams, Greeks calculations, and plain-English strategy
explanations for common options strategies used in Indian equity markets.

Strategies supported
--------------------
1.  Long Call
2.  Long Put
3.  Covered Call
4.  Bull Call Spread (Debit Spread)
5.  Bear Put Spread  (Debit Spread)
6.  Long Straddle
7.  Long Strangle
8.  Short Straddle
9.  Short Strangle
10. Iron Condor

Key concepts
------------
• A "leg" is one option position (buy or sell, call or put, at one strike).
• "Premium" = option price paid (positive = cost to buyer, income to seller).
• Payoff at expiry is purely intrinsic value (time value = 0).
• P&L = Payoff − Net Premium Paid (for buys) or Net Premium Received (for sells).

⚠️  DISCLAIMER: All payoff and Greek values shown here are THEORETICAL,
    computed using the Black-Scholes model with synthetic data.
    They are for EDUCATIONAL PURPOSES ONLY and NOT financial advice.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.utils import black_scholes_price, compute_greeks

logger = logging.getLogger("market_study_tool.options_view")


# ---------------------------------------------------------------------------
# Strategy catalogue
# ---------------------------------------------------------------------------

STRATEGY_CATALOGUE = {
    "Long Call": {
        "legs": 1,
        "description": "Buy one call option. Profit when spot rises above breakeven.",
        "outlook":      "Strongly bullish",
        "max_profit":   "Unlimited",
        "max_loss":     "Premium paid",
        "when_to_use":  "You expect a significant upward move in the underlying.",
        "risk":         "You lose the full premium if the market doesn't rise above the strike.",
        "iv_preference":"Low IV (cheap options)",
        "strikes_needed": ["strike_buy_ce"],
    },
    "Long Put": {
        "legs": 1,
        "description": "Buy one put option. Profit when spot falls below breakeven.",
        "outlook":      "Strongly bearish",
        "max_profit":   "Strike − Premium (large)",
        "max_loss":     "Premium paid",
        "when_to_use":  "You expect a significant downward move.",
        "risk":         "You lose the full premium if the market doesn't fall.",
        "iv_preference":"Low IV",
        "strikes_needed": ["strike_buy_pe"],
    },
    "Covered Call": {
        "legs": 2,
        "description": "Hold futures/underlying + Sell an OTM call. Earn premium income.",
        "outlook":      "Neutral to mildly bullish",
        "max_profit":   "Call premium received + (Call strike − Entry price)",
        "max_loss":     "Entry price − Premium received (large if market crashes)",
        "when_to_use":  "You hold a long futures position and want to earn extra income.",
        "risk":         "You cap your upside. If market falls sharply, you still lose on futures.",
        "iv_preference":"High IV (expensive premiums to sell)",
        "strikes_needed": ["entry_price", "strike_sell_ce"],
    },
    "Bull Call Spread": {
        "legs": 2,
        "description": "Buy lower-strike call + Sell higher-strike call. Limited risk, limited reward.",
        "outlook":      "Moderately bullish",
        "max_profit":   "Width of spread − Net premium paid",
        "max_loss":     "Net premium paid",
        "when_to_use":  "You expect moderate upside but want to reduce the cost of a long call.",
        "risk":         "Caps your profit. Loses net premium if market stays flat or falls.",
        "iv_preference":"Neutral to slightly low IV",
        "strikes_needed": ["strike_buy_ce", "strike_sell_ce"],
    },
    "Bear Put Spread": {
        "legs": 2,
        "description": "Buy higher-strike put + Sell lower-strike put. Limited risk, limited reward.",
        "outlook":      "Moderately bearish",
        "max_profit":   "Width of spread − Net premium paid",
        "max_loss":     "Net premium paid",
        "when_to_use":  "You expect moderate downside but want cheaper entry than a naked put.",
        "risk":         "Caps profit. Loses net debit if market stays flat or rises.",
        "iv_preference":"Neutral to low IV",
        "strikes_needed": ["strike_sell_pe", "strike_buy_pe"],
    },
    "Long Straddle": {
        "legs": 2,
        "description": "Buy ATM call + Buy ATM put (same strike, same expiry).",
        "outlook":      "Volatile — big move expected but direction unknown",
        "max_profit":   "Unlimited (call side) / Strike − Total Premium (put side)",
        "max_loss":     "Total premium paid (if spot stays exactly at ATM)",
        "when_to_use":  "Before a major event (budget, election, earnings) where you expect a big move.",
        "risk":         "Very expensive (two premiums). Needs a large move to profit.",
        "iv_preference":"Low IV before buying (IV tends to rise into events)",
        "strikes_needed": ["strike_atm"],
    },
    "Long Strangle": {
        "legs": 2,
        "description": "Buy OTM call + Buy OTM put (different strikes, same expiry). Cheaper than straddle.",
        "outlook":      "Very volatile — huge move expected",
        "max_profit":   "Unlimited (call) / Put Strike − Total Premium (put side)",
        "max_loss":     "Total premium paid",
        "when_to_use":  "Similar to straddle but cheaper; needs a bigger move to profit.",
        "risk":         "Wider breakevens mean the market must move more than a straddle.",
        "iv_preference":"Low IV",
        "strikes_needed": ["strike_buy_pe", "strike_buy_ce"],
    },
    "Short Straddle": {
        "legs": 2,
        "description": "Sell ATM call + Sell ATM put. Profit when market stays near the strike.",
        "outlook":      "Low volatility expected — range-bound market",
        "max_profit":   "Total premium received",
        "max_loss":     "Unlimited (theoretically)",
        "when_to_use":  "When you expect the market to stay in a narrow range until expiry.",
        "risk":         "Unlimited loss on a big move. Requires margin. Very high risk.",
        "iv_preference":"High IV (sell expensive premium)",
        "strikes_needed": ["strike_atm"],
    },
    "Short Strangle": {
        "legs": 2,
        "description": "Sell OTM call + Sell OTM put. Profit when market stays between the strikes.",
        "outlook":      "Neutral, range-bound",
        "max_profit":   "Total premium received",
        "max_loss":     "Unlimited",
        "when_to_use":  "When you expect low volatility and a range-bound market.",
        "risk":         "Unlimited risk. However, wider strikes provide more cushion than a straddle.",
        "iv_preference":"High IV",
        "strikes_needed": ["strike_sell_pe", "strike_sell_ce"],
    },
    "Iron Condor": {
        "legs": 4,
        "description": (
            "Sell OTM call + Buy further-OTM call + "
            "Sell OTM put + Buy further-OTM put. "
            "Range-bound strategy with defined risk."
        ),
        "outlook":      "Neutral, low volatility",
        "max_profit":   "Net premium received",
        "max_loss":     "Width of wider wing − Net premium received",
        "when_to_use":  "Classic expiry week strategy when you expect the index to stay in a range.",
        "risk":         "Loses money on a big move. More forgiving than a straddle/strangle.",
        "iv_preference":"High IV (sell expensive wings)",
        "strikes_needed": ["strike_pe_wing_buy", "strike_sell_pe", "strike_sell_ce", "strike_ce_wing_buy"],
    },
}


class OptionsAnalyzer:
    """
    Computes payoff diagrams, Greeks, and explanations for options strategies.

    Parameters
    ----------
    config : dict
        Parsed config.yaml.
    """

    def __init__(self, config: dict) -> None:
        self.config  = config
        self.rf_rate = config["market"]["risk_free_rate"]

    # ------------------------------------------------------------------
    # Leg builder helpers
    # ------------------------------------------------------------------

    def build_legs(
        self,
        strategy_name: str,
        strikes: dict,
        chain_df: pd.DataFrame,
        T: float,
    ) -> list:
        """
        Build a list of option legs for the given strategy and strikes.

        Each leg is a dict:
            { type, action, strike, premium, qty }

        Parameters
        ----------
        strategy_name : str   — one of STRATEGY_CATALOGUE keys
        strikes       : dict  — mapping of strike keys to numeric values
                                (keys depend on strategy, see STRATEGY_CATALOGUE)
        chain_df      : pd.DataFrame — option chain for premium lookup
        T             : float        — time to expiry in years

        Returns
        -------
        list of leg dicts
        """
        spot = float(chain_df["spot"].iloc[0]) if not chain_df.empty else 0.0

        def get_premium(strike: float, opt_type: str) -> float:
            """Look up option premium from chain, or compute via BS if missing."""
            row = chain_df[chain_df["strike"] == strike]
            if not row.empty:
                col = "CE_LTP" if opt_type == "CE" else "PE_LTP"
                return float(row[col].iloc[0])
            # Fallback: Black-Scholes with ATM IV ≈ 16%
            return black_scholes_price(spot, strike, T, self.rf_rate, 0.16, opt_type)

        legs = []
        s = strikes  # shorthand

        if strategy_name == "Long Call":
            k = s.get("strike_buy_ce", spot)
            legs = [{"type": "CE", "action": "buy", "strike": k, "premium": get_premium(k, "CE"), "qty": 1}]

        elif strategy_name == "Long Put":
            k = s.get("strike_buy_pe", spot)
            legs = [{"type": "PE", "action": "buy", "strike": k, "premium": get_premium(k, "PE"), "qty": 1}]

        elif strategy_name == "Covered Call":
            k_sell = s.get("strike_sell_ce", spot * 1.03)
            entry  = s.get("entry_price",    spot)
            legs = [
                {"type": "futures", "action": "buy",  "strike": entry,  "premium": 0.0, "qty": 1},
                {"type": "CE",      "action": "sell", "strike": k_sell, "premium": get_premium(k_sell, "CE"), "qty": 1},
            ]

        elif strategy_name == "Bull Call Spread":
            k_buy  = s.get("strike_buy_ce",  spot)
            k_sell = s.get("strike_sell_ce", spot * 1.02)
            legs = [
                {"type": "CE", "action": "buy",  "strike": k_buy,  "premium": get_premium(k_buy, "CE"),  "qty": 1},
                {"type": "CE", "action": "sell", "strike": k_sell, "premium": get_premium(k_sell, "CE"), "qty": 1},
            ]

        elif strategy_name == "Bear Put Spread":
            k_buy  = s.get("strike_buy_pe",  spot)
            k_sell = s.get("strike_sell_pe", spot * 0.98)
            legs = [
                {"type": "PE", "action": "buy",  "strike": k_buy,  "premium": get_premium(k_buy, "PE"),  "qty": 1},
                {"type": "PE", "action": "sell", "strike": k_sell, "premium": get_premium(k_sell, "PE"), "qty": 1},
            ]

        elif strategy_name == "Long Straddle":
            k = s.get("strike_atm", spot)
            legs = [
                {"type": "CE", "action": "buy", "strike": k, "premium": get_premium(k, "CE"), "qty": 1},
                {"type": "PE", "action": "buy", "strike": k, "premium": get_premium(k, "PE"), "qty": 1},
            ]

        elif strategy_name == "Long Strangle":
            k_ce = s.get("strike_buy_ce", spot * 1.02)
            k_pe = s.get("strike_buy_pe", spot * 0.98)
            legs = [
                {"type": "CE", "action": "buy", "strike": k_ce, "premium": get_premium(k_ce, "CE"), "qty": 1},
                {"type": "PE", "action": "buy", "strike": k_pe, "premium": get_premium(k_pe, "PE"), "qty": 1},
            ]

        elif strategy_name == "Short Straddle":
            k = s.get("strike_atm", spot)
            legs = [
                {"type": "CE", "action": "sell", "strike": k, "premium": get_premium(k, "CE"), "qty": 1},
                {"type": "PE", "action": "sell", "strike": k, "premium": get_premium(k, "PE"), "qty": 1},
            ]

        elif strategy_name == "Short Strangle":
            k_ce = s.get("strike_sell_ce", spot * 1.02)
            k_pe = s.get("strike_sell_pe", spot * 0.98)
            legs = [
                {"type": "CE", "action": "sell", "strike": k_ce, "premium": get_premium(k_ce, "CE"), "qty": 1},
                {"type": "PE", "action": "sell", "strike": k_pe, "premium": get_premium(k_pe, "PE"), "qty": 1},
            ]

        elif strategy_name == "Iron Condor":
            k_pe_buy  = s.get("strike_pe_wing_buy", spot * 0.95)
            k_pe_sell = s.get("strike_sell_pe",     spot * 0.98)
            k_ce_sell = s.get("strike_sell_ce",     spot * 1.02)
            k_ce_buy  = s.get("strike_ce_wing_buy", spot * 1.05)
            legs = [
                {"type": "PE", "action": "buy",  "strike": k_pe_buy,  "premium": get_premium(k_pe_buy,  "PE"), "qty": 1},
                {"type": "PE", "action": "sell", "strike": k_pe_sell, "premium": get_premium(k_pe_sell, "PE"), "qty": 1},
                {"type": "CE", "action": "sell", "strike": k_ce_sell, "premium": get_premium(k_ce_sell, "CE"), "qty": 1},
                {"type": "CE", "action": "buy",  "strike": k_ce_buy,  "premium": get_premium(k_ce_buy,  "CE"), "qty": 1},
            ]
        else:
            logger.warning("Unknown strategy: %s", strategy_name)

        return legs

    # ------------------------------------------------------------------
    # Payoff at expiry
    # ------------------------------------------------------------------

    def compute_payoff(self, legs: list, spot_range: np.ndarray) -> np.ndarray:
        """
        Calculate strategy P&L at expiry across a range of spot prices.

        At expiry, an option's value is purely its intrinsic value:
        • Call intrinsic = max(Spot − Strike, 0)
        • Put  intrinsic = max(Strike − Spot, 0)

        P&L for a buyer  = Intrinsic − Premium paid
        P&L for a seller = Premium received − Intrinsic

        For a futures leg:
        P&L = (Spot at expiry) − Entry price

        Parameters
        ----------
        legs       : list of leg dicts (from build_legs)
        spot_range : np.ndarray  — array of spot prices at which to evaluate

        Returns
        -------
        np.ndarray : total P&L per point of underlying (multiply by lot size for ₹ P&L)
        """
        total_pnl = np.zeros(len(spot_range))

        for leg in legs:
            premium = leg["premium"]
            qty     = leg["qty"]
            mult    = 1 if leg["action"] == "buy" else -1  # +1 buyer, −1 seller

            if leg["type"] == "CE":
                intrinsic = np.maximum(spot_range - leg["strike"], 0.0)
                pnl_leg   = mult * (intrinsic - premium) * qty

            elif leg["type"] == "PE":
                intrinsic = np.maximum(leg["strike"] - spot_range, 0.0)
                pnl_leg   = mult * (intrinsic - premium) * qty

            elif leg["type"] == "futures":
                # Long futures: P&L = Spot − Entry
                pnl_leg = (spot_range - leg["strike"]) * qty

            else:
                pnl_leg = np.zeros(len(spot_range))

            total_pnl += pnl_leg

        return total_pnl

    def compute_strategy_greeks(
        self,
        legs: list,
        spot: float,
        T: float,
        sigma: float = 0.16,
    ) -> dict:
        """
        Calculate aggregate Greeks for the strategy at the current spot.

        Strategy-level Greeks are the *sum* of individual leg Greeks,
        taking into account sign (buy = +1, sell = −1).

        Why aggregate Greeks matter
        ----------------------------
        • Net Delta tells you how much ₹ you gain/lose per 1-point move.
        • Net Gamma tells you how your delta changes — high positive gamma
          means your position becomes more profitable in a big move.
        • Net Theta tells you your daily time decay (negative = you pay, positive = you earn).
        • Net Vega tells you your IV sensitivity — long options have positive vega.

        Returns
        -------
        dict with: delta, gamma, theta, vega (aggregate), and per-leg breakdown
        """
        total = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        breakdown = []

        for leg in legs:
            if leg["type"] == "futures":
                g = {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
            else:
                g = compute_greeks(spot, leg["strike"], T, self.rf_rate, sigma, leg["type"])

            sign = 1 if leg["action"] == "buy" else -1
            qty  = leg["qty"]

            for k in total:
                total[k] += sign * qty * g[k]

            breakdown.append({
                "type":   leg["type"],
                "action": leg["action"],
                "strike": leg["strike"],
                **{k: round(sign * qty * g[k], 4) for k in g},
            })

        total = {k: round(v, 4) for k, v in total.items()}
        return {"aggregate": total, "legs": breakdown}

    # ------------------------------------------------------------------
    # Risk/reward summary
    # ------------------------------------------------------------------

    def risk_reward_summary(
        self, legs: list, lot_size: int, spot: float
    ) -> dict:
        """
        Calculate max profit, max loss, and breakeven points.

        For complex strategies (Iron Condor, etc.) these are approximated
        using the payoff curve rather than closed-form formulas.

        Returns
        -------
        dict with: net_premium, max_profit, max_loss, breakevens,
                   risk_reward_ratio, summary_text
        """
        spot_range = np.linspace(spot * 0.70, spot * 1.30, 5000)
        pnl        = self.compute_payoff(legs, spot_range)

        # Net premium = sum of premiums paid (positive) and received (negative)
        net_premium = sum(
            leg["premium"] * leg["qty"] * (1 if leg["action"] == "buy" else -1)
            for leg in legs
            if leg["type"] in ("CE", "PE")
        )

        max_profit_per_unit = float(np.max(pnl))
        max_loss_per_unit   = float(np.min(pnl))

        # Breakeven points: where pnl crosses zero
        sign_changes = np.where(np.diff(np.sign(pnl)))[0]
        breakevens   = [round(float(spot_range[i]), 0) for i in sign_changes]

        # Risk/reward ratio (positive values only)
        rr = abs(max_profit_per_unit / max_loss_per_unit) if max_loss_per_unit != 0 else float("inf")

        max_profit_inr = max_profit_per_unit * lot_size
        max_loss_inr   = max_loss_per_unit   * lot_size

        return {
            "net_premium":      round(net_premium,     2),
            "max_profit_pts":   round(max_profit_per_unit, 2),
            "max_loss_pts":     round(max_loss_per_unit,   2),
            "max_profit_inr":   round(max_profit_inr,  2),
            "max_loss_inr":     round(max_loss_inr,    2),
            "breakevens":       breakevens[:4],         # show at most 4
            "risk_reward_ratio":round(rr, 2),
        }

    # ------------------------------------------------------------------
    # Strategy explanation
    # ------------------------------------------------------------------

    def get_strategy_explanation(
        self,
        strategy_name: str,
        sentiment_label: str = "Neutral",
        pcr_5d_avg: Optional[float] = None,
        atm_iv: Optional[float] = None,
    ) -> str:
        """
        Generate a plain-English explanation of the strategy and its
        suitability given the current market conditions.

        Parameters
        ----------
        strategy_name  : str   — strategy key from STRATEGY_CATALOGUE
        sentiment_label: str   — from InstitutionalAnalyzer.generate_sentiment
        pcr_5d_avg     : float — recent PCR value
        atm_iv         : float — current ATM implied volatility (%)

        Returns
        -------
        str : Multi-paragraph educational explanation
        """
        cat = STRATEGY_CATALOGUE.get(strategy_name, {})
        if not cat:
            return f"No information available for strategy: {strategy_name}"

        lines = [
            f"### {strategy_name}",
            "",
            f"**What it is:** {cat['description']}",
            "",
            f"**Market Outlook Required:** {cat['outlook']}",
            f"**Max Profit:** {cat['max_profit']}",
            f"**Max Loss:** {cat['max_loss']}",
            "",
            f"**When to use:** {cat['when_to_use']}",
            f"**Main risk:** {cat['risk']}",
            f"**IV preference:** {cat['iv_preference']}",
            "",
            "---",
            "**Current Market Context (Study Exercise Only):**",
        ]

        # Suitability assessment
        favourable   = []
        unfavourable = []

        outlook = cat["outlook"].lower()

        if "bullish" in outlook and "bullish" in sentiment_label.lower():
            favourable.append(f"Market sentiment ({sentiment_label}) aligns with the bullish outlook needed.")
        elif "bearish" in outlook and "bearish" in sentiment_label.lower():
            favourable.append(f"Market sentiment ({sentiment_label}) aligns with the bearish outlook needed.")
        elif "neutral" in outlook or "range" in outlook:
            if "neutral" in sentiment_label.lower() or "sideways" in sentiment_label.lower():
                favourable.append(f"Market sentiment ({sentiment_label}) aligns with the neutral/range-bound outlook.")
            else:
                unfavourable.append(f"Market sentiment ({sentiment_label}) is trending — consider a directional strategy instead.")
        else:
            unfavourable.append(f"Current sentiment ({sentiment_label}) may not align with this strategy.")

        if pcr_5d_avg is not None:
            if pcr_5d_avg > 1.2:
                lines.append(f"- PCR (5d avg): {pcr_5d_avg:.2f} — High put activity; market may be over-hedged.")
            elif pcr_5d_avg < 0.8:
                lines.append(f"- PCR (5d avg): {pcr_5d_avg:.2f} — High call activity; market may be over-optimistic.")
            else:
                lines.append(f"- PCR (5d avg): {pcr_5d_avg:.2f} — Balanced positioning.")

        if atm_iv is not None:
            if atm_iv > 20:
                lines.append(f"- ATM IV: {atm_iv:.1f}% — Options are *expensive*. Selling strategies benefit.")
                if "sell" in cat["iv_preference"].lower() or "high" in cat["iv_preference"].lower():
                    favourable.append(f"High IV ({atm_iv:.1f}%) favours selling premiums — good for this strategy.")
                else:
                    unfavourable.append(f"High IV ({atm_iv:.1f}%) makes buying options expensive — less ideal for this strategy.")
            else:
                lines.append(f"- ATM IV: {atm_iv:.1f}% — Options are *reasonably priced*. Buying strategies benefit.")
                if "low" in cat["iv_preference"].lower():
                    favourable.append(f"Low IV ({atm_iv:.1f}%) means cheaper option premiums — good for this buying strategy.")

        lines.append("")
        if favourable:
            lines.append("✅ **Favourable conditions:**")
            for f in favourable:
                lines.append(f"  - {f}")

        if unfavourable:
            lines.append("⚠️  **Caution:**")
            for u in unfavourable:
                lines.append(f"  - {u}")

        lines += [
            "",
            "---",
            "> ⚠️  **Disclaimer:** This analysis is for EDUCATIONAL STUDY ONLY.",
            "> It does NOT constitute financial advice. Options involve significant risk",
            "> including total loss of premium and, for sellers, unlimited loss.",
            "> Never trade without fully understanding the risks involved.",
        ]

        return "\n".join(lines)
