"""
src/realtime_data.py
====================
Reusable real-time NIFTY option-chain fetcher.

Extracted from the Auto Trade Log tab so the background auto-trader can pull
fresh market data on every tick (instead of relying on the scheduled cron).

Scrapes the public, no-auth option chain from niftytrader.in, writes the same
JSON files the cron produces (downloads/option_chain_*.json, pcr_*.json), then
runs the existing CSV converter so downstream loaders (load_morning_data) see
fresh prices.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("realtime_data")

ROOT = Path(__file__).parent.parent
DOWNLOADS = ROOT / "downloads"

_NIFTYTRADER_URL = "https://www.niftytrader.in/nse-option-chain/nifty"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.google.com",
}


def fetch_option_chain(symbol: str = "NIFTY", timeout_sec: int = 12) -> Optional[Dict]:
    """Scrape a live option-chain snapshot. Returns the parsed dict or None."""
    try:
        import requests  # local import so the module loads without requests
    except Exception:
        logger.warning("requests not installed; cannot fetch real-time data.")
        return None

    try:
        resp = requests.get(_NIFTYTRADER_URL, headers=_HEADERS, timeout=timeout_sec)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Real-time fetch failed: %s", exc)
        return None

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', resp.text)
    if not match:
        logger.warning("Could not locate __NEXT_DATA__ payload.")
        return None

    try:
        nd = json.loads(match.group(1))
    except Exception as exc:
        logger.warning("Failed to parse embedded JSON: %s", exc)
        return None

    pp = nd.get("props", {}).get("pageProps", {})
    spot = pp.get("initialSpot", {})
    if not spot:
        return None

    out = {
        "symbol": symbol,
        "timestamp": spot.get("timestamp", ""),
        "cron_run_time": datetime.now(timezone.utc).isoformat(),
        "cron_run_label": datetime.now().strftime("%H:%M"),
        "source": "niftytrader.in (live, no-auth)",
        "source_url": _NIFTYTRADER_URL,
        "spot_price": float(spot.get("last_trade_price", 0) or 0),
        "open": float(spot.get("open", 0) or 0),
        "high": float(spot.get("high", 0) or 0),
        "low": float(spot.get("low", 0) or 0),
        "vix": float(spot.get("vix_value", 0) or 0),
        "vix_change": float(spot.get("vix_change", 0) or 0),
        "max_pain": float(spot.get("max_pain", 0) or 0),
        "lot_size": int(spot.get("lot_size", 25) or 25),
        "expected_range": pp.get("ExpectedRange", ""),
        "pcr": float(pp.get("pcrVal", 0) or 0),
        "pcr_change": float(pp.get("chngPcrValue", 0) or 0) if pp.get("chngPcrValue") else None,
        "strikes": [],
    }

    for row in sorted(pp.get("initialOptionChainData", []), key=lambda x: float(x.get("strike_price", 0) or 0)):
        out["strikes"].append({
            "strike": float(row.get("strike_price", 0) or 0),
            "expiry": row.get("expiry_date", ""),
            "pcr": float(row.get("pcr", 0)) if row.get("pcr") else None,
            "CE": {
                "oi": int(row.get("calls_oi", 0) or 0),
                "chg_oi": int(row.get("calls_change_oi", 0) or 0),
                "ltp": float(row.get("calls_ltp", 0) or 0),
                "iv": float(row.get("calls_iv", 0) or 0),
                "volume": int(row.get("calls_volume", 0) or 0),
                "buildup": row.get("calls_builtup", ""),
            },
            "PE": {
                "oi": int(row.get("puts_oi", 0) or 0),
                "chg_oi": int(row.get("puts_change_oi", 0) or 0),
                "ltp": float(row.get("puts_ltp", 0) or 0),
                "iv": float(row.get("puts_iv", 0) or 0),
                "volume": int(row.get("puts_volume", 0) or 0),
                "buildup": row.get("puts_builtup", ""),
            },
        })
    return out


def refresh_realtime(symbol: str = "NIFTY", update_pnl: bool = True,
                     return_snapshot: bool = False) -> Dict:
    """Fetch a live snapshot, persist cron-compatible files, refresh CSVs.

    Returns a small status dict:
        {ok, spot, open, high, low, vix, pcr, day_move_pct, message}

    If ``return_snapshot`` is True, the raw parsed snapshot dict is included under
    the ``snapshot`` key so callers can value positions in-memory without the
    shared-CSV round-trip. Shared-file writing is unchanged.
    """
    snap = fetch_option_chain(symbol)
    if not snap:
        return {"ok": False, "message": "Real-time fetch failed or unavailable."}

    date_stamp = datetime.now().strftime("%Y%m%d")
    DOWNLOADS.mkdir(exist_ok=True)
    (DOWNLOADS / f"option_chain_{symbol}_{date_stamp}.json").write_text(
        json.dumps(snap, indent=2), encoding="utf-8")
    (DOWNLOADS / f"pcr_{symbol}_{date_stamp}.json").write_text(
        json.dumps({"pcr_overall": snap["pcr"], "timestamp": snap["timestamp"]}, indent=2),
        encoding="utf-8")

    # Convert to the app CSVs consumed by load_morning_data / update_open_trades.
    try:
        import importlib
        import convert_cron_to_app
        importlib.reload(convert_cron_to_app)
        convert_cron_to_app.main()
    except Exception as exc:
        logger.warning("CSV conversion failed: %s", exc)

    day_open = float(snap.get("open", 0) or 0)
    spot = float(snap.get("spot_price", 0) or 0)
    day_move_pct = round(((spot - day_open) / day_open) * 100, 3) if day_open > 0 else 0.0

    out = {
        "ok": True,
        "spot": spot,
        "open": day_open,
        "high": float(snap.get("high", 0) or 0),
        "low": float(snap.get("low", 0) or 0),
        "vix": float(snap.get("vix", 0) or 0),
        "pcr": float(snap.get("pcr", 0) or 0),
        "day_move_pct": day_move_pct,
        "timestamp": snap.get("timestamp", ""),
        "message": "Real-time snapshot refreshed.",
    }
    if return_snapshot:
        out["snapshot"] = snap
    return out


def snapshot_ltp(snap: Dict, strike: int, opt_type: str) -> Optional[float]:
    """Return the CE/PE LTP for a strike from an in-memory snapshot, or None."""
    if not snap:
        return None
    opt = str(opt_type).upper()
    if opt not in ("CE", "PE"):
        return None
    target = int(strike)
    for row in snap.get("strikes", []):
        try:
            if int(round(float(row.get("strike", 0) or 0))) == target:
                ltp = float(row.get(opt, {}).get("ltp", 0) or 0)
                return ltp if ltp > 0 else None
        except Exception:
            continue
    return None


def value_legs_from_snapshot(snap: Dict, legs) -> Optional[float]:
    """Net cost-to-close from an in-memory snapshot = sum(short LTP) - sum(long LTP).

    Mirrors live_auto_runner._position_value but sources LTPs directly from the
    fresh snapshot (no shared-CSV round-trip). Returns None if any leg LTP is
    unavailable.
    """
    if not snap or not legs:
        return None
    short_sum = 0.0
    long_sum = 0.0
    for leg in legs:
        ltp = snapshot_ltp(snap, int(leg.get("strike", 0) or 0),
                           str(leg.get("option_type", "")))
        if ltp is None or ltp <= 0:
            return None
        if str(leg.get("action", "")).upper() == "SELL":
            short_sum += ltp
        else:
            long_sum += ltp
    return round(short_sum - long_sum, 2)

