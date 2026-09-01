"""
src/final_trade_decision.py — Final Paper-Trade Decision Generator
==================================================================

Takes all pre-computed analytics (sentiment, strategy-builder outputs,
option chain, futures data) and produces ONE clean, minimal trade setup
for both:

  A) Institutional Trader Logic  — futures or directional option
  B) Option Seller Logic         — premium-selling setup

Every trade idea includes:
  • CE / PE / Futures direction
  • Strike price or key level
  • Premium (approximate from chain LTP)
  • Entry price
  • Stop-loss  (rule-based: ATR or premium multiple)
  • Target     (rule-based: ATR or premium multiple)
  • Risk level (Low / Medium / High)
  • Expected time to target
  • Margin required (approximate SPAN estimate — NOT official NSE margin)
  • Reason for entry (2 lines)
  • Conditions that invalidate the trade

⚠️  PAPER-TRADE / STUDY ONLY.
    This module does NOT place real orders, connect to brokers, or provide
    financial advice.  All figures are approximations for learning purposes.
    Always verify actual margins, premiums, and rules with your broker/NSE.
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.final_trade_decision")

# ---------------------------------------------------------------------------
# Constants (approximate, educational)
# ---------------------------------------------------------------------------
FUTURES_MARGIN_PCT  = 0.21   # ~21% SPAN + exposure margin for index futures
OPTIONS_SELL_MARGIN_PCT = 0.20  # ~20% of notional for short options (SPAN approx)
INTRADAY_MARGIN_DISCOUNT = 0.4  # brokers often give 40-60% discount for intraday


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atr(futures_df: pd.DataFrame, period: int = 14) -> float:
    # Drop zero/null price rows (Yahoo Finance holiday placeholders) before ATR
    df = futures_df[(futures_df["close"] > 0) & (futures_df["high"] > 0)].copy()
    if df.empty:
        return 0.0
    prev = df["close"].shift(1).fillna(df["close"])
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"]  - prev).abs(),
    ], axis=1).max(axis=1)
    atr_val = float(tr.rolling(period, min_periods=1).mean().iloc[-1])
    # Safety cap: ATR should not exceed 3% of current price for index instruments
    close = float(df["close"].iloc[-1])
    return min(atr_val, close * 0.03)


def _nearest_strike(chain_df: pd.DataFrame, value: float) -> int:
    strikes = np.array(sorted(chain_df["strike"].unique()))
    return int(strikes[np.argmin(np.abs(strikes - value))])


def _ltp(chain_df: pd.DataFrame, strike: int, opt_type: str) -> float:
    row = chain_df[chain_df["strike"] == strike]
    if row.empty:
        return 0.0
    return float(row["CE_LTP"].iloc[0] if opt_type == "CE" else row["PE_LTP"].iloc[0])


def _iv(chain_df: pd.DataFrame, strike: int, opt_type: str) -> float:
    row = chain_df[chain_df["strike"] == strike]
    if row.empty:
        return 0.0
    return float(row["CE_IV"].iloc[0] if opt_type == "CE" else row["PE_IV"].iloc[0])


def _margin_inr(notional: float, pct: float) -> float:
    return round(notional * pct, -2)   # rounded to nearest ₹100


def _rr_label(risk: float, reward: float) -> str:
    if reward <= 0 or risk <= 0:
        return "N/A"
    ratio = reward / risk
    if ratio >= 2.0:
        return f"1 : {ratio:.1f}  ✅ Favourable"
    elif ratio >= 1.0:
        return f"1 : {ratio:.1f}  ⚠️  Moderate"
    else:
        return f"1 : {ratio:.1f}  ❌ Unfavourable"


# ---------------------------------------------------------------------------
# A) Institutional Logic
# ---------------------------------------------------------------------------

def institutional_trade(
    futures_df: pd.DataFrame,
    chain_df: pd.DataFrame,
    sentiment: dict,
    lot_size: int,
    config: dict,
    budget_inr: float = 150_000,
) -> Dict:
    """
    Build a clean, final institutional-style trade idea.

    Logic
    -----
    • Uses sentiment score + market structure to decide direction.
    • ATR-based stop-loss (1.5 × ATR against trade) and target (2.5 × ATR).
    • Prefers futures for strong-trend regimes; ATM option for moderate.
    • Margin estimate = lot_size × price × FUTURES_MARGIN_PCT.

    Returns
    -------
    dict — ready for display in app.py
    """
    if futures_df.empty or chain_df.empty:
        return {"error": "Insufficient data for institutional trade setup."}

    close   = float(futures_df["close"].iloc[-1])
    atr     = _atr(futures_df)
    score   = sentiment.get("score", 0)
    label   = sentiment.get("label", "Neutral")
    sma_20  = float(futures_df["close"].rolling(20, min_periods=1).mean().iloc[-1])
    sma_50  = float(futures_df["close"].rolling(50, min_periods=1).mean().iloc[-1])
    swing_high = float(futures_df["high"].tail(20).max())
    swing_low  = float(futures_df["low"].tail(20).min())

    # Direction
    if score >= 1:
        direction      = "Long (Bullish)"
        instrument     = "Buy CE (ATM) or Long Futures"
        entry          = round(close, 2)
        sl             = round(close - 1.5 * atr, 2)
        target_1       = round(close + 2.0 * atr, 2)
        target_2       = round(close + 3.0 * atr, 2)
        opt_type       = "CE"
        invalid_cond   = [
            f"Daily close below ₹{sl:,.0f} (SL invalidates the setup)",
            f"Close below 20-day SMA ₹{sma_20:,.0f} with above-average volume",
            "PCR drops sharply below 0.7 (excess bullishness — caution)",
        ]
    elif score <= -1:
        direction      = "Short (Bearish)"
        instrument     = "Buy PE (ATM) or Short Futures"
        entry          = round(close, 2)
        sl             = round(close + 1.5 * atr, 2)
        target_1       = round(close - 2.0 * atr, 2)
        target_2       = round(close - 3.0 * atr, 2)
        opt_type       = "PE"
        invalid_cond   = [
            f"Daily close above ₹{sl:,.0f} (SL invalidates the setup)",
            f"Close above 20-day SMA ₹{sma_20:,.0f} with volume expansion",
            "PCR rises sharply above 1.3 (excessive fear — potential bounce)",
        ]
    else:
        direction      = "Neutral / Wait"
        instrument     = "No directional trade — wait for clearer signal"
        entry          = close
        sl             = round(close - 0.5 * atr, 2)
        target_1       = round(close + 1.0 * atr, 2)
        target_2       = round(close + 1.5 * atr, 2)
        opt_type       = "CE"
        invalid_cond   = [
            "Market remains directionless — any trade here has low edge.",
            "Wait for sentiment score ≥ ±2 before committing capital.",
        ]

    # ATM strike and premium for option alternative
    atm_strike  = _nearest_strike(chain_df, close)
    atm_premium = _ltp(chain_df, atm_strike, opt_type)
    atm_iv_val  = _iv(chain_df, atm_strike, opt_type)
    opt_sl      = round(atm_premium * 0.50, 2)    # 50% premium loss
    opt_target  = round(atm_premium * 2.00, 2)    # double the premium
    opt_invalid = [f"Premium drops to ₹{opt_sl:.2f} (50% stop)", "IV drops sharply after event (IV crush)"]

    # Margin (approximate)
    futures_notional   = close * lot_size
    futures_margin     = _margin_inr(futures_notional, FUTURES_MARGIN_PCT)
    options_buy_margin = round(atm_premium * lot_size, -2)

    # Risk/Reward
    risk   = abs(entry - sl)
    reward = abs(target_1 - entry)

    risk_label = "High" if risk > 2 * atr else ("Medium" if risk > atr else "Low")
    if direction == "Neutral / Wait":
        risk_label = "N/A"

    # Reason
    bullish_facts = " | ".join(sentiment.get("bullish_factors", [])[:2])
    bearish_facts = " | ".join(sentiment.get("bearish_factors", [])[:2])
    reason = bullish_facts if score >= 1 else (bearish_facts if score <= -1 else "No strong directional signal present.")

    time_map = {
        "Strongly Bullish":  "1-3 trading days",
        "Moderately Bullish":"2-4 trading days",
        "Neutral / Sideways":"N/A — wait for signal",
        "Moderately Bearish":"2-4 trading days",
        "Strongly Bearish":  "1-3 trading days",
    }

    return {
        "logic":            "Institutional Trader",
        "direction":        direction,
        "instrument":       instrument,
        # Futures option
        "futures_entry":    f"₹{entry:,.2f}",
        "futures_sl":       f"₹{sl:,.2f}",
        "futures_target1":  f"₹{target_1:,.2f}",
        "futures_target2":  f"₹{target_2:,.2f}",
        "futures_margin":   f"₹{futures_margin:,.0f} (approx, positional)",
        "futures_margin_intraday": f"₹{_margin_inr(futures_notional, FUTURES_MARGIN_PCT * INTRADAY_MARGIN_DISCOUNT):,.0f} (approx, intraday)",
        # Options alternative
        "option_type":      opt_type,
        "option_strike":    atm_strike,
        "option_premium":   f"₹{atm_premium:.2f}",
        "option_iv":        f"{atm_iv_val:.1f}%",
        "option_sl":        f"₹{opt_sl:.2f}",
        "option_target":    f"₹{opt_target:.2f}",
        "option_margin":    f"₹{options_buy_margin:,.0f} (premium × lot)",
        # Summary
        "risk_reward":      _rr_label(risk, reward),
        "risk_level":       risk_label,
        "expected_time":    time_map.get(label, "2-4 trading days"),
        "reason":           reason,
        "invalid_conditions": invalid_cond,
        "sma_20":           f"₹{sma_20:,.0f}",
        "sma_50":           f"₹{sma_50:,.0f}",
        "swing_high":       f"₹{swing_high:,.0f}",
        "swing_low":        f"₹{swing_low:,.0f}",
        "atr":              round(atr, 2),
        "sentiment_label":  label,
        "sentiment_score":  score,
        # Raw numeric for trade logging
        "_entry_price":     atm_premium,
        "_sl_price":        opt_sl,
        "_target_price":    opt_target,
        "_strike":          atm_strike,
        "_opt_type":        opt_type,
        "_direction":       "buy",
        # Budget helpers
        "_margin_per_lot_option":  round(max(atm_premium * lot_size, 1), 0),
        "_margin_per_lot_futures": round(futures_margin, 0),
        "recommended_lots": max(1, int(budget_inr / max(atm_premium * lot_size, 1))),
    }


# ---------------------------------------------------------------------------
# B) Option Seller Logic
# ---------------------------------------------------------------------------

def option_seller_trade(
    futures_df: pd.DataFrame,
    chain_df: pd.DataFrame,
    sentiment: dict,
    option_ideas: list,
    lot_size: int,
    config: dict,
    budget_inr: float = 150_000,
) -> Dict:
    """
    Build a clean, final option-selling trade idea.

    Logic
    -----
    • Picks the best idea from the strategy_builder's option_ideas list.
    • Computes specific strikes, premiums, and rule-based SL/target.
    • Margin: ~20% of total notional of short legs (conservative SPAN proxy).
    • SL: if collected premium doubles (2× entry credit).
    • Target: collect 50% of maximum premium.

    Returns
    -------
    dict — ready for display in app.py
    """
    if chain_df.empty or not option_ideas:
        return {"error": "Insufficient data for option seller trade setup."}

    close   = float(chain_df["spot"].iloc[0])
    atr     = _atr(futures_df) if not futures_df.empty else close * 0.01
    tick    = config["data"]["tick_sizes"].get("NIFTY", 50)

    # Use the first idea from strategy_builder as primary
    idea = option_ideas[0]
    regime_label = idea.fit_conditions

    # Derive specific strikes
    upper_ce_strike = _nearest_strike(chain_df, close + 1.0 * atr)
    lower_pe_strike = _nearest_strike(chain_df, close - 1.0 * atr)
    wing_ce_strike  = _nearest_strike(chain_df, close + 2.0 * atr)
    wing_pe_strike  = _nearest_strike(chain_df, close - 2.0 * atr)

    ce_premium  = _ltp(chain_df, upper_ce_strike, "CE")
    pe_premium  = _ltp(chain_df, lower_pe_strike, "PE")
    ce_wing_p   = _ltp(chain_df, wing_ce_strike,  "CE")
    pe_wing_p   = _ltp(chain_df, wing_pe_strike,  "PE")

    # Gross credit and risk
    gross_credit_ic = (ce_premium + pe_premium) - (ce_wing_p + pe_wing_p)
    gross_credit_ic = max(gross_credit_ic, 0.0)

    strangle_credit = ce_premium + pe_premium
    spread_width    = abs(upper_ce_strike - wing_ce_strike)

    # SL and target for iron condor
    ic_target = round(gross_credit_ic * 0.50, 2)  # 50% credit captured
    ic_sl     = round(gross_credit_ic * 2.00, 2)  # 2× credit lost

    # Margin estimate for iron condor (max loss side × lot_size × 1 lot)
    max_loss_ic   = spread_width - gross_credit_ic
    ic_margin     = _margin_inr(spread_width * lot_size, 1.0)  # full spread width as margin

    # Margin estimate for strangle (both sides, 20% notional)
    notional_ce   = upper_ce_strike * lot_size
    notional_pe   = lower_pe_strike * lot_size
    strangle_margin = _margin_inr((notional_ce + notional_pe) * OPTIONS_SELL_MARGIN_PCT, 1.0)

    # Prefer iron condor if there's enough credit, else strangle
    if gross_credit_ic >= 5.0:
        chosen_name   = "Iron Condor (Defined Risk)"
        short_ce      = upper_ce_strike
        short_pe      = lower_pe_strike
        buy_ce        = wing_ce_strike
        buy_pe        = wing_pe_strike
        credit        = round(gross_credit_ic, 2)
        target        = ic_target
        sl_rule       = f"₹{ic_sl:.2f} net loss OR spot crosses {lower_pe_strike}/{upper_ce_strike}"
        target_rule   = f"₹{ic_target:.2f} profit (50% of credit collected)"
        margin        = f"₹{ic_margin:,.0f} (approx — max-loss spread width)"
        description   = (f"Sell {lower_pe_strike} PE @ ₹{pe_premium:.2f} + "
                         f"Sell {upper_ce_strike} CE @ ₹{ce_premium:.2f}; "
                         f"Buy wings {wing_pe_strike} PE / {wing_ce_strike} CE for protection.")
        time_estimate = "3-8 trading days"
        risk_level    = "Medium"
        invalid       = [
            f"Spot closes beyond {lower_pe_strike} or {upper_ce_strike} with momentum",
            "IV expands sharply after event (doubles short option premium)",
        ]
    else:
        chosen_name   = "Short Strangle"
        short_ce      = upper_ce_strike
        short_pe      = lower_pe_strike
        buy_ce, buy_pe = None, None
        credit        = round(strangle_credit, 2)
        target        = round(strangle_credit * 0.50, 2)
        sl_rule       = f"If premium of either short leg doubles OR total loss > ₹{round(strangle_credit * 2 * lot_size, -2):,.0f}"
        target_rule   = f"₹{round(strangle_credit * 0.50, 2):.2f} net premium decay (50% of collected)"
        margin        = f"₹{strangle_margin:,.0f} (approx — ~20% notional, no hedge)"
        description   = (f"Sell {lower_pe_strike} PE @ ₹{pe_premium:.2f} + "
                         f"Sell {upper_ce_strike} CE @ ₹{ce_premium:.2f}. Uncapped risk setup.")
        time_estimate = "2-6 trading days"
        risk_level    = "High"
        invalid       = [
            f"Spot breaks {lower_pe_strike} or {upper_ce_strike} with volume",
            "Event risk triggers a gap beyond the short strikes",
        ]

    pcr_now = float(sentiment.get("pcr_5d_avg") or 1.0)
    reason = (
        f"Range-bound regime with PCR={pcr_now:.2f}; "
        f"OI walls at {sentiment.get('oi_conc', {}).get('pe_wall', 'N/A')} (support) "
        f"and {sentiment.get('oi_conc', {}).get('ce_wall', 'N/A')} (resistance). "
        f"Time decay works in seller's favour in low-trend environment."
    )

    return {
        "logic":            "Option Seller",
        "strategy":         chosen_name,
        "description":      description,
        "instrument":       "CE + PE (multi-leg)",
        "short_ce_strike":  short_ce,
        "short_pe_strike":  short_pe,
        "buy_ce_strike":    buy_ce,
        "buy_pe_strike":    buy_pe,
        "ce_premium":       f"₹{ce_premium:.2f}",
        "pe_premium":       f"₹{pe_premium:.2f}",
        "total_credit":     f"₹{credit:.2f} per unit",
        "total_credit_lot": f"₹{round(credit * lot_size, 2):,.2f} per lot",
        "sl_rule":          sl_rule,
        "target_rule":      target_rule,
        "risk_level":       risk_level,
        "expected_time":    time_estimate,
        "margin_required":  margin,
        "reason":           reason,
        "fit_conditions":   regime_label,
        "invalid_conditions": invalid,
        "profit_range":     f"₹{lower_pe_strike:,} — ₹{upper_ce_strike:,}  (spot stays in this band)",
        # Raw numeric for trade logging
        "_entry_price":     credit,
        "_sl_price":        round(credit * 2.0, 2),
        "_target_price":    round(credit * 0.5, 2),
        "_strike_ce":       short_ce,
        "_strike_pe":       short_pe,
        "_opt_type":        "CE+PE",
        "_direction":       "sell",
        # Budget helpers
        "_margin_per_lot": round(ic_margin if gross_credit_ic >= 5.0 else strangle_margin, 0),
        "recommended_lots": max(1, int(budget_inr / max(
            (ic_margin if gross_credit_ic >= 5.0 else strangle_margin), 1
        ))),
    }
