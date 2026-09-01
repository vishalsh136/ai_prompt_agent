"""
src/real_data_loader.py — Parse real NSE market data files
============================================================

Supported file formats
----------------------
1. NSE Option Chain CSV  (downloaded from nseindia.com → option chain page)
   Format: CALLS section | STRIKE | PUTS section, two-row header.

2. NSE NIFTY 50 Historical CSV  (downloaded from nseindia.com → historical data)
   Format: Date, Open, High, Low, Close, Shares Traded, Turnover (₹ Cr)

3. NSE PCR (Put-Call Ratio) intraday CSV
   Format: TIME, CREATED-AT, PCR, CHG IN OI PCR, VPCR

Each loader returns a pandas DataFrame in the exact schema expected by
DataProvider so the rest of the app works without changes.

⚠️  DISCLAIMER: Loading real market data does NOT make this tool capable of
    live trading. All analysis remains educational and hypothetical.
    This tool does NOT execute orders or connect to any broker.
"""

import csv
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("market_study_tool.real_data_loader")


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _to_float(val: str) -> float:
    """
    Convert an NSE-style number string to float.

    NSE CSVs use Indian-style comma grouping  ("1,32,770")
    and '-' or '--' for missing values.
    """
    if not isinstance(val, str):
        try:
            return float(val)
        except (TypeError, ValueError):
            return np.nan
    val = val.strip().replace(",", "")
    if val in ("-", "--", ""):
        return np.nan
    try:
        return float(val)
    except ValueError:
        return np.nan


# ---------------------------------------------------------------------------
# Option Chain
# ---------------------------------------------------------------------------

