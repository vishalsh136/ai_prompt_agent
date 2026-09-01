# Indian Market Study Tool

> **⚠️ DISCLAIMER — Read before proceeding**
>
> This application is for **EDUCATIONAL AND STUDY PURPOSES ONLY**.
> It does NOT place real trades, connect to any broker API, or give financial advice.
> All market data is **synthetic** unless you supply real downloaded files.
> Options and futures trading carries significant financial risk — consult a SEBI-registered
> advisor before making any real investment decision.

---

## What Is This?

A self-contained Python desktop/web application for studying Indian equity derivatives.
It supports a **daily paper-trade workflow**:

1. Upload 3 NSE files in the morning → get full dashboard analysis
2. Go to **Final Trade Decision** → see clean institutional + option-seller trade setup
3. Click "Log Trade" → trade is saved to a local journal
4. Return 2–3 hours later with updated files → **Trade Journal** shows P&L, HOLD/EXIT suggestion
5. End of day → review trade history with win/loss stats

---

## Project Structure

```
ai_prompt_agent/
├── app.py                       ← Main Streamlit entry point (7 tabs)
├── main.py                      ← Launcher
├── config.yaml                  ← All defaults (symbols, lot sizes, margins)
├── requirements.txt
├── README.md
│
├── src/
│   ├── utils.py                 ← Black-Scholes, Greeks, logging, formatting
│   ├── data_provider.py         ← Data loading (synthetic + real files; indices & stocks)
│   ├── real_data_loader.py      ← Parse NSE downloaded CSV files
│   ├── institutional_view.py    ← MA, ATR, OI/volume analysis, Max Pain, sentiment
│   ├── options_view.py          ← 10 option strategy payoffs, Greeks, explanations
│   ├── strategy_builder.py      ← Rule-based strategy engine (option seller + futures)
│   ├── final_trade_decision.py  ← Clean final trade setup (entry/SL/target/margin)
│   ├── trade_tracker.py         ← Paper-trade journal (log, P&L update, hold/exit)
│   └── backtesting.py           ← MA crossover + PCR contrarian backtesting
│
├── data/                        ← Auto-generated CSVs + trade journal
│   ├── futures_NIFTY.csv
│   ├── option_chain_NIFTY.csv
│   ├── pcr_NIFTY.csv
│   ├── trade_journal.json       ← Your paper-trade log (created on first trade)
│   └── …
│
└── logs/
    └── app.log
```

---

## Quick Start

```bash
cd c:\apps\ai_prompt_agent
pip install -r requirements.txt
python main.py
# OR: streamlit run app.py
```

---

## Daily Workflow

### Morning (upload files)
1. Download from NSE:
   - Price history CSV (Historical Data page)
   - Option Chain CSV (Option Chain page → download)
   - PCR CSV (if available)
2. In the sidebar → **📂 Real Data** → enable toggle → enter file paths → click **Load Real Data**

### Analysis
3. **Tab 1 — Institutional View**: candlestick + MAs + OI/volume + PCR + option chain + sentiment
4. **Tab 2 — Options Trader View**: payoff diagrams, Greeks for 10 strategies
5. **Tab 4 — Strategy Builder**: regime-based option seller + institutional futures setups

### Final Decision
6. **Tab 5 — 🎯 Final Trade Decision**: clean, minimal setup for BOTH logics:
   - Entry price | SL | Target 1 | Target 2
   - Margin required (approx)
   - Risk:Reward | Expected time
   - Invalidation conditions
7. Choose a trade → enter qty → click **"📝 Log This Trade (Paper)"**

### Mid-day Review (2–3 hours later)
8. Upload updated data files (same sidebar process)
9. **Tab 6 — 📓 Trade Journal** → open trades auto-refresh:
   - Current P&L per lot + total P&L
   - HOLD / EXIT / REVIEW suggestion with reason
   - Auto-closes if SL or Target is hit
    - Risk controls can be tuned from sidebar (**Risk Controls**) for shock handling

### End of Day
10. Trade History section shows all trades, win rate, total P&L

---

## Tabs Overview

| Tab | Purpose |
|-----|---------|
| 🏦 Institutional View | Candlestick, MAs, OI/volume signals, option chain, PCR, sentiment |
| ⚙️ Options Trader View | Payoff diagrams, Greeks, risk/reward for 10 strategies |
| 🧪 Backtesting Lab | MA crossover & PCR contrarian historical simulation |
| 🧭 Strategy Builder | Regime-based selling + futures strategy ideas |
| 🎯 Final Trade Decision | **Clean final setup: entry/SL/target/margin for both logics** |
| 📓 Trade Journal | **Log trades, track P&L, get hold/exit suggestions** |
| 📚 Learn / Help | PCR, option chain, Greeks, backtesting tutorials + risk disclaimer |

