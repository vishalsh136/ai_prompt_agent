# Auto Trade Log P&L Update Guide

## Overview
The P&L (Profit & Loss) for auto trades is **automatically calculated and updated** through a 3-phase workflow running via PowerShell Scheduled Task.

---

## 3-Phase Workflow

### Phase 1: ENTRY (10:15 AM) ⏰
**What happens:**
- Cron downloads latest NSE market data
- `auto_trade_engine.py --mode=entry` runs
- **4 new trades are created** in `data/auto_trade_log.json` (one per strategy):
  1. Institutional Strategy
  2. Option Seller Strategy
  3. Option Buyer Strategy
  4. Hedging Strategy
  
- Initial fields set:
  - `entry_price` ← from market data at 10:15
  - `stop_loss` ← calculated by strategy
  - `target` ← calculated by strategy
  - `current_pnl` = 0.0 (not yet updated)
  - `status` = "Open"

**Time to see trades:** ~10:15 AM IST
**P&L status:** ❌ Not yet calculated (will be 0.0)

---

### Phase 2: INTRADAY UPDATE (11:00 AM - 2:59 PM) 📊
**What happens:**
- Cron runs every ~15-30 min during market hours
- `auto_trade_engine.py --mode=update` runs
- **Current P&L is recalculated** for all open trades:
  - Gets latest option prices from NSE
  - Calculates spread value for spread trades
  - Computes P&L: `(current_price - entry_price) × lot_size × qty`
  - Checks if SL (Stop Loss) or Target is hit

- Updated fields:
  - `current_ltp` ← latest market price
  - `current_pnl` ← profit/loss amount (₹)
  - `current_pnl_pct` ← profit/loss percentage (%)
  - `last_updated` ← when P&L was last refreshed

**Time to see P&L:** ~11:00 AM onwards (updates every ~15 min)
**P&L status:** ✅ **LIVE UPDATES** during trading hours
**Where to see:** Tab 10 "📊 Auto Trade Log" → "All Trades" table

---

### Phase 3: EOD (3:30 PM - 6:30 PM) 🏁
**What happens:**
- Final cron run after market close
- `auto_trade_engine.py --mode=eod` runs
- **Trades are closed** with final P&L:
  - If SL/Target was hit during day → uses that price
  - Otherwise → uses last 15:30/18:30 price as exit
  
- Final fields set:
  - `exit_price` ← closing price or trigger price
  - `exit_time` ← when trade closed
  - `exit_trigger` ← "SL_Hit", "Target_Hit", or "EOD_Close"
  - `status` = "Closed" or "SL_Hit" or "Target_Hit"
  - `pnl_amount` ← final P&L (₹)
  - `pnl_pct` ← final P&L (%)

**Time to see final P&L:** ~3:30 PM onwards
**P&L status:** ✅ **FINAL P&L** locked in

---

## How to View P&L

### In Streamlit App:
1. Open **Tab 10**: "📊 Auto Trade Log"
2. Look at **"All Trades" section** (bottom of tab)
3. Columns visible:
   - `current_pnl` (live during day)
   - `current_pnl_pct` (live during day)
   - `pnl_amount` (final, after EOD)
   - `pnl_pct` (final, after EOD)

### In JSON File Directly:
```bash
# View raw JSON
type data/auto_trade_log.json

# Or via Python
python -c "import json; print(json.dumps(json.load(open('data/auto_trade_log.json')), indent=2))"
```

### Expected JSON Structure:
```json
{
  "id": "20260717_NIFTY_Institutional",
  "date": "2026-07-17",
  "entry_time": "10:15",
  "status": "Open",  // "Open" during day, changes to "Closed"/"SL_Hit"/"Target_Hit" at EOD
  "entry_price": 250.0,
  "stop_loss": 245.0,
  "target": 260.0,
  "current_ltp": 252.50,      // Updates during day
  "current_pnl": 625.0,       // Updates every 15 min
  "current_pnl_pct": 5.0,     // Updates every 15 min
  "last_updated": "11:30",    // When it was last refreshed
  "exit_price": 258.0,        // Only after EOD
  "exit_trigger": "Target_Hit",  // Only after EOD
  "pnl_amount": 2000.0,       // Only after EOD
  "pnl_pct": 16.0             // Only after EOD
}
```

