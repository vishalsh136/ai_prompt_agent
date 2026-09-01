#!/usr/bin/env python
"""Print the most recent delta block from strategy drift monitor logs."""
from __future__ import annotations

from pathlib import Path

OUT_LOG = Path("logs/strategy_drift_monitor.out.log")


def main() -> int:
    if not OUT_LOG.exists():
        print("Monitor log not found:", OUT_LOG)
        return 1

    lines = OUT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        print("Monitor log is empty.")
        return 0

    # Locate the latest delta/initial marker and print that block.
    markers = [
        i for i, ln in enumerate(lines)
        if ("[MONITOR]" in ln and ("delta update" in ln or "initial snapshot" in ln))
    ]

    # Backward compatibility for older monitor output.
    if not markers:
        markers = [
            i for i, ln in enumerate(lines)
            if ("delta update" in ln or "initial snapshot" in ln)
        ]

    if not markers:
        # Fallback: show last 20 lines if no marker is present yet.
        for ln in lines[-20:]:
            print(ln)
        return 0

    start = markers[-1]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if "delta update" in lines[i] or "initial snapshot" in lines[i]:
            end = i
            break

    for ln in lines[start:end]:
        print(ln)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
