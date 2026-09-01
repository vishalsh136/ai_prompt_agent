"""
src/institutional_view.py — Institutional-style market analytics
================================================================

What this module does
---------------------
Mimics the kind of analysis that a futures desk or proprietary trading firm
might run when looking at an index (e.g., NIFTY).  It is entirely rule-based
and deterministic — there is no ML or "AI magic" behind the commentary.

Analyses implemented
--------------------
1. Moving averages (20-, 50-, 200-day) with trend classification.
2. Average True Range (ATR) — a measure of daily price volatility.
3. Volume and OI trend analysis — confirms or denies a price trend.
4. Option chain structure — Max Pain, PCR from chain, IV skew, OI distribution.
5. Sentiment score — aggregates the signals above into a single label.
6. Key support/resistance levels — derived from option chain OI concentration.

Educational notes are embedded in every method's docstring.

⚠️  DISCLAIMER: The generated "institutional view" is a STUDY EXERCISE.
    It does NOT reflect actual institutional order flow, research, or advice.
    Do NOT trade based on this output.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.institutional_view")


class InstitutionalAnalyzer:
    """
    Runs institutional-style analytics on futures and options data.

    Parameters
    ----------
    config : dict
        Parsed config.yaml (from utils.get_config()).
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self.rf_rate = config["market"]["risk_free_rate"]

    # ------------------------------------------------------------------
    # Futures analytics
    # ------------------------------------------------------------------

    def compute_moving_averages(
        self, futures_df: pd.DataFrame, windows: list = None
    ) -> pd.DataFrame:
        """
        Add Simple Moving Average (SMA) columns to the futures DataFrame.

        Why moving averages?
        --------------------
        Moving averages smooth out daily noise and help identify the *trend*.
        The 20-day MA reflects short-term trend; 50-day medium-term; 200-day
        long-term.

        Golden Cross / Death Cross
        --------------------------
        • Golden Cross: 50-day MA crosses above 200-day MA → long-term bullish
        • Death  Cross: 50-day MA crosses below 200-day MA → long-term bearish
        These are lagging indicators — they confirm trends, not predict them.

        Parameters
        ----------
        futures_df : pd.DataFrame  (must have 'close' column)
        windows    : list of int   (default: [20, 50, 200])

        Returns
        -------
        pd.DataFrame with additional columns: sma_20, sma_50, sma_200
        """
        if windows is None:
            windows = [20, 50, 200]

        df = futures_df.copy()
        for w in windows:
            df[f"sma_{w}"] = df["close"].rolling(window=w, min_periods=1).mean().round(2)

        return df

    def compute_atr(self, futures_df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Compute the Average True Range (ATR).

        ATR measures *volatility*, not direction.  Developed by J. Welles Wilder,
        it is the average of the True Range over the last `period` days.

        True Range = max(
            High − Low,
            |High − Previous Close|,
            |Low  − Previous Close|
        )

        Interpreting ATR
        ----------------
        • High ATR → large daily swings → market is volatile (good for options sellers?)
        • Low  ATR → tight range → market is calm (directional traders wait for breakout)
        • ATR does NOT tell you which direction the market will move.

        Returns
        -------
        pd.DataFrame with additional column: atr_{period}
        """
        df = futures_df.copy()
        prev_close = df["close"].shift(1).fillna(df["close"])

        hl  = df["high"] - df["low"]
        hpc = (df["high"] - prev_close).abs()
        lpc = (df["low"]  - prev_close).abs()

        tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        df[f"atr_{period}"] = tr.rolling(window=period, min_periods=1).mean().round(2)

        return df

    def compute_volume_oi_analysis(self, futures_df: pd.DataFrame) -> pd.DataFrame:
        """
        Classify each day's price + volume + OI combination.

        The four classic relationships between price, volume and OI:

        | Price | Volume | OI     | Interpretation                  |
        |-------|--------|--------|---------------------------------|
        | Up    | Up     | Up     | New longs added — bullish trend  |
        | Up    | Down   | Down   | Short-covering — weak rally      |
        | Down  | Up     | Up     | New shorts added — bearish trend  |
        | Down  | Down   | Down   | Long unwinding — mild weakness    |

        Returns
        -------
        pd.DataFrame with additional columns:
          price_change, vol_change, oi_change, oi_price_signal
        """
        df = futures_df.copy()
        df["price_change"] = df["close"].pct_change().fillna(0)
        df["vol_change"]   = df["volume"].pct_change().fillna(0)
        df["oi_change"]    = df["oi"].pct_change().fillna(0)

        def classify(row: pd.Series) -> str:
            p_up = row["price_change"] >= 0
            o_up = row["oi_change"] >= 0
            if p_up and o_up:
                return "Bullish (Long Buildup)"
            elif p_up and not o_up:
                return "Weak Rally (Short Cover)"
            elif not p_up and o_up:
                return "Bearish (Short Buildup)"
            else:
                return "Mild Weakness (Long Unwind)"

        df["oi_price_signal"] = df.apply(classify, axis=1)
        return df

    # ------------------------------------------------------------------
    # Option chain analytics
    # ------------------------------------------------------------------

    def compute_max_pain(self, chain_df: pd.DataFrame) -> float:
        """
        Calculate the Max Pain strike price.

        What is Max Pain?
        -----------------
        Max Pain theory says that option sellers (writers) — who tend to be
        better capitalised institutions — benefit most when the underlying
        expires at the price where the *total value of all open options is
        minimised* (i.e., option buyers lose the most money).

        Calculation
        -----------
        For each candidate strike K_i:
            pain(K_i) = Σ_j [CE_OI(j) × max(K_i − K_j, 0)]   ← calls expire worthless
                      + Σ_j [PE_OI(j) × max(K_j − K_i, 0)]   ← puts expire worthless
        The strike that minimises pain(K_i) is Max Pain.

        Practical note
        --------------
        Max Pain is a controversial concept — the market does NOT always
        gravitate to max pain, especially in trending markets or when large
        macro events occur.  Use it as one data point, not a prediction.

        Parameters
        ----------
        chain_df : pd.DataFrame
            Single-date option chain (from DataProvider.get_option_chain).

        Returns
        -------
        float : Max Pain strike price
        """
        strikes   = chain_df["strike"].values.astype(float)
        ce_oi     = chain_df["CE_OI"].values.astype(float)
        pe_oi     = chain_df["PE_OI"].values.astype(float)

        pain = []
        for K_i in strikes:
            call_pain = np.sum(ce_oi * np.maximum(K_i - strikes, 0))
            put_pain  = np.sum(pe_oi * np.maximum(strikes - K_i, 0))
            pain.append(call_pain + put_pain)

        max_pain_strike = float(strikes[np.argmin(pain)])
        logger.info("Max Pain computed: ₹%.0f", max_pain_strike)
        return max_pain_strike

    def compute_iv_skew(self, chain_df: pd.DataFrame) -> dict:
        """
        Analyse the implied volatility skew.

        IV Skew Definition
        ------------------
        Skew = (OTM Put IV) − (OTM Call IV)

        A positive skew means OTM puts are more expensive than OTM calls,
        which is the normal condition in equity markets (tail-risk premium).

        Skew interpretation
        -------------------
        • High positive skew → market fears a sharp downside move
                               (demand for puts is high)
        • Low / negative skew → unusual, may indicate call buying frenzy
                                (e.g., strong rallying market)
        • Skew rising while market flat → bearish sentiment building

        Returns
        -------
        dict with: atm_iv, avg_otm_put_iv, avg_otm_call_iv, skew, skew_label
        """
        spot   = float(chain_df["spot"].iloc[0])
        atm    = round(spot / 50) * 50   # nearest 50-tick strike

        atm_row = chain_df[chain_df["strike"] == atm]
        atm_iv  = float(atm_row["CE_IV"].values[0]) if not atm_row.empty else np.nan

        # OTM puts = strikes below ATM; OTM calls = strikes above ATM
        otm_puts  = chain_df[chain_df["strike"] < atm - 50]
        otm_calls = chain_df[chain_df["strike"] > atm + 50]

        avg_pe_iv = float(otm_puts["PE_IV"].mean())  if not otm_puts.empty  else atm_iv
        avg_ce_iv = float(otm_calls["CE_IV"].mean()) if not otm_calls.empty else atm_iv

        skew = avg_pe_iv - avg_ce_iv

        if skew > 3.0:
            label = "High Put Skew (Fearful market)"
        elif skew > 1.0:
            label = "Normal Put Skew"
        elif skew > -1.0:
            label = "Flat Skew (Unusual)"
        else:
            label = "Negative Skew (Call buying dominance)"

        return {
            "atm_iv":         round(atm_iv,   2),
            "avg_otm_put_iv": round(avg_pe_iv, 2),
            "avg_otm_call_iv":round(avg_ce_iv, 2),
            "skew":           round(skew,      2),
            "skew_label":     label,
        }

    def compute_oi_concentration(self, chain_df: pd.DataFrame) -> dict:
        """
        Find the strikes with highest call and put OI — these often act as
        resistance and support respectively.

        Why does OI concentration matter?
        ----------------------------------
        Large option writers (usually institutions) hedge their books by
        trading the underlying near these strikes.  The result is that
        heavy CE OI at a strike often acts as a **resistance** (writers
        buy the underlying as price rises, then sell as it falls back).
        Heavy PE OI acts as **support** for similar reasons.

        This is a simplified view — in reality it depends on whether the
        writers are delta-hedging and their exact positioning.

        Returns
        -------
        dict with: ce_wall (resistance strike), pe_wall (support strike),
                   ce_wall_oi, pe_wall_oi, itm_ce_oi_pct, itm_pe_oi_pct
        """
        spot = float(chain_df["spot"].iloc[0])

        ce_max_idx = chain_df["CE_OI"].idxmax()
        pe_max_idx = chain_df["PE_OI"].idxmax()

        ce_wall    = float(chain_df.loc[ce_max_idx, "strike"])
        pe_wall    = float(chain_df.loc[pe_max_idx, "strike"])
        ce_wall_oi = int(chain_df.loc[ce_max_idx, "CE_OI"])
        pe_wall_oi = int(chain_df.loc[pe_max_idx, "PE_OI"])

        # ITM CE = calls with strike < spot; ITM PE = puts with strike > spot
        total_ce_oi  = chain_df["CE_OI"].sum()
        total_pe_oi  = chain_df["PE_OI"].sum()
        itm_ce_oi    = chain_df.loc[chain_df["strike"] < spot, "CE_OI"].sum()
        itm_pe_oi    = chain_df.loc[chain_df["strike"] > spot, "PE_OI"].sum()

        return {
            "ce_wall":       ce_wall,
            "pe_wall":       pe_wall,
            "ce_wall_oi":    ce_wall_oi,
            "pe_wall_oi":    pe_wall_oi,
            "itm_ce_oi_pct": round(itm_ce_oi / total_ce_oi * 100, 1) if total_ce_oi else 0,
            "itm_pe_oi_pct": round(itm_pe_oi / total_pe_oi * 100, 1) if total_pe_oi else 0,
        }

    # ------------------------------------------------------------------
    # Sentiment synthesis
    # ------------------------------------------------------------------

    def generate_sentiment(
        self,
        futures_df: pd.DataFrame,
        chain_df: pd.DataFrame,
        pcr_df: pd.DataFrame,
    ) -> dict:
        """
        Aggregate multiple signals into a single market sentiment summary.

        How the scoring works
        ---------------------
        Each sub-signal contributes +1 (bullish) or −1 (bearish) or 0 (neutral)
        to a running score.  The final label is determined by the total score.

        Signals used:
        1. Price vs 20-day SMA
        2. Price vs 50-day SMA
        3. Price vs 200-day SMA
        4. OI / Price classification (last day)
        5. PCR level (recent 5-day average vs thresholds)
        6. Max Pain vs Spot (is spot above / below max pain?)
        7. IV Skew (elevated skew = bearish signal)

        ⚠️  This scoring system is a simplified heuristic for EDUCATIONAL use.
            Real institutional sentiment analysis uses order flow, dark pools,
            FII/DII data, and much more complex models.

        Returns
        -------
        dict with: score, label, explanation, bullish_factors, bearish_factors,
                   key_levels, risk_factors
        """
        bullish  = []
        bearish  = []
        neutral  = []
        score    = 0

        if futures_df.empty:
            return {"score": 0, "label": "Neutral", "explanation": "Insufficient data."}

        # --- Enrich futures data ---
        df = self.compute_moving_averages(futures_df)
        df = self.compute_atr(df)
        df = self.compute_volume_oi_analysis(df)
        last = df.iloc[-1]
        spot = float(last["close"])

        # Signal 1-3: Price vs moving averages
        for w, label_suffix in [(20, "short"), (50, "medium"), (200, "long")]:
            col = f"sma_{w}"
            if col in last.index and not pd.isna(last[col]):
                if spot > last[col]:
                    score += 1
                    bullish.append(f"Price above {w}-day SMA (₹{last[col]:,.0f}) — {label_suffix}-term bullish")
                else:
                    score -= 1
                    bearish.append(f"Price below {w}-day SMA (₹{last[col]:,.0f}) — {label_suffix}-term bearish")

        # Signal 4: OI/Price signal
        oi_sig = last.get("oi_price_signal", "")
        if "Bullish" in oi_sig:
            score += 1
            bullish.append(f"OI/Price: {oi_sig}")
        elif "Bearish" in oi_sig:
            score -= 1
            bearish.append(f"OI/Price: {oi_sig}")
        else:
            neutral.append(f"OI/Price: {oi_sig}")

        # Signal 5: PCR (recent 5-day average)
        if not pcr_df.empty:
            recent_pcr = pcr_df["pcr_oi"].tail(5).mean()
            bull_thr   = self.config["strategy_defaults"]["pcr"]["bullish_threshold"]
            bear_thr   = self.config["strategy_defaults"]["pcr"]["bearish_threshold"]
            if recent_pcr > bear_thr:
                score += 1   # contrarian: high PCR = over-bearish = potential bounce
                bullish.append(f"PCR(5d avg) = {recent_pcr:.2f} > {bear_thr} → Contrarian bullish signal")
            elif recent_pcr < bull_thr:
                score -= 1   # contrarian: low PCR = over-bullish = caution
                bearish.append(f"PCR(5d avg) = {recent_pcr:.2f} < {bull_thr} → Contrarian caution signal")
            else:
                neutral.append(f"PCR(5d avg) = {recent_pcr:.2f} — Neutral zone")
        else:
            recent_pcr = None

        # Signal 6: Max Pain vs Spot
        max_pain = None
        if not chain_df.empty:
            max_pain = self.compute_max_pain(chain_df)
            if spot > max_pain:
                score += 1
                bullish.append(f"Spot (₹{spot:,.0f}) above Max Pain (₹{max_pain:,.0f})")
            else:
                score -= 1
                bearish.append(f"Spot (₹{spot:,.0f}) below Max Pain (₹{max_pain:,.0f})")

            # Signal 7: IV Skew
            skew_data = self.compute_iv_skew(chain_df)
            if skew_data["skew"] > 4.0:
                score -= 1
                bearish.append(f"High IV skew ({skew_data['skew']:.1f}%) — {skew_data['skew_label']}")
            else:
                neutral.append(f"IV skew: {skew_data['skew']:.1f}% — {skew_data['skew_label']}")

            oi_conc = self.compute_oi_concentration(chain_df)
        else:
            skew_data = {}
            oi_conc   = {}

        # Final label
        if score >= 3:
            label = "Strongly Bullish"
        elif score >= 1:
            label = "Moderately Bullish"
        elif score == 0:
            label = "Neutral / Sideways"
        elif score >= -2:
            label = "Moderately Bearish"
        else:
            label = "Strongly Bearish"

        # ATR for context
        atr_col = "atr_14"
        atr_val = float(last[atr_col]) if atr_col in last.index else None

        # Key levels
        key_levels = {
            "current_price":  spot,
            "sma_20":  float(last.get("sma_20",  np.nan)),
            "sma_50":  float(last.get("sma_50",  np.nan)),
            "sma_200": float(last.get("sma_200", np.nan)),
            "atr_14":  atr_val,
            "max_pain": max_pain,
            "ce_wall":  oi_conc.get("ce_wall"),
            "pe_wall":  oi_conc.get("pe_wall"),
        }

        # Risk factors (always present regardless of sentiment)
        risk_factors = [
            "This analysis is based on SYNTHETIC sample data and is for study only.",
            "Option chain data is a snapshot; positions change continuously.",
            "Moving averages are lagging indicators — they confirm, not predict.",
            "PCR contrarian signals work best at extremes, not in trending markets.",
            "Global macro events (Fed, geopolitical) can override all local signals.",
            "Max Pain theory is empirical and not always reliable.",
        ]

        return {
            "score":           score,
            "label":           label,
            "bullish_factors": bullish,
            "bearish_factors": bearish,
            "neutral_factors": neutral,
            "key_levels":      key_levels,
            "skew_data":       skew_data,
            "oi_conc":         oi_conc,
            "risk_factors":    risk_factors,
            "pcr_5d_avg":      round(recent_pcr, 3) if recent_pcr else None,
        }
