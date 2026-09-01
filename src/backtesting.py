"""
src/backtesting.py — Simple historical backtesting engine
==========================================================

What this module does
---------------------
Implements a basic event-driven backtesting engine that simulates running
rule-based trading strategies on historical futures data.

Strategies implemented
----------------------
1. Moving Average Crossover
   • Buy signal  : Short-term MA crosses *above* long-term MA (Golden Cross).
   • Sell signal : Short-term MA crosses *below* long-term MA (Death Cross).
   • Position    : Long-only (single lot per signal).
   • Exit        : Reversed on opposite signal.

2. PCR Contrarian Strategy
   • Buy signal  : PCR (5-day avg) rises above `bearish_threshold`
                   (market is over-bearish → potential bounce).
   • Sell signal : PCR falls below `bullish_threshold`
                   (market is over-optimistic → take profit / caution).
   • This is a *contrarian* strategy, NOT a momentum strategy.

Metrics computed
----------------
• Total return          : (Final value − Initial capital) / Initial capital
• CAGR                  : Compound Annual Growth Rate
• Max Drawdown          : Worst peak-to-trough fall in portfolio value
• Win Rate              : % of closed trades with a positive P&L
• Average Win / Loss    : Average profit of winners / average loss of losers
• Sharpe Ratio (approx) : Annualised excess return / standard deviation
  Note: True Sharpe uses daily returns; this approximation uses trade returns.

Important limitations
---------------------
1. Look-ahead bias   : All signals use only data available *at* decision time.
2. Slippage          : A configurable % is deducted from each fill price.
3. Transaction costs : A configurable % is deducted per trade.
4. No partial fills  : Orders are always filled at the configured price.
5. Survivorship bias : We only test on the one synthetic instrument — no history
                       of indices being reconstituted.
6. No overnight risk : Gaps are not modelled beyond the OHLCV data.

⚠️  DISCLAIMER: All backtest results are HYPOTHETICAL.
    Past performance of a strategy on historical (or synthetic) data does NOT
    predict future real-world results.  This is for EDUCATIONAL STUDY ONLY.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.backtesting")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """Represents a single completed round-trip trade."""
    entry_date:  pd.Timestamp
    exit_date:   pd.Timestamp
    entry_price: float
    exit_price:  float
    direction:   str          # "long"
    pnl:         float        # ₹ P&L after costs


@dataclass
class BacktestResult:
    """Holds all outputs of a backtest run."""
    equity_curve:   pd.DataFrame       # date + portfolio_value columns
    trades:         list               # list of Trade objects
    metrics:        dict               # summary statistics
    regime_summary: dict               # how strategy performed in different market conditions
    signals_df:     pd.DataFrame       # full signal log for debugging
    strategy_name:  str
    parameters:     dict


# ---------------------------------------------------------------------------
# Backtesting engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Simple single-instrument futures backtesting engine.

    Parameters
    ----------
    config : dict
        Parsed config.yaml (from utils.get_config()).
    """

    def __init__(self, config: dict) -> None:
        self.config       = config
        self.init_capital = float(config["backtesting"]["initial_capital"])
        self.tx_cost      = float(config["backtesting"]["transaction_cost_pct"])
        self.slippage     = float(config["backtesting"]["slippage_pct"])

    # ------------------------------------------------------------------
    # Strategy 1: Moving Average Crossover
    # ------------------------------------------------------------------

    def run_ma_crossover(
        self,
        futures_df: pd.DataFrame,
        short_window: int  = 20,
        long_window: int   = 50,
        initial_capital: Optional[float] = None,
        lot_size: int      = 1,
    ) -> BacktestResult:
        """
        Run a simple moving-average crossover strategy on futures.

        Logic
        -----
        • Compute short-window SMA and long-window SMA of daily closing price.
        • When short MA > long MA  → Go Long (buy one lot at next open).
        • When short MA < long MA  → Close Long (sell at next open).
        • Only one position at a time (no pyramiding).
        • No short selling (long-only, as most retail participants operate).

        Why MA crossover?
        -----------------
        It is the *simplest* trend-following rule and is often used as a
        baseline to compare against.  In academic research (e.g., Faber 2007),
        a basic 200-day MA filter on equity indices has historically improved
        risk-adjusted returns — though it has significant drawdowns and can
        underperform in sideways markets.

        Parameters
        ----------
        futures_df      : pd.DataFrame  — from DataProvider.get_futures_history
        short_window    : int           — short SMA period (e.g., 20)
        long_window     : int           — long SMA period (e.g., 50)
        initial_capital : float or None — ₹ starting capital
        lot_size        : int           — number of futures lots per trade

        Returns
        -------
        BacktestResult
        """
        capital = initial_capital or self.init_capital
        df = futures_df.copy().sort_values("date").reset_index(drop=True)

        # Compute moving averages
        df["sma_short"] = df["close"].rolling(window=short_window, min_periods=short_window).mean()
        df["sma_long"]  = df["close"].rolling(window=long_window,  min_periods=long_window).mean()

        # Drop rows where either MA is NaN (warm-up period)
        df = df.dropna(subset=["sma_short", "sma_long"]).reset_index(drop=True)

        # Signal: +1 when short > long, 0 otherwise
        df["signal"] = (df["sma_short"] > df["sma_long"]).astype(int)

        # Detect crossovers (signal changes)
        df["prev_signal"] = df["signal"].shift(1, fill_value=0)
        df["entry_signal"] = (df["signal"] == 1) & (df["prev_signal"] == 0)  # crossover up
        df["exit_signal"]  = (df["signal"] == 0) & (df["prev_signal"] == 1)  # crossover down

        logger.info(
            "MA Crossover [%d/%d]: %d entry signals, %d exit signals over %d days",
            short_window, long_window,
            df["entry_signal"].sum(), df["exit_signal"].sum(), len(df),
        )

        return self._simulate(df, capital, lot_size,
                              strategy_name="MA Crossover",
                              params={"short_window": short_window, "long_window": long_window})

    # ------------------------------------------------------------------
    # Strategy 2: PCR Contrarian
    # ------------------------------------------------------------------

    def run_pcr_strategy(
        self,
        futures_df: pd.DataFrame,
        pcr_df: pd.DataFrame,
        bullish_threshold: float     = 0.75,
        bearish_threshold: float     = 1.25,
        pcr_smoothing_days: int      = 5,
        initial_capital: Optional[float] = None,
        lot_size: int                = 1,
    ) -> BacktestResult:
        """
        Run a PCR-based contrarian strategy.

        Logic
        -----
        • Smooth daily PCR with a rolling mean (pcr_smoothing_days).
        • When smoothed PCR crosses *above* bearish_threshold → Buy
          (market is too bearish/oversold → expect bounce).
        • When smoothed PCR crosses *below* bullish_threshold → Sell
          (market is too optimistic → expect mean-reversion down).
        • Hold position between signals; long-only.

        Why contrarian?
        ---------------
        High PCR means market participants are buying lots of put options —
        hedging against a fall.  When *everyone* is hedged, the marginal
        seller of puts dries up and the market tends to recover.  This is
        a classic mean-reversion / sentiment extreme strategy.

        It does NOT work in every market regime — in a persistent downtrend,
        high PCR can stay elevated for weeks.

        Parameters
        ----------
        futures_df        : pd.DataFrame — daily futures prices
        pcr_df            : pd.DataFrame — from DataProvider.get_pcr
        bullish_threshold : float        — sell signal when PCR < this
        bearish_threshold : float        — buy signal when PCR > this
        pcr_smoothing_days: int          — rolling average for PCR
        initial_capital   : float        — ₹ starting capital
        lot_size          : int

        Returns
        -------
        BacktestResult
        """
        capital = initial_capital or self.init_capital

        # Merge on date
        df = futures_df.copy().sort_values("date").reset_index(drop=True)
        pcr = pcr_df[["date", "pcr_oi"]].copy().sort_values("date")
        df  = df.merge(pcr, on="date", how="left")

        # Forward-fill weekly PCR values to daily
        df["pcr_oi"] = df["pcr_oi"].ffill()

        # Smooth PCR
        df["pcr_smooth"] = df["pcr_oi"].rolling(window=pcr_smoothing_days, min_periods=1).mean()
        df = df.dropna(subset=["pcr_smooth"]).reset_index(drop=True)

        # Signals
        df["prev_pcr"] = df["pcr_smooth"].shift(1, fill_value=df["pcr_smooth"].iloc[0])
        df["entry_signal"] = (df["pcr_smooth"] >= bearish_threshold) & (df["prev_pcr"] < bearish_threshold)
        df["exit_signal"]  = (df["pcr_smooth"] <= bullish_threshold) & (df["prev_pcr"] > bullish_threshold)

        logger.info(
            "PCR Contrarian [buy>%.2f, sell<%.2f]: %d entry signals, %d exit signals",
            bearish_threshold, bullish_threshold,
            df["entry_signal"].sum(), df["exit_signal"].sum(),
        )

        return self._simulate(df, capital, lot_size,
                              strategy_name="PCR Contrarian",
                              params={
                                  "bullish_threshold": bullish_threshold,
                                  "bearish_threshold": bearish_threshold,
                                  "pcr_smoothing_days": pcr_smoothing_days,
                              })

    # ------------------------------------------------------------------
    # Core simulation engine
    # ------------------------------------------------------------------

    def _simulate(
        self,
        df: pd.DataFrame,
        initial_capital: float,
        lot_size: int,
        strategy_name: str,
        params: dict,
    ) -> BacktestResult:
        """
        Execute trade signals on the price series and build equity curve.

        Execution model
        ---------------
        • Signals generated on day T are executed at the *open* of day T+1.
          (Realistic: you can't execute at the same candle you generated the signal.)
        • Transaction cost and slippage are applied to both entry and exit prices.
        • Only one position at a time.

        Parameters
        ----------
        df              : pd.DataFrame — must have: date, open, close, entry_signal, exit_signal
        initial_capital : float
        lot_size        : int
        strategy_name   : str
        params          : dict          — strategy parameters for logging

        Returns
        -------
        BacktestResult
        """
        cash     = initial_capital
        position = 0          # number of lots held
        entry_px = 0.0
        entry_dt = None
        trades   = []
        equity   = []

        total_cost_pct = self.tx_cost + self.slippage

        # We need next-day open for execution, so shift signals by 1
        df = df.copy().reset_index(drop=True)
        n  = len(df)

        for i in range(n):
            row = df.iloc[i]
            # Execution uses current day's open (signal was from previous close)
            exec_price = float(row["open"])
            date       = row["date"]
            close      = float(row["close"])

            # Check previous day's signal (index i-1)
            if i > 0:
                prev = df.iloc[i - 1]

                # Entry: go long
                if prev["entry_signal"] and position == 0:
                    buy_price = exec_price * (1 + total_cost_pct)
                    position  = lot_size
                    entry_px  = buy_price
                    entry_dt  = date
                    logger.debug("BUY  %d lot(s) @ ₹%.2f on %s", lot_size, buy_price, date.date())

                # Exit: close long
                elif prev["exit_signal"] and position > 0:
                    sell_price = exec_price * (1 - total_cost_pct)
                    pnl        = (sell_price - entry_px) * position
                    cash      += pnl + (entry_px * position)  # return capital + pnl
                    trades.append(Trade(
                        entry_date=entry_dt, exit_date=date,
                        entry_price=entry_px, exit_price=sell_price,
                        direction="long", pnl=pnl,
                    ))
                    logger.debug("SELL %d lot(s) @ ₹%.2f on %s | PnL: ₹%.0f", lot_size, sell_price, date.date(), pnl)
                    position = 0

            # Mark-to-market portfolio value
            mtm = cash + position * close - (position * entry_px if position > 0 else 0)
            equity.append({"date": date, "portfolio_value": mtm})

        # Close any open position at the end of the period
        if position > 0:
            last_close = float(df.iloc[-1]["close"]) * (1 - total_cost_pct)
            pnl        = (last_close - entry_px) * position
            cash      += pnl + (entry_px * position)
            trades.append(Trade(
                entry_date=entry_dt, exit_date=df.iloc[-1]["date"],
                entry_price=entry_px, exit_price=last_close,
                direction="long", pnl=pnl,
            ))

        equity_df = pd.DataFrame(equity)

        metrics       = self.compute_metrics(equity_df, trades, initial_capital)
        regime_summary = self.identify_regimes(df, equity_df)

        logger.info(
            "%s backtest complete: Return=%.1f%%, MaxDD=%.1f%%, Trades=%d",
            strategy_name,
            metrics.get("total_return_pct", 0),
            metrics.get("max_drawdown_pct", 0),
            len(trades),
        )

        return BacktestResult(
            equity_curve=equity_df,
            trades=trades,
            metrics=metrics,
            regime_summary=regime_summary,
            signals_df=df,
            strategy_name=strategy_name,
            parameters=params,
        )

    # ------------------------------------------------------------------
    # Performance metrics
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        equity_df: pd.DataFrame,
        trades: list,
        initial_capital: float,
        risk_free_rate: float = 0.07,
    ) -> dict:
        """
        Calculate standard performance metrics for a completed backtest.

        Metrics explained
        -----------------
        Total Return
            Simply how much money was made / lost as a percentage.

        CAGR (Compound Annual Growth Rate)
            The steady annualised return that would produce the same
            total return over the period.  Formula: (FV/IV)^(1/years) − 1

        Max Drawdown
            The worst loss from a portfolio peak to the subsequent trough.
            E.g., if the portfolio hits ₹12L then falls to ₹9L, that is a
            25% drawdown.  Max drawdown is crucial for position sizing.

        Sharpe Ratio
            Excess return (above risk-free rate) per unit of volatility.
            Sharpe = (Annualised Return − Risk-free Rate) / Annualised Volatility
            A Sharpe > 1.0 is generally considered good.
            Note: This is an *approximation* — a proper Sharpe requires at
            least 3 years of data and adjustments for autocorrelation.

        Win Rate
            Percentage of closed trades that had positive P&L.
            A 50% win rate can still be profitable if average win > average loss.

        Returns
        -------
        dict with all metrics above
        """
        if equity_df.empty:
            return {}

        pv       = equity_df["portfolio_value"].values
        final_pv = float(pv[-1])
        total_return   = (final_pv - initial_capital) / initial_capital
        n_days         = len(pv)
        n_years        = n_days / 252.0

        # CAGR
        cagr = (final_pv / initial_capital) ** (1.0 / n_years) - 1 if n_years > 0 else 0.0

        # Daily returns
        daily_ret    = np.diff(pv) / pv[:-1]
        ann_vol      = float(np.std(daily_ret) * np.sqrt(252))
        ann_ret      = float(np.mean(daily_ret) * 252)
        sharpe       = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0

        # Max Drawdown
        peak     = np.maximum.accumulate(pv)
        drawdown = (pv - peak) / peak
        max_dd   = float(np.min(drawdown))

        # Trade statistics
        pnls      = [t.pnl for t in trades]
        wins      = [p for p in pnls if p > 0]
        losses    = [p for p in pnls if p <= 0]
        win_rate  = len(wins) / len(pnls) * 100 if pnls else 0.0
        avg_win   = float(np.mean(wins))   if wins   else 0.0
        avg_loss  = float(np.mean(losses)) if losses else 0.0

        return {
            "total_return_pct":  round(total_return * 100, 2),
            "cagr_pct":          round(cagr          * 100, 2),
            "max_drawdown_pct":  round(max_dd        * 100, 2),
            "sharpe_ratio":      round(sharpe,               2),
            "annualised_vol_pct":round(ann_vol        * 100, 2),
            "num_trades":        len(trades),
            "win_rate_pct":      round(win_rate,             1),
            "avg_win_inr":       round(avg_win,              2),
            "avg_loss_inr":      round(avg_loss,             2),
            "total_pnl_inr":     round(sum(pnls),           2) if pnls else 0.0,
        }

    # ------------------------------------------------------------------
    # Regime analysis
    # ------------------------------------------------------------------

    def identify_regimes(
        self, signals_df: pd.DataFrame, equity_df: pd.DataFrame
    ) -> dict:
        """
        Classify the backtest period into market regimes and analyse
        how the strategy performed in each.

        Regimes used
        ------------
        • Trending Up   : Close > 50-day SMA by more than 2%
        • Trending Down : Close < 50-day SMA by more than 2%
        • Sideways      : Close within ±2% of 50-day SMA

        High Volatility : Daily ATR > 1.5× the period's average ATR

        Note: Regime classification is approximate and uses the same data
        that the strategy trained on — in production you'd use a separate
        regime indicator (e.g., hidden Markov model, ADX).

        Returns
        -------
        dict with regime-level statistics
        """
        if "close" not in signals_df.columns:
            return {}

        df = signals_df.copy()
        df["sma_50"] = df["close"].rolling(50, min_periods=1).mean()
        df["deviation"] = (df["close"] - df["sma_50"]) / df["sma_50"]

        def regime_label(dev: float) -> str:
            if dev >  0.02:
                return "Trending Up"
            elif dev < -0.02:
                return "Trending Down"
            else:
                return "Sideways"

        df["regime"] = df["deviation"].apply(regime_label)

        # Merge with equity
        merged = df[["date", "regime"]].merge(equity_df, on="date", how="left")
        merged["daily_ret"] = merged["portfolio_value"].pct_change().fillna(0)

        summary = {}
        for regime, grp in merged.groupby("regime"):
            avg_ret = float(grp["daily_ret"].mean() * 252 * 100)
            volatility = float(grp["daily_ret"].std() * np.sqrt(252) * 100)
            summary[regime] = {
                "days":             len(grp),
                "avg_ann_return_pct": round(avg_ret,    2),
                "volatility_pct":     round(volatility, 2),
            }

        return summary

    # ------------------------------------------------------------------
    # Strategy 3: RSI Mean-Reversion
    # ------------------------------------------------------------------

    def run_rsi_strategy(
        self,
        futures_df: pd.DataFrame,
        rsi_period: int          = 14,
        oversold: float          = 30.0,
        overbought: float        = 70.0,
        initial_capital: Optional[float] = None,
        lot_size: int            = 1,
    ) -> BacktestResult:
        """
        RSI mean-reversion strategy.

        Buy when RSI crosses UP through oversold (< oversold then rises above).
        Sell when RSI crosses DOWN through overbought (> overbought then falls below).
        Classic contrarian approach — buys fear, sells greed.
        """
        capital = initial_capital or self.init_capital
        df = futures_df.copy().sort_values("date").reset_index(drop=True)

        # Compute RSI using Wilder's smoothed average
        delta = df["close"].diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
        rs  = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        df = df.dropna(subset=["rsi"]).reset_index(drop=True)

        df["prev_rsi"] = df["rsi"].shift(1, fill_value=50)

        # Entry: RSI crosses UP from oversold zone
        df["entry_signal"] = (df["rsi"] > oversold) & (df["prev_rsi"] <= oversold)
        # Exit: RSI crosses DOWN from overbought zone
        df["exit_signal"]  = (df["rsi"] < overbought) & (df["prev_rsi"] >= overbought)

        logger.info(
            "RSI [period=%d, oversold=%.0f, overbought=%.0f]: %d entries, %d exits",
            rsi_period, oversold, overbought,
            df["entry_signal"].sum(), df["exit_signal"].sum(),
        )

        return self._simulate(df, capital, lot_size,
                              strategy_name="RSI Mean-Reversion",
                              params={"rsi_period": rsi_period,
                                      "oversold": oversold,
                                      "overbought": overbought})

    # ------------------------------------------------------------------
    # Strategy 4: Bollinger Band Breakout
    # ------------------------------------------------------------------

    def run_bollinger_strategy(
        self,
        futures_df: pd.DataFrame,
        bb_period: int           = 20,
        num_std: float           = 2.0,
        initial_capital: Optional[float] = None,
        lot_size: int            = 1,
    ) -> BacktestResult:
        """
        Bollinger Band breakout / reversion strategy.

        Entry: Close breaks ABOVE the upper band (momentum breakout) → Buy.
        Exit:  Close drops BELOW the middle band (mean-reversion).

        Bollinger Bands contract during low volatility and expand during
        high volatility.  A breakout above the upper band often signals
        the start of a strong trend.
        """
        capital = initial_capital or self.init_capital
        df = futures_df.copy().sort_values("date").reset_index(drop=True)

        df["bb_mid"] = df["close"].rolling(bb_period, min_periods=bb_period).mean()
        df["bb_std"] = df["close"].rolling(bb_period, min_periods=bb_period).std()
        df["bb_up"]  = df["bb_mid"] + num_std * df["bb_std"]
        df["bb_lo"]  = df["bb_mid"] - num_std * df["bb_std"]
        df = df.dropna(subset=["bb_mid"]).reset_index(drop=True)

        df["prev_close"] = df["close"].shift(1, fill_value=df["close"].iloc[0])

        # Entry: close crosses above upper band
        df["entry_signal"] = (df["close"] > df["bb_up"]) & (df["prev_close"] <= df["bb_up"])
        # Exit: close falls below middle band
        df["exit_signal"]  = (df["close"] < df["bb_mid"]) & (df["prev_close"] >= df["bb_mid"])

        logger.info(
            "Bollinger [period=%d, std=%.1f]: %d entries, %d exits",
            bb_period, num_std,
            df["entry_signal"].sum(), df["exit_signal"].sum(),
        )

        return self._simulate(df, capital, lot_size,
                              strategy_name="Bollinger Band Breakout",
                              params={"bb_period": bb_period, "num_std": num_std})

    # ------------------------------------------------------------------
    # Strategy 5: MACD Signal Line Crossover
    # ------------------------------------------------------------------

    def run_macd_strategy(
        self,
        futures_df: pd.DataFrame,
        fast: int                = 12,
        slow: int                = 26,
        signal: int              = 9,
        initial_capital: Optional[float] = None,
        lot_size: int            = 1,
    ) -> BacktestResult:
        """
        MACD (Moving Average Convergence Divergence) signal crossover.

        Entry: MACD line crosses ABOVE the signal line → Buy.
        Exit:  MACD line crosses BELOW the signal line → Sell.

        MACD is one of the most widely-used momentum indicators.
        It captures changes in momentum, direction, and duration of a trend.
        """
        capital = initial_capital or self.init_capital
        df = futures_df.copy().sort_values("date").reset_index(drop=True)

        ema_fast   = df["close"].ewm(span=fast,   adjust=False).mean()
        ema_slow   = df["close"].ewm(span=slow,   adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["histogram"]   = df["macd"] - df["macd_signal"]
        df = df.iloc[slow:].reset_index(drop=True)  # skip warm-up

        df["prev_hist"] = df["histogram"].shift(1, fill_value=0)

        # Entry: histogram crosses from negative to positive (MACD crosses above signal)
        df["entry_signal"] = (df["histogram"] > 0) & (df["prev_hist"] <= 0)
        # Exit: histogram crosses from positive to negative
        df["exit_signal"]  = (df["histogram"] < 0) & (df["prev_hist"] >= 0)

        logger.info(
            "MACD [%d/%d/%d]: %d entries, %d exits",
            fast, slow, signal,
            df["entry_signal"].sum(), df["exit_signal"].sum(),
        )

        return self._simulate(df, capital, lot_size,
                              strategy_name="MACD Crossover",
                              params={"fast": fast, "slow": slow, "signal": signal})

    # ------------------------------------------------------------------
    # Enhanced metrics: Calmar, Sortino, MAR, monthly P&L
    # ------------------------------------------------------------------

    def compute_extended_metrics(
        self,
        equity_df: pd.DataFrame,
        trades: list,
        initial_capital: float,
        risk_free_rate: float = 0.065,
    ) -> dict:
        """
        Additional risk-adjusted performance metrics beyond the basic set.

        Calmar Ratio  = CAGR / |Max Drawdown|  — reward per unit of worst loss
        Sortino Ratio = Excess return / Downside deviation (only negative days)
        MAR Ratio     = same as Calmar in this implementation
        Profit Factor = Total gross profit / Total gross loss
        Avg trade duration (days)
        Longest losing streak
        Recovery factor = Total return / Max drawdown
        """
        if equity_df.empty or len(equity_df) < 2:
            return {}

        base = self.compute_metrics(equity_df, trades, initial_capital, risk_free_rate)
        pv   = equity_df["portfolio_value"].values

        daily_ret  = np.diff(pv) / pv[:-1]
        ann_ret    = float(np.mean(daily_ret) * 252)
        max_dd     = abs(base.get("max_drawdown_pct", 0) / 100)
        n_years    = len(pv) / 252.0

        # Calmar / MAR
        calmar = (ann_ret / max_dd) if max_dd > 0 else 0.0

        # Sortino: only downside deviation
        neg_ret    = daily_ret[daily_ret < 0]
        down_dev   = float(np.std(neg_ret) * np.sqrt(252)) if len(neg_ret) > 0 else 0.0
        sortino    = (ann_ret - risk_free_rate) / down_dev if down_dev > 0 else 0.0

        # Recovery factor
        total_ret  = base.get("total_return_pct", 0) / 100
        recovery   = total_ret / max_dd if max_dd > 0 else 0.0

        # Profit factor
        pnls       = [t.pnl for t in trades]
        gross_win  = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

        # Average trade duration
        durations = []
        for t in trades:
            try:
                d = (pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).days
                durations.append(d)
            except Exception:
                pass
        avg_duration = round(float(np.mean(durations)), 1) if durations else 0.0

        # Longest losing streak
        streak = max_streak = 0
        for p in pnls:
            if p <= 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0

        # Monthly P&L table
        monthly = self._monthly_pnl(equity_df)

        return {
            **base,
            "calmar_ratio":     round(calmar,        2),
            "sortino_ratio":    round(sortino,        2),
            "recovery_factor":  round(recovery,       2),
            "profit_factor":    round(profit_factor,  2),
            "avg_trade_days":   avg_duration,
            "max_losing_streak": max_streak,
            "monthly_pnl":      monthly,
        }

    def _monthly_pnl(self, equity_df: pd.DataFrame) -> dict:
        """Compute monthly P&L % — returns dict {(year,month): pct_return}."""
        if equity_df.empty:
            return {}
        df = equity_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").resample("ME")["portfolio_value"].last().dropna()
        monthly_ret = df.pct_change().dropna() * 100
        return {f"{d.year}-{d.month:02d}": round(float(v), 2)
                for d, v in monthly_ret.items()}
