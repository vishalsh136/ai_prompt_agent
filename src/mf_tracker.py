"""
src/mf_tracker.py — Mutual Fund Performance Tracker
=====================================================

Fetches NAV data from the free, open MF API (api.mfapi.in) — no authentication
required. Provides performance analytics, SIP simulation, and comparison
with the NIFTY 50 benchmark.

API used:
  Search : GET https://api.mfapi.in/mf/search?q={query}
  History: GET https://api.mfapi.in/mf/{scheme_code}

Returns full NAV history since fund inception (thousands of daily records).

⚠️  DISCLAIMER: All analysis is for educational purposes only.
    Mutual fund investments are subject to market risk.
    Past performance is NOT indicative of future returns.
    Consult a SEBI-registered investment advisor before investing.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.mf_tracker")

# ---------------------------------------------------------------------------
# Popular funds catalogue — curated default list (Direct Growth plans only)
# ---------------------------------------------------------------------------
POPULAR_FUNDS: Dict[str, Dict] = {
    # ── Index Funds (Passive) ────────────────────────────────────────────────
    "120716": {"name": "UTI Nifty 50 Index Fund — Direct Growth",
               "category": "Index — Nifty 50",  "risk": "Moderate", "section": "Index"},
    "118482": {"name": "Bandhan Nifty 50 Index Fund — Direct Growth",
               "category": "Index — Nifty 50",  "risk": "Moderate", "section": "Index"},
    "113296": {"name": "Nippon India Nifty 50 Index Fund — Growth",
               "category": "Index — Nifty 50",  "risk": "Moderate", "section": "Index"},
    # ── Large Cap (Active) ───────────────────────────────────────────────────
    "118825": {"name": "Mirae Asset Large Cap Fund — Direct Growth",
               "category": "Large Cap — Active", "risk": "Moderate", "section": "Equity"},
    # ── Flexi / Multi Cap ────────────────────────────────────────────────────
    "122639": {"name": "Parag Parikh Flexi Cap Fund — Direct Growth",
               "category": "Flexi Cap",          "risk": "Moderate-High", "section": "Equity"},
    # ── Small Cap ────────────────────────────────────────────────────────────
    "125497": {"name": "SBI Small Cap Fund — Direct Growth",
               "category": "Small Cap",           "risk": "High", "section": "Equity"},
    # ── Mid Cap ─────────────────────────────────────────────────────────────
    "118989": {"name": "HDFC Mid-Cap Opportunities — Direct Growth",
               "category": "Mid Cap",             "risk": "High", "section": "Equity"},
    # ── ELSS / Tax-Saving (Section 80C — 3-year lock-in) ────────────────────
    "120503": {"name": "Axis ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "135781": {"name": "Mirae Asset ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "147481": {"name": "Parag Parikh ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "120847": {"name": "Quant ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "119773": {"name": "Kotak ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "119242": {"name": "DSP ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "119060": {"name": "HDFC ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "118803": {"name": "Nippon India ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
    "118285": {"name": "Canara Robeco ELSS Tax Saver — Direct Growth",
               "category": "ELSS (Tax Saving)",   "risk": "High",
               "section": "ELSS", "lock_in_yrs": 3, "tax_80c": True},
}

MF_API_BASE = "https://api.mfapi.in/mf"

# Convenient filtered views
ELSS_FUNDS  = {k: v for k, v in POPULAR_FUNDS.items() if v.get("section") == "ELSS"}
INDEX_FUNDS = {k: v for k, v in POPULAR_FUNDS.items() if v.get("section") == "Index"}
EQUITY_FUNDS= {k: v for k, v in POPULAR_FUNDS.items() if v.get("section") == "Equity"}


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def search_funds(query: str, max_results: int = 10) -> List[Dict]:
    """
    Search mutual funds by name using the MF API.
    Returns list of {schemeCode, schemeName} dicts.
    """
    encoded = urllib.parse.quote(query)
    url = f"{MF_API_BASE}/search?q={encoded}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            results = json.loads(r.read())
        return results[:max_results]
    except Exception as e:
        logger.warning("MF search failed for '%s': %s", query, e)
        return []


def load_nav_history(
    scheme_code: str,
    years: int = 3,
) -> Tuple[pd.DataFrame, Dict]:
    """
    Fetch NAV history for a fund from api.mfapi.in.

    Parameters
    ----------
    scheme_code : str  — AMFI scheme code (e.g., "120716")
    years       : int  — how many years of history to return

    Returns
    -------
    (nav_df, meta)
    nav_df : pd.DataFrame with columns [date, nav, nav_change_pct]
             Sorted ascending by date.
    meta   : dict with scheme_name, scheme_category, fund_house
    """
    url = f"{MF_API_BASE}/{scheme_code}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        raise RuntimeError(f"Failed to fetch fund {scheme_code}: {e}")

    meta  = data.get("meta", {})
    rows  = data.get("data", [])

    if not rows:
        raise ValueError(f"No NAV data returned for scheme {scheme_code}")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
    df["nav"]  = pd.to_numeric(df["nav"], errors="coerce")
    df = df.dropna().sort_values("date").reset_index(drop=True)

    # Filter to requested years
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
    df = df[df["date"] >= cutoff].copy()

    if df.empty:
        raise ValueError(f"No data in last {years} years for scheme {scheme_code}")

    # Daily return
    df["nav_change_pct"] = df["nav"].pct_change() * 100
    df["nav_change_pct"] = df["nav_change_pct"].fillna(0).round(4)

    # Normalise to 100 (base = 100 at start of period)
    df["nav_indexed"] = df["nav"] / df["nav"].iloc[0] * 100

    logger.info("Loaded %s: %d NAV records, %s to %s",
                meta.get("scheme_name", scheme_code),
                len(df),
                df["date"].min().date(),
                df["date"].max().date())

    return df, meta


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def compute_fund_metrics(
    nav_df: pd.DataFrame,
    risk_free_rate: float = 0.065,
) -> Dict:
    """
    Compute risk-adjusted performance metrics for a fund.

    Returns
    -------
    dict with:
      cagr_pct, total_return_pct, sharpe_ratio, sortino_ratio,
      calmar_ratio, max_drawdown_pct, volatility_pct,
      best_day_pct, worst_day_pct, profitable_days_pct
    """
    if nav_df.empty or len(nav_df) < 10:
        return {}

    nav    = nav_df["nav"].values
    dates  = nav_df["date"].values
    n_days = len(nav)

    # Returns
    daily_ret  = np.diff(nav) / nav[:-1]
    total_ret  = (nav[-1] / nav[0]) - 1
    n_years    = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25
    cagr       = (nav[-1] / nav[0]) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Volatility
    ann_vol    = float(np.std(daily_ret) * np.sqrt(252))
    ann_ret    = float(np.mean(daily_ret) * 252)

    # Max Drawdown
    peak   = np.maximum.accumulate(nav)
    dd     = (nav - peak) / peak
    max_dd = float(np.min(dd))

    # Sharpe
    sharpe  = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0

    # Sortino
    neg_ret  = daily_ret[daily_ret < 0]
    down_dev = float(np.std(neg_ret) * np.sqrt(252)) if len(neg_ret) else 0
    sortino  = (ann_ret - risk_free_rate) / down_dev if down_dev > 0 else 0

    # Calmar
    calmar   = (cagr / abs(max_dd)) if max_dd < 0 else 0

    # Win rate
    win_days = float(np.sum(daily_ret > 0) / len(daily_ret) * 100)

    return {
        "cagr_pct":            round(cagr         * 100, 2),
        "total_return_pct":    round(total_ret     * 100, 2),
        "sharpe_ratio":        round(sharpe,              2),
        "sortino_ratio":       round(sortino,             2),
        "calmar_ratio":        round(calmar,              2),
        "max_drawdown_pct":    round(max_dd         * 100, 2),
        "volatility_pct":      round(ann_vol        * 100, 2),
        "best_day_pct":        round(float(np.max(daily_ret)) * 100, 2),
        "worst_day_pct":       round(float(np.min(daily_ret)) * 100, 2),
        "profitable_days_pct": round(win_days,             1),
        "n_years":             round(n_years,              2),
        "n_days":              n_days,
        "start_nav":           round(float(nav[0]),  2),
        "current_nav":         round(float(nav[-1]), 2),
    }


def compute_rolling_returns(nav_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute 1-year, 3-year, 5-year rolling CAGR at each date.
    Returns a DataFrame with date + rolling_1y, rolling_3y, rolling_5y columns.
    """
    df = nav_df.copy().set_index("date")["nav"]

    def _rolling_cagr(series: pd.Series, years: int) -> pd.Series:
        periods = int(years * 252)
        if len(series) < periods:
            return pd.Series(np.nan, index=series.index)
        shifted = series.shift(periods)
        cagr = (series / shifted) ** (1 / years) - 1
        return cagr * 100

    out = pd.DataFrame(index=df.index)
    out["rolling_1y"] = _rolling_cagr(df, 1).round(2)
    out["rolling_3y"] = _rolling_cagr(df, 3).round(2)
    out["rolling_5y"] = _rolling_cagr(df, 5).round(2)
    return out.reset_index().dropna(how="all", subset=["rolling_1y"])


