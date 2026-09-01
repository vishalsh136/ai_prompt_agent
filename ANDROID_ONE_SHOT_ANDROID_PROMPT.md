# Android Migration Blueprint + One-Shot Prompt

## Objective
Build an Android app that reproduces the full behavior of the current Python Streamlit app, including:
- Instrument selection, real/synthetic data flow, and date filtering
- Institutional analysis, options analysis, strategy builder, buyer/hedging engine
- Final trade decision generation (institutional + option seller + option buyer + hedge)
- Trade journal logging, updates, and auto-close rules
- Backtesting engine and metrics
- Learn/help educational content

This document gives:
1. A complete functional analysis of the current app
2. A target Android architecture and implementation map
3. A one-shot prompt you can paste into an AI coding agent to generate the Android project

---

## Current App Analysis (Source of Truth)

### Runtime and stack
- UI framework: Streamlit
- Language: Python
- Data: CSV files + JSON journal, all local
- Charts: Plotly
- Math/stats: numpy, pandas, scipy
- Config: YAML

### Main modules and responsibilities
- app.py: full app shell, tabs, orchestration, user interactions
- src/data_provider.py: synthetic generation, real-data loading, unified read APIs
- src/real_data_loader.py: parser for NSE-like CSV formats
- src/institutional_view.py: moving averages, ATR, OI/price signals, max pain, IV skew, sentiment scoring
- src/options_view.py: strategy catalog, leg builder, payoff, Greeks, risk-reward
- src/strategy_builder.py: option-seller and institutional rule-based strategy ideas
- src/option_buyer_strategies.py: buyer ideas + conservative hedge ideas + regime assessment
- src/final_trade_decision.py: final tradable setup objects from all analytics
- src/trade_tracker.py: journal persistence, PnL refresh, suggestions, close/delete
- src/backtesting.py: MA crossover + PCR contrarian, simulation, metrics, regime summary
- src/utils.py: Black-Scholes, Greeks, config, formatting, logging

### App navigation
The Python app has 8 tabs:
1. Institutional View
2. Options Trader View
3. Backtesting Lab
4. Strategy Builder
5. Option Buyers and Hedging
6. Final Trade Decision
7. Trade Journal
8. Learn / Help

### Inputs and state model
Global inputs:
- Instrument type: Index or Stock
- Symbol selection
- Date range
- Real-data toggle and paths for:
  - price history CSV
  - option chain CSV
  - PCR CSV

Global state concept:
- current symbol + lot size + tick size
- synthetic-vs-real source mode
- loaded datasets (futures, option chain, PCR)
- generated analytics summaries
- persistent trade journal

### Data schema expectations

#### Futures history
Columns:
- date, open, high, low, close, volume, oi

#### Option chain
Columns:
- date, strike
- CE_LTP, CE_IV, CE_OI, CE_Volume
- PE_LTP, PE_IV, PE_OI, PE_Volume
- spot

#### PCR
Columns:
- date, pcr_oi, pcr_vol, total_ce_oi, total_pe_oi

#### Trade journal entry
Fields:
- id, timestamp, symbol, instrument, direction, strike
- entry_price, stop_loss, target
- qty_lots, lot_size
- strategy_type, regime, structure, reason, expected_time, margin_approx
- status, exit_price, pnl_per_lot, total_pnl
- suggestion, suggestion_reason, notes

### Core quant logic to preserve exactly

#### Black-Scholes
- Used for fallback pricing and analytics
- Inputs: S, K, T, r, sigma, CE/PE

#### Greeks
- delta, gamma, theta, vega

#### Institutional analytics
- SMA 20/50/200
- ATR(14)
- OI/price classification
- max pain from option-chain OI
- IV skew analysis
- OI wall detection (support/resistance)
- sentiment score from 7 rule signals
- label mapping by score:
  - >= 3: Strongly Bullish
  - >= 1: Moderately Bullish
  - 0: Neutral / Sideways
  - >= -2: Moderately Bearish
  - else: Strongly Bearish

#### Options strategy analytics
- 10 strategy catalog entries
- dynamic leg construction by strategy
- payoff at expiry over spot range
- net strategy Greeks
- risk/reward summary including breakevens

#### Backtesting
Strategies:
- MA Crossover
- PCR Contrarian

Execution model:
- signal generated on day T
- executed at next-day open (T+1)
- include tx cost + slippage

Metrics:
- total return, CAGR, max drawdown, sharpe, annualized vol
- number of trades, win rate, average win/loss, total PnL

#### Final Trade Decision
Three decision streams in final UI:
- Institutional logic setup
- Option seller setup
- Option buyer best pick + conservative hedge alternative

