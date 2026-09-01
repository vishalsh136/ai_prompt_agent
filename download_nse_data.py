"""
download_nse_data.py — Download live NSE market data files
===========================================================

Downloads three data sources and saves them to the `downloads/` folder:

  1. NSE Historical Index Data  (nseindia.com)
  2. NSE Option Chain            (nseindia.com)
  3. Put-Call Ratio (PCR)        (niftytrader.in)

Run directly:
    python download_nse_data.py

Or schedule via Task Scheduler (Windows) using schedule_download.bat.

⚠️  DISCLAIMER: This tool is for educational analysis only.
    Do NOT use downloaded data for live trading decisions.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

LOG_FILE = DOWNLOAD_DIR / "download.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("nse_downloader")

# Symbol to download (matches config.yaml default)
SYMBOL = "NIFTY"

# NSE API base
NSE_BASE = "https://www.nseindia.com"

# Common browser-like headers required by NSE (they block plain requests)
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

NIFTYTRADER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.niftytrader.in/",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# NSE Session (required — NSE sets cookies on the home page first)
# ---------------------------------------------------------------------------

def create_nse_session() -> requests.Session:
    """
    Create a requests.Session that has valid NSE cookies.
    NSE blocks API calls unless the session first visited the home page.
    """
    session = requests.Session()
    session.headers.update(NSE_HEADERS)

    logger.info("Initialising NSE session (fetching cookies)…")
    try:
        # Step 1: hit the home page to get session cookies
        resp = session.get(NSE_BASE, timeout=20)
        resp.raise_for_status()
        time.sleep(1)  # brief pause — NSE rate-limits aggressive clients

        # Step 2: hit the option-chain page so the Referer cookie is set
        session.get(f"{NSE_BASE}/option-chain", timeout=20)
        time.sleep(1)

        logger.info("NSE session ready. Cookies: %s", list(session.cookies.keys()))
    except requests.RequestException as exc:
        logger.error("Failed to initialise NSE session: %s", exc)
        raise
    return session


# ---------------------------------------------------------------------------
# Download 1: NSE Historical Index Data
# ---------------------------------------------------------------------------

def download_historical_index(session: requests.Session, symbol: str = SYMBOL) -> Path:
    """
    Download historical OHLCV data for the given index for the past 365 days.
    Saves as:  downloads/historical_{symbol}_{date}.csv
    """
    today = datetime.today()
    from_date = (today - timedelta(days=365)).strftime("%d-%m-%Y")
    to_date = today.strftime("%d-%m-%Y")

    # Map common symbol names to NSE index names
    index_name_map = {
        "NIFTY":     "NIFTY 50",
        "BANKNIFTY": "NIFTY BANK",
        "FINNIFTY":  "NIFTY FIN SERVICE",
    }
    index_name = index_name_map.get(symbol.upper(), symbol)

    url = f"{NSE_BASE}/api/historical/indicesHistory"
    params = {
        "indexType": index_name,
        "from": from_date,
        "to": to_date,
    }

    logger.info("Downloading historical index data for %s (%s to %s)…", symbol, from_date, to_date)
    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("Historical index download failed: %s", exc)
        raise
    except json.JSONDecodeError as exc:
        logger.error("Historical index — unexpected response (not JSON): %s", exc)
        raise

    # NSE returns { "data": { "indexCloseOnlineRecords": [...], ... } }
    records = (
        data.get("data", {}).get("indexCloseOnlineRecords")
        or data.get("data", {}).get("indexTurnoverRecords")
        or data.get("data", [])
    )

    if not records:
        logger.warning("Historical index: no records found in response.")
        logger.debug("Raw response keys: %s", list(data.keys()))

    out_path = DOWNLOAD_DIR / f"historical_{symbol}_{today.strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved historical data → %s  (%d records)", out_path, len(records))
    return out_path


# ---------------------------------------------------------------------------
# Download 2: NSE Option Chain
# ---------------------------------------------------------------------------

def download_option_chain(session: requests.Session, symbol: str = SYMBOL) -> Path:
    """
    Download the current option chain snapshot for the given symbol.
    Saves as:  downloads/option_chain_{symbol}_{date}.json
    """
    # NSE differentiates indices vs equities in the API path
    indices = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
    if symbol.upper() in indices:
        url = f"{NSE_BASE}/api/option-chain-indices"
    else:
        url = f"{NSE_BASE}/api/option-chain-equities"

    params = {"symbol": symbol.upper()}

    logger.info("Downloading option chain for %s…", symbol)
    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.error("Option chain download failed: %s", exc)
        raise
    except json.JSONDecodeError as exc:
        logger.error("Option chain — unexpected response (not JSON): %s", exc)
        raise

    records = data.get("records", {}).get("data", [])
    today = datetime.today()
    out_path = DOWNLOAD_DIR / f"option_chain_{symbol}_{today.strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved option chain → %s  (%d strike records)", out_path, len(records))
    return out_path


# ---------------------------------------------------------------------------
# Download 3: Put-Call Ratio (PCR) from niftytrader.in
# ---------------------------------------------------------------------------

def download_pcr(symbol: str = SYMBOL) -> Path:
    """
    Download the Put-Call Ratio data from niftytrader.in.
    Saves as:  downloads/pcr_{symbol}_{date}.json
    """
    # niftytrader.in exposes a JSON endpoint for PCR data
    symbol_map = {
        "NIFTY":     "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "FINNIFTY":  "FINNIFTY",
    }
    nse_symbol = symbol_map.get(symbol.upper(), symbol.upper())

    url = "https://www.niftytrader.in/getDataForPCRChart"
    params = {"symbol": nse_symbol, "expType": "current"}

    logger.info("Downloading PCR data for %s from niftytrader.in…", symbol)
    try:
        resp = requests.get(url, params=params, headers=NIFTYTRADER_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("PCR download (primary endpoint) failed: %s", exc)
        logger.info("Attempting fallback — scraping PCR page…")
        data = _scrape_pcr_fallback(symbol)

    today = datetime.today()
    out_path = DOWNLOAD_DIR / f"pcr_{symbol}_{today.strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved PCR data → %s", out_path)
    return out_path


def _scrape_pcr_fallback(symbol: str) -> dict:
    """
    Fallback: derive PCR from the NSE option chain data already saved,
    or return a stub if neither source is available.
    """
    # Look for today's option chain file we just downloaded
    today_str = datetime.today().strftime("%Y%m%d")
    oc_file = DOWNLOAD_DIR / f"option_chain_{symbol}_{today_str}.json"

    if oc_file.exists():
        logger.info("Deriving PCR from option chain file: %s", oc_file)
        raw = json.loads(oc_file.read_text(encoding="utf-8"))
        records = raw.get("records", {}).get("data", [])
        total_call_oi = sum(
            r.get("CE", {}).get("openInterest", 0) for r in records if r.get("CE")
        )
        total_put_oi = sum(
            r.get("PE", {}).get("openInterest", 0) for r in records if r.get("PE")
        )
        pcr = round(total_put_oi / total_call_oi, 4) if total_call_oi else 0
        return {
            "symbol": symbol,
            "timestamp": datetime.today().isoformat(),
            "source": "derived_from_option_chain",
            "put_oi": total_put_oi,
            "call_oi": total_call_oi,
            "pcr": pcr,
        }

    logger.warning("No option chain file found to derive PCR. Returning stub.")
    return {"symbol": symbol, "timestamp": datetime.today().isoformat(), "pcr": None, "error": "unavailable"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("NSE Data Download — %s", datetime.today().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Download directory: %s", DOWNLOAD_DIR.resolve())
    logger.info("=" * 60)

    results = {}

    # --- Historical index data (requires NSE session) ---
    try:
        session = create_nse_session()
        path = download_historical_index(session)
        results["historical_index"] = str(path)
    except Exception as exc:
        logger.error("Historical index download FAILED: %s", exc)
        results["historical_index"] = f"FAILED: {exc}"

    # --- Option chain (reuse session) ---
    try:
        path = download_option_chain(session)
        results["option_chain"] = str(path)
    except Exception as exc:
        logger.error("Option chain download FAILED: %s", exc)
        results["option_chain"] = f"FAILED: {exc}"

    # --- PCR ---
    try:
        path = download_pcr()
        results["pcr"] = str(path)
    except Exception as exc:
        logger.error("PCR download FAILED: %s", exc)
        results["pcr"] = f"FAILED: {exc}"

    # --- Summary ---
    logger.info("-" * 60)
    logger.info("Download summary:")
    for key, val in results.items():
        status = "OK" if not str(val).startswith("FAILED") else "FAILED"
        logger.info("  %-25s %s  →  %s", key, status, val)
    logger.info("=" * 60)

    # Exit with error code if any download failed
    if any(str(v).startswith("FAILED") for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