def simulate_sip(
    nav_df: pd.DataFrame,
    monthly_amount: float = 5000,
    start_date: Optional[str] = None,
) -> Dict:
    """
    Simulate a monthly SIP (Systematic Investment Plan).

    Invests `monthly_amount` on the 1st available trading day of each month.

    Returns
    -------
    dict with:
      total_invested, current_value, absolute_return, xirr_approx,
      units_accumulated, monthly_series (DataFrame with date, invested, value)
    """
    df = nav_df.copy()
    if start_date:
        df = df[df["date"] >= pd.Timestamp(start_date)]

    if df.empty:
        return {}

    # Monthly first trading days
    df["ym"]   = df["date"].dt.to_period("M")
    monthly    = df.groupby("ym").first().reset_index()

    units_held   = 0.0
    total_invest = 0.0
    series_rows  = []

    for _, row in monthly.iterrows():
        nav_val       = float(row["nav"])
        units_bought  = monthly_amount / nav_val
        units_held   += units_bought
        total_invest += monthly_amount
        current_val   = units_held * nav_val
        series_rows.append({
            "date":          row["date"],
            "invested_cum":  round(total_invest, 0),
            "value_cum":     round(current_val,  0),
            "pnl":           round(current_val - total_invest, 0),
        })

    if not series_rows:
        return {}

    last   = series_rows[-1]
    abs_ret = (last["value_cum"] - last["invested_cum"]) / last["invested_cum"] * 100

    # XIRR approximation via bisection on NPV of monthly cash flows
    # cash_flows: [-monthly_amount each month] + [+final_value at end]
    _cash_flows = [-monthly_amount] * len(series_rows)
    _cash_flows[-1] += last["value_cum"]   # add redemption at end

    def _npv(rate_annual: float) -> float:
        r = rate_annual / 12
        return sum(cf / (1 + r) ** i for i, cf in enumerate(_cash_flows))

    lo, hi = -0.5, 5.0   # -50% to 500% annual
    xirr   = 0.0
    try:
        for _ in range(60):
            mid = (lo + hi) / 2
            if _npv(mid) > 0:
                lo = mid
            else:
                hi = mid
        xirr = (lo + hi) / 2
    except Exception:
        n_years = (monthly["date"].max() - monthly["date"].min()).days / 365.25
        xirr = (last["value_cum"] / last["invested_cum"]) ** (1 / n_years) - 1 if n_years > 0.5 else 0

    return {
        "total_invested":    round(total_invest, 0),
        "current_value":     round(last["value_cum"], 0),
        "absolute_return_pct": round(abs_ret, 2),
        "xirr_approx_pct":   round(xirr * 100, 2),
        "units_accumulated": round(units_held, 4),
        "current_nav":       round(float(monthly.iloc[-1]["nav"]), 4),
        "months":            len(series_rows),
        "series":            pd.DataFrame(series_rows),
    }