#### Journal suggestion logic
For each open trade, compute current price and progress:
- BUY: pnl_unit = current - entry
- SELL: pnl_unit = entry - current
- pnl_per_lot = pnl_unit * lot_size
- total_pnl = pnl_per_lot * qty_lots

Auto close:
- if stop-loss progress >= 100% -> close as SL hit
- if target progress >= 100% -> close as target hit

Suggestion buckets:
- target >= 70% -> EXIT partial/full
- stop-loss >= 70% -> REVIEW near stop-loss
- target >= 30% -> HOLD
- small positive -> HOLD
- otherwise -> MONITOR

---

## Android Target Architecture

## Recommended stack
- Kotlin
- Jetpack Compose (single-activity, navigation-compose)
- MVVM + UseCase layer + Repository pattern
- Hilt for DI
- Room for local persistence (journal + optional cache)
- DataStore Preferences for app settings (symbol, date range, real-data toggle)
- MPAndroidChart or Vico for charts in Compose
- kotlinx.serialization or Moshi for JSON
- OpenCSV/Apache Commons CSV for robust CSV parsing

## Layering
- presentation:
  - screens per tab equivalent
  - ViewModels with UiState + one-off effects
- domain:
  - entities, use-cases, rule engines
- data:
  - repositories
  - local DB and file parser datasource
  - synthetic generator datasource

## Packages
- com.yourapp.core
- com.yourapp.data
- com.yourapp.domain
- com.yourapp.feature.institutional
- com.yourapp.feature.options
- com.yourapp.feature.backtest
- com.yourapp.feature.strategybuilder
- com.yourapp.feature.buyers
- com.yourapp.feature.finaldecision
- com.yourapp.feature.journal
- com.yourapp.feature.learn

## Screen parity map
- InstitutionalScreen
- OptionsScreen
- BacktestScreen
- StrategyBuilderScreen
- BuyerHedgeScreen
- FinalDecisionScreen
- TradeJournalScreen
- LearnScreen

---

## Android Data Model Map

Create Kotlin data classes mirroring Python structures:
- FuturesBar
- OptionChainRow
- PcrRow
- SentimentResult
- StrategyIdea
- BuyerStrategyIdea
- HedgingStrategyIdea
- InstitutionalDecision
- OptionSellerDecision
- TradeEntity (Room)
- BacktestTrade
- BacktestMetrics
- BacktestResult

---

## Feature-by-Feature Build Notes

## 1) Data ingestion and generation
- Implement DataProviderRepository with:
  - getFuturesHistory(symbol, dateRange)
  - getOptionChain(symbol, date)
  - getPcr(symbol, dateRange)
  - loadRealData(paths, symbol)
  - clearRealData()
  - ensureSymbolData(symbol)
- Synthetic generation should follow same formulas and seeded random behavior.

## 2) Institutional engine
- Port methods from institutional_view.py one-to-one.
- Keep threshold constants configurable via in-app config object mirroring config.yaml.

## 3) Options engine
- Port strategy catalog and leg builder exactly.
- Keep payoff range and calculations aligned with Python behavior.

## 4) Strategy builder engine
- Port regime detection and strategy generation methods with same rule thresholds.

## 5) Buyer and hedging engine
- Port all six buyer ideas and five hedge ideas logic and text templates.

## 6) Final trade decision
- Port both institutional_trade and option_seller_trade logic.
- Add buyer+hedge selection logic used in final tab.

## 7) Journal
- Replace JSON file with Room table while retaining same fields and rules.
- Add migration helper: import existing data/trade_journal.json if present.

## 8) Backtesting
- Port simulation and metrics formulas exactly.
- Add chart views for equity and drawdown.

## 9) Learn/help
- Static markdown-like content in expandable Compose cards.

---

## Acceptance Criteria (Parity Checklist)
- All 8 tab-equivalent screens exist and are navigable.
- Real/synthetic toggle works and updates all screens.
- Final Trade Decision generates all three logic outputs.
- Journal can log, auto-update, auto-close, and manually close trades.
- Backtest produces metrics and equity/drawdown charts.
- Calculated values (for same input sample) match Python within floating-point tolerance.
- App works offline with local files and local persistence only.

---

## One-Shot Prompt (Copy/Paste)

Use the exact prompt below in your coding agent:

