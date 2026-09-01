"""
src/option_buyer_strategies.py — Option Buyer & Hedging Strategy Engine
========================================================================

Provides two families of educational, rule-based strategy ideas:

A) OPTION BUYER STRATEGIES
   — For when you want to pay a known, limited premium and profit from a
     directional move or a volatility explosion.
   — Best when IV is LOW (options are cheap) and a big move is expected.

B) HEDGING / CONSERVATIVE STRATEGIES
   — Focus: minimum loss, defined risk, small but reliable return.
   — These are credit-spread and hybrid setups where TIME DECAY works for you.
   — Best when IV is HIGH (you collect rich premium) and you expect stability.

Key educational concepts embedded in every strategy:
   • When to use it (market conditions, IV level, PCR context)
   • Strike selection rationale
   • Breakeven move required (how much the market must move to profit)
   • Win probability intuition
   • Primary risk

⚠️  PAPER-TRADE / STUDY ONLY.
    No real orders. No broker connectivity. All figures are approximations.
    Verify actual premiums, margins, and rules with your broker before any trade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.option_buyer_strategies")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BuyerStrategyIdea:
    strategy_name:     str
    category:          str   # Directional | Event-Driven | Hedging | Income
    direction:         str   # Bullish | Bearish | Neutral/Big Move | Neutral/Stable
    instrument:        str   # CE | PE | CE+PE | Futures+CE | Futures+PE
    strikes_desc:      str   # human-readable description of strike selection
    entry_price:       str
    stop_loss_rule:    str
    target_rule:       str
    max_loss_per_lot:  str
    max_gain_per_lot:  str
    breakeven_move_pct:str   # % market must move to reach breakeven
    win_condition:     str
    when_to_use:       str
    iv_preference:     str   # Buy low IV | Sell/collect high IV
    risk_level:        str   # Low | Medium | High
    expected_time:     str
    margin_required:   str
    greeks_note:       str
    main_risks:        str
    # raw numerics for logging
    _entry:   float = field(default=0.0, repr=False)
    _sl:      float = field(default=0.0, repr=False)
    _target:  float = field(default=0.0, repr=False)
    _strike:  int   = field(default=0,   repr=False)
    _opt_type:str   = field(default="CE",repr=False)
    _direction_code: str = field(default="buy", repr=False)


@dataclass
class HedgingStrategyIdea:
    strategy_name:     str
    category:          str   # Credit Spread | Calendar | Covered | Protective
    direction:         str   # Neutral | Bullish | Bearish
    instrument:        str
    strikes_desc:      str
    net_credit_or_debit: str # positive = net credit (income); negative = net debit (cost)
    entry_description: str
    sl_rule:           str
    target_rule:       str
    max_loss_per_lot:  str
    max_gain_per_lot:  str
    win_probability_note: str   # qualitative edge description
    when_to_use:       str
    market_conditions: str
    iv_preference:     str
    expected_time:     str
    margin_required:   str
    greeks_note:       str
    main_risks:        str


# ---------------------------------------------------------------------------
# Internal helpers (shared with final_trade_decision but kept self-contained)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    prev = df["close"].shift(1).fillna(df["close"])
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"]  - prev).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period, min_periods=1).mean().iloc[-1])


def _nearest(chain_df: pd.DataFrame, value: float) -> int:
    arr = np.array(sorted(chain_df["strike"].unique()))
    return int(arr[np.argmin(np.abs(arr - value))])


def _ltp(chain_df: pd.DataFrame, strike: int, opt_type: str) -> float:
    row = chain_df[chain_df["strike"] == strike]
    if row.empty:
        return 0.05
    return max(float(row["CE_LTP"].iloc[0] if opt_type == "CE" else row["PE_LTP"].iloc[0]), 0.05)


def _iv_at(chain_df: pd.DataFrame, strike: int, opt_type: str) -> float:
    row = chain_df[chain_df["strike"] == strike]
    if row.empty:
        return 16.0
    return float(row["CE_IV"].iloc[0] if opt_type == "CE" else row["PE_IV"].iloc[0])


def _pct_move(spot: float, strike: float) -> str:
    if spot <= 0:
        return "N/A"
    return f"{abs((strike - spot) / spot) * 100:.1f}%"


# ---------------------------------------------------------------------------
# A) Option Buyer Strategies
# ---------------------------------------------------------------------------

def generate_buyer_strategies(
    chain_df: pd.DataFrame,
    futures_df: pd.DataFrame,
    sentiment: dict,
    lot_size: int,
    config: dict,
) -> List[BuyerStrategyIdea]:
    """
    Generate 4–6 educational option-buying setups.

    Logic
    -----
    1. Assess IV level (low IV → cheap options → buying is better value).
    2. Assess trend/sentiment to pick direction.
    3. Provide directional, event-driven, and spread alternatives.

    Rule of thumb taught here:
    • Buy options when ATM IV < 18% (below average)
    • Use spreads when you are moderately directional (better cost efficiency)
    • Use straddles/strangles when expecting a large move but unsure of direction
    """
    if chain_df.empty or futures_df.empty:
        return []

    spot   = float(chain_df["spot"].iloc[0])
    atr    = _atr(futures_df)
    score  = sentiment.get("score", 0)
    label  = sentiment.get("label", "Neutral")

    atm    = _nearest(chain_df, spot)
    otm_c1 = _nearest(chain_df, spot + 1.0 * atr)  # 1-ATR OTM call
    otm_p1 = _nearest(chain_df, spot - 1.0 * atr)  # 1-ATR OTM put
    otm_c2 = _nearest(chain_df, spot + 2.0 * atr)  # 2-ATR OTM call (wing)
    otm_p2 = _nearest(chain_df, spot - 2.0 * atr)  # 2-ATR OTM put (wing)

    # Premiums
    atm_ce = _ltp(chain_df, atm, "CE")
    atm_pe = _ltp(chain_df, atm, "PE")
    otm_ce = _ltp(chain_df, otm_c1, "CE")
    otm_pe = _ltp(chain_df, otm_p1, "PE")
    far_ce = _ltp(chain_df, otm_c2, "CE")
    far_pe = _ltp(chain_df, otm_p2, "PE")

    atm_iv = _iv_at(chain_df, atm, "CE")
    iv_note = "cheap (good time to buy)" if atm_iv < 18 else "elevated (consider spreads to reduce cost)"

    ideas: List[BuyerStrategyIdea] = []

    # --- 1. Directional Long Call ---
    ce_sl     = round(atm_ce * 0.50, 2)
    ce_target = round(atm_ce * 2.00, 2)
    ce_margin = round(atm_ce * lot_size, -2)
    ideas.append(BuyerStrategyIdea(
        strategy_name="Long Call (Directional Buy)",
        category="Directional",
        direction="Bullish",
        instrument="CE",
        strikes_desc=f"ATM Call @ {atm}",
        entry_price=f"₹{atm_ce:.2f}  (ATM IV: {atm_iv:.1f}% — {iv_note})",
        stop_loss_rule=f"Exit if premium falls to ₹{ce_sl:.2f} (50% of entry). Strict rule.",
        target_rule=f"Book at ₹{ce_target:.2f} (2× entry premium) or when spot approaches resistance.",
        max_loss_per_lot=f"₹{round(atm_ce * lot_size, 0):,.0f} (entire premium if option expires worthless)",
        max_gain_per_lot="Unlimited (spot can rise without bound)",
        breakeven_move_pct=f"Spot must rise > ₹{atm + atm_ce:.0f} ({_pct_move(spot, atm + atm_ce)}) by expiry",
        win_condition="Spot closes above breakeven point at expiry, OR premium doubles before expiry.",
        when_to_use="Strong bullish signal (score ≥ 2), low IV, clear trend above 20-day SMA.",
        iv_preference="BUY when ATM IV < 18%. Avoid buying when IV > 22% (expensive).",
        risk_level="Medium",
        expected_time="1-4 trading days (close before expiry to avoid rapid theta decay)",
        margin_required=f"₹{ce_margin:,.0f} (premium only — no SPAN margin for buyers)",
        greeks_note="Delta ~0.5 (moves ₹0.50 per ₹1 spot move). Theta is your enemy: you lose ~₹{:.0f}/day even if spot is flat.".format(atm_ce * 0.03),
        main_risks="Time decay (theta) erodes value daily. IV crush after event (premium drops). Wrong direction.",
        _entry=atm_ce, _sl=ce_sl, _target=ce_target, _strike=atm, _opt_type="CE", _direction_code="buy",
    ))

    # --- 2. Directional Long Put ---
    pe_sl     = round(atm_pe * 0.50, 2)
    pe_target = round(atm_pe * 2.00, 2)
    pe_margin = round(atm_pe * lot_size, -2)
    ideas.append(BuyerStrategyIdea(
        strategy_name="Long Put (Directional Buy)",
        category="Directional",
        direction="Bearish",
        instrument="PE",
        strikes_desc=f"ATM Put @ {atm}",
        entry_price=f"₹{atm_pe:.2f}  (ATM IV: {atm_iv:.1f}% — {iv_note})",
        stop_loss_rule=f"Exit if premium falls to ₹{pe_sl:.2f} (50% of entry). No averaging down.",
        target_rule=f"Book at ₹{pe_target:.2f} (2× entry) or when spot approaches support level.",
        max_loss_per_lot=f"₹{round(atm_pe * lot_size, 0):,.0f} (premium only)",
        max_gain_per_lot=f"Up to ₹{round(atm * lot_size, 0):,.0f} (if spot goes to zero, theoretical max)",
        breakeven_move_pct=f"Spot must fall below ₹{atm - atm_pe:.0f} ({_pct_move(spot, atm - atm_pe)}) by expiry",
        win_condition="Spot closes below breakeven at expiry, OR premium doubles intraday.",
        when_to_use="Strong bearish signal (score ≤ -2), low IV, price below 20/50-day SMA with volume.",
        iv_preference="BUY when ATM IV < 18%. Note: put IV is usually slightly higher than call IV (put skew).",
        risk_level="Medium",
        expected_time="1-4 trading days",
        margin_required=f"₹{pe_margin:,.0f} (premium only)",
        greeks_note=f"Delta ~ -0.5 (moves ₹0.50 for ₹1 fall). Theta ~-₹{atm_pe * 0.03:.0f}/day.",
        main_risks="Theta decay, wrong direction, IV crush post-event.",
        _entry=atm_pe, _sl=pe_sl, _target=pe_target, _strike=atm, _opt_type="PE", _direction_code="buy",
    ))

    # --- 3. Bull Call Spread (moderately bullish, REDUCED COST) ---
    spread_cost  = round(atm_ce - otm_ce, 2)
    spread_width = abs(otm_c1 - atm)
    spread_max_profit = round((spread_width - spread_cost) * lot_size, -2)
    spread_max_loss   = round(spread_cost * lot_size, -2)
    spread_sl    = round(spread_cost * 0.60, 2)   # 60% of debit paid
    ideas.append(BuyerStrategyIdea(
        strategy_name="Bull Call Spread (Debit Spread)",
        category="Directional — Reduced Cost",
        direction="Moderately Bullish",
        instrument="CE",
        strikes_desc=f"Buy {atm} CE @ ₹{atm_ce:.2f} | Sell {otm_c1} CE @ ₹{otm_ce:.2f}",
        entry_price=f"Net debit: ₹{spread_cost:.2f} per unit  (vs ₹{atm_ce:.2f} for naked call)",
        stop_loss_rule=f"Exit if net debit position loses ₹{spread_sl:.2f} (60% of paid). Or spot falls below 20-day SMA.",
        target_rule=f"Max profit at or above {otm_c1}: ₹{round(spread_width - spread_cost, 2):.2f}/unit. Book near expiry if near top strike.",
        max_loss_per_lot=f"₹{spread_max_loss:,.0f} (net debit paid)",
        max_gain_per_lot=f"₹{spread_max_profit:,.0f} (width minus cost)",
        breakeven_move_pct=f"Spot must reach ₹{atm + spread_cost:.0f} ({_pct_move(spot, atm + spread_cost)}) to breakeven",
        win_condition=f"Spot above ₹{atm + spread_cost:.0f} at expiry. Full profit if above {otm_c1}.",
        when_to_use="Moderately bullish view. Reduces entry cost by ~{:.0f}% vs naked call.".format((otm_ce / atm_ce) * 100),
        iv_preference="Works in any IV environment. Cap on upside means you don't need low IV like naked call.",
        risk_level="Low",
        expected_time="3-10 trading days (hold to expiry or near target)",
        margin_required=f"₹{spread_max_loss:,.0f} (net debit, no additional SPAN for defined-risk buyers)",
        greeks_note="Net delta ~0.3 (less sensitive than naked call). Theta partially neutralised by short leg.",
        main_risks="Capped profit — you cap your upside. If market surges, you only earn spread width.",
        _entry=spread_cost, _sl=spread_sl, _target=round(spread_width - spread_cost, 2),
        _strike=atm, _opt_type="CE", _direction_code="buy",
    ))

    # --- 4. Bear Put Spread ---
    put_spread_cost = round(atm_pe - otm_pe, 2)
    put_width       = abs(atm - otm_p1)
    put_max_profit  = round((put_width - put_spread_cost) * lot_size, -2)
    put_max_loss    = round(put_spread_cost * lot_size, -2)
    put_sl          = round(put_spread_cost * 0.60, 2)
    ideas.append(BuyerStrategyIdea(
        strategy_name="Bear Put Spread (Debit Spread)",
        category="Directional — Reduced Cost",
        direction="Moderately Bearish",
        instrument="PE",
        strikes_desc=f"Buy {atm} PE @ ₹{atm_pe:.2f} | Sell {otm_p1} PE @ ₹{otm_pe:.2f}",
        entry_price=f"Net debit: ₹{put_spread_cost:.2f} per unit",
        stop_loss_rule=f"Exit if debit position loses ₹{put_sl:.2f} (60% of paid). Or spot reclaims 20-day SMA.",
        target_rule=f"Max profit at or below {otm_p1}: ₹{round(put_width - put_spread_cost, 2):.2f}/unit.",
        max_loss_per_lot=f"₹{put_max_loss:,.0f}",
        max_gain_per_lot=f"₹{put_max_profit:,.0f}",
        breakeven_move_pct=f"Spot must fall to ₹{atm - put_spread_cost:.0f} ({_pct_move(spot, atm - put_spread_cost)}) to breakeven",
        win_condition=f"Spot below ₹{atm - put_spread_cost:.0f} at expiry.",
        when_to_use="Moderately bearish view. Good cost-to-risk alternative to naked put.",
        iv_preference="Works in any IV. More efficient than naked put in high-IV environments.",
        risk_level="Low",
        expected_time="3-10 trading days",
        margin_required=f"₹{put_max_loss:,.0f} (net debit only)",
        greeks_note="Net delta ~ -0.3. Theta partially offset. Less IV sensitivity than naked put.",
        main_risks="Capped downside profit. Market reversal from key support levels.",
        _entry=put_spread_cost, _sl=put_sl, _target=round(put_width - put_spread_cost, 2),
        _strike=atm, _opt_type="PE", _direction_code="buy",
    ))

    # --- 5. Long Straddle (event-driven, big move either way) ---
    straddle_cost    = round(atm_ce + atm_pe, 2)
    straddle_sl      = round(straddle_cost * 0.30, 2)   # exit if 30% of total cost is lost
    straddle_target  = round(straddle_cost * 1.50, 2)
    straddle_margin  = round(straddle_cost * lot_size, -2)
    upper_be         = atm + straddle_cost
    lower_be         = atm - straddle_cost
    ideas.append(BuyerStrategyIdea(
        strategy_name="Long Straddle (Event Play)",
        category="Event-Driven",
        direction="Neutral / Big Move Expected",
        instrument="CE + PE",
        strikes_desc=f"Buy ATM {atm} CE @ ₹{atm_ce:.2f} AND {atm} PE @ ₹{atm_pe:.2f}",
        entry_price=f"₹{straddle_cost:.2f} total cost per unit",
        stop_loss_rule=f"Exit if total value drops below ₹{straddle_sl:.2f} (lost 30% of combined premium).",
        target_rule=f"Exit whichever side gains 80-100%. Target ₹{straddle_target:.2f} total. Close before expiry.",
        max_loss_per_lot=f"₹{round(straddle_cost * lot_size, 0):,.0f} (if spot stays exactly at {atm})",
        max_gain_per_lot="Unlimited on CE side | Large on PE side",
        breakeven_move_pct=f"Need spot above ₹{upper_be:.0f} (+{_pct_move(spot, upper_be)}) OR below ₹{lower_be:.0f} (-{_pct_move(spot, lower_be)})",
        win_condition="A large directional move in either direction before expiry.",
        when_to_use="Before major events: RBI policy, budget, election result, earnings (if applicable). Buy when IV is STILL LOW.",
        iv_preference="MUST buy before IV spikes. If IV is already high (≥22%), straddle is very expensive — consider strangle instead.",
        risk_level="High",
        expected_time="Enter 3-5 days before event. Exit on or after event day.",
        margin_required=f"₹{straddle_margin:,.0f} (combined premiums, no SPAN for buyers)",
        greeks_note="Net delta ~0 (neutral). Very high Vega — profits if IV rises. High negative theta — time decay hurts rapidly.",
        main_risks="IV crush after event (premiums collapse even if market moves). Insufficient movement.",
        _entry=straddle_cost, _sl=straddle_sl, _target=straddle_target,
        _strike=atm, _opt_type="CE+PE", _direction_code="buy",
    ))

    # --- 6. OTM Strangle (cheaper event play, bigger move needed) ---
    strangle_cost   = round(otm_ce + otm_pe, 2)
    strangle_sl     = round(strangle_cost * 0.35, 2)
    strangle_target = round(strangle_cost * 2.00, 2)
    strangle_margin = round(strangle_cost * lot_size, -2)
    ideas.append(BuyerStrategyIdea(
        strategy_name="Long Strangle (Cheaper Event Play)",
        category="Event-Driven",
        direction="Neutral / Very Large Move Expected",
        instrument="CE + PE (OTM)",
        strikes_desc=f"Buy {otm_c1} CE @ ₹{otm_ce:.2f} AND {otm_p1} PE @ ₹{otm_pe:.2f}",
        entry_price=f"₹{strangle_cost:.2f} total cost ({round((1 - strangle_cost/straddle_cost)*100):.0f}% cheaper than straddle)",
        stop_loss_rule=f"Exit if total value drops below ₹{strangle_sl:.2f} (35% of cost lost).",
        target_rule=f"Target ₹{strangle_target:.2f} (2× cost). Exit winning side when doubled.",
        max_loss_per_lot=f"₹{round(strangle_cost * lot_size, 0):,.0f}",
        max_gain_per_lot="Large (smaller delta than straddle, needs bigger move)",
        breakeven_move_pct=f"Need spot above ₹{otm_c1 + strangle_cost:.0f} (+{_pct_move(spot, otm_c1 + strangle_cost)}) OR below ₹{otm_p1 - strangle_cost:.0f} (-{_pct_move(spot, otm_p1 - strangle_cost)})",
        win_condition="A very large move in either direction. Better than straddle when move is expected to be huge.",
        when_to_use="Same as straddle but when you expect an extreme move or want lower absolute cost.",
        iv_preference="Buy when IV < 18%. OTM options are hit hardest by IV crush.",
        risk_level="High",
        expected_time="Enter before event. Exit on event day or next.",
        margin_required=f"₹{strangle_margin:,.0f}",
        greeks_note="Very low delta (OTM options). Very high Vega sensitivity. Rapid theta decay.",
        main_risks="Needs a much bigger move than straddle to profit. IV crush is devastating.",
        _entry=strangle_cost, _sl=strangle_sl, _target=strangle_target,
        _strike=otm_c1, _opt_type="CE+PE", _direction_code="buy",
    ))

    return ideas


# ---------------------------------------------------------------------------
# B) Hedging / Conservative Strategies (Min Loss, Guaranteed Small Return)
# ---------------------------------------------------------------------------

def generate_hedging_strategies(
    chain_df: pd.DataFrame,
    futures_df: pd.DataFrame,
    sentiment: dict,
    lot_size: int,
    config: dict,
) -> List[HedgingStrategyIdea]:
    """
    Generate 4-5 conservative strategy ideas focused on:
    • Defined maximum loss
    • High probability of small gain
    • Time decay working FOR you
    • Structured risk/reward suitable for learners

    Core insight: these strategies SELL overpriced optionality while
    BUYING cheaper further-OTM options as insurance.
    The result: high win probability, small but reliable income.
    """
    if chain_df.empty or futures_df.empty:
        return []

    spot  = float(chain_df["spot"].iloc[0])
    atr   = _atr(futures_df)
    atm   = _nearest(chain_df, spot)
    score = sentiment.get("score", 0)

    # Strike helpers
    sell_c = _nearest(chain_df, spot + 0.8 * atr)   # ~1 ATR OTM call (sell)
    buy_c  = _nearest(chain_df, spot + 1.8 * atr)   # ~2 ATR wing call (buy)
    sell_p = _nearest(chain_df, spot - 0.8 * atr)   # ~1 ATR OTM put (sell)
    buy_p  = _nearest(chain_df, spot - 1.8 * atr)   # ~2 ATR wing put (buy)

    # Premiums
    sc_p   = _ltp(chain_df, sell_c, "CE")
    bc_p   = _ltp(chain_df, buy_c,  "CE")
    sp_p   = _ltp(chain_df, sell_p, "PE")
    bp_p   = _ltp(chain_df, buy_p,  "PE")
    atm_ce = _ltp(chain_df, atm, "CE")
    atm_pe = _ltp(chain_df, atm, "PE")
    atm_iv = _iv_at(chain_df, atm, "CE")

    ideas: List[HedgingStrategyIdea] = []

    # ---------------------------------------------------------------
    # 1. Bull Put Credit Spread ⭐ (BEST for "guaranteed small return")
    # ---------------------------------------------------------------
    bps_credit      = round(sp_p - bp_p, 2)
    bps_spread_width = abs(sell_p - buy_p)
    bps_max_loss    = round((bps_spread_width - bps_credit) * lot_size, -2)
    bps_max_gain    = round(bps_credit * lot_size, -2)
    bps_win_prob    = f"~{min(75, 50 + int(abs(spot - sell_p) / atr * 20)):.0f}% (spot stays above {sell_p})"

    ideas.append(HedgingStrategyIdea(
        strategy_name="⭐ Bull Put Credit Spread (Best Small-Return Strategy)",
        category="Credit Spread",
        direction="Neutral to Bullish",
        instrument="PE",
        strikes_desc=(f"SELL {sell_p} PE @ ₹{sp_p:.2f}  +  BUY {buy_p} PE @ ₹{bp_p:.2f} (protection)"),
        net_credit_or_debit=f"NET CREDIT: ₹{bps_credit:.2f} per unit  →  ₹{bps_max_gain:,.0f} per lot (YOUR INCOME)",
        entry_description=(
            f"Sell the {sell_p} put (collect ₹{sp_p:.2f}) and simultaneously buy the {buy_p} put "
            f"(pay ₹{bp_p:.2f}) as insurance. Net you RECEIVE ₹{bps_credit:.2f} upfront."
        ),
        sl_rule=(f"Exit entire spread if net loss reaches ₹{round(bps_credit * 1.5 * lot_size, -2):,.0f} "
                 f"(1.5× credit collected) or if spot closes below {sell_p}."),
        target_rule=(f"Keep full credit ₹{bps_max_gain:,.0f} if spot stays above {sell_p} at expiry. "
                     f"Also close for 70-80% credit if 3-5 days before expiry."),
        max_loss_per_lot=f"₹{bps_max_loss:,.0f} (capped — spread width minus credit)",
        max_gain_per_lot=f"₹{bps_max_gain:,.0f} (full credit — earned if spot stays above {sell_p})",
        win_probability_note=bps_win_prob,
        when_to_use=(
            "Market is neutral to bullish. PCR elevated (bearish sentiment = contrarian buy). "
            f"Spot well above {sell_p} support zone."
        ),
        market_conditions=(
            f"Best in Range-Bound or Uptrend regime. Spot above 20-day SMA. "
            f"PCR > 0.9 (market not overly bullish). IV ≥ 15% to collect good premium."
        ),
        iv_preference="SELL when IV ≥ 15-18%. Higher IV = richer premiums collected.",
        expected_time="5-15 trading days (hold to expiry or close at 70-80% profit)",
        margin_required=f"₹{round(bps_spread_width * lot_size, -2):,.0f} (spread width × lot = max risk capital)",
        greeks_note=(
            "Positive theta (you earn every day). Negative vega (IV rise hurts). "
            "Near-zero delta (neutral). Theta works like clockwork if spot stays in range."
        ),
        main_risks="Sharp downside gap below both strikes. IV explosion after macro event.",
    ))

    # ---------------------------------------------------------------
    # 2. Bear Call Credit Spread ⭐
    # ---------------------------------------------------------------
    bcs_credit      = round(sc_p - bc_p, 2)
    bcs_spread_width = abs(buy_c - sell_c)
    bcs_max_loss    = round((bcs_spread_width - bcs_credit) * lot_size, -2)
    bcs_max_gain    = round(bcs_credit * lot_size, -2)

    ideas.append(HedgingStrategyIdea(
        strategy_name="⭐ Bear Call Credit Spread (Small Return, Capped Risk)",
        category="Credit Spread",
        direction="Neutral to Bearish",
        instrument="CE",
        strikes_desc=f"SELL {sell_c} CE @ ₹{sc_p:.2f}  +  BUY {buy_c} CE @ ₹{bc_p:.2f} (protection)",
        net_credit_or_debit=f"NET CREDIT: ₹{bcs_credit:.2f} per unit  →  ₹{bcs_max_gain:,.0f} per lot",
        entry_description=(
            f"Sell {sell_c} call (collect ₹{sc_p:.2f}), buy {buy_c} call (pay ₹{bc_p:.2f}). "
            f"You keep ₹{bcs_credit:.2f} if market stays below {sell_c} at expiry."
        ),
        sl_rule=(f"Exit if net loss exceeds ₹{round(bcs_credit * 1.5 * lot_size, -2):,.0f} or spot closes above {sell_c}."),
        target_rule=f"Keep full credit if spot below {sell_c} at expiry. Close early at 70% profit.",
        max_loss_per_lot=f"₹{bcs_max_loss:,.0f}",
        max_gain_per_lot=f"₹{bcs_max_gain:,.0f}",
        win_probability_note=f"~{min(75, 50 + int(abs(sell_c - spot) / atr * 20)):.0f}% (spot stays below {sell_c})",
        when_to_use="Market neutral to bearish or at resistance. Spot below key OI resistance level.",
        market_conditions=(
            f"Best when {sell_c} is at or above strong CE OI wall (resistance). "
            "Market in downtrend or range. High IV for richer premium."
        ),
        iv_preference="SELL when IV ≥ 15%. Higher IV = better premium collected.",
        expected_time="5-15 trading days",
        margin_required=f"₹{round(bcs_spread_width * lot_size, -2):,.0f}",
        greeks_note="Positive theta (earn daily decay). Negative vega (IV increase hurts). Net short delta.",
        main_risks="Sharp rally above short call strike. Strong bullish breakout on volume.",
    ))

    # ---------------------------------------------------------------
    # 3. Iron Condor (Range — Both Sides Covered) ⭐
    # ---------------------------------------------------------------
    ic_credit = round((sc_p - bc_p) + (sp_p - bp_p), 2)
    ic_width  = max(abs(sell_c - buy_c), abs(sell_p - buy_p))
    ic_margin = round(ic_width * lot_size, -2)
    ic_gain   = round(ic_credit * lot_size, -2)
    ic_loss   = round((ic_width - ic_credit) * lot_size, -2)

    ideas.append(HedgingStrategyIdea(
        strategy_name="⭐ Iron Condor (Range-Bound Income)",
        category="Credit Spread — Both Sides",
        direction="Neutral / Range-Bound",
        instrument="CE + PE",
        strikes_desc=(
            f"Sell {sell_p} PE @ ₹{sp_p:.2f}  |  Sell {sell_c} CE @ ₹{sc_p:.2f}  |  "
            f"Buy wings {buy_p} PE / {buy_c} CE"
        ),
        net_credit_or_debit=f"NET CREDIT: ₹{max(ic_credit, 0):.2f}/unit  →  ₹{ic_gain:,.0f}/lot income",
        entry_description=(
            f"Four-leg strategy: collect premium from both sides (CE and PE) while buying "
            f"wings for protection. Profitable if spot stays between {sell_p} and {sell_c}."
        ),
        sl_rule=(f"Exit the breached side if loss exceeds 1.5× credit collected from that side. "
                 f"Or exit full condor if total loss reaches ₹{round(ic_credit * 1.5 * lot_size, -2):,.0f}."),
        target_rule=f"Close at 50-60% of total credit (₹{round(ic_credit * 0.55 * lot_size, -2):,.0f}). Ideal: 5-8 days before expiry.",
        max_loss_per_lot=f"₹{ic_loss:,.0f} (worst-case if spot beyond wings)",
        max_gain_per_lot=f"₹{ic_gain:,.0f} (full credit if spot stays in range {sell_p}–{sell_c})",
        win_probability_note=f"~65-70% (spot stays in {sell_p}–{sell_c} range)",
        when_to_use="Range-bound market, no major events expected. Expiry week is classic iron condor time.",
        market_conditions="Low trend strength. OI walls visible on both sides in option chain. IV ≥ 14%.",
        iv_preference="Best when IV ≥ 16% — both legs collect meaningful premium.",
        expected_time="5-10 trading days (expiry week ideal)",
        margin_required=f"₹{ic_margin:,.0f} (max-loss wing × lot size)",
        greeks_note="Net positive theta (best friend). Net negative vega (IV rise hurts). Near-zero delta.",
        main_risks="Strong breakout beyond the sold strikes. Gap risk on expiry day.",
    ))

    # ---------------------------------------------------------------
    # 4. Covered Call on Long Futures (Income on existing position)
    # ---------------------------------------------------------------
    cc_premium = round(sc_p * lot_size, -2)

    ideas.append(HedgingStrategyIdea(
        strategy_name="Covered Call on Futures (Weekly Income)",
        category="Income / Covered Strategy",
        direction="Neutral to Mildly Bullish",
        instrument="Long Futures + Short CE",
        strikes_desc=f"Hold long futures entry ~₹{spot:,.0f}  +  SELL {sell_c} CE @ ₹{sc_p:.2f}",
        net_credit_or_debit=f"Premium income: ₹{sc_p:.2f}/unit → ₹{cc_premium:,.0f}/lot per expiry",
        entry_description=(
            f"If you already hold (or plan to hold) a long futures position, sell the {sell_c} "
            f"OTM call every expiry cycle to collect ₹{sc_p:.2f} income. "
            f"This 'rents out' your futures position."
        ),
        sl_rule=(f"Exit the call if it doubles (reaches ₹{sc_p * 2:.2f}). "
                 f"Exit the futures if spot falls below {sell_p} (your futures SL level)."),
        target_rule=f"Keep full ₹{sc_p:.2f} premium if spot stays below {sell_c} at expiry. Repeat each cycle.",
        max_loss_per_lot=f"Futures: large (if market falls). Call premium: ₹{cc_premium:,.0f} income partially offsets.",
        max_gain_per_lot=f"₹{round((sell_c - spot + sc_p) * lot_size, -2):,.0f} (capped at sell_c strike + premium)",
        win_probability_note=f"~70% chance of keeping full premium if {sell_c} is OTM",
        when_to_use="You hold a long futures position and want to generate regular income. Market range-bound to mildly bullish.",
        market_conditions="Neutral to bullish. High IV preferred. Use 1 ATR OTM call to give enough room.",
        iv_preference="SELL when IV ≥ 15%. The higher the IV, the more income you collect.",
        expected_time="One expiry cycle (weekly or monthly). Repeat every cycle.",
        margin_required=f"Futures SPAN margin (see Tab 5 for estimate). Call margin offsets slightly.",
        greeks_note="Futures: delta 1. Short call: delta ~ -0.3. Net delta ~0.7 (reduced market exposure). Positive theta.",
        main_risks="Big rally — you lose upside above sell_c. Big fall — futures loss not fully covered by call premium.",
    ))

    # ---------------------------------------------------------------
    # 5. Protective Put (Insurance Hedge on Long Position)
    # ---------------------------------------------------------------
    otm_p1  = sell_p   # ~0.8 ATR OTM put strike — reasonable insurance level
    otm_pe  = sp_p     # premium at that strike
    pp_cost    = otm_pe
    pp_margin  = round(pp_cost * lot_size, -2)

    ideas.append(HedgingStrategyIdea(
        strategy_name="Protective Put (Insurance Hedge)",
        category="Protective / Insurance",
        direction="Bullish with Downside Insurance",
        instrument="Long Futures + Buy PE",
        strikes_desc=f"Hold long futures ~₹{spot:,.0f}  +  BUY {otm_p1} PE @ ₹{otm_pe:.2f} (insurance)",
        net_credit_or_debit=f"NET COST: ₹{otm_pe:.2f}/unit → ₹{pp_margin:,.0f}/lot (insurance premium)",
        entry_description=(
            f"Protect an existing long position by buying the {otm_p1} put as insurance. "
            f"If market falls below {otm_p1}, the put gains value and offsets your futures loss. "
            f"Think of it as paying ₹{otm_pe:.2f} to insure against a crash."
        ),
        sl_rule="There is no traditional SL — the put IS your SL. Let the put handle downside.",
        target_rule=f"Profit from futures rise. The put expires worthless (₹{pp_margin:,.0f} cost = insurance premium paid).",
        max_loss_per_lot=f"₹{round((spot - otm_p1 + otm_pe) * lot_size, -2):,.0f} (capped at futures entry minus put strike)",
        max_gain_per_lot="Unlimited on upside (futures gains dominate)",
        win_probability_note="High — you have unlimited upside and known, capped downside.",
        when_to_use=(
            "You are bullish but worried about a sudden downside shock (event risk, global cues). "
            "Pay a small insurance cost to sleep well."
        ),
        market_conditions="Pre-event holding period. Volatile periods. Overnight positions during uncertainty.",
        iv_preference="This is a BUYING strategy — prefer low IV. If IV is high, the insurance is expensive.",
        expected_time="Hold through expiry or until the fear event passes",
        margin_required=f"Futures SPAN margin + ₹{pp_margin:,.0f} put premium",
        greeks_note="Futures delta = 1, Put delta ~ -0.3. Net delta ~0.7. Vega positive (gains if IV rises). Theta negative.",
        main_risks="Insurance cost erodes if market stays flat and put expires worthless. IV crush lowers put value.",
    ))

    return ideas


# ---------------------------------------------------------------------------
# Regime assessment for buyer strategies
# ---------------------------------------------------------------------------

def assess_buyer_regime(
    futures_df: pd.DataFrame,
    chain_df: pd.DataFrame,
    sentiment: dict,
) -> Dict:
    """
    Determine which category of buyer strategy is most appropriate now.

    Returns a guidance dict for the UI.
    """
    if futures_df.empty or chain_df.empty:
        return {"guidance": "Insufficient data", "preferred": "None"}

    atm    = _nearest(chain_df, float(chain_df["spot"].iloc[0]))
    atm_iv = _iv_at(chain_df, atm, "CE")
    score  = sentiment.get("score", 0)
    label  = sentiment.get("label", "Neutral")

    if atm_iv < 16:
        iv_guidance = "✅ IV is LOW — good time to BUY options (cheap)"
    elif atm_iv < 20:
        iv_guidance = "⚠️  IV is MODERATE — use spreads to reduce cost"
    else:
        iv_guidance = "❌ IV is HIGH — options are EXPENSIVE; selling strategies preferred"

    if abs(score) >= 2:
        strategy_guidance = "Strong directional signal → prefer directional Long Call/Put or spread"
    elif abs(score) == 1:
        strategy_guidance = "Moderate signal → prefer Bull/Bear spread (lower cost)"
    else:
        strategy_guidance = "No clear direction → prefer straddle/strangle before event, or hedging strategies"

    return {
        "atm_iv":           round(atm_iv, 2),
        "iv_guidance":      iv_guidance,
        "strategy_guidance":strategy_guidance,
        "sentiment":        label,
        "score":            score,
    }
