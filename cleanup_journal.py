#!/usr/bin/env python
"""Clean up duplicate journal entries and stale positions from the bug"""
import json
from pathlib import Path
from datetime import datetime

TODAY = "2026-08-03"
JOURNAL = Path("data/live_algo_journal.jsonl")
POSITIONS = Path("data/live_algo_positions.json")

# ── 1. Clean journal: keep only the LAST auto_entry per position_id ─────────
if JOURNAL.exists():
    lines = JOURNAL.read_text(encoding="utf-8").splitlines()
    entries = []
    for l in lines:
        try: entries.append((l, json.loads(l)))
        except: pass

    # Track last-seen auto_entry per position_id
    seen_entry = {}
    clean = []
    for raw, rec in entries:
        pid  = rec.get("position_id", "")
        evt  = rec.get("event", "")
        ts   = rec.get("ts_utc", "")[:10]

        if evt == "auto_entry_failed" and ts == TODAY:
            print(f"  Removing failed entry: {rec.get('ts_utc','')[:16]} reason={rec.get('reason','')}")
            continue  # drop all failed entries from today

        if evt == "auto_entry" and ts == TODAY and pid:
            # Keep only the latest; skip earlier duplicates
            seen_entry[pid] = (raw, rec)
            continue

        clean.append(raw)

    # Add back only the most recent auto_entry per pid
    for pid, (raw, rec) in seen_entry.items():
        clean.append(raw)
        print(f"  Keeping latest auto_entry for {pid}: {rec.get('ts_utc','')[:16]}")

    JOURNAL.write_text("\n".join(clean) + ("\n" if clean else ""), encoding="utf-8")
    print(f"\nJournal cleaned: {len(lines)} lines → {len(clean)} lines")

# ── 2. Show current positions (no cleanup needed — last entry is valid) ──────
if POSITIONS.exists():
    pos = json.loads(POSITIONS.read_text(encoding="utf-8"))
    print(f"\nCurrent positions ({len(pos)}):")
    for pid, p in pos.items():
        print(f"  {pid}: status={p.get('status')} entry_value={p.get('entry_value')} entry_time={str(p.get('entry_time',''))[:16]}")
