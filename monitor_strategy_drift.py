#!/usr/bin/env python
"""Automated strategy drift monitor with delta-only reporting."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List, Tuple

import sys
sys.path.insert(0, "src")

from strategy_selector import DEFAULT_STRATEGIES, recommend  # noqa: E402

JOURNAL_PATH = Path("data/live_algo_journal.jsonl")
STATE_PATH = Path("data/monitor_strategy_drift_state.json")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _load_mtm_today(today_iso: str) -> List[dict]:
    if not JOURNAL_PATH.exists():
        return []

    rows: List[dict] = []
    for ln in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if rec.get("event") != "auto_mark_to_market":
            continue
        if str(rec.get("ts_utc", "")).startswith(today_iso):
            rows.append(rec)
    return rows


def _position_metrics(rows: List[dict], window: int) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    pids = sorted({str(r.get("position_id", "")).strip() for r in rows if str(r.get("position_id", "")).strip()})

    for pid in pids:
        s = [r for r in rows if str(r.get("position_id", "")).strip() == pid]
        s = s[-window:]
        if not s:
            continue
        pnls = [float(r.get("pnl_inr", 0) or 0) for r in s]
        vals = [float(r.get("current_value", 0) or 0) for r in s]
        moves = [float(r.get("day_move_pct", 0) or 0) for r in s]
        drift = pnls[-1] - pnls[0] if len(pnls) >= 2 else 0.0

        out[pid] = {
            "events": len(s),
            "pnl_latest": round(pnls[-1], 2),
            "pnl_min": round(min(pnls), 2),
            "pnl_max": round(max(pnls), 2),
            "pnl_avg": round(mean(pnls), 2),
            "current_value_latest": round(vals[-1], 2),
            "day_move_latest": round(moves[-1], 3),
            "drift_window": round(drift, 2),
        }
    return out


def _active_skip_map(rec: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for idea in rec.get("ideas", []) or []:
        st = str(idea.get("strategy", "")).strip()
        if not st:
            continue
        skip = idea.get("skip_reason")
        out[st] = "ACTIVE" if not skip else f"SKIP:{skip}"
    return out


def _diff(prev: dict, curr: dict) -> Tuple[bool, List[str]]:
    changed = False
    lines: List[str] = []

    prev_rec = prev.get("recommended")
    curr_rec = curr.get("recommended")
    if prev_rec != curr_rec:
        changed = True
        lines.append(f"recommended changed: {prev_rec} -> {curr_rec}")

    prev_skip = prev.get("strategy_state", {})
    curr_skip = curr.get("strategy_state", {})
    for k in sorted(set(prev_skip) | set(curr_skip)):
        if prev_skip.get(k) != curr_skip.get(k):
            changed = True
            lines.append(f"{k}: {prev_skip.get(k)} -> {curr_skip.get(k)}")

    prev_pos = prev.get("positions", {})
    curr_pos = curr.get("positions", {})
    for pid in sorted(set(prev_pos) | set(curr_pos)):
        if pid not in prev_pos:
            changed = True
            lines.append(f"position added: {pid}")
            continue
        if pid not in curr_pos:
            changed = True
            lines.append(f"position removed: {pid}")
            continue

        p = prev_pos[pid]
        c = curr_pos[pid]
        for key in ("pnl_latest", "drift_window", "current_value_latest", "day_move_latest"):
            if p.get(key) != c.get(key):
                changed = True
                lines.append(f"{pid} {key}: {p.get(key)} -> {c.get(key)}")

    return changed, lines


def _snapshot(window: int) -> dict:
    now = datetime.now()
    today_iso = now.strftime("%Y-%m-%d")
    rows = _load_mtm_today(today_iso)
    pos_metrics = _position_metrics(rows, window)
    rec = recommend(DEFAULT_STRATEGIES)

    snap = {
        "ts": now.isoformat(timespec="seconds"),
        "date": today_iso,
        "mtm_events_today": len(rows),
        "recommended": rec.get("recommended"),
        "recommended_message": rec.get("message"),
        "strategy_state": _active_skip_map(rec),
        "positions": pos_metrics,
    }
    return snap


def _classify_cycle(deltas: List[str]) -> Tuple[str, Dict[str, int]]:
    stats = {
        "pnl_better": 0,
        "pnl_worse": 0,
        "drift_better": 0,
        "drift_worse": 0,
        "credit_better": 0,
        "credit_worse": 0,
    }

    for line in deltas:
        if "pnl_latest:" in line:
            try:
                old, new = line.split("pnl_latest:", 1)[1].split("->", 1)
                old_v = float(old.strip())
                new_v = float(new.strip())
                if new_v > old_v:
                    stats["pnl_better"] += 1
                elif new_v < old_v:
                    stats["pnl_worse"] += 1
            except Exception:
                pass

        if "drift_window:" in line:
            try:
                old, new = line.split("drift_window:", 1)[1].split("->", 1)
                old_v = float(old.strip())
                new_v = float(new.strip())
                if new_v > old_v:
                    stats["drift_better"] += 1
                elif new_v < old_v:
                    stats["drift_worse"] += 1
            except Exception:
                pass

        if "THIN_CREDIT(credit=" in line and "->" in line:
            try:
                left, right = line.split("->", 1)
                old_s = left.split("THIN_CREDIT(credit=", 1)[1].split("<", 1)[0]
                new_s = right.split("THIN_CREDIT(credit=", 1)[1].split("<", 1)[0]
                old_v = float(old_s.strip())
                new_v = float(new_s.strip())
                if new_v > old_v:
                    stats["credit_better"] += 1
                elif new_v < old_v:
                    stats["credit_worse"] += 1
            except Exception:
                pass

    score = (
        stats["pnl_better"]
        + stats["drift_better"]
        + stats["credit_better"]
        - stats["pnl_worse"]
        - stats["drift_worse"]
        - stats["credit_worse"]
    )

    if score >= 2:
        label = "Improving"
    elif score <= -2:
        label = "Deteriorating"
    else:
        label = "Neutral"

    return label, stats


def print_initial(curr: dict) -> None:
    print(f"[MONITOR][{curr['ts']}] initial snapshot", flush=True)
    print(f"mtm_events_today: {curr['mtm_events_today']}", flush=True)
    print(f"recommended: {curr.get('recommended')} | {curr.get('recommended_message')}", flush=True)
    print("cycle_classification: Baseline", flush=True)
    for k, v in sorted((curr.get("strategy_state") or {}).items()):
        print(f"strategy {k}: {v}", flush=True)
    for pid, m in sorted((curr.get("positions") or {}).items()):
        print(f"position {pid}: pnl={m['pnl_latest']} drift={m['drift_window']} value={m['current_value_latest']} day_move={m['day_move_latest']}", flush=True)


def print_delta(curr: dict, deltas: List[str]) -> None:
    print(f"[MONITOR][{curr['ts']}] delta update", flush=True)
    label, stats = _classify_cycle(deltas)
    print(
        "cycle_classification: "
        f"{label} | pnl_better={stats['pnl_better']} pnl_worse={stats['pnl_worse']} "
        f"drift_better={stats['drift_better']} drift_worse={stats['drift_worse']} "
        f"credit_better={stats['credit_better']} credit_worse={stats['credit_worse']}",
        flush=True,
    )
    if not deltas:
        print("no material changes", flush=True)
        return
    for line in deltas:
        print(f"- {line}", flush=True)


def run_once(window: int) -> int:
    prev = _load_json(STATE_PATH, {})
    curr = _snapshot(window)

    if not prev:
        print_initial(curr)
        _save_json(STATE_PATH, curr)
        return 0

    changed, deltas = _diff(prev, curr)
    if changed:
        print_delta(curr, deltas)
    else:
        print_delta(curr, [])
    _save_json(STATE_PATH, curr)
    return 0


def run_loop(interval_sec: int, window: int) -> int:
    while True:
        try:
            run_once(window)
        except Exception as exc:
            now = datetime.now().isoformat(timespec="seconds")
            print(f"[MONITOR][{now}] monitor error: {exc}", flush=True)
        time.sleep(max(10, int(interval_sec)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated strategy drift monitor (delta-only).")
    ap.add_argument("--once", action="store_true", help="Run one snapshot cycle and exit.")
    ap.add_argument("--loop", action="store_true", help="Run continuously.")
    ap.add_argument("--interval", type=int, default=300, help="Loop interval seconds (default: 300).")
    ap.add_argument("--window", type=int, default=30, help="MTM points per-position for drift stats (default: 30).")
    args = ap.parse_args()

    if args.loop:
        return run_loop(args.interval, args.window)
    return run_once(args.window)


if __name__ == "__main__":
    raise SystemExit(main())
