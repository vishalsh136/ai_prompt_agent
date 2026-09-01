# Auto Algo Trader: Fully Automated Entry & Exit Confirmation

## Executive Summary

✅ **The Auto Algo Trader is 100% AUTOMATED** — No manual watching required.

Once you set `"armed": true` in the config, the system:
- **Automatically reads** market data every 30 seconds
- **Automatically evaluates** circuit breakers, regime guards, strategy performance
- **Automatically enters** positions when all conditions pass
- **Automatically exits** positions on ANY of 8 independent triggers
- **Logs every decision** to journal for audit and backtesting

---

## Architecture: Two Operational Modes

### Mode 1: `--once` (Manual Tick)
```bash
python -m src.algo_auto_trader --once
```
Runs **one cycle** and prints the decision to console. Used for:
- Manual testing
- Debugging strategy selection
- Integration with external automation (cron, workflow, etc)

**Output Example**:
```json
{
  "ts": "2026-07-28T10:15:30.123456",
  "action": "auto_entry",
  "strategy": "Agent-OptionSeller",
  "entry_value": 1250.5,
  "pnl_inr": 0,
  "reason": "Iron Condor entry at ATM-2 standard deviation..."
}
```

### Mode 2: `--loop` (Continuous Automation)
```bash
python -m src.algo_auto_trader --loop --interval 30
```
Runs **continuously** every 30 seconds, never stops. Used for:
- Live trading (paper or real, depending on `allow_live` flag)
- Production deployment on server/VPS
- 24/7 monitoring (if market is open)

