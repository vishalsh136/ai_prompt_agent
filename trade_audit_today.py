#!/usr/bin/env python
"""Audit current open auto positions against latest option-chain snapshot."""
import json
from pathlib import Path


DOWNLOADS = Path("downloads")
STATE = Path("data/live_algo_positions.json")


def _latest(pattern: str) -> Path | None:
    files = sorted(DOWNLOADS.glob(pattern))
    return files[-1] if files else None


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


oc_path = _latest("option_chain_NIFTY_*.json")
if not oc_path:
    print("No option_chain_NIFTY_*.json file found")
    raise SystemExit(1)

oc_raw = _load_json(oc_path)
spot = float(oc_raw.get("spot_price", 0) or 0)
vix = float(oc_raw.get("vix", 0) or 0)
ts = oc_raw.get("timestamp", "-")

print("=" * 72)
print(f"LIVE TRADE AUDIT — {oc_path.name}")
print("=" * 72)
print(f"Snapshot: {ts} | Spot: {spot:.2f} | VIX: {vix:.2f}")

if not STATE.exists():
    print("\nNo live position state file found.")
    raise SystemExit(0)

positions = _load_json(STATE)
open_positions = [(pid, p) for pid, p in positions.items() if str(p.get("status", "")).lower() == "open"]

if not open_positions:
    print("\nNo open positions.")
    raise SystemExit(0)


def _ltp(strike: int, option_type: str) -> float | None:
    for s in oc_raw.get("strikes", []):
        if int(float(s.get("strike", 0) or 0)) != int(strike):
            continue
        leg = (s.get("CE") or {}) if option_type == "CE" else (s.get("PE") or {})
        val = leg.get("ltp")
        if val is None:
            return None
        return float(val)
    return None


for pid, pos in open_positions:
    strategy = str(pos.get("strategy", ""))
    entry_value = float(pos.get("entry_value", 0) or 0)
    units = int(pos.get("units_per_leg", 0) or 0)
    legs = pos.get("legs") or []

    short_sum = 0.0
    long_sum = 0.0
    missing = []
    for leg in legs:
        strike = int(leg.get("strike", 0) or 0)
        opt_type = str(leg.get("option_type", "")).upper()
        action = str(leg.get("action", "")).upper()
        ltp = _ltp(strike, opt_type)
        if ltp is None:
            missing.append(f"{strike}{opt_type}")
            continue
        if action == "SELL":
            short_sum += ltp
        else:
            long_sum += ltp

    print("\n" + "-" * 72)
    print(f"Position: {pid}")
    print(f"Strategy: {strategy} | Entry value: {entry_value:.2f} | Units/leg: {units}")
    print(f"Entry time: {pos.get('entry_time', '-')}")

    if missing:
        print(f"Valuation unavailable for legs: {', '.join(missing)}")
        continue

    current_value = round(short_sum - long_sum, 2)
    pnl = round((entry_value - current_value) * units, 2)
    print(f"Current value: {current_value:.2f}")
    print(f"MTM PnL: {pnl:+.2f}")

print("\nAudit complete.")