def load_option_chain(path: str) -> pd.DataFrame:
    """
    Parse an NSE option chain CSV into a tidy DataFrame.

    NSE option chain file structure
    --------------------------------
    Line 0 : CALLS,,PUTS          ← section labels (skip)
    Line 1 : column names (23 cols)
    Lines 2+: data rows

    Column positions (0-indexed):
      0  : (blank row-label)
      1  : CE_OI
      2  : CE_CHNG_OI
      3  : CE_Volume
      4  : CE_IV   (implied volatility %)
      5  : CE_LTP  (last traded price)
      6  : CE_CHNG (price change)
      7–10: CE bid/ask quantities and prices
      11 : STRIKE
      12–15: PE bid/ask quantities and prices
      16 : PE_CHNG
      17 : PE_LTP
      18 : PE_IV
      19 : PE_Volume
      20 : PE_CHNG_OI
      21 : PE_OI
      22 : (blank)

    Spot price is inferred from put-call parity:
        At ATM strike K*: CE_LTP ≈ PE_LTP  →  spot ≈ K* + (CE - PE)

    Returns
    -------
    pd.DataFrame with columns:
        date, strike, CE_LTP, CE_IV, CE_OI, CE_Volume,
        PE_LTP, PE_IV, PE_OI, PE_Volume, spot

    The 'date' is the *expiry date* parsed from the filename
    (e.g., "option-chain-ED-NIFTY-30-Jun-2026.csv" → 2026-06-30).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Option chain file not found: {path.resolve()}")

    # --- Extract expiry date from filename ---
    date_match = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", path.stem)
    if date_match:
        chain_date = pd.to_datetime(
            f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}",
            format="%d-%b-%Y",
        )
    else:
        chain_date = pd.Timestamp.today().normalize()
        logger.warning("Could not parse date from filename %s; using today.", path.name)

    # --- Read raw lines ---
    with open(path, encoding="utf-8-sig", errors="ignore") as f:
        lines = f.readlines()

    # NSE layout: line 0 = section labels, line 1 = column names, line 2+ = data
    COL_NAMES = [
        "_row",
        "CE_OI", "CE_CHNG_OI", "CE_Volume", "CE_IV", "CE_LTP", "CE_CHNG",
        "CE_BID_QTY", "CE_BID", "CE_ASK", "CE_ASK_QTY",
        "strike",
        "PE_BID_QTY", "PE_BID", "PE_ASK", "PE_ASK_QTY",
        "PE_CHNG", "PE_LTP", "PE_IV", "PE_Volume", "PE_CHNG_OI", "PE_OI",
        "_end",
    ]

    rows = []
    for line in lines[2:]:                      # skip line 0 and line 1
        if not line.strip():
            continue
        parts = next(csv.reader([line]))
        # Pad or trim to exactly 23 columns
        parts = parts[:23] if len(parts) >= 23 else parts + [""] * (23 - len(parts))
        rows.append(parts)

    if not rows:
        raise ValueError(f"No data rows found in option chain file: {path}")

    df = pd.DataFrame(rows, columns=COL_NAMES)

    # --- Convert numeric columns ---
    NUMERIC = [
        "CE_OI", "CE_CHNG_OI", "CE_Volume", "CE_IV", "CE_LTP",
        "CE_BID", "CE_ASK",
        "strike",
        "PE_BID", "PE_ASK", "PE_CHNG", "PE_LTP", "PE_IV",
        "PE_Volume", "PE_CHNG_OI", "PE_OI",
    ]
    for col in NUMERIC:
        df[col] = df[col].apply(_to_float)

    # Drop rows without a valid strike
    df = df.dropna(subset=["strike"]).copy()
    df["strike"] = df["strike"].round(0).astype(int)

    # Fill NaN OI/Volume (deep-ITM or deep-OTM may show '-')
    for col in ["CE_OI", "PE_OI", "CE_Volume", "PE_Volume"]:
        df[col] = df[col].fillna(0).astype(int)

    df["date"] = chain_date

    # --- Infer spot price from put-call parity ---
    # For European options: CE - PE ≈ S - K  (ignoring carry for short-dated options)
    # At ATM:  CE ≈ PE  →  parity_diff ≈ 0  →  spot ≈ strike
    valid = df["CE_LTP"].notna() & df["PE_LTP"].notna() & (df["CE_LTP"] > 0) & (df["PE_LTP"] > 0)
    df_valid = df[valid].copy()
    if df_valid.empty:
        spot = float(df["strike"].median())
        logger.warning("Could not infer spot from parity — using median strike %.0f", spot)
    else:
        df_valid["parity_diff"] = (df_valid["CE_LTP"] - df_valid["PE_LTP"]).abs()
        atm_idx  = df_valid["parity_diff"].idxmin()
        atm_k    = float(df_valid.loc[atm_idx, "strike"])
        ce_atm   = float(df_valid.loc[atm_idx, "CE_LTP"])
        pe_atm   = float(df_valid.loc[atm_idx, "PE_LTP"])
        spot     = round(atm_k + (ce_atm - pe_atm), 2)

    df["spot"] = spot

    # Fill remaining NaN prices
    df["CE_LTP"] = df["CE_LTP"].fillna(0.05)
    df["PE_LTP"] = df["PE_LTP"].fillna(0.05)
    df["CE_IV"]  = df["CE_IV"].fillna(0.0)
    df["PE_IV"]  = df["PE_IV"].fillna(0.0)

    result = df[[
        "date", "strike", "CE_LTP", "CE_IV", "CE_OI", "CE_Volume",
        "PE_LTP", "PE_IV", "PE_OI", "PE_Volume", "spot",
    ]].sort_values("strike").reset_index(drop=True)

    logger.info(
        "Loaded real option chain: %d strikes, expiry=%s, inferred spot=₹%.2f",
        len(result), chain_date.date(), spot,
    )
    return result


# ---------------------------------------------------------------------------
# NIFTY 50 Historical (price history)
# ---------------------------------------------------------------------------

def load_price_history(path: str) -> pd.DataFrame:
    """
    Parse NSE NIFTY 50 historical data CSV.

    Expected columns (from nseindia.com historical download):
        Date, Open, High, Low, Close, Shares Traded, Turnover (₹ Cr)

    Note: This is *index* data, not futures data — there is no Open Interest
    column for indices.  OI is set to 0 as a placeholder.

    Returns
    -------
    pd.DataFrame with columns: date, open, high, low, close, volume, oi
    (schema matches DataProvider.get_futures_history)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Price history file not found: {path.resolve()}")

    df = pd.read_csv(path)
    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]

    rename_map = {
        "Date":           "date",
        "Open":           "open",
        "High":           "high",
        "Low":            "low",
        "Close":          "close",
        "Shares Traded":  "volume",
        "Turnover (₹ Cr)":"turnover",
    }
    df = df.rename(columns=rename_map)

    # Parse dates: NSE uses "25-JUN-2026" format
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Index data has no futures OI; set to 0
    df["oi"] = 0

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)

    df = df.dropna(subset=["close"])

    logger.info(
        "Loaded real price history: %d days, %s → %s",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
    )
    return df[["date", "open", "high", "low", "close", "volume", "oi"]]