---

## Stock-Specific Support

Any NSE F&O stock can be analysed:

1. **Sidebar** → Instrument Type → **Stock** → select stock (RELIANCE, TCS, INFY, etc.)
2. Synthetic data auto-generates on first selection
3. To use real data: upload stock-specific CSVs in the same NSE format as NIFTY

### Add a new stock

1. Add to `config.yaml`:

```yaml
symbols:
  stocks:
    - MYSTOCK        # ← add here

data:
  lot_sizes:
    MYSTOCK: 500     # ← NSE lot size

  tick_sizes:
    MYSTOCK: 50      # ← strike interval
```

2. The app immediately shows it in the dropdown. Synthetic data is generated on first use.

### Data format for real stock uploads

All three files must match the NSE download format:

| File | Source | Format |
|------|--------|--------|
| Price history | NSE Historical Data page | `Date, Open, High, Low, Close, Shares Traded, Turnover (₹ Cr)` |
| Option chain | NSE Option Chain page → Download | NSE two-row header format |
| PCR | NSE / third-party | `TIME, CREATED-AT, PCR, CHG IN OI PCR, VPCR` |

---

## Trade Journal Details

**Storage:** `data/trade_journal.json` — plain JSON, human-readable  
**No database required**

### Fields stored per trade

```
id, timestamp, symbol, instrument, direction, strike,
entry_price, stop_loss, target, qty_lots, lot_size,
strategy_type, regime, structure, reason, expected_time,
margin_approx, status (Open/Closed), exit_price,
pnl_per_lot, total_pnl, suggestion, suggestion_reason, notes
```

### P&L calculation (hypothetical)
- **Buy trade:** P&L per unit = current price − entry price
- **Sell trade:** P&L per unit = entry price − current price
- **P&L per lot** = P&L per unit × lot size
- **Total P&L** = P&L per lot × qty lots

### Suggestion thresholds
| Condition | Suggestion |
|-----------|-----------|
| ≥ 100% to target | EXIT — Target Reached (auto-close) |
| ≥ 70% to target | EXIT (partial/full) |
| ≥ 30% to target | HOLD |
| Profit moves well, then reverses to trailing guard | EXIT — Trailing Stop (auto-close) |
| ≥ 100% to SL | EXIT — Stop-Loss Hit (auto-close) |
| ≥ 70% to SL | REVIEW — Near Stop-Loss |
| Gap shock + adverse move | REVIEW — Gap Shock |
| Daily portfolio P&L breaches risk cap | EXIT — Daily Risk Limit (auto-close all open trades) |
| Otherwise | HOLD / MONITOR |

### Sudden Market Change Handling (paper-trade logic)
- Gap/sudden move detection is applied from latest futures open vs previous close.
- Stop-loss exits use a slippage-aware fill model during shock conditions.
- A trailing protection rule can lock partial gains after meaningful progress.
- A daily risk kill-switch can auto-close open trades when aggregate daily loss exceeds a safety threshold.
- These thresholds are configurable in `config.yaml` and adjustable live in the sidebar.
- Sidebar actions: **Apply risk controls** (session only), **Reset to config defaults**, **Save as defaults** (writes to `config.yaml`).
- The sidebar also shows an always-visible **Active Risk Profile** summary card.

---

## Configuration (`config.yaml`)

| Key | Description |
|-----|-------------|
| `symbols.indices` | List of index instruments |
| `symbols.stocks` | List of stock instruments |
| `data.lot_sizes` | NSE lot sizes by symbol |
| `data.tick_sizes` | Strike spacing by symbol |
| `data.margin_pct.futures` | Approx futures margin % (21%) |
| `data.margin_pct.options_sell` | Approx selling margin % (20%) |
| `risk_controls.gap_shock_pct` | Gap % threshold to trigger shock handling |
| `risk_controls.base_stop_slippage_pct` | Base slippage used on stop exits |
| `risk_controls.extra_slippage_per_gap_pct` | Extra slippage multiplier during gap shocks |
| `risk_controls.max_stop_slippage_pct` | Upper cap for stop-exit slippage |
| `risk_controls.trailing_lock_pct` | Fraction of favorable move to lock via trailing stop |
| `risk_controls.trailing_activation_pct_to_target` | Target-progress % required before trailing activates |
| `risk_controls.daily_max_loss_inr` | Daily portfolio loss kill-switch threshold |
| `market.risk_free_rate` | Used in Black-Scholes |
| `strategy_defaults.pcr` | PCR signal thresholds |
| `backtesting.initial_capital` | Starting capital for backtests |

