"""
src/groww_instruments.py
========================
Groww instruments-master resolver.

Resolves an exact Groww `trading_symbol` for an F&O option leg from the official
instruments CSV:
    https://growwapi-assets.groww.in/instruments/instrument.csv

Behaviour:
- Uses a locally cached CSV at data/groww_instruments.csv.
- Only downloads over the network when explicitly requested (refresh=True) or
  when no cache exists AND allow_download=True. No network on import.
- Resolution is a pure local lookup once the CSV is present.

Relevant columns (comma-separated):
  exchange, exchange_token, trading_symbol, groww_symbol, name, instrument_type,
  segment, series, isin, underlying_symbol, underlying_exchange_token,
  expiry_date, strike_price, lot_size, tick_size, freeze_quantity,
  is_reserved, buy_allowed, sell_allowed
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
import csv

INSTRUMENTS_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"
DEFAULT_CACHE_PATH = "data/groww_instruments.csv"


def download_instruments(cache_path: str = DEFAULT_CACHE_PATH, timeout_sec: int = 30) -> Dict:
    """Download the instruments CSV to the local cache. Requires `requests`."""
    try:
        import requests
    except Exception:
        return {"ok": False, "message": "'requests' library not installed; cannot download instruments."}
    try:
        resp = requests.get(INSTRUMENTS_URL, timeout=timeout_sec)
        if not resp.ok:
            return {"ok": False, "message": f"Download failed: HTTP {resp.status_code}"}
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return {"ok": True, "message": f"Instruments cached to {cache_path}", "bytes": len(resp.content)}
    except Exception as exc:
        return {"ok": False, "message": f"Download error: {exc}"}


def _normalize_expiry(expiry: str) -> str:
    """Return YYYY-MM-DD form of an expiry string if possible."""
    expiry = (expiry or "").strip()
    if not expiry:
        return ""
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d%b%y", "%d%b%Y"):
        try:
            return datetime.strptime(expiry, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return expiry


def resolve_trading_symbol(
    underlying: str,
    expiry: str,
    strike: int,
    option_type: str,
    cache_path: str = DEFAULT_CACHE_PATH,
    allow_download: bool = False,
) -> Dict:
    """Resolve exact Groww trading_symbol for an option leg.

    Returns {ok, trading_symbol, lot_size, exchange, groww_symbol} or {ok:False, message}.
    """
    path = Path(cache_path)
    if not path.exists():
        if allow_download:
            dl = download_instruments(cache_path)
            if not dl.get("ok"):
                return {"ok": False, "message": dl.get("message", "Instruments not available.")}
        else:
            return {"ok": False, "message": f"Instruments cache missing at {cache_path}. Refresh first."}

    target_expiry = _normalize_expiry(expiry)
    underlying = (underlying or "").strip().upper()
    option_type = (option_type or "").strip().upper()
    try:
        strike_i = int(float(strike))
    except Exception:
        return {"ok": False, "message": f"Invalid strike: {strike}"}

    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("underlying_symbol", "").strip().upper() != underlying):
                    continue
                if (row.get("instrument_type", "").strip().upper() != option_type):
                    continue
                if (row.get("segment", "").strip().upper() != "FNO"):
                    continue
                if _normalize_expiry(row.get("expiry_date", "")) != target_expiry:
                    continue
                try:
                    if int(float(row.get("strike_price", "0") or 0)) != strike_i:
                        continue
                except Exception:
                    continue
                return {
                    "ok": True,
                    "trading_symbol": row.get("trading_symbol", "").strip(),
                    "groww_symbol": row.get("groww_symbol", "").strip(),
                    "exchange": row.get("exchange", "NSE").strip(),
                    "lot_size": int(float(row.get("lot_size", "0") or 0)),
                }
    except Exception as exc:
        return {"ok": False, "message": f"Instruments read error: {exc}"}

    return {
        "ok": False,
        "message": f"No match for {underlying} {target_expiry} {strike_i} {option_type}.",
    }
