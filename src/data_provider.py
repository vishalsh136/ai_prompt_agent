"""
src/data_provider.py — Data abstraction layer for the Indian Market Study Tool
==============================================================================

What this module does
---------------------
Provides a single DataProvider class that loads (or generates) all market
data used by the app.  Every other module should go through DataProvider
instead of reading files directly.  This makes it easy to swap out the
sample data for real API data later.

Supported data types
--------------------
1. Futures OHLCV + Open Interest  (daily)
2. Option Chain snapshots          (weekly, one per trading Friday)
3. Put-Call Ratio                  (daily, derived from option chain)

How to extend for real data
----------------------------
1. Obtain a data vendor subscription (e.g., NSE official data, Zerodha Kite
   Historical API, Upstox, TrueData, etc.).
2. Create a subclass or add new methods in DataProvider.
3. Replace the CSV read in each `get_*` method with your API call.
4. Keep the same return types (pandas DataFrame) so the rest of the app
   continues working without changes.

⚠️  DISCLAIMER: All data generated here is SYNTHETIC / FICTIONAL.
    It is produced by a random model (GBM) and does NOT represent actual
    NSE/BSE data.  Do NOT use it for real trading decisions.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.utils import black_scholes_price
from src import real_data_loader

logger = logging.getLogger("market_study_tool.data_provider")


class DataProvider:
    """
    Unified interface for accessing market data (futures, options, PCR).

    On first run the class auto-generates realistic synthetic data files
    in the `data/` directory.  Subsequent runs load the cached CSVs.

    Parameters
    ----------
    config : dict
        Parsed config.yaml dictionary (from utils.get_config()).

    Example usage
    -------------
    >>> from src.utils import get_config
    >>> from src.data_provider import DataProvider
    >>> cfg = get_config()
    >>> dp  = DataProvider(cfg)
    >>> futures_df = dp.get_futures_history("NIFTY", "2024-01-01", "2024-06-30")
    >>> chain_df   = dp.get_option_chain("NIFTY", "2024-03-28")
    >>> pcr_df     = dp.get_pcr("NIFTY", "2024-01-01", "2024-06-30")
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)

        # Real data cache (populated via load_real_data())
        self._real_futures:      Optional[pd.DataFrame] = None
        self._real_chain:        Optional[pd.DataFrame] = None
        self._real_pcr:          Optional[pd.DataFrame] = None
        self._real_chain_symbol: Optional[str]          = None

        # Ensure sample data files exist for all configured symbols
        for symbol in config["symbols"]["indices"]:
            self._ensure_data_exists(symbol)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_real_data(
        self,
        futures_path: str,
        chain_path: str,
        pcr_path: str,
        symbol: str = "NIFTY",
    ) -> dict:
        """
        Load real downloaded NSE files into the DataProvider cache.

        Once called, subsequent calls to get_futures_history, get_option_chain,
        and get_pcr will return the real data (for the specified symbol).

        Parameters
        ----------
        futures_path : str — path to NIFTY 50 historical CSV
        chain_path   : str — path to NSE option chain CSV
        pcr_path     : str — path to PCR CSV
        symbol       : str — which symbol these files correspond to

        Returns
        -------
        dict with keys: futures_rows, chain_rows, pcr_rows, spot, chain_date
        """
        validation = real_data_loader.validate_files(futures_path, chain_path, pcr_path)
        if not validation["all_ok"]:
            missing = [m for m in validation["messages"] if "❌" in m]
            raise FileNotFoundError("Some real data files are missing:\n" + "\n".join(missing))

        inferred_symbol = self._infer_real_data_symbol(futures_path, chain_path, pcr_path)
        requested_symbol = str(symbol).upper().strip()
        if inferred_symbol and inferred_symbol != requested_symbol:
            raise ValueError(
                f"Real files appear to be for {inferred_symbol}, but selected symbol is {requested_symbol}. "
                f"Please select {inferred_symbol} and load again."
            )

        active_symbol = inferred_symbol or requested_symbol

        self._real_futures = real_data_loader.load_price_history(futures_path)
        self._real_chain   = real_data_loader.load_option_chain(chain_path)
        self._real_pcr     = real_data_loader.load_pcr_data(pcr_path, self._real_chain)
        self._real_chain_symbol = active_symbol

        return {
            "symbol":       active_symbol,
            "futures_rows": len(self._real_futures),
            "chain_rows":   len(self._real_chain),
            "pcr_rows":     len(self._real_pcr),
            "spot":         float(self._real_chain["spot"].iloc[0]),
            "chain_date":   str(self._real_chain["date"].iloc[0].date()),
        }

    def _infer_real_data_symbol(self, futures_path: str, chain_path: str, pcr_path: str) -> Optional[str]:
        """Infer symbol from real-data file names using configured symbols."""
        haystack = " ".join([
            Path(futures_path).name.upper(),
            Path(chain_path).name.upper(),
            Path(pcr_path).name.upper(),
        ])
        symbols = list(self.config.get("symbols", {}).get("indices", [])) + list(
            self.config.get("symbols", {}).get("stocks", [])
        )

        # Match longer names first (e.g. BANKNIFTY before NIFTY)
        for sym in sorted({str(s).upper().strip() for s in symbols if s}, key=len, reverse=True):
            if re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", haystack):
                return sym
        return None

    def clear_real_data(self) -> None:
        """Revert to synthetic data for all queries."""
        self._real_futures      = None
        self._real_chain        = None
        self._real_pcr          = None
        self._real_chain_symbol = None

    def get_available_symbols(self) -> list:
        """Return indices only (for backward-compat with existing calls)."""
        return self.config["symbols"]["indices"]

    def get_all_symbols(self) -> dict:
        """
        Return all symbols grouped by type.

        Returns
        -------
        dict with keys: 'indices' (list), 'stocks' (list)
        """
        return {
            "indices": self.config["symbols"].get("indices", []),
            "stocks":  self.config["symbols"].get("stocks", []),
        }

    def ensure_symbol_data(self, symbol: str) -> None:
        """Generate synthetic data for symbol on demand (e.g., for stocks)."""
        self._ensure_data_exists(symbol)

    def get_futures_history(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load daily futures OHLCV + Open Interest data for a symbol.

        Columns returned
        ----------------
        date, open, high, low, close, volume, oi

        How to interpret
        -----------------
        • close     : Settlement price for that day.
        • volume    : Number of contracts traded — a proxy for activity.
        • oi        : Open Interest = total outstanding contracts.
                      Rising OI with rising price = strong bullish trend.
                      Falling OI with rising price = short-covering, weak trend.

        Parameters
        ----------
        symbol     : str  — e.g. "NIFTY", "BANKNIFTY"
        start_date : str  — "YYYY-MM-DD" or None (returns full history)
        end_date   : str  — "YYYY-MM-DD" or None

        Returns
        -------
        pd.DataFrame  (sorted by date, filtered to the requested range)
        """
        # --- Use real data if loaded ---
        if self._real_futures is not None and symbol == (self._real_chain_symbol or "NIFTY"):
            df = self._real_futures.copy()
            if start_date:
                df = df[df["date"] >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df["date"] <= pd.Timestamp(end_date)]
            return df.reset_index(drop=True)

        # --- Fall back to synthetic CSV ---
        path = self.data_dir / f"futures_{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Futures data file not found: {path}")

        df = pd.read_csv(path, parse_dates=["date"])
        df = df.sort_values("date").reset_index(drop=True)

        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        if df.empty:
            logger.warning("No futures data for %s between %s and %s", symbol, start_date, end_date)

        return df.reset_index(drop=True)

    def get_option_chain(
        self,
        symbol: str,
        date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load option chain snapshot for the given symbol and date.

        If `date` is None or has no exact match, the nearest available
        date (looking backwards) is returned.

        Columns returned
        ----------------
        date, strike, CE_LTP, CE_IV, CE_OI, CE_Volume,
                      PE_LTP, PE_IV, PE_OI, PE_Volume, spot

        How to interpret
        -----------------
        • CE_LTP / PE_LTP : Last traded price of call / put.
        • CE_IV  / PE_IV  : Implied volatility (%) — the market's expectation
                            of future volatility embedded in the option price.
        • CE_OI  / PE_OI  : Open interest by strike.
                            Max Pain = strike with minimum total OI value.
        • spot            : Index spot price at time of snapshot.

        Returns
        -------
        pd.DataFrame  for the selected date (one row per strike)
        """
        # --- Use real data if loaded ---
        if self._real_chain is not None and symbol == (self._real_chain_symbol or "NIFTY"):
            logger.info("Serving real option chain: %d strikes, date=%s",
                        len(self._real_chain), self._real_chain["date"].iloc[0].date())
            return self._real_chain.copy()

        # --- Fall back to synthetic CSV ---
        path = self.data_dir / f"option_chain_{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Option chain file not found: {path}")

        df = pd.read_csv(path, parse_dates=["date"])
        df = df.sort_values(["date", "strike"]).reset_index(drop=True)

        available_dates = sorted(df["date"].unique())
        if not available_dates:
            raise ValueError(f"No option chain data available for {symbol}")

        if date is None:
            selected = available_dates[-1]
        else:
            target = pd.Timestamp(date)
            # Find nearest date ≤ target
            past = [d for d in available_dates if d <= target]
            selected = past[-1] if past else available_dates[0]

        result = df[df["date"] == selected].reset_index(drop=True)
        logger.info("Loaded option chain for %s on %s (%d strikes)", symbol, selected.date(), len(result))
        return result

    def get_pcr(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Load daily Put-Call Ratio time series.

        Columns returned
        ----------------
        date, pcr_oi, pcr_vol, total_ce_oi, total_pe_oi

        What is PCR?
        ------------
        PCR (Put-Call Ratio) = Total Put OI / Total Call OI

        It is one of the most-watched sentiment indicators in Indian markets.

        Typical interpretation (contrarian):
        • PCR > 1.2  → Heavy put buying → market may be over-hedged/fearful
                       → Potential contrarian BUY signal (NOT a guarantee)
        • PCR < 0.8  → Heavy call buying → market may be over-optimistic
                       → Potential contrarian SELL/caution signal
        • PCR ≈ 1.0  → Balanced positioning

        Important caveat: PCR works best as a *sentiment extreme* indicator,
        not as a standalone trading signal.  Always combine with price action.

        Returns
        -------
        pd.DataFrame  sorted by date, filtered to the requested range
        """
        # --- Use real data if loaded ---
        if self._real_pcr is not None and symbol == (self._real_chain_symbol or "NIFTY"):
            df = self._real_pcr.copy()
            if start_date:
                df = df[df["date"] >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df["date"] <= pd.Timestamp(end_date)]
            return df.reset_index(drop=True)

        # --- Fall back to synthetic CSV ---
        path = self.data_dir / f"pcr_{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"PCR data file not found: {path}")

        df = pd.read_csv(path, parse_dates=["date"])
        df = df.sort_values("date").reset_index(drop=True)

        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        return df.reset_index(drop=True)

    def get_available_option_dates(self, symbol: str) -> list:
        """Return sorted list of available option chain dates for a symbol."""
        if self._real_chain is not None and symbol == (self._real_chain_symbol or "NIFTY"):
            return sorted(self._real_chain["date"].dt.date.unique().tolist())
        path = self.data_dir / f"option_chain_{symbol}.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path, parse_dates=["date"])
        return sorted(df["date"].dt.date.unique().tolist())

    # ------------------------------------------------------------------
    # Data generation (runs once, then cached as CSVs)
    # ------------------------------------------------------------------

    def _ensure_data_exists(self, symbol: str) -> None:
        """Generate synthetic data files if they do not already exist."""
        futures_path      = self.data_dir / f"futures_{symbol}.csv"
        option_chain_path = self.data_dir / f"option_chain_{symbol}.csv"
        pcr_path          = self.data_dir / f"pcr_{symbol}.csv"

        if futures_path.exists() and option_chain_path.exists() and pcr_path.exists():
            logger.info("Sample data already exists for %s — skipping generation.", symbol)
            return

        logger.info("Generating synthetic sample data for %s …", symbol)

        futures_df      = self._generate_futures_data(symbol)
        option_chain_df = self._generate_option_chain_data(symbol, futures_df)
        pcr_df          = self._generate_pcr_data(option_chain_df)

        futures_df.to_csv(futures_path, index=False)
        option_chain_df.to_csv(option_chain_path, index=False)
        pcr_df.to_csv(pcr_path, index=False)

        logger.info(
            "Data generated: %d futures rows, %d option chain rows, %d PCR rows.",
            len(futures_df), len(option_chain_df), len(pcr_df),
        )

    def _generate_futures_data(self, symbol: str) -> pd.DataFrame:
        """
        Synthesise two years of daily NIFTY/BANKNIFTY futures data (2023–2024).

        Method: Geometric Brownian Motion (GBM)
        ----------------------------------------
        GBM is the stochastic process assumed by Black-Scholes.  Each day's
        return is drawn from a log-normal distribution:

            S(t+dt) = S(t) · exp[(μ − σ²/2)·dt + σ·√dt·Z]

        where Z ~ N(0,1), μ = annual drift, σ = annual volatility, dt = 1/252.

        Parameters used (approximate historical values for Indian indices):
        • NIFTY      : start ₹18,000, μ=15% p.a., σ=15% p.a.
        • BANKNIFTY  : start ₹42,000, μ=12% p.a., σ=20% p.a.
        • FINNIFTY   : start ₹18,500, μ=18% p.a., σ=18% p.a.
        """
        rng = np.random.default_rng(seed={"NIFTY": 42, "BANKNIFTY": 43, "FINNIFTY": 44}.get(symbol, 42))

        # Approximate 2023 start prices and volatilities for common NSE instruments.
        # These are fictional/educational approximations — not real historical prices.
        params = {
            "NIFTY":     {"S0": 18000,  "mu": 0.15, "sigma": 0.15},
            "BANKNIFTY": {"S0": 42000,  "mu": 0.12, "sigma": 0.20},
            "FINNIFTY":  {"S0": 18500,  "mu": 0.18, "sigma": 0.18},
            # Stocks (fictional start prices, approximate historical volatility)
            "RELIANCE":  {"S0":  2400,  "mu": 0.12, "sigma": 0.22},
            "TCS":       {"S0":  3300,  "mu": 0.10, "sigma": 0.20},
            "INFY":      {"S0":  1450,  "mu": 0.11, "sigma": 0.22},
            "HDFCBANK":  {"S0":  1600,  "mu": 0.12, "sigma": 0.20},
            "ICICIBANK": {"S0":   950,  "mu": 0.15, "sigma": 0.23},
            "SBIN":      {"S0":   580,  "mu": 0.14, "sigma": 0.25},
            "WIPRO":     {"S0":   420,  "mu": 0.10, "sigma": 0.22},
            "BAJFINANCE":{"S0":  7000,  "mu": 0.13, "sigma": 0.26},
            "TATASTEEL": {"S0":   130,  "mu": 0.11, "sigma": 0.30},
            "ADANIENT":  {"S0":  2500,  "mu": 0.16, "sigma": 0.35},
        }
        p   = params.get(symbol, params["NIFTY"])
        S0  = p["S0"]
        mu  = p["mu"]
        sig = p["sigma"]
        dt  = 1.0 / 252

        dates = pd.bdate_range(start="2023-01-02", end="2024-12-31")
        n = len(dates)

        # Daily log-returns using GBM
        daily_rets = np.exp(
            (mu - 0.5 * sig ** 2) * dt
            + sig * np.sqrt(dt) * rng.standard_normal(n)
        )
        close = S0 * np.cumprod(daily_rets)

        # Open = previous close ± small gap
        prev_close = np.roll(close, 1)
        prev_close[0] = S0
        open_ = prev_close * (1 + rng.normal(0, sig * np.sqrt(dt) * 0.3, n))

        # High / Low: intraday range proportional to daily volatility
        intraday_range = close * sig * np.sqrt(dt) * rng.uniform(0.8, 2.0, n)
        high = np.maximum(close, open_) + intraday_range * 0.5
        low  = np.minimum(close, open_) - intraday_range * 0.5

        # Volume (lot-equivalent contracts traded)
        base_vol = 500_000 if symbol == "NIFTY" else 200_000
        volume = rng.lognormal(np.log(base_vol), 0.5, n).astype(int)

        # Open Interest — gradually trending with noise
        base_oi = 10_000_000 if symbol == "NIFTY" else 5_000_000
        oi_trend = np.linspace(0.85, 1.15, n)
        oi = (base_oi * oi_trend * np.exp(rng.normal(0, 0.05, n))).astype(int)

        return pd.DataFrame({
            "date":   dates,
            "open":   np.round(open_,  2),
            "high":   np.round(high,   2),
            "low":    np.round(low,    2),
            "close":  np.round(close,  2),
            "volume": volume,
            "oi":     oi,
        })

    def _generate_option_chain_data(
        self, symbol: str, futures_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Synthesise weekly option chain snapshots.

        For each trading Friday we create a full option chain with:
        • Strikes from ATM−10 ticks to ATM+10 ticks
        • CE/PE prices from Black-Scholes
        • IV smile: flat for calls, put-skew for OTM puts (realistic)
        • OI shaped like a normal distribution centred at ATM

        IV Smile / Skew (educational note)
        ------------------------------------
        In reality, OTM put IVs are higher than ATM IVs because:
        1. Portfolio managers buy OTM puts as tail-risk insurance.
        2. The 1987 crash taught markets that fat tails exist.
        The resulting asymmetric IV shape is called the 'volatility skew'
        and is visible in every NSE option chain.
        """
        rng  = np.random.default_rng(seed=123)
        tick = self.config["data"]["tick_sizes"].get(symbol, 50)
        r    = self.config["market"]["risk_free_rate"]

        df_idx  = futures_df.set_index("date")
        records = []

        # Resample to weekly (Fridays)
        weekly = futures_df.copy()
        weekly["week"] = weekly["date"].dt.to_period("W")
        weekly_last = weekly.groupby("week").last().reset_index()

        for _, row in weekly_last.iterrows():
            date  = row["date"]
            spot  = float(row["close"])
            atm   = round(spot / tick) * tick

            # Assume ~30 calendar days to next monthly expiry
            T_days = rng.integers(20, 45)
            T      = T_days / 365.0

            for i in range(-10, 11):
                strike = atm + i * tick

                # Base ATM IV with daily noise
                atm_iv = 0.16 + rng.uniform(-0.03, 0.03)

                # IV skew: OTM puts are pricier (negative i = put-side)
                if i < 0:
                    pe_iv = atm_iv + abs(i) * 0.007   # ~0.7% per tick OTM
                    ce_iv = atm_iv + abs(i) * 0.002
                elif i > 0:
                    pe_iv = atm_iv + i * 0.003
                    ce_iv = atm_iv - i * 0.001         # call IV slightly lower
                else:
                    pe_iv = atm_iv
                    ce_iv = atm_iv

                ce_iv = max(ce_iv, 0.06)
                pe_iv = max(pe_iv, 0.06)

                ce_ltp = black_scholes_price(spot, strike, T, r, ce_iv, "CE")
                pe_ltp = black_scholes_price(spot, strike, T, r, pe_iv, "PE")

                # OI: normal distribution centered at ATM
                sigma_oi = tick * 4
                oi_weight = np.exp(-((strike - atm) ** 2) / (2 * sigma_oi ** 2))
                base_ce_oi = int(rng.lognormal(np.log(max(oi_weight * 600_000, 1000)), 0.35))
                base_pe_oi = int(rng.lognormal(np.log(max(oi_weight * 700_000, 1000)), 0.35))

                ce_vol = int(base_ce_oi * rng.uniform(0.15, 0.35))
                pe_vol = int(base_pe_oi * rng.uniform(0.15, 0.35))

                records.append({
                    "date":      date,
                    "strike":    strike,
                    "CE_LTP":    round(max(ce_ltp, 0.05), 2),
                    "CE_IV":     round(ce_iv * 100.0,     2),
                    "CE_OI":     base_ce_oi,
                    "CE_Volume": ce_vol,
                    "PE_LTP":    round(max(pe_ltp, 0.05), 2),
                    "PE_IV":     round(pe_iv * 100.0,     2),
                    "PE_OI":     base_pe_oi,
                    "PE_Volume": pe_vol,
                    "spot":      round(spot, 2),
                })

        return pd.DataFrame(records)

    def _generate_pcr_data(self, option_chain_df: pd.DataFrame) -> pd.DataFrame:
        """
        Derive daily PCR from the option chain snapshots.

        PCR (OI-based) = Σ Put OI across all strikes / Σ Call OI across all strikes

        We also compute PCR (volume-based) which is noisier but more real-time.
        Both are useful — OI-based PCR reflects accumulated positions, while
        volume-based PCR reflects the day's trading sentiment.
        """
        records = []
        for date, grp in option_chain_df.groupby("date"):
            total_ce_oi  = int(grp["CE_OI"].sum())
            total_pe_oi  = int(grp["PE_OI"].sum())
            total_ce_vol = int(grp["CE_Volume"].sum())
            total_pe_vol = int(grp["PE_Volume"].sum())

            pcr_oi  = total_pe_oi  / total_ce_oi  if total_ce_oi  > 0 else 1.0
            pcr_vol = total_pe_vol / total_ce_vol if total_ce_vol > 0 else 1.0

            records.append({
                "date":        date,
                "pcr_oi":      round(pcr_oi,  3),
                "pcr_vol":     round(pcr_vol, 3),
                "total_ce_oi": total_ce_oi,
                "total_pe_oi": total_pe_oi,
            })

        return pd.DataFrame(records).sort_values("date").reset_index(drop=True)
