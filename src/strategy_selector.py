"""
src/strategy_selector.py
========================
Evaluate the paper-trade strategies, apply the "Winner - Smart (Win)" filter,
and backtest which strategy has historically performed best.

Used by the Auto Algo Trader (Tab 14) for dry-run evaluation and, optionally,
to auto-pick the strategy to trade.

Strategies covered:
    OptionBuyer, Hedging, Agent-Institutional, Agent-OptionSeller
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).parent.parent
AUTO_LOG = ROOT / "data" / "auto_trade_log.json"

# The four strategies requested for the dry-run / backtest workflow.
DEFAULT_STRATEGIES = ["Institutional", "OptionSeller", "OptionBuyer", "Hedging", "Agent-Institutional", "Agent-OptionSeller"]

STRATEGY_LABELS = {
    "Institutional": "🏦 Institutional",
    "OptionSeller": "⚙️ OptionSeller",
    "OptionBuyer": "🛒 OptionBuyer",
    "Hedging": "🛡️ Hedging",
    "Agent-Institutional": "🤖🏦 Agent-Institutional",
    "Agent-OptionSeller": "🤖⚙️ Agent-OptionSeller",
}

SMART_WIN = "🧠 Smart (Win)"
CROWD_LOSE = "👥 Crowd (Lose)"


def winner_label(direction: str, instrument: str, sentiment_score: int = 0) -> str:
    """Classify a strategy idea as Smart (Win) or Crowd (Lose).

    Sellers and defined-risk spreads are always Smart (Win) — statistical edge.
    Buyers are Smart (Win) when aligned with the current market sentiment
    (bullish: score>=1 buys CE; bearish: score<=-1 buys PE), otherwise Crowd (Lose).
    """
    d = str(direction or "").lower().strip()
    inst = str(instrument or "").lower().strip()
    if not inst and not d:
        return "—"
    # Sellers and spreads always get the Smart label
    if "sell" in d or "spread" in inst or "condor" in inst or "strangle" in inst:
        return SMART_WIN
    # Buyers: Smart only when sentiment aligns with the option type
    if "buy" in d:
        is_ce = "ce" in inst
        is_pe = "pe" in inst
        if is_ce and sentiment_score >= 1:
            return SMART_WIN   # Bullish market + buy CE = smart
        if is_pe and sentiment_score <= -1:
            return SMART_WIN   # Bearish market + buy PE = smart
        return CROWD_LOSE      # Buying against or in neutral market
    return "—"


def _optimizer_opts(cfg, trades, hist, oc, vix):
    """Reproduce the agent optimizer parameters used at entry time."""
    try:
        from src.agent_logic import DecisionOptimizerAgent
        agent = DecisionOptimizerAgent(cfg)
        perf = agent.analyze_journal_metrics(trades)
        reg = agent.evaluate_market_regime(hist, oc, vix)
        return agent.optimize_logic_parameters(perf, reg)
    except Exception:
        return {
            "optimal_sl_atr_multiplier": 1.5,
            "optimal_target_atr_multiplier": 2.5,
            "risk_allocation_multiplier": 1.0,
        }


def evaluate_strategies(strategies: Optional[List[str]] = None) -> Dict:
    """Run the requested strategy engines against the latest market snapshot.

    Returns {ok, message, spot, ideas:[{strategy, instrument, direction, strike,
    entry_price, stop_loss, target, qty_lots, investment_amount, winner, smart_win}]}.
    """
    strategies = strategies or list(DEFAULT_STRATEGIES)

    from src.auto_trade_engine import (
        load_morning_data, validate_conditions, _load_log,
        _run_institutional, _run_option_seller,
        _run_option_buyer, _run_hedging,
        _run_institutional_agent, _run_option_seller_agent,
    )
    from src.institutional_view import InstitutionalAnalyzer
    from src.strategy_builder import StrategyBuilder
    from src.utils import get_config

    hist, oc, pcr, vix, oc_json = load_morning_data()
    if hist is None or hist.empty or oc is None or oc.empty:
        return {"ok": False, "message": "Market data unavailable — fetch a live snapshot first.", "ideas": []}

    cfg = get_config(str(ROOT / "config.yaml"))
    ia = InstitutionalAnalyzer(cfg)
    sb = StrategyBuilder(cfg)
    sent = ia.generate_sentiment(hist, oc, pcr)
    validation = validate_conditions(oc, oc_json, vix, require_cron_run=None)
    vix_safe = validation.get("vix_safe_to_sell", True)

    trades = _load_log()
    opts = _optimizer_opts(cfg, trades, hist, oc, vix)

    runners = {
        "Institutional": lambda: _run_institutional(hist, oc, sent, cfg),
        "OptionSeller": lambda: _run_option_seller(hist, oc, sent, cfg, sb, vix_safe),
        "OptionBuyer": lambda: _run_option_buyer(hist, oc, sent, cfg),
        "Hedging": lambda: _run_hedging(hist, oc, sent, cfg),
        "Agent-Institutional": lambda: _run_institutional_agent(hist, oc, sent, cfg, opts),
        "Agent-OptionSeller": lambda: _run_option_seller_agent(hist, oc, sent, cfg, sb, vix_safe, opts),
    }

    spot = float(oc["spot"].iloc[0]) if not oc.empty else 0.0
    sentiment_score = int(sent.get("score", 0) or 0)
    ideas: List[Dict] = []
    for name in strategies:
        runner = runners.get(name)
        if not runner:
            continue
        try:
            res = runner()
        except Exception as exc:
            res = {"skip_reason": f"ERROR: {exc}"}
        skip = res.get("skip_reason")
        instrument = res.get("instrument", "")
        direction = res.get("direction", "")
        wl = "—" if skip else winner_label(direction, instrument, sentiment_score)
        ideas.append({
            "strategy": name,
            "label": STRATEGY_LABELS.get(name, name),
            "instrument": instrument,
            "direction": direction,
            "strike": str(res.get("strike", "")),
            # Pass through wing strikes so idea_to_legs can build 4-leg condors
            "short_ce_strike": res.get("short_ce_strike"),
            "short_pe_strike": res.get("short_pe_strike"),
            "buy_ce_strike":   res.get("buy_ce_strike"),
            "buy_pe_strike":   res.get("buy_pe_strike"),
            "entry_price": res.get("entry_price", 0.0),
            "stop_loss": res.get("stop_loss", 0.0),
            "target": res.get("target", 0.0),
            "qty_lots": res.get("qty_lots", 1),
            "investment_amount": res.get("investment_amount", 0.0),
            "reason": res.get("reason", ""),
            "skip_reason": skip,
            "winner": wl,
            "smart_win": (wl == SMART_WIN),
        })

    return {"ok": True, "message": f"Evaluated {len(ideas)} strategy(ies).",
            "spot": spot, "sentiment": sent.get("label", ""), "vix": vix, "ideas": ideas}


def backtest_winrate(strategies: Optional[List[str]] = None) -> List[Dict]:
    """Per-strategy historical performance from the auto trade log (closed trades).

    Returns rows: {strategy, trades, wins, win_rate_pct, avg_pnl, total_pnl,
    smart_win_trades, smart_win_rate_pct}.
    """
    strategies = strategies or list(DEFAULT_STRATEGIES)
    rows: List[Dict] = []
    log: List[Dict] = []
    if AUTO_LOG.exists():
        try:
            log = json.loads(AUTO_LOG.read_text(encoding="utf-8"))
        except Exception:
            log = []

    def _pnl(t: Dict) -> float:
        for k in ("pnl_amount", "total_pnl", "current_pnl"):
            v = t.get(k)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return 0.0

    for name in strategies:
        closed = [t for t in log if t.get("strategy_type") == name and str(t.get("status", "")).lower() == "closed"]
        n = len(closed)
        wins = sum(1 for t in closed if _pnl(t) > 0)
        total = round(sum(_pnl(t) for t in closed), 2)
        avg = round(total / n, 2) if n else 0.0

        smart = [t for t in closed if winner_label(t.get("direction", ""), t.get("instrument", "")) == SMART_WIN]
        sn = len(smart)
        s_wins = sum(1 for t in smart if _pnl(t) > 0)

        rows.append({
            "strategy": name,
            "label": STRATEGY_LABELS.get(name, name),
            "trades": n,
            "wins": wins,
            "win_rate_pct": round(wins / n * 100, 1) if n else 0.0,
            "avg_pnl": avg,
            "total_pnl": total,
            "smart_win_trades": sn,
            "smart_win_rate_pct": round(s_wins / sn * 100, 1) if sn else 0.0,
        })
    return rows


def recommend(strategies: Optional[List[str]] = None, momentum: Optional[Dict] = None) -> Dict:
    """Recommend a strategy to trade.

    Preference:
      1. Among strategies whose *current* idea is Smart (Win) and not skipped,
         pick the one with the best historical win-rate (>=3 closed trades),
         tie-break by avg P&L.
      2. If none have enough history, pick the Smart-Win candidate with the
         highest current target/stop reward proxy.
      3. Fallback: None (nothing qualifies).

    momentum: optional {"strong_trend": bool, "direction": "bullish"|"bearish"}.
      On a strong trend day, a directional buyer idea aligned with the trend
      (buy CE on bullish, buy PE on bearish) is preferred over a neutral seller,
      since sellers leave money on the table when the market trends hard.
    """
    strategies = strategies or list(DEFAULT_STRATEGIES)
    ev = evaluate_strategies(strategies)
    if not ev.get("ok"):
        return {"ok": False, "message": ev.get("message"), "recommended": None, "ideas": []}

    ideas = ev["ideas"]
    bt = {r["strategy"]: r for r in backtest_winrate(strategies)}

    momentum = momentum or {}
    strong_trend = bool(momentum.get("strong_trend"))
    trend_dir = str(momentum.get("direction", "")).lower()

    def _aligned_directional(i: Dict) -> bool:
        """True when a buyer idea's option type aligns with the trend direction."""
        if not strong_trend:
            return False
        d = str(i.get("direction", "")).lower()
        inst = str(i.get("instrument", "")).lower()
        if "buy" not in d:
            return False
        if trend_dir == "bearish" and "pe" in inst:
            return True
        if trend_dir == "bullish" and "ce" in inst:
            return True
        return False

    smart_candidates = [i for i in ideas if i["smart_win"] and not i["skip_reason"]]
    if not smart_candidates:
        return {"ok": True, "message": "No Smart (Win) candidate right now.",
                "recommended": None, "ideas": ideas, "backtest": list(bt.values())}

    def _key(i: Dict):
        r = bt.get(i["strategy"], {})
        has_hist = r.get("trades", 0) >= 3
        wr = r.get("win_rate_pct", 0.0) if has_hist else -1.0
        avg = r.get("avg_pnl", 0.0) if has_hist else 0.0
        # Momentum tilt: on strong trend days, aligned directional buyers rank first.
        momentum_pref = 1 if _aligned_directional(i) else 0
        return (momentum_pref, wr, avg)

    best = sorted(smart_candidates, key=_key, reverse=True)[0]
    _trend_note = " [momentum-tilt]" if _aligned_directional(best) else ""
    return {
        "ok": True,
        "message": f"Recommended: {best['label']} (Smart-Win).{_trend_note}",
        "recommended": best["strategy"],
        "recommended_idea": best,
        "ideas": ideas,
        "backtest": list(bt.values()),
    }