**Behavior**:
- Tick every 30 seconds (configurable via `poll_interval_sec` or `--interval`)
- Every tick: check open positions → auto-exit if triggered
- Every tick: if flat, check if conditions allow entry → auto-enter if clear
- Logs every decision with timestamp to `data/live_algo_journal.jsonl`
- Catches exceptions and continues (doesn't crash on API errors)

---

## Entry Process (100% AUTOMATED)

### Every 30-Second Tick:

```
┌─────────────────────────────────────────────────────────┐
│ ENTRY DECISION FLOW (if no open position)               │
└─────────────────────────────────────────────────────────┘

1. Refresh Real-Time Data
   └─→ refresh_realtime() pulls live spot, PCR, VIX, day_move
   └─→ If feed fails → BLOCK NEW ENTRIES (data_stale guard)

2. Check Entry Blockers (in order)
   ├─→ Is "armed" enabled in config? → if NO, return "not_armed"
   ├─→ Is data stale? → BLOCK
   ├─→ Daily max loss hit (-₹15,000)? → HALT all trading
   ├─→ Daily profit target hit (₹4,000)? → HALT all trading
   ├─→ Past hard squareoff time (15:20)? → IDLE
   ├─→ Crash guard triggered (NIFTY down 1.5%)? → BLOCK
   ├─→ Rally guard triggered (NIFTY up 1.5%)? → BLOCK
   ├─→ Gap guard triggered (day open moved 1.2%)? → BLOCK (first trade only)
   ├─→ Outside trade window (09:20-15:20)? → IDLE
   ├─→ Max orders per day (6) reached? → HALT
   ├─→ Max open positions (2) reached? → IDLE
   └─→ Cool-off active (30 min after loss)? → COOLOFF

3. Strategy Selection (if enabled_strategies = auto_winner)
   ├─→ Run all 6 strategy engines on live data
   ├─→ Filter for "Smart-Win" candidates (sellers, spreads)
   ├─→ Score by backtest win-rate + current P&L
   ├─→ Pick the best performer
   └─→ Log selection reason & backtest details

4. Pre-Entry Regime Guards (NEW)
   ├─→ Guard 1: Block OptionBuyer/Institutional in neutral market
   │   └─→ PCR between 0.8–1.2 AND VIX < 16 → SKIP
   │   └─→ Today's market (PCR=0.92, VIX=12.56) → BLOCKS buyers ✓
   └─→ Guard 2: Block buyers when VIX > 20
       └─→ Prefer sellers at high volatility

5. Estimate Margin & Position Size
   ├─→ Broker: estimate_margin_proxy()
   ├─→ Cap check: position value ≤ ₹150,000?
   └─→ If exceeds → BLOCK

6. Place Order (Automatically)
   └─→ adapter.place_basket_order(req)
       ├─→ DRY RUN mode (dry_run=true): simulated
       └─→ LIVE mode (dry_run=false, allow_live=true): real broker order

7. Log Entry Event
   ├─→ Append to data/live_algo_journal.jsonl: "auto_entry" event
   ├─→ Log: position_id, strategy, entry_value, entry_time, est_amount
   └─→ Example:
       {
         "event": "auto_entry",
         "position_id": "algo_NIFTY_Agent-OptionSeller_20260728",
         "strategy": "Agent-OptionSeller",
         "entry_value": 1250.50,
         "entry_time": "2026-07-28T10:15:30Z",
         "lots": 1,
         "units_per_leg": 65
       }

8. Return Action to Console
   └─→ action: "auto_entry" (success) or
       action: "blocked" / "idle" / "halted" / "no_trade" (reason)
```

---

## Exit Process (100% AUTOMATED)

### Every 30-Second Tick (if Position Open):

```
┌─────────────────────────────────────────────────────────┐
│ EXIT DECISION FLOW (if open position exists)            │
└─────────────────────────────────────────────────────────┘

1. Value the Open Position
   ├─→ Source priority:
   │   ├─→ Broker live LTP (if available)
   │   ├─→ In-memory snapshot (faster, no CSV round-trip)
   │   └─→ Fallback: CSV shared data (cached)
   └─→ If valuation fails → HOLD (wait for next tick)

2. Calculate P&L
   ├─→ pnl = (entry_value - current_value) × units_per_leg
   └─→ Example: entry=₹1200, current=₹950, units=65 → pnl=₹16,250

3. Check 8 Exit Triggers (evaluated in order)
   ├─→ 1️⃣ TARGET_PROFIT: pnl ≥ ₹2,000? → EXIT
   │      (Seller enters at ₹3K premium, closes at ₹1.5K = ₹1,500 profit)
   │
   ├─→ 2️⃣ MAX_LOSS: pnl ≤ -₹3,000? → EXIT IMMEDIATELY
   │      (Protective stop-loss, prevents catastrophic loss)
   │
   ├─→ 3️⃣ TIME_EXIT: minutes_open ≥ 120 (buyers) or 180 (sellers)? → EXIT
   │      (New: buyers exit after 2 hrs to cut theta-decay drag)
   │      (Sellers hold 3 hrs to collect more decay)
   │
   ├─→ 4️⃣ HARD_SQUAREOFF: time ≥ 15:20? → FORCE EXIT
   │      (Market close, no overnight holding allowed)
   │
   ├─→ 5️⃣ DAILY_LOSS_CUTOFF: realized_pnl ≤ -₹15,000? → EXIT
   │      (Daily circuit breaker, prevents account blowup)
   │
   ├─→ 6️⃣ DAILY_PROFIT_LOCK: realized_pnl ≥ ₹4,000? → EXIT
   │      (New: take profits, avoid over-trading on good days)
   │
   ├─→ 7️⃣ STALE_DATA_GUARD: data feed failed? → EXIT (if enabled)
   │      (Protective: don't hold if market data unavailable)
   │
   └─→ 8️⃣ CRASH/RALLY_GUARD: spot moved ±1.5% intraday? → EXIT
         (If crash_guard=true: exit shorts on 1.5% drop)
         (If rally_guard=true: exit longs on 1.5% rise)

4. If ANY Trigger Fires
   ├─→ Call adapter.square_off_all(symbol, strategy)
   ├─→ If DRY_RUN: simulated squareoff
   └─→ If LIVE: real broker order to close position

5. Update Position Status
   ├─→ Set status = "closed"
   ├─→ Set exit_value, exit_time, pnl_inr, exit_trigger
   └─→ Remove from active positions

6. Log Exit Event
   ├─→ Append to data/live_algo_journal.jsonl: "auto_exit" event
   ├─→ Log: trigger, pnl, minutes_held, entry_value, exit_value
   └─→ Example:
       {
         "event": "auto_exit",
         "position_id": "algo_NIFTY_Agent-OptionSeller_20260728",
         "strategy": "Agent-OptionSeller",
         "trigger": "TARGET_PROFIT",
         "entry_value": 1250.50,
         "exit_value": 625.25,
         "pnl_inr": 1625.00,
         "minutes_open": 47
       }

7. Return Action to Console
   └─→ action: "exit", trigger: "TARGET_PROFIT", pnl_inr: ₹1,625
```

---

## Configuration Flags (Control Automation)

| Flag | Value | Effect |
|------|-------|--------|
| `controls.armed` | `true` | ✅ ENABLE automation |
| `controls.armed` | `false` | ❌ DISABLE (returns "not_armed" every tick) |
| `controls.dry_run` | `true` | Simulate (don't place real orders) |
| `controls.dry_run` | `false` | Real orders (requires `allow_live=true` also) |
| `controls.allow_live` | `true` | Permit live orders (only if `dry_run=false`) |
| `controls.allow_live` | `false` | Block live orders (force simulation) |
| `trading.selection_mode` | `"auto_winner"` | Auto-pick best strategy |
| `trading.selection_mode` | `"manual"` | Use fixed strategy+strikes |
| `trading.poll_interval_sec` | `30` | Check every 30 seconds |
| `risk.time_exit_minutes` | `120` (buyers) / `180` (sellers) | Auto-exit after N minutes |

---

## Live Testing Path

### Step 1: Enable on Paper (Safest)
```python
# In algo_trade_config.json:
"controls": {
    "armed": true,           # Turn ON automation
    "dry_run": true,         # Paper trading (simulated)
    "allow_live": false      # Don't send real orders
}
```
Then run:
```bash
python -m src.algo_auto_trader --loop --interval 30
```
Watch `data/live_algo_journal.jsonl` fill with auto entries/exits. No real money at risk.

### Step 2: Paper with Real Valuation
```python
"trading": {
    "value_from_broker": true   # Get live LTP from broker
}
```
Entries/exits still simulated, but valued at real broker prices.

### Step 3: Live Trading (CAREFUL)
```python
"controls": {
    "armed": true,
    "dry_run": false,        # Send real orders!
    "allow_live": true       # ENABLE live execution
}
"trading": {
    "selection_mode": "auto_winner",  # Use smart selection
    "enabled_strategies": [...]       # Strategies to consider
}
"risk": {
    "daily_max_loss_inr": 15000.0,    # Circuit breaker
    "daily_profit_target_inr": 4000.0 # Lock profits
}
```

---

## Verification Checklist

✅ **Entry Automation**:
- [ ] `armed: true` in config
- [ ] `selection_mode: "auto_winner"` (or manual legs configured)
- [ ] Market is open (09:20-15:20 IST)
- [ ] No circuit breaker blocks active (crash, rally, daily max loss)
- [ ] First run logs `"action": "auto_entry"` to console

✅ **Exit Automation**:
- [ ] Position shows `"status": "open"` in live_positions
- [ ] Every 30-second tick evaluates exit conditions
- [ ] When target hit → logs `"action": "exit", "trigger": "TARGET_PROFIT"`
- [ ] When max loss hit → logs `"action": "exit", "trigger": "MAX_LOSS"`
- [ ] When time expired → logs `"action": "exit", "trigger": "TIME_EXIT"`

✅ **Logging**:
- [ ] Check `data/live_algo_journal.jsonl` exists and grows
- [ ] Each line is a valid JSON event (auto_entry, auto_exit, etc)
- [ ] Timestamps are present and sequential

---

## No Manual Watching Required

| Scenario | Auto Trader Behavior |
|----------|----------------------|
| **Entry Condition Met** | Auto enters, logs entry, returns to idle |
| **Target Profit Hit** | Auto exits same day, closes position, logs exit |
| **Max Loss Hit** | Auto exits immediately, cuts loss, logs exit |
| **3 Hours Passed** | Auto exits for seller; 2 hrs for buyer |
| **Market Closes (15:20)** | Auto hard-squareoff all positions |
| **NIFTY Down 1.5%** | Auto exits shorts (crash guard) |
| **NIFTY Up 1.5%** | Auto exits longs (rally guard) |
| **Daily Max Loss Hit** | Auto halts new entries, exits open |
| **Daily Profit Lock Hit** | Auto halts new entries (₹4,000 reached) |
| **Data Feed Fails** | Auto blocks new entries, logs data_stale |

**Conclusion**: Set `armed: true`, start the loop, and the system takes it from there. Zero human intervention needed except to monitor logs and adjust config between sessions.

---

**Status**: ✅ FULLY AUTOMATED — Entry and exit are 100% market-driven, no manual watching required