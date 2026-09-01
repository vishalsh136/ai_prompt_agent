"""
doc_agent.py — Automatic Documentation Update Agent
=====================================================
Monitors the application source files for changes and updates
APP_FUNCTIONALITY_REFERENCE.md whenever code is modified.

Usage:
  python doc_agent.py            # update only changed sections
  python doc_agent.py --force    # rebuild all sections
  python doc_agent.py --status   # show which files changed, do not write

Trigger options:
  1. Manual       : run the command above
  2. VS Code task : add to .vscode/tasks.json (see bottom of this file)
  3. Git hook     : copy .git/hooks/post-commit template (see bottom)

Files managed:
  doc_agent_state.json     — SHA-256 hashes of watched files (auto-created)
  doc_agent_changelog.md   — append-only log of every update run

Section map (file -> section heading in APP_FUNCTIONALITY_REFERENCE.md):
  app.py                     ->  §8 UI Tabs, §13 Data Schema
  src/institutional_view.py  ->  §4.1 InstitutionalAnalyzer
  src/options_view.py        ->  §4.2 OptionsAnalyzer, §5 Strategies
  src/strategy_builder.py    ->  §4.3 StrategyBuilder
  src/backtesting.py         ->  §4.4 BacktestEngine
  src/auto_trade_engine.py   ->  §9 Auto Trade Engine
  src/trade_tracker.py       ->  §10 Trade Journal
  src/final_trade_decision.py->  §5.4 Institutional Strategies
  src/option_buyer_strategies.py -> §5.1-5.2 Buyer/Hedging
  src/real_data_loader.py    ->  §7 Data Formats
  config.yaml                ->  §3 Configuration
  download_nse_data.ps1      ->  §2 Data Pipeline, §11 Cron
  convert_cron_to_app.py     ->  §2 Data Pipeline
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).parent
DOC_FILE   = ROOT / "APP_FUNCTIONALITY_REFERENCE.md"
STATE_FILE = ROOT / "doc_agent_state.json"
CHANGELOG  = ROOT / "doc_agent_changelog.md"

# ---------------------------------------------------------------------------
# Watched files and their section targets
# ---------------------------------------------------------------------------
WATCHED: Dict[str, List[str]] = {
    "app.py":                           ["## 8. UI Tabs — Feature Specification"],
    "src/institutional_view.py":        ["### 4.1 InstitutionalAnalyzer (`src/institutional_view.py`)"],
    "src/options_view.py":              ["### 4.2 OptionsAnalyzer (`src/options_view.py`)"],
    "src/strategy_builder.py":          ["### 4.3 StrategyBuilder (`src/strategy_builder.py`)"],
    "src/backtesting.py":               ["### 4.4 BacktestEngine (`src/backtesting.py`)"],
    "src/auto_trade_engine.py":         ["## 9. Auto Trade Engine — Logic Flow"],
    "src/trade_tracker.py":             ["## 10. Trade Journal & P&L Tracking"],
    "src/final_trade_decision.py":      ["### 5.4 Institutional / Futures Strategies"],
    "src/option_buyer_strategies.py":   ["### 5.1 Option Buyer Strategies"],
    "src/real_data_loader.py":          ["## 7. Data Sources & Formats"],
    "config.yaml":                      ["## 3. Configuration (config.yaml)"],
    "download_nse_data.ps1":            ["## 2. Data Pipeline"],
    "convert_cron_to_app.py":           ["## 2. Data Pipeline"],
    "src/utils.py":                     ["## 6. Mathematical Models"],
}


# ===========================================================================
# 1. File hash tracking
# ===========================================================================

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
    except Exception:
        return ""
    return h.hexdigest()[:16]  # 16 chars is enough for change detection


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"hashes": {}, "last_run": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def detect_changes(state: dict, force: bool = False) -> List[str]:
    """Return list of watched files that changed since last run."""
    changed = []
    for rel in WATCHED:
        path = ROOT / rel
        if not path.exists():
            continue
        current = _sha256(path)
        previous = state["hashes"].get(rel, "")
        if force or current != previous:
            changed.append(rel)
    return changed


# ===========================================================================
# 2. Parsers — extract structured info from each file type
# ===========================================================================

def _first_line(s: str) -> str:
    """Return first non-empty line of a string."""
    for line in (s or "").strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def parse_python_file(path: Path) -> dict:
    """
    Extract from a Python source file:
      - module docstring
      - public classes with their methods + docstrings
      - public standalone functions
      - module-level constants (UPPER_CASE)
      - notable dict literals (STRATEGY_CATALOGUE etc.)
    """
    src = path.read_text(encoding="utf-8-sig", errors="ignore")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"error": "SyntaxError", "path": str(path)}

    info: dict = {
        "module_doc": ast.get_docstring(tree) or "",
        "classes": [],
        "functions": [],
        "constants": [],
        "strategy_dicts": [],
    }

    for node in ast.walk(tree):
        # Module-level constants
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        val = ast.literal_eval(node.value)
                        val_repr = repr(val)[:80]
                    except Exception:
                        val_repr = ast.dump(node.value)[:80]
                    info["constants"].append({"name": target.id, "value": val_repr})

        # Strategy catalogue dicts
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and "CATALOGUE" in target.id.upper():
                    if isinstance(node.value, ast.Dict):
                        keys = []
                        for k in node.value.keys:
                            try:
                                keys.append(ast.literal_eval(k))
                            except Exception:
                                pass
                        info["strategy_dicts"].append({"name": target.id, "keys": keys})

    # Classes
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name.startswith("_"):
            continue
        class_doc = ast.get_docstring(node) or ""
        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                args = [a.arg for a in item.args.args if a.arg != "self"]
                doc = _first_line(ast.get_docstring(item) or "")
                methods.append({"name": item.name, "args": args, "doc": doc})
        info["classes"].append({
            "name": node.name,
            "doc": _first_line(class_doc),
            "methods": methods,
        })

    # Standalone public functions (not inside a class)
    class_nodes = {id(n) for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            args = [a.arg for a in node.args.args]
            doc = _first_line(ast.get_docstring(node) or "")
            info["functions"].append({"name": node.name, "args": args, "doc": doc})

    return info


def parse_config_yaml(path: Path) -> dict:
    """Extract key configuration sections from config.yaml."""
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}

    info: dict = {}

    # Symbols
    syms = data.get("symbols", {})
    info["indices"]  = syms.get("indices", [])
    info["stocks"]   = syms.get("stocks",  [])[:5]  # first 5
    info["default"]  = syms.get("default", "NIFTY")

    # Lot sizes
    info["lot_sizes"] = data.get("data", {}).get("lot_sizes", {})

    # Market params
    mkt = data.get("market", {})
    info["risk_free_rate"] = mkt.get("risk_free_rate", "N/A")
    info["dividend_yield"] = mkt.get("dividend_yield", "N/A")

    # Backtesting
    bt = data.get("backtesting", {})
    info["initial_capital"]  = bt.get("initial_capital", "N/A")
    info["slippage_pct"]     = bt.get("slippage_pct", "N/A")
    info["transaction_cost"] = bt.get("transaction_cost_pct", "N/A")

    return info


def parse_powershell_script(path: Path) -> dict:
    """Extract cron schedule params and API URLs from a PowerShell script."""
    src = path.read_text(encoding="utf-8-sig", errors="ignore")

    info: dict = {
        "urls":     re.findall(r'https?://[^\s\'"]+', src),
        "schedule": {},
        "modes":    [],
    }

    # Cron schedule params
    for param in ["/ST", "/ET", "/RI", "/D"]:
        m = re.search(rf'{param}\s+([\w,:]+)', src, re.IGNORECASE)
        if m:
            info["schedule"][param] = m.group(1)

    # Mode descriptions
    for m in re.finditer(r'#\s*(entry|update|eod|skip)\s*[-–>]+\s*(.+)', src, re.IGNORECASE):
        info["modes"].append(f"{m.group(1)}: {m.group(2).strip()}")

    # Deduplicate URLs and strip trailing punctuation
    seen = set()
    clean_urls = []
    for u in info["urls"]:
        u = u.rstrip("'\".,")
        if u not in seen:
            seen.add(u)
            clean_urls.append(u)
    info["urls"] = clean_urls

    return info


def parse_app_tabs(path: Path) -> dict:
    """Extract tab names and key subheaders from app.py."""
    src = path.read_text(encoding="utf-8-sig", errors="ignore")

    # Tab names from st.tabs([...])
    tabs_match = re.search(r'st\.tabs\(\s*\[([\s\S]+?)\]\s*\)', src)
    tabs = []
    if tabs_match:
        for m in re.finditer(r'["\']([^"\']+)["\']', tabs_match.group(1)):
            tabs.append(m.group(1))

    # Key subheaders
    subheaders = re.findall(r'st\.subheader\(["\']([^"\']+)["\']', src)

    # Key buttons
    buttons = re.findall(r'st\.button\(["\']([^"\']+)["\']', src)

    return {
        "tabs":       tabs,
        "subheaders": list(dict.fromkeys(subheaders))[:20],  # dedupe, first 20
        "buttons":    list(dict.fromkeys(buttons))[:15],
    }


# ===========================================================================
# 3. Section builder — generate markdown for each changed file
# ===========================================================================

def build_section_update(rel_path: str, info: dict) -> str:
    """
    Generate a markdown snippet describing the current state of a file.
    This replaces or appends to the relevant section in the doc.
    """
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"\n> *Auto-updated by doc_agent on {ts}*\n"]

    if rel_path == "config.yaml":
        out.append("### Current Configuration Values\n")
        out.append(f"- **Default symbol**: `{info.get('default')}`")
        out.append(f"- **Indices**: {', '.join(info.get('indices', []))}")
        out.append(f"- **Stocks (sample)**: {', '.join(info.get('stocks', []))}...")
        out.append(f"- **Risk-free rate**: {info.get('risk_free_rate')}")
        out.append(f"- **Dividend yield**: {info.get('dividend_yield')}")
        out.append(f"- **Initial backtest capital**: ₹{info.get('initial_capital'):,}" if isinstance(info.get("initial_capital"), int) else f"- **Initial backtest capital**: {info.get('initial_capital')}")
        out.append("\n**Lot sizes:**\n")
        for sym, ls in info.get("lot_sizes", {}).items():
            out.append(f"| {sym} | {ls} |")

    elif rel_path == "app.py":
        tabs = info.get("tabs", [])
        out.append("### Current UI Tabs\n")
        for i, t in enumerate(tabs, 1):
            out.append(f"{i}. `{t}`")
        if info.get("buttons"):
            out.append("\n**Key action buttons:**")
            for b in info["buttons"][:10]:
                out.append(f"- `{b}`")

    elif rel_path in ("download_nse_data.ps1", "convert_cron_to_app.py"):
        out.append("### Data Sources (URLs)\n")
        for url in info.get("urls", [])[:8]:
            out.append(f"- `{url}`")
        if info.get("schedule"):
            out.append("\n**Cron schedule parameters:**\n```")
            for k, v in info["schedule"].items():
                out.append(f"  {k} {v}")
            out.append("```")
        if info.get("modes"):
            out.append("\n**Engine modes:**")
            for m in info["modes"]:
                out.append(f"- {m}")

    else:
        # Python source file
        module_doc = _first_line(info.get("module_doc", ""))
        if module_doc:
            out.append(f"*{module_doc}*\n")

        for cls in info.get("classes", []):
            out.append(f"\n#### `{cls['name']}`")
            if cls.get("doc"):
                out.append(f"> {cls['doc']}")
            if cls.get("methods"):
                out.append("\n**Public methods:**\n")
                out.append("| Method | Args | Description |")
                out.append("|---|---|---|")
                for m in cls["methods"]:
                    args = ", ".join(m["args"]) if m["args"] else "—"
                    doc  = m["doc"][:60] + ("…" if len(m["doc"]) > 60 else "") if m["doc"] else "—"
                    out.append(f"| `{m['name']}()` | `{args}` | {doc} |")

        for fn in info.get("functions", []):
            out.append(f"\n**`{fn['name']}({', '.join(fn['args'])})`**")
            if fn.get("doc"):
                out.append(f"  — {fn['doc']}")

        for sd in info.get("strategy_dicts", []):
            out.append(f"\n**`{sd['name']}` keys ({len(sd['keys'])} strategies):**")
            out.append(", ".join(f"`{k}`" for k in sd["keys"]))

        consts = [c for c in info.get("constants", []) if not c["name"].startswith("_")][:8]
        if consts:
            out.append("\n**Key constants:**\n")
            for c in consts:
                out.append(f"- `{c['name']} = {c['value']}`")

    return "\n".join(out)


# ===========================================================================
# 4. Markdown doc updater
# ===========================================================================

def _find_section_bounds(lines: List[str], heading: str) -> Tuple[int, int]:
    """
    Find the start and end line indices of a section by its heading.
    End = next heading of same or higher level, or end of file.
    """
    level = len(heading) - len(heading.lstrip("#"))
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == heading.strip():
            start = i
            break
    if start == -1:
        return -1, -1

    end = len(lines)
    for i in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s", lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    return start, end


def update_doc_sections(changed_files: List[str], parsed: Dict[str, dict]) -> List[str]:
    """
    For each changed file, inject an auto-update block into its section(s).
    Returns list of sections that were actually updated.
    """
    if not DOC_FILE.exists():
        print(f"[WARN] {DOC_FILE} not found — skipping doc update.")
        return []

    lines = DOC_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_sections = []

    for rel in changed_files:
        info = parsed.get(rel, {})
        if "error" in info:
            print(f"  [SKIP] {rel} — parse error: {info['error']}")
            continue

        snippet = build_section_update(rel, info)
        snippet_lines = (snippet + "\n").splitlines(keepends=True)

        # Find the AUTO-UPDATE tag pattern we previously inserted
        tag_start = f"<!-- doc_agent:start:{rel} -->"
        tag_end   = f"<!-- doc_agent:end:{rel} -->"

        # Check if tag already exists
        tag_s_idx = next((i for i, l in enumerate(lines) if tag_start in l), -1)
        tag_e_idx = next((i for i, l in enumerate(lines) if tag_end   in l), -1)

        if tag_s_idx != -1 and tag_e_idx != -1 and tag_e_idx > tag_s_idx:
            # Replace existing block
            new_block = [f"{tag_start}\n"] + snippet_lines + [f"{tag_end}\n"]
            lines = lines[:tag_s_idx] + new_block + lines[tag_e_idx + 1:]
            updated_sections.append(rel)
        else:
            # Find relevant section heading and append after the first subheader
            section_headings = WATCHED.get(rel, [])
            placed = False
            for heading in section_headings:
                s, e = _find_section_bounds([l.rstrip("\n") for l in lines], heading)
                if s == -1:
                    continue
                # Insert after the heading line + optional blank line
                insert_at = s + 1
                while insert_at < e and lines[insert_at].strip() == "":
                    insert_at += 1
                new_block = [f"{tag_start}\n"] + snippet_lines + [f"{tag_end}\n", "\n"]
                lines = lines[:insert_at] + new_block + lines[insert_at:]
                updated_sections.append(f"{rel} -> {heading}")
                placed = True
                break
            if not placed:
                print(f"  [WARN] Section not found for {rel} — appending at end.")
                new_block = [f"\n{tag_start}\n"] + snippet_lines + [f"{tag_end}\n"]
                lines = lines + new_block
                updated_sections.append(f"{rel} (appended)")

    DOC_FILE.write_text("".join(lines), encoding="utf-8")
    return updated_sections


# ===========================================================================
# 5. Changelog writer
# ===========================================================================

def write_changelog(changed_files: List[str], updated_sections: List[str],
                    parsed: Dict[str, dict]) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"\n## {ts} — Auto-updated by doc_agent\n",
        "### Changed Files\n",
    ]
    for rel in changed_files:
        info = parsed.get(rel, {})
        # Summarise what was found
        classes   = [c["name"] for c in info.get("classes",   [])]
        functions = [f["name"] for f in info.get("functions", [])]
        detail = []
        if classes:
            detail.append(f"classes: {', '.join(classes[:4])}")
        if functions:
            detail.append(f"functions: {', '.join(functions[:4])}")
        detail_str = " — " + "; ".join(detail) if detail else ""
        lines.append(f"- `{rel}`{detail_str}")

    lines.append("\n### Sections Updated\n")
    for s in updated_sections:
        lines.append(f"- {s}")

    lines.append("")
    entry = "\n".join(lines)

    existing = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Documentation Changelog\n"
    # Insert after the first heading
    first_nl = existing.find("\n")
    CHANGELOG.write_text(existing[:first_nl + 1] + entry + existing[first_nl + 1:], encoding="utf-8")
    print(f"  Changelog updated: {CHANGELOG}")


# ===========================================================================
# 6. Main
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Documentation Update Agent")
    parser.add_argument("--force",  action="store_true", help="Rebuild all sections")
    parser.add_argument("--status", action="store_true", help="Show changes only, no write")
    parser.add_argument("--file",   help="Process a specific file only")
    args = parser.parse_args()

    state = load_state()
    changed = detect_changes(state, force=args.force)

    if args.file:
        changed = [args.file] if args.file in WATCHED else []

    if not changed:
        print("doc_agent: No changes detected. Documentation is up to date.")
        return

    print(f"doc_agent: {len(changed)} file(s) changed:")
    for f in changed:
        print(f"  {f}")

    if args.status:
        return

    # Parse each changed file
    parsed: Dict[str, dict] = {}
    for rel in changed:
        path = ROOT / rel
        if not path.exists():
            continue
        print(f"  Parsing {rel}...")
        if rel.endswith(".py"):
            parsed[rel] = parse_python_file(path)
        elif rel.endswith(".yaml") or rel.endswith(".yml"):
            parsed[rel] = parse_config_yaml(path)
        elif rel.endswith(".ps1") or rel.endswith(".bat"):
            parsed[rel] = parse_powershell_script(path)
        elif rel == "app.py":
            parsed[rel] = parse_app_tabs(path)
        else:
            parsed[rel] = {}

    # app.py needs both parsers
    if "app.py" in changed:
        app_path = ROOT / "app.py"
        py_info  = parse_python_file(app_path)
        tab_info = parse_app_tabs(app_path)
        parsed["app.py"] = {**py_info, **tab_info}

    # Update documentation
    print(f"  Updating {DOC_FILE.name}...")
    updated = update_doc_sections(changed, parsed)

    # Write changelog
    write_changelog(changed, updated, parsed)

    # Save new hashes
    for rel in changed:
        path = ROOT / rel
        if path.exists():
            state["hashes"][rel] = _sha256(path)
    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    print(f"\ndoc_agent: Done. {len(updated)} section(s) updated.")
    print(f"  Documentation: {DOC_FILE}")
    print(f"  State:         {STATE_FILE}")
    print(f"  Changelog:     {CHANGELOG}")


if __name__ == "__main__":
    main()


# ===========================================================================
# VS Code Task (add to .vscode/tasks.json)
# ===========================================================================
# {
#   "version": "2.0.0",
#   "tasks": [
#     {
#       "label": "Update Docs (doc_agent)",
#       "type": "shell",
#       "command": "python doc_agent.py",
#       "group": "build",
#       "presentation": { "reveal": "always", "panel": "dedicated" },
#       "problemMatcher": []
#     }
#   ]
# }
#
# ===========================================================================
# Git post-commit hook (save as .git/hooks/post-commit, chmod +x on Linux)
# ===========================================================================
# #!/bin/sh
# python doc_agent.py
# if [ -n "$(git status --porcelain APP_FUNCTIONALITY_REFERENCE.md)" ]; then
#   git add APP_FUNCTIONALITY_REFERENCE.md doc_agent_changelog.md doc_agent_state.json
#   git commit --amend --no-edit --quiet
# fi