def compare_with_nifty(
    nav_df: pd.DataFrame,
    nifty_csv: str = "downloads/app_historical_NIFTY.csv",
) -> pd.DataFrame:
    """
    Normalise fund NAV and NIFTY 50 to the same start date (base = 100)
    for a like-for-like performance comparison.

    Returns DataFrame with columns: date, fund_indexed, nifty_indexed
    """
    try:
        nifty = pd.read_csv(nifty_csv)
        nifty.columns = [c.strip() for c in nifty.columns]
        nifty["date"] = pd.to_datetime(nifty["Date"], format="%d-%b-%Y", errors="coerce")
        nifty = nifty.dropna(subset=["date"]).sort_values("date")
        nifty["close"] = pd.to_numeric(nifty["Close"], errors="coerce")
        nifty = nifty[["date", "close"]].dropna()
    except Exception:
        return pd.DataFrame()

    # Align on date range
    start = max(nav_df["date"].min(), nifty["date"].min())
    fund  = nav_df[nav_df["date"] >= start].copy()
    nifty = nifty[nifty["date"] >= start].copy()

    if fund.empty or nifty.empty:
        return pd.DataFrame()

    fund["fund_indexed"]  = fund["nav"]   / fund["nav"].iloc[0]   * 100
    nifty["nifty_indexed"] = nifty["close"] / nifty["close"].iloc[0] * 100

    merged = pd.merge_asof(
        fund[["date", "fund_indexed"]].sort_values("date"),
        nifty[["date", "nifty_indexed"]].sort_values("date"),
        on="date", direction="nearest",
    )
    return merged