"""
You are an expert Android engineer. Build a full production-ready Android app in Kotlin + Jetpack Compose that is a functional parity migration of an existing Python Streamlit app called Indian Market Study Tool.

Goal:
Create the complete Android project in one pass, including architecture, data layer, domain engines, UI screens, persistence, file import parsers, and tests. The app is educational only and does NOT place real trades.

Hard requirements:
1) Tech stack:
- Kotlin, Jetpack Compose, Navigation Compose
- MVVM + Repository + UseCases
- Hilt DI
- Room DB (trade journal)
- DataStore for settings
- Kotlin Coroutines + Flow
- CSV parsing library and JSON serialization
- Chart library compatible with Compose

2) App navigation with 8 screens equivalent to these tabs:
- Institutional View
- Options Trader View
- Backtesting Lab
- Strategy Builder
- Option Buyers and Hedging
- Final Trade Decision
- Trade Journal
- Learn / Help

3) Data and config:
- Add app-level config equivalent to YAML:
  - symbols indices/stocks
  - lot sizes
  - tick sizes
  - margin percentages
  - risk free rate
  - strategy thresholds
  - backtest defaults
- Implement synthetic data generator for futures + option chain + PCR with deterministic seeded randomness
- Implement real-data import from local CSV files:
  - price history CSV
  - option chain CSV (NSE style)
  - PCR CSV
- Keep schemas equivalent to Python app

4) Domain engines (must port logic exactly):
- Black-Scholes pricing
- Greeks delta/gamma/theta/vega
- Institutional analysis:
  - SMA 20/50/200
  - ATR(14)
  - OI-price signal classification
  - max pain
  - IV skew
  - OI concentration walls
  - sentiment score and label mapping
- Options strategy engine:
  - 10 strategy catalog
  - leg builder
  - payoff at expiry
  - aggregate Greeks
  - risk/reward with breakevens
- Strategy builder engine:
  - option seller regime detection
  - option seller strategy generation
  - institutional market-structure strategy generation
- Option buyer and hedging engine:
  - buyer regime assessment
  - 6 buyer strategy ideas
  - 5 hedging/conservative strategy ideas
- Final trade decision engine:
  - institutional_trade output object
  - option_seller_trade output object
  - select best buyer idea + best hedge idea
- Backtest engine:
  - MA crossover strategy
  - PCR contrarian strategy
  - next-day-open execution
  - transaction cost + slippage
  - metrics: total return, CAGR, max DD, sharpe, annualized vol, win rate, avg win/loss, trade count
  - regime summary

5) Trade Journal:
- Room entity with fields equivalent to Python journal model
- Operations:
  - add trade
  - list/open/history filters
  - update all open trades with current data
  - auto-close on SL/target
  - generate suggestions HOLD/EXIT/REVIEW/MONITOR
  - manual close
  - delete trade
- PnL formulas exactly match Python behavior for buy/sell

6) UI requirements:
- Material 3 Compose
- State-driven UI via UiState data classes
- Loading/error/empty states on each screen
- Reusable components for cards, metrics, tables, and strategy panels
- Disclaimer banners on top and relevant screens
- Responsive layouts for phone and tablet

7) Project output:
- Complete Gradle project with modules and packages
- All source code files
- Sample seed data in assets
- Unit tests for all core engines
- Integration tests for repositories and journal operations
- README with setup, architecture, and feature map

8) Non-functional constraints:
- Offline-first, no broker or trading API integration
- Educational-only disclaimers in app and README
- Clean code, comments for complex quant formulas
- Deterministic calculations where possible

Deliverables now:
A) Full project tree
B) All Kotlin files with complete implementations (no TODO placeholders)
C) Build instructions and run instructions
D) Test instructions and expected test results

Also include a parity mapping table showing each Python module mapped to Android package/class.
"""

---

## Suggested execution order for implementation
1. Scaffold app, DI, navigation, theme
2. Add config + models
3. Implement math engines (BS/Greeks)
4. Implement data provider + parsers + synthetic generator
5. Implement institutional/options/strategy/buyer/decision engines
6. Implement journal (Room) and backtest engine
7. Build screens and wire ViewModels
8. Add tests, sample data, README

---

## Risk and migration notes
- Python pandas operations must be translated carefully to Kotlin collections/math loops.
- Floating-point tolerance should be used in parity tests.
- Option-chain parser must handle noisy CSVs (extra commas, missing values, two-row headers).
- Charting behavior can differ by library; prioritize numeric parity over visual parity.
- Keep all educational disclaimers prominent to match original intent.

---

## Done definition
Android project is considered complete when:
- It compiles and runs on emulator/device
- All core logic tests pass
- User can execute full daily workflow:
  - load data
  - review analyses
  - generate final decisions
  - log paper trades
  - refresh and manage journal
  - run backtests
- Functional outputs are aligned with Python baseline for same inputs
