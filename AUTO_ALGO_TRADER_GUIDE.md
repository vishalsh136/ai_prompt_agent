# 🤖 Auto Algo Trader — Usage Guide

This guide explains how to use the **🤖 Auto Algo Trader** tab (Tab 14) for
**dry-run testing**, **backtesting**, and **live trading**.

> ⚠️ **Safety first:** The trader only places **real orders** when
> `allow_live = true` **AND** `dry_run = false`. By default it runs in
> **dry-run** mode (simulated orders). Always validate in dry-run before going live.

---

## 1. What this tab does

It combines the paper-engine strategy logic (Auto Trade Log) with live broker
execution into one automated trader that:

- Fetches **real-time** market data (no cron needed) from niftytrader.in.
- Values your position each poll and applies **risk guards**.
- Enters/exits automatically inside your configured **trade window**.
- Supports **manual** strategy selection or **auto_winner** (auto-pick the best
  🧠 Smart (Win) strategy).

Config is stored in `algo_trade_config.json` (repo root, git-ignored).
Journal → `data/live_algo_journal.jsonl`. Positions → `data/live_algo_positions.json`.

---

## 2. Tab layout (Sections A–G)

| Section | Purpose |
|---------|---------|
| **A · Broker & Credentials** | Pick active broker (Groww default), view masked API key/secret/token, edit & save, regenerate access token. |
| **B · Strategy & Strikes** | Symbol, strategy, lots, expiry, strike inputs, legs preview, trade window & square-off time, poll interval. |
| **C · Risk Controls** | Target profit, per-trade max loss, time exit, max trade amount, max lots, max open positions, max orders/day, daily max loss, daily profit lock, crash/rally/gap guards, cool-off. |
| **D · Run Controls** | Selection mode (manual / auto_winner), enabled strategies, Save / Arm / Disarm / Run-tick, **dry-run** & **allow-live** toggles. |
| **E · Real-time Market Snapshot** | Fetch live spot / day-move / VIX / PCR on demand. |
| **F · Live Status** | Open auto-algo positions, realized P&L today, execution journal. |
| **G · Strategy Selection & Backtest** | Evaluate the 4 strategies live, filter by 🧠 Smart (Win), view historical win-rates, get a recommendation. |

---

## 3. Dry-run workflow (recommended first)

Use dry-run to confirm your setup works end-to-end **without placing real orders**.

1. **Section A** — Select your broker (Groww is default). You don't need real
   credentials for dry-run.
2. **Section B** — Set `symbol`, `strategy`, `lots`, `expiry`, and strikes.
   Check the **legs preview** table looks correct. Set the **trade window**
   (e.g. `09:20`–`15:20`) and **hard square-off** time.
3. **Section C** — Set your risk limits (target profit, max loss, daily max loss, etc.).
4. **Section D**:
   - Leave **Dry run = ON** (default).
   - Leave **Allow live = OFF**.
   - Choose **Strategy selection = manual** (or `auto_winner`, see §5).
   - Click **💾 Save Config**.
5. Click **▶ Run Single Tick** to run one cycle. Review the JSON result:
   - `action: idle` → not armed / outside window / waiting.
   - `action: entry` → a (simulated) entry was made.
   - `action: exit` → a (simulated) exit was triggered (with the reason).
   - `action: blocked / halted / cooloff` → a risk guard stopped the trade.
6. When satisfied, click **🟢 Arm Trader**, then run the loop in a terminal:

   ```powershell
   python -m src.algo_auto_trader --loop
   ```

7. Watch **Section F** for positions, realized P&L, and the journal.
8. Click **⚪ Disarm** to stop new entries.

> All entries/exits in dry-run are simulated and journaled with `"dry_run": true`.

---

## 4. Backtesting & choosing a strategy (Section G)

Section G helps you decide which strategy to trade — read-only, no orders placed.

1. **Select strategies to evaluate** (default: all 4 —
   OptionBuyer, Hedging, Agent-Institutional, Agent-OptionSeller).