---

## P&L Calculation Formula

### For Buy Trades (Long Options):
```
P&L = (current_price - entry_price) × lot_size × qty
```
- ✅ Profit when `current_price > entry_price`
- ❌ Loss when `current_price < entry_price`

### For Sell Trades (Short Options / Spreads):
```
P&L = (entry_price - current_price) × lot_size × qty
```
- ✅ Profit when `current_price < entry_price` (premium falls)
- ❌ Loss when `current_price > entry_price` (premium rises)

### Example:
**Institutional Trade (Buy CE)**
- Entry Price: ₹250
- Current Price: ₹252.50
- Lot Size: 25
- Qty: 1 lot
- P&L = (252.50 - 250) × 25 × 1 = **₹62.50**
- P&L % = (62.50 / entry_investment) × 100 = **5%**

---

## Troubleshooting P&L

### ❌ P&L shows 0.0 or "—"
**Causes:**
- App hasn't fully synced data yet
- Option chain CSV might be stale
- Market data not downloaded yet

**Solution:**
- Wait for next cron run (~15 min)
- Manually run: `powershell -ExecutionPolicy Bypass -File download_nse_data.ps1 -Mode=update`

### ❌ P&L not updating after 11:00 AM
**Causes:**
- Cron scheduler might not be running
- `data/auto_trade_log.json` might be locked by another process

**Solution:**
```powershell
# Check if scheduled task is running
Get-ScheduledTask -TaskName "*download*" | Get-ScheduledTaskInfo

# Manually trigger update
powershell -ExecutionPolicy Bypass -File download_nse_data.ps1 -Mode=update
```

### ❌ "current_pnl" is very high/low (unrealistic)
**Causes:**
- Wrong option chain data (old/stale)
- Strike mismatch between trade and option chain

**Solution:**
- Verify `data/option_chain_NIFTY.csv` is today's data
- Check if trade strike matches available strikes in CSV

---

## Complete Cron Schedule

| Time | Mode | What Runs | Output |
|------|------|-----------|--------|
| **9:15 AM** | (data-only) | Downloads historical + option chain | CSV files in `downloads/` |
| **10:15 AM** | `entry` | Runs strategy engines, logs 4 trades | `data/auto_trade_log.json` created/updated with "Open" trades |
| **11:00 AM-2:59 PM** | `update` | Updates P&L every 15 min | `current_pnl`, `current_pnl_pct` updated |
| **3:30 PM** | `eod` | Closes all trades | `status="Closed"`, `pnl_amount`, `pnl_pct` finalized |

---

## Manual Trigger Commands

### View current P&L status:
```powershell
type data\auto_trade_log.json | ConvertFrom-Json
```

### Trigger entry phase (create trades):
```powershell
python src/auto_trade_engine.py --mode=entry
```

### Trigger update phase (refresh P&L):
```powershell
python src/auto_trade_engine.py --mode=update
```

### Trigger EOD phase (close trades):
```powershell
python src/auto_trade_engine.py --mode=eod
```

### Full download + auto (auto-detect mode):
```powershell
powershell -ExecutionPolicy Bypass -File download_nse_data.ps1 -Mode=auto
```

---

## Summary

| Aspect | Answer |
|--------|--------|
| **Do I need full cron?** | ✅ YES - Scheduled Task automatically runs cron 3-4x daily |
| **When does P&L appear?** | 📊 ~11:00 AM (after 2nd cron update) |
| **Does it auto-update?** | ✅ YES - every ~15 minutes during 11 AM - 3 PM |
| **Final P&L when?** | 🏁 ~3:30 PM (after market close cron) |
| **Need manual action?** | ❌ NO - all automatic via Scheduled Task |
| **Manual trigger?** | ✅ Optional: `powershell -ExecutionPolicy Bypass -File download_nse_data.ps1 -Mode=update` |

