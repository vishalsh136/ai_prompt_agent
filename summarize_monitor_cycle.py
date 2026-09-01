#!/usr/bin/env python
"""Classify latest monitor cycle as Improving / Neutral / Deteriorating."""
from __future__ import annotations

import re
from pathlib import Path

LOG_PATH = Path("logs/strategy_drift_monitor.out.log")


def _latest_delta_block(lines: list[str]) -> list[str]:
    marker_idx = [
        i for i, ln in enumerate(lines)
        if ("[MONITOR]" in ln and "delta update" in ln) or ("delta update" in ln and ln.strip().startswith("["))
    ]
    if not marker_idx:
        return []
    start = marker_idx[-1]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if ("[MONITOR]" in lines[i] and "delta update" in lines[i]) or ("delta update" in lines[i] and lines[i].strip().startswith("[")):
            end = i
            break
    return lines[start:end]


def classify(block: list[str]) -> tuple[str, dict]:
    stats = {
        "pnl_worse": 0,
        "pnl_better": 0,
        "drift_worse": 0,
        "drift_better": 0,
        "seller_credit_worse": 0,
        "seller_credit_better": 0,
    }

    pnl_re = re.compile(r"pnl_latest:\s*([-+]?\d+(?:\.\d+)?)\s*->\s*([-+]?\d+(?:\.\d+)?)")
    drift_re = re.compile(r"drift_window:\s*([-+]?\d+(?:\.\d+)?)\s*->\s*([-+]?\d+(?:\.\d+)?)")
    credit_re = re.compile(r"THIN_CREDIT\(credit=([-+]?\d+(?:\.\d+)?)<")

    prev_credit = None

    for ln in block:
        m = pnl_re.search(ln)
        if m:
            old = float(m.group(1))
            new = float(m.group(2))
            if new > old:
                stats["pnl_better"] += 1
            elif new < old:
                stats["pnl_worse"] += 1

        m = drift_re.search(ln)
        if m:
            old = float(m.group(1))
            new = float(m.group(2))
            if new > old:
                stats["drift_better"] += 1
            elif new < old:
                stats["drift_worse"] += 1

        if "OptionSeller" in ln or "Agent-OptionSeller" in ln or "Hedging" in ln:
            m = credit_re.search(ln)
            if m:
                val = float(m.group(1))
                if prev_credit is not None:
                    if val > prev_credit:
                        stats["seller_credit_better"] += 1
                    elif val < prev_credit:
                        stats["seller_credit_worse"] += 1
                prev_credit = val

    score = (
        stats["pnl_better"]
        + stats["drift_better"]
        + stats["seller_credit_better"]
        - stats["pnl_worse"]
        - stats["drift_worse"]
        - stats["seller_credit_worse"]
    )

    if score >= 2:
        label = "Improving"
    elif score <= -2:
        label = "Deteriorating"
    else:
        label = "Neutral"

    return label, stats


def main() -> int:
    if not LOG_PATH.exists():
        print("No monitor log found.")
        return 1

    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    block = _latest_delta_block(lines)
    if not block:
        print("No delta block found yet.")
        return 0

    label, stats = classify(block)

    print(block[0])
    print(f"Cycle Classification: {label}")
    print(
        "Signals | "
        f"pnl_better={stats['pnl_better']} pnl_worse={stats['pnl_worse']} | "
        f"drift_better={stats['drift_better']} drift_worse={stats['drift_worse']} | "
        f"credit_better={stats['seller_credit_better']} credit_worse={stats['seller_credit_worse']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