2. Click **🔍 Evaluate strategies now (dry-run)**:
   - Shows spot / sentiment / VIX.
   - **All strategy ideas** table (instrument, direction, strike, entry, SL,
     target, and the **Winner** column).
   - **🧠 Smart (Win) candidates only** — the filtered subset worth trading
     (sells / spreads). Naked buys are flagged 👥 Crowd (Lose).
3. Click **📊 Historical backtest / win-rate**:
   - Per-strategy **win-rate**, avg P&L, total P&L, and Smart-Win win-rate,
     computed from closed trades in `data/auto_trade_log.json`.
   - A **✅ Recommended** strategy (best Smart-Win by historical win-rate,
     needs ≥ 3 trades).

Use these results to pick the strategy for manual mode, or to trust `auto_winner`.

CLI equivalents:

```powershell
python -c "from src.strategy_selector import backtest_winrate; import json; print(json.dumps(backtest_winrate(), indent=2))"
python -c "from src.strategy_selector import recommend; import json; print(json.dumps(recommend(), indent=2))"
```

---

## 5. Auto-winner mode (auto-pick Smart (Win))

Instead of a fixed strategy, let the trader pick the best Smart (Win) candidate
each entry.

1. **Section D** — Set **Strategy selection = auto_winner**.
2. Choose the **Strategies for auto_winner** (multiselect; default all 4).
3. Click **💾 Save Config**, then **🟢 Arm Trader**.
   - Strikes/expiry are **not** required in auto_winner mode — the trader derives
     legs from the recommended idea automatically.
4. On each entry the trader calls the recommender, converts the winning idea to
   broker legs, and trades that strategy. If there's no Smart (Win) candidate it
   returns `no_trade`.

> Recommended: keep **dry-run ON** while validating auto_winner, then review the
> journal in Section F before enabling live.

---

## 6. Going live (real orders)

Only after dry-run + backtest look correct.

1. **Section A** — Enter real broker credentials (API key/secret). Save.
2. Click **♻ Regenerate token** (optionally tick **allow live**) to mint a fresh
   access token. Confirm it shows a token.
3. **Section D**:
   - Turn **Dry run = OFF**.
   - Turn **Allow live = ON**.
   - Keep **Auto-regenerate token = ON** so the loop can refresh an expired token.
   - Click **💾 Save Config**, then **🟢 Arm Trader**.
4. Run the loop unattended in a terminal:

   ```powershell
   python -m src.algo_auto_trader --loop
   ```

5. Monitor **Section F** (positions / realized P&L / journal). Use **⚪ Disarm**
   to stop new entries; open positions still exit via their triggers and the
   hard square-off time.

> 🔒 If either **Dry run = ON** or **Allow live = OFF**, orders remain simulated.

---

## 7. Risk guards (what stops a trade)

Configured in **Section C**, enforced every tick:

- **Target profit / Max loss / Time exit** — per-position exit triggers.
- **Hard square-off time** — force-close after this time.
- **Daily max loss** — halts new entries once hit.
- **Daily profit lock** — halts after the day's profit target.
- **Crash / Rally guard** — blocks (or exits) on large day moves (% vs open).
- **Gap guard** — blocks first entry on a large opening gap.
- **Max trade amount** — caps capital per trade (via margin proxy).
- **Max lots / open positions / orders per day** — position and frequency caps.
- **Cool-off after loss** — pause new entries for N minutes after a losing exit.

---

## 8. Command reference

```powershell
# One cycle (prints JSON result)
python -m src.algo_auto_trader --once

# Continuous loop (unattended; survives app reruns)
python -m src.algo_auto_trader --loop

# Regenerate broker access token
python -m src.token_manager --broker Groww          # dry
python -m src.token_manager --broker Groww --live   # live
```

---

## 9. Quick checklist

- [ ] Configure broker (A), strategy/strikes/window (B), risk limits (C).
- [ ] Dry-run: Save → Run Single Tick → review JSON → Arm → `--loop`.
- [ ] Section G: evaluate ideas + backtest → confirm strategy.
- [ ] Only then: real creds → regenerate token → Dry-run OFF + Allow-live ON → Arm → `--loop`.
- [ ] Monitor Section F; Disarm to stop.