# ---------------------------------------------------------------------------
# PCR Data
# ---------------------------------------------------------------------------

def load_pcr_data(
    path: str,
    option_chain_df: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Load PCR data.

    The NSE PCR file is *intraday* — one row per minute for a single trading
    day.  This function:
    1. Reads the intraday file and computes the end-of-day PCR for each date.
    2. If an option_chain_df is provided, derives today's PCR from total OI
       in the chain and appends it so the most recent day is always present.

    Parameters
    ----------
    path             : str        — path to the PCR CSV file
    option_chain_df  : DataFrame  — optional; used to derive today's PCR from OI

    Returns
    -------
    pd.DataFrame with columns: date, pcr_oi, pcr_vol, total_ce_oi, total_pe_oi
    (schema matches DataProvider.get_pcr)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PCR file not found: {path.resolve()}")

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    # Parse date from CREATED-AT column (ISO format: "2026-05-08T00:00:00")
    df["date"] = pd.to_datetime(df["CREATED-AT"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"])

    # Rename columns
    df = df.rename(columns={
        "PCR":           "pcr_oi",
        "VPCR":          "pcr_vol",
        "CHG IN OI PCR": "chg_pcr",
    })

    # Aggregate to daily end-of-day (last reading of the day)
    daily = (
        df.groupby("date")
        .last()
        .reset_index()[["date", "pcr_oi", "pcr_vol"]]
    )
    daily["total_ce_oi"] = 0
    daily["total_pe_oi"] = 0

    # Derive today's PCR from option chain OI if provided
    if option_chain_df is not None and not option_chain_df.empty:
        chain_date   = pd.Timestamp(option_chain_df["date"].iloc[0]).normalize()
        total_ce_oi  = int(option_chain_df["CE_OI"].sum())
        total_pe_oi  = int(option_chain_df["PE_OI"].sum())
        pcr_from_oc  = round(total_pe_oi / total_ce_oi, 4) if total_ce_oi > 0 else 1.0

        # PCR volume from option chain
        total_ce_vol = int(option_chain_df["CE_Volume"].sum())
        total_pe_vol = int(option_chain_df["PE_Volume"].sum())
        pcr_vol_oc   = round(total_pe_vol / total_ce_vol, 4) if total_ce_vol > 0 else 1.0

        # Add or update the chain date row
        chain_row = pd.DataFrame([{
            "date":        chain_date,
            "pcr_oi":      pcr_from_oc,
            "pcr_vol":     pcr_vol_oc,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
        }])

        # Remove any existing row for this date (avoid duplicates)
        daily = daily[daily["date"] != chain_date]
        daily = pd.concat([daily, chain_row], ignore_index=True)

        logger.info(
            "Option chain PCR for %s: OI-based=%.3f, Vol-based=%.3f",
            chain_date.date(), pcr_from_oc, pcr_vol_oc,
        )

    daily = daily.sort_values("date").reset_index(drop=True)
    daily["pcr_oi"]  = daily["pcr_oi"].round(4)
    daily["pcr_vol"] = daily["pcr_vol"].round(4)

    logger.info(
        "Loaded PCR data: %d days, %s → %s",
        len(daily),
        daily["date"].min().date(),
        daily["date"].max().date(),
    )
    return daily


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def validate_files(futures_path: str, chain_path: str, pcr_path: str) -> dict:
    """
    Check which real data files exist and are readable.

    Returns
    -------
    dict with keys: futures_ok, chain_ok, pcr_ok, all_ok, messages
    """
    results   = {}
    messages  = []

    for key, path in [("futures", futures_path), ("chain", chain_path), ("pcr", pcr_path)]:
        p = Path(path)
        # PCR files can be small when only a few ticks are available (expiry days etc.)
        min_size = 50 if key == "pcr" else 200
        ok = p.exists() and p.stat().st_size > min_size
        results[f"{key}_ok"] = ok
        if not ok:
            messages.append(f"❌ {key.title()} file not found or empty: {p.name}")
        else:
            size_kb = p.stat().st_size // 1024
            messages.append(f"✅ {key.title()}: {p.name} ({size_kb} KB)")

    results["all_ok"]  = all(results[k] for k in ["futures_ok", "chain_ok", "pcr_ok"])
    results["messages"] = messages
    return results