def idea_to_legs(idea: Dict) -> List[Dict]:
    """Convert a strategy idea into broker legs (best-effort).

    Handles:
      - Single-leg buys/sells
      - 2-leg vertical credit spreads (e.g. 'PE:24100/PE:23850') → SELL/BUY same type
      - 2-leg short strangles (e.g. 'CE:24450/PE:24050') → SELL/SELL different types
      - 4-leg iron condors using short_ce/pe + buy_ce/pe fields
    Returns [] when the idea cannot be mapped safely.
    """
    strike_raw = str(idea.get("strike", "")).strip()
    direction = str(idea.get("direction", "")).lower()
    instrument = str(idea.get("instrument", "")).upper()

    # ── 4-leg Iron Condor (when wing strikes are explicitly stored) ──
    short_ce = int(idea.get("short_ce_strike") or 0)
    short_pe = int(idea.get("short_pe_strike") or 0)
    buy_ce   = int(idea.get("buy_ce_strike")   or 0)
    buy_pe   = int(idea.get("buy_pe_strike")   or 0)
    if short_ce > 0 and short_pe > 0 and buy_ce > 0 and buy_pe > 0:
        return [
            {"action": "SELL", "option_type": "CE", "strike": short_ce},
            {"action": "SELL", "option_type": "PE", "strike": short_pe},
            {"action": "BUY",  "option_type": "CE", "strike": buy_ce},
            {"action": "BUY",  "option_type": "PE", "strike": buy_pe},
        ]

    # ── 2-leg spread or strangle ("CE:24450/PE:24050" or "PE:24100/PE:23850") ──
    if "/" in strike_raw and ":" in strike_raw:
        tokens = [t.strip() for t in re.split(r"[/|]", strike_raw) if t.strip()]
        parsed: List[Dict] = []
        for tok in tokens:
            m = re.search(r"(CE|PE)[^0-9]*([0-9]{4,6})", tok.upper())
            if m:
                parsed.append({"option_type": m.group(1), "strike": int(m.group(2))})
        if len(parsed) < 2:
            return []
        leg1, leg2 = parsed[0], parsed[1]
        if leg1["option_type"] != leg2["option_type"]:
            # Mixed types (CE+PE) → both SELL (short strangle)
            return [
                {"action": "SELL", "option_type": leg1["option_type"], "strike": leg1["strike"]},
                {"action": "SELL", "option_type": leg2["option_type"], "strike": leg2["strike"]},
            ]
        else:
            # Same type (PE+PE or CE+CE) → credit spread: first=SELL, second=BUY
            return [
                {"action": "SELL", "option_type": leg1["option_type"], "strike": leg1["strike"]},
                {"action": "BUY",  "option_type": leg2["option_type"], "strike": leg2["strike"]},
            ]

    # ── Single strike leg ──
    nums = re.findall(r"[0-9]{4,6}", strike_raw)
    if not nums:
        return []
    strike = int(nums[0])
    opt = "CE" if "CE" in instrument else ("PE" if "PE" in instrument else "")
    if not opt:
        return []
    action = "SELL" if "sell" in direction else "BUY"
    return [{"action": action, "option_type": opt, "strike": strike}]