---

## How to Add a New Strategy to Strategy Builder

1. Add a case to `StrategyBuilder.generate_option_seller_strategies()` in [src/strategy_builder.py](src/strategy_builder.py)
2. Return a `StrategyIdea` dataclass instance
3. The tab auto-renders the new idea

---

## License

MIT — for educational use only.
- Risk disclaimer

---

## How to Extend the App

### Add a new underlying (e.g., BANKNIFTY)

`config.yaml` already includes BANKNIFTY. The `DataProvider` auto-generates
data for all symbols in `config.yaml → symbols.indices`. No code change needed.

### Plug in real API data

Replace the CSV-based methods in `DataProvider` with your data source:

```python
# src/data_provider.py — example stub for a real API
def get_futures_history(self, symbol, start_date=None, end_date=None):
    # Replace this block with your API call:
    # e.g., from upstox_sdk import History
    # data = History.get_ohlc(symbol, start_date, end_date)
    # return data.to_dataframe()
    pass  # Keep the same return type: pd.DataFrame with columns:
          # date, open, high, low, close, volume, oi
```

The rest of the application continues to work without changes because it
only depends on the DataFrame schema, not on where the data comes from.

### Add a new options strategy

1. Add an entry to `STRATEGY_CATALOGUE` in `src/options_view.py`.
2. Add a case to `OptionsAnalyzer.build_legs()` for the new strategy.

### Add a new backtesting strategy

Add a new method to `BacktestEngine` in `src/backtesting.py` following the
same pattern as `run_ma_crossover`:
1. Compute signals on the input DataFrame.
2. Call `self._simulate(df, ...)`.
3. Return a `BacktestResult`.
Then add the strategy to the `bt_strategy` selectbox in `app.py`.

---

## Configuration (`config.yaml`)

| Section                        | What it controls                              |
|-------------------------------|-----------------------------------------------|
| `symbols.indices`             | List of instruments to generate data for       |
| `data.lot_sizes`              | NSE lot sizes per symbol                       |
| `data.tick_sizes`             | Strike spacing (e.g., 50 for NIFTY)            |
| `market.risk_free_rate`       | Discount rate used in Black-Scholes            |
| `strategy_defaults.pcr`       | PCR signal thresholds                          |
| `backtesting.initial_capital` | Starting capital for backtests                 |
| `backtesting.transaction_cost_pct` | Cost per trade (fraction of trade value) |
| `logging.log_file`            | Path for the application log                   |

---

## Technologies Used

| Library     | Purpose                          |
|-------------|----------------------------------|
| Streamlit   | Web UI framework                 |
| Pandas      | Data manipulation                |
| NumPy       | Numerical computation            |
| SciPy       | Black-Scholes (norm distribution)|
| Plotly      | Interactive charts               |
| Matplotlib  | (available for custom plots)     |
| PyYAML      | Configuration file parsing       |

---

## Frequently Asked Questions

**Q: Can I use this to trade in real life?**
No. The app uses synthetic data and has no broker connectivity. It is strictly
for studying concepts.

**Q: The data doesn't look like real NIFTY prices — why?**
All data is generated by a mathematical model (Geometric Brownian Motion). It
has realistic statistical properties but is not actual historical NSE data.

**Q: How do I get real NSE data?**
You can obtain historical data from:
- NSE official website (bhavcopy archives, free)
- Zerodha Kite API (requires a Zerodha account)
- TrueData, Global Data Feed, or similar commercial vendors
- SEBI-authorised data distributors

**Q: Is this app safe to run on my laptop?**
Yes. It runs entirely locally and makes no network requests (except for
Streamlit's internal UI, which is also local).

---

## Architecture & UI Assessment

For a comprehensive analysis of your algo trading app's architecture, UI approach, advantages, drawbacks, and recommended improvements, see:

📄 **[ARCHITECTURE_UI_ASSESSMENT.md](ARCHITECTURE_UI_ASSESSMENT.md)**

This document covers:
- ✅ What's correct about your current approach
- ⚠️ Known drawbacks and limitations
- ✅ Key advantages
- 🎯 Recommendations for improvement (prioritized roadmap)
- 📊 Comparison: Streamlit vs. FastAPI vs. TradingView
- 🏆 Verdict: When to upgrade your architecture

**TL;DR:** Streamlit + JSON is correct for learning/prototyping. Upgrade to FastAPI + SQLite only when paper trading reaches 50+ trades with validated profitability.

---

## License

This project is provided under the MIT License for educational use.
See individual source files for the disclaimer embedded in each module.
