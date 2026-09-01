# Indian Market Study Tool — Complete Functionality Reference

> **Purpose of this document:** Full specification of every module, strategy,
> algorithm, data flow, and UI behaviour in the application.  
> Use this as a blueprint to rebuild the same logic in any language, framework,
> or mobile platform.

---

## 📋 IMPORTANT: Read First

**For a strategic assessment of this app's architecture, UI approach, and future roadmap, see:**

📄 **[ARCHITECTURE_UI_ASSESSMENT.md](ARCHITECTURE_UI_ASSESSMENT.md)** 
- ✅ What's correct about current approach (Streamlit + JSON + modular strategies)
- ⚠️ Drawbacks & limitations (no real-time push notifications, JSON race conditions, 30-sec polling gaps)
- ✅ Key advantages (fast iteration, audit trail, dry-run safety, multi-broker flexibility)
- 🎯 Prioritized improvement roadmap (WebSocket → SQLite → FastAPI)
- 📊 Comparison: Streamlit vs. FastAPI vs. TradingView
- 🏆 Verdict: Stay with Streamlit for learning; upgrade to FastAPI only at 50+ trades with validated edge

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Pipeline](#2-data-pipeline)
3. [Configuration](#3-configuration)
4. [Core Analytics Modules](#4-core-analytics-modules)
   - 4.1 Institutional Analyzer
   - 4.2 Options Analyzer
   - 4.3 Strategy Builder
   - 4.4 Backtesting Engine
   - 4.5 Auto Trade Engine
5. [Trading Strategies Catalogue](#5-trading-strategies-catalogue)
   - 5.1 Option Buyer Strategies
   - 5.2 Hedging / Credit Strategies
   - 5.3 Option Seller Strategies
   - 5.4 Institutional / Futures Strategies
6. [Mathematical Models](#6-mathematical-models)
7. [Data Sources & Formats](#7-data-sources--formats)
8. [UI Tabs — Feature Specification](#8-ui-tabs--feature-specification)
9. [Auto Trade Engine — Logic Flow](#9-auto-trade-engine--logic-flow)
10. [Trade Journal & P&L Tracking](#10-trade-journal--pl-tracking)
11. [Cron / Scheduler Design](#11-cron--scheduler-design)
12. [Key Constants & Thresholds](#12-key-constants--thresholds)
13. [Data Schema Reference](#13-data-schema-reference)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     STREAMLIT FRONTEND (app.py)                  │
│  Tab1  Tab2  Tab3  Tab4  Tab5  Tab6  Tab7  Tab8  Tab9           │
└────────────────────┬────────────────────────────────────────────┘
                     │ calls
┌────────────────────▼────────────────────────────────────────────┐
│                    SRC MODULES                                   │
│  InstitutionalAnalyzer  OptionsAnalyzer  StrategyBuilder        │
│  BacktestEngine  AutoTradeEngine  TradeTracker                  │
└────────────────────┬────────────────────────────────────────────┘
                     │ reads
┌────────────────────▼────────────────────────────────────────────┐
│                   DATA LAYER                                     │
│  DataProvider (synthetic fallback) + RealDataLoader (CSV/JSON)  │
└────────────────────┬────────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────────┐
│               SCHEDULED CRON (PowerShell)                        │
│  download_nse_data.ps1  →  convert_cron_to_app.py              │
│  auto_trade_engine.py   →  data/auto_trade_log.json            │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Stack
| Layer | Technology |
|---|---|
| Frontend | Streamlit (Python) |
| Language | Python 3.14 |
| Charts | Plotly (candlestick, bar, scatter, heatmap) |
| Numerics | NumPy, Pandas, SciPy |
| Scheduler | Windows Task Scheduler (schtasks) |
| Data download | PowerShell + curl.exe |
| Storage | JSON files + CSV files (no database) |

---

## 2. Data Pipeline

<!-- doc_agent:start:convert_cron_to_app.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

### Data Sources (URLs)

<!-- doc_agent:end:convert_cron_to_app.py -->

<!-- doc_agent:start:download_nse_data.ps1 -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

### Data Sources (URLs)

- `https://query1.finance.yahoo.com/v8/finance/chart/$Ticker`
- `https://www.nseindia.com/`
- `https://www.nseindia.com/option-chain`
- `https://www.nseindia.com/api/allIndices`
- `https://www.google.com`
- `https://www.niftytrader.in/nse-option-chain/nifty`
- `https://www.niftytrader.in/nse-option-chain/banknifty`
- `https://www.niftytrader.in/nse-option-chain/finnifty`

**Engine modes:**
- entry: 10:15 run  : log today's trades
- update: intraday   : refresh P&L on open positions
- eod: 15:30/18:30: close positions with final prices
<!-- doc_agent:end:download_nse_data.ps1 -->

### 2.1 Download Flow (per cron run)

```
NSE Archives (free, no auth)      Yahoo Finance (free, no auth)      niftytrader.in (free, no auth)
      ↓                                    ↓                                  ↓
Bhavcopy ZIP (F&O EOD)         Historical OHLCV (365 days)       Option chain + PCR (live)
      ↓                                    ↓                                  ↓
option_chain_NIFTY_{date}.json    historical_NIFTY_{date}.json      pcr_NIFTY_{date}.json
      +                                                              live_market_{date}.json
      ↓
convert_cron_to_app.py
      ↓
app_historical_NIFTY.csv   ← NSE-format CSV for real_data_loader
app_option_chain_NIFTY.csv ← NSE-format CSV with computed IV
app_pcr_NIFTY.csv          ← NSE PCR format with timestamps
```

### 2.2 Data Sources

| Data | URL | Auth | Format | Frequency |
|---|---|---|---|---|
| Historical OHLCV | `query1.finance.yahoo.com/v8/finance/chart/^NSEI` | None | JSON | Daily |
| Option Chain (live) | `niftytrader.in/nse-option-chain/nifty` | None | HTML (Next.js SSR) | Hourly |
| PCR intraday | `niftytrader.in/nifty-put-call-ratio` | None | HTML (Next.js SSR) | Hourly |
| Live Index | `nseindia.com/api/allIndices` | Cookies | JSON | Hourly |
| F&O Bhavcopy (EOD) | `nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip` | None | ZIP/CSV | Daily (after 18:00) |

### 2.3 Data Freshness Tags (embedded in JSON)
Every downloaded file contains:
- `timestamp` — when the market data was last updated (from source)
- `cron_run_time` — exact datetime the cron downloaded the file
- `cron_run_label` — human-readable "10:15", "09:15", etc.

---

## 3. Configuration (config.yaml)

```yaml
symbols:
  indices: [NIFTY, BANKNIFTY, FINNIFTY]
  stocks:  [RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, ...]
  default: NIFTY

data:
  lot_sizes:
    NIFTY: 25        # contracts per lot
    BANKNIFTY: 15
    FINNIFTY: 40
  tick_sizes:
    NIFTY: 50        # strike price interval
    BANKNIFTY: 100
  paths:
    futures:       data/futures_{symbol}.csv
    option_chain:  data/option_chain_{symbol}.csv
    pcr:           data/pcr_{symbol}.csv

market:
  risk_free_rate: 0.065   # RBI repo rate (used in Black-Scholes)
  dividend_yield: 0.012   # NIFTY 50 dividend yield

backtesting:
  initial_capital: 500000
  slippage_pct: 0.001     # 0.1% per trade
  transaction_cost_pct: 0.0003

logging:
  log_file: logs/app.log
  level: INFO
```

---

## 4. Core Analytics Modules

### 4.1 InstitutionalAnalyzer (`src/institutional_view.py`)

Mimics analysis run by a futures desk. All methods are deterministic and rule-based.

#### 4.1.1 `compute_moving_averages(futures_df, windows=[20,50,200])`
- Adds `sma_20`, `sma_50`, `sma_200` columns
- Each = `close.rolling(window).mean()`
- **Golden Cross**: sma_50 crosses above sma_200 → bullish
- **Death Cross**: sma_50 crosses below sma_200 → bearish

#### 4.1.2 `compute_atr(futures_df, period=14)`
- True Range = `max(H-L, |H-prev_close|, |L-prev_close|)`
- ATR = `True Range.rolling(period).mean()`
- Filter: rows where `close == 0` are excluded (holiday placeholders)
- Safety cap: ATR ≤ 3% of current price
- Added column: `atr_14`

#### 4.1.3 `compute_volume_oi_analysis(futures_df)`
Generates `oi_price_signal` column with values:

| Price | OI | Signal |
|---|---|---|
| Up (>0.3%) | Up (>0%) | `Long Buildup` — strong bullish |
| Up | Down | `Short Covering` — weak rally |
| Down (<-0.3%) | Up | `Short Buildup` — strong bearish |
| Down | Down | `Long Unwinding` — weak decline |
| Flat | Any | `No Clear Signal` |

#### 4.1.4 `generate_sentiment(futures_df, chain_df, pcr_df)`
Aggregates 7 signals into a score (-7 to +7) and label:

| Signal | Bullish condition | Contribution |
|---|---|---|
| Price vs SMA-20 | close > sma_20 | +1 |
| Price vs SMA-50 | close > sma_50 | +1 |
| MA alignment | sma_20 > sma_50 | +1 |
| OI signal | Long Buildup | +1 |
| PCR 5-day avg | > 0.8 and < 1.5 | +1 (neutral range) |
| OI wall (support) | PE wall near current | +1 |
| Max Pain | close near max pain | +1 |

**Label mapping:**
- Score ≥ 5 → `Strongly Bullish`
- Score 3–4 → `Moderately Bullish`
- Score -2 to +2 → `Neutral / Sideways`
- Score -4 to -3 → `Moderately Bearish`
- Score ≤ -5 → `Strongly Bearish`

**Key levels computed:**
- `current_price`, `sma_20`, `sma_50`, `sma_200`
- `max_pain` — strike with minimum total option buyer loss
- `ce_wall` — strike with highest Call OI (resistance)
- `pe_wall` — strike with highest Put OI (support)
- `pcr_5d_avg` — 5-day average of daily PCR

---

### 4.2 OptionsAnalyzer (`src/options_view.py`)

#### 4.2.1 `build_legs(strategy_name, strike_values, chain_df, T)`
Constructs a list of `OptionLeg` objects from the chosen strategy and strikes.
Each leg: `{type: CE|PE, action: buy|sell, strike: int, premium: float, T: float}`

#### 4.2.2 `compute_payoff(legs, spot_range)`
For each spot price in the range:
```
payoff = Σ (intrinsic_value(leg, spot) - premium) × direction_multiplier
```
where `direction_multiplier = +1` for buy, `-1` for sell.
Intrinsic: `max(spot-strike, 0)` for CE, `max(strike-spot, 0)` for PE.

#### 4.2.3 `risk_reward_summary(legs, lot_size, spot)`
Returns:
- `net_premium` — total cost/credit per unit
- `max_profit_inr` — maximum possible profit × lot_size
- `max_loss_inr` — maximum possible loss × lot_size
- `risk_reward_ratio` — max_profit / max_loss
- `breakevens` — list of spot prices where P&L = 0

#### 4.2.4 `compute_strategy_greeks(legs, spot, T, sigma)`
Aggregates Black-Scholes Greeks across all legs:
- **Delta (δ)**: Σ delta_i × direction_i
- **Gamma (Γ)**: Σ gamma_i × direction_i
- **Theta (Θ)**: Σ theta_i × direction_i (₹/day per lot)
- **Vega (ν)**: Σ vega_i × direction_i (₹ per 1% IV change)

---

### 4.3 StrategyBuilder (`src/strategy_builder.py`)

Two engines:

#### 4.3.1 Option Seller Regime Detection (`detect_option_seller_regime`)
Inputs: `futures_df, chain_df, pcr_df, sentiment`  
Computes:
- `atm_iv` — IV at ATM strike (from chain)
- `pcr_now` — current PCR
- `trend_strength_pct` — `(close - sma_50) / sma_50 × 100`
- `vol_regime` — "HIGH" if ATR/close > 1.5%, else "LOW"
- `iv_regime` — "HIGH" if atm_iv > 18%, "LOW" if < 12%, else "NORMAL"
- `ce_wall`, `pe_wall` — OI concentration strikes
- `regime` — "Sideways Range" | "Trending Up" | "Trending Down" | "High Volatility"

**Regime rules:**
```
if trend_strength > +2%  → Trending Up
if trend_strength < -2%  → Trending Down
if atm_iv > 22%          → High Volatility
else                     → Sideways Range
```

#### 4.3.2 Option Seller Strategy Generation (`generate_option_seller_strategies`)
Generates 3–5 ideas based on regime:

| Regime | Strategies suggested |
|---|---|
| Sideways Range | Short Straddle, Bull Put Spread, Bear Call Spread, Iron Condor |
| Trending Up | Bull Put Spread (OTM), Covered Call |
| Trending Down | Bear Call Spread (OTM), Protective Put Spread |
| High Volatility | Iron Condor (wide), Calendar Spread |

Each idea contains: `strategy_name`, `instrument`, `direction`, `strike_or_level`, `premium_or_price`, `entry_reason`, `stop_loss_rule`, `target_rule`, `risk_level`, `expected_time_to_target`, `fit_conditions`, `main_risks`, `assumptions`

#### 4.3.3 Market Structure Detection (`detect_market_structure`)
- `swing_high` — `high.tail(20).max()`
- `swing_low` — `low.tail(20).min()`
- `structure` — "Higher Highs / Higher Lows" | "Lower Highs / Lower Lows" | "Range-bound"
- `bias` — "Bullish" | "Bearish" | "Neutral"
- `volume_confirmation` — "Confirmed" | "Diverging" | "N/A"
- `volatility_regime` — based on ATR%

#### 4.3.4 Strategy Summary (`build_strategy_summary`)
Picks the single best strategy from all ideas and returns a compact dict:
`{suggested_strategy, entry, stop_loss, target, risk_note}`

---

### 4.4 BacktestEngine (`src/backtesting.py`)

#### 4.4.1 `run_ma_crossover(futures_df, short_window, long_window, lot_size)`
Event-driven simulation:
```
For each day:
  if sma_short crosses above sma_long AND not in position:
    BUY at next day's open
  if sma_short crosses below sma_long AND in position:
    SELL at next day's open
Each trade: pnl = (exit - entry) × lot_size - slippage - costs
```

**Metrics computed:**
- `total_return_pct` = (final_value - initial) / initial × 100
- `cagr_pct` = (final/initial)^(1/years) - 1 × 100
- `max_drawdown_pct` = max((peak - current) / peak) × 100
- `sharpe_ratio` = mean_trade_return / std_trade_return × sqrt(252)
- `win_rate_pct` = winning_trades / total_trades × 100
- `num_trades`, `avg_win_inr`, `avg_loss_inr`

#### 4.4.2 `run_pcr_strategy(futures_df, pcr_df, bullish_threshold, bearish_threshold, pcr_smoothing_days, lot_size)`
**PCR Contrarian logic:**
```
Smooth PCR = pcr_oi.rolling(smoothing_days).mean()
Buy signal  : Smooth PCR > bearish_threshold (over-fear → buy dip)
Sell signal : Smooth PCR < bullish_threshold (over-complacency → sell)
```
Same metrics as MA Crossover.

#### 4.4.3 Regime Analysis
Each backtest also produces `regime_summary` dict:
```python
{
  "Trending Up":   {"days": int, "avg_annual_return": float, "volatility": float},
  "Trending Down": {...},
  "Sideways":      {...},
}
```
Regime classification: close vs sma_50 ± 2%.

---

### 4.5 AutoTradeEngine (`src/auto_trade_engine.py`)

See Section 9 for full detail.

**Key functions:**
- `run_auto_trade_entry()` — runs at 10:15, logs 4 trades
- `update_open_trades(mode)` — runs hourly, updates P&L
- `validate_conditions(oc_df, json_path, vix, require_cron_run)` — safety checks
- `load_morning_data()` — loads latest CSVs
- `_compute_pnl(trade, exit_price)` — P&L calculation
- `_determine_exit_trigger(trade, current_ltp)` — SL/Target check

---

## 5. Trading Strategies Catalogue

### 5.1 Option Buyer Strategies

<!-- doc_agent:start:src/option_buyer_strategies.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/option_buyer_strategies.py — Option Buyer & Hedging Strategy Engine*


#### `BuyerStrategyIdea`

#### `HedgingStrategyIdea`

**`generate_buyer_strategies(chain_df, futures_df, sentiment, lot_size, config)`**
  — Generate 4–6 educational option-buying setups.

**`generate_hedging_strategies(chain_df, futures_df, sentiment, lot_size, config)`**
  — Generate 4-5 conservative strategy ideas focused on:

**`assess_buyer_regime(futures_df, chain_df, sentiment)`**
  — Determine which category of buyer strategy is most appropriate now.
<!-- doc_agent:end:src/option_buyer_strategies.py -->

Each strategy is defined with: entry logic, SL rule, target rule, IV preference, breakeven calculation, win condition, margin type (Premium only).

#### Long Call (Bullish)
- **When:** Sentiment score ≥ 2, IV < 18%
- **Entry:** Buy ATM CE at current LTP
- **SL:** 50% of premium paid
- **Target:** 100% of premium (2× entry)
- **Breakeven move:** `(premium / spot) × 100`%
- **Margin:** Premium × lot_size

#### Long Put (Bearish)
- **When:** Sentiment score ≤ -2, IV < 18%
- **Entry:** Buy ATM PE at current LTP
- **SL:** 50% of premium paid
- **Target:** 100% of premium
- **Margin:** Premium × lot_size

#### Bull Call Spread (Moderately Bullish)
- **Legs:** Buy lower strike CE + Sell higher strike CE
- **Max profit:** Strike diff − net debit
- **Max loss:** Net debit paid
- **Breakeven:** Lower strike + net debit

#### Bear Put Spread (Moderately Bearish)
- **Legs:** Buy higher strike PE + Sell lower strike PE
- **Max profit:** Strike diff − net debit
- **Max loss:** Net debit
- **Breakeven:** Higher strike − net debit

#### Long Straddle (Big Move — Direction Unknown)
- **Legs:** Buy ATM CE + Buy ATM PE
- **Cost:** CE premium + PE premium
- **Breakeven (up):** Strike + total premium
- **Breakeven (down):** Strike − total premium
- **Best when:** Event before expiry, IV < 15%

#### Long Strangle (Very Large Move)
- **Legs:** Buy OTM CE (strike + 1–2%) + Buy OTM PE (strike − 1–2%)
- **Cheaper** than straddle, requires larger move

---

### 5.2 Hedging / Credit Strategies

#### Bull Put Credit Spread ⭐ (Best win-probability)
- **When:** Bullish/neutral regime, VIX normal
- **Legs:** Sell lower-strike PE + Buy even-lower PE (wing)
- **Net credit** received upfront
- **Max gain:** Net credit × lot_size
- **Max loss:** (Strike diff − net credit) × lot_size
- **Win condition:** Spot stays above sold PE strike at expiry
- **Win probability:** ~65–75%
- **SL:** Debit to close = 2× credit received

#### Bear Call Credit Spread ⭐
- **When:** Bearish/neutral regime
- **Legs:** Sell higher-strike CE + Buy even-higher CE (wing)
- **Win condition:** Spot stays below sold CE strike

#### Iron Condor (Range-bound)
- **Legs:** Bull Put Spread + Bear Call Spread combined
- **Income:** Both credits received
- **Risk:** Defined on both sides
- **Best when:** VIX < 20, no major events, PCR 0.8–1.2

#### Covered Call
- **When:** Holding long futures, neutral to slightly bullish
- **Legs:** Long futures + Sell OTM CE
- **Income:** CE premium collected
- **Risk:** Unlimited below futures entry − CE premium

---

### 5.3 Option Seller Strategies

Generated by `StrategyBuilder.generate_option_seller_strategies()`:

#### Short Straddle
- **Legs:** Sell ATM CE + Sell ATM PE
- **Income:** Both premiums
- **Risk:** Unlimited on both sides (naked)
- **SL:** Total premium received doubles (100% loss)
- **Target:** 50% of total premium decays
- **Best when:** VIX high, range-bound, before expiry week

#### Short Strangle
- **Legs:** Sell OTM CE + Sell OTM PE
- **Wider range** than straddle
- **Less premium** but higher win probability

---

### 5.4 Institutional / Futures Strategies

<!-- doc_agent:start:src/final_trade_decision.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/final_trade_decision.py — Final Paper-Trade Decision Generator*


**`institutional_trade(futures_df, chain_df, sentiment, lot_size, config, budget_inr)`**
  — Build a clean, final institutional-style trade idea.

**`option_seller_trade(futures_df, chain_df, sentiment, option_ideas, lot_size, config, budget_inr)`**
  — Build a clean, final option-selling trade idea.

**Key constants:**

- `FUTURES_MARGIN_PCT = 0.21`
- `OPTIONS_SELL_MARGIN_PCT = 0.2`
- `INTRADAY_MARGIN_DISCOUNT = 0.4`
<!-- doc_agent:end:src/final_trade_decision.py -->

Generated by `StrategyBuilder.generate_institutional_strategies()` and `institutional_trade()`:

#### Long Futures (Bullish)
- **When:** Sentiment score ≥ 1, price > SMA-20
- **Entry:** Current close
- **SL:** Entry − 1.5 × ATR
- **Target 1:** Entry + 2.0 × ATR
- **Target 2:** Entry + 3.0 × ATR
- **Risk:Reward:** min 1:1.3

#### Short Futures (Bearish)
- **When:** Sentiment score ≤ -1
- **Entry:** Current close
- **SL:** Entry + 1.5 × ATR
- **Target 1:** Entry − 2.0 × ATR

#### ATM CE / PE (Option Alternative to Futures)
- Always computed as alternative to futures direction
- SL = 50% of ATM premium
- Target = 100% of ATM premium (2×)
- Margin = premium × lot_size (no SPAN needed)

---

## 6. Mathematical Models

<!-- doc_agent:start:src/utils.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/utils.py — Common helpers for the Indian Market Study Tool*


**`setup_logging(log_file, level)`**
  — Configure application-wide logging.

**`get_config(config_path)`**
  — Load the YAML configuration file.

**`black_scholes_price(S, K, T, r, sigma, option_type)`**
  — Calculate theoretical option price using the Black-Scholes model.

**`compute_greeks(S, K, T, r, sigma, option_type)`**
  — Calculate the four main option Greeks using Black-Scholes.

**`format_inr(value)`**
  — Format a float as Indian Rupees with compact suffixes.

**`pct_str(value, decimals)`**
  — Format a decimal fraction as a percentage string, e.g. 0.154 → '+15.40%'.

**`color_for_value(value, good_positive)`**
  — Return 'green' or 'red' depending on value sign and convention.
<!-- doc_agent:end:src/utils.py -->

### 6.1 Black-Scholes European Option Pricing

```
d1 = [ln(S/K) + (r - q + σ²/2) × T] / (σ × √T)
d2 = d1 − σ × √T

Call price = S × e^(-qT) × N(d1) − K × e^(-rT) × N(d2)
Put  price = K × e^(-rT) × N(-d2) − S × e^(-qT) × N(-d1)
```

**Parameters:**
- S = spot price
- K = strike price  
- T = time to expiry in years
- r = risk-free rate (6.5% = 0.065)
- q = dividend yield (1.2% = 0.012)
- σ = implied volatility (decimal)
- N(·) = cumulative normal distribution

### 6.2 Greeks Formulas

```
Delta (CE) = e^(-qT) × N(d1)
Delta (PE) = e^(-qT) × (N(d1) - 1)

Gamma = e^(-qT) × N'(d1) / (S × σ × √T)

Theta (CE) = [-S × N'(d1) × σ × e^(-qT) / (2√T)
              - r × K × e^(-rT) × N(d2)
              + q × S × e^(-qT) × N(d1)] / 365

Vega = S × e^(-qT) × N'(d1) × √T / 100
```

Where `N'(x)` = standard normal PDF = `(1/√2π) × e^(-x²/2)`

### 6.3 Implied Volatility (Newton-Raphson / Bisection)

```
Given: market_price, S, K, T, r, q, option_type
Find: σ such that BS_price(S, K, T, r, q, σ) = market_price

Algorithm: Bisection method
  lo = 0.001 (0.1%), hi = 20.0 (2000%)
  repeat until |BS_price(mid) - market_price| < 1e-5:
    mid = (lo + hi) / 2
    if BS_price(mid) < market_price: lo = mid
    else: hi = mid

Bounds: 1% ≤ IV ≤ 200% (else return 0)
```

### 6.4 ATR Calculation

```
TR_i = max(
  High_i - Low_i,
  |High_i - Close_{i-1}|,
  |Low_i  - Close_{i-1}|
)

ATR(14) = Simple Moving Average of TR over 14 days

Safety rules:
- Skip rows where Close = 0 (holidays)
- Cap ATR at 3% of current close
```

### 6.5 Max Pain Calculation

```
For each strike K:
  CE_pain(K) = Σ_{K' < K} CE_OI(K') × (K - K')
  PE_pain(K) = Σ_{K' > K} PE_OI(K') × (K' - K)
  total_pain(K) = CE_pain(K) + PE_pain(K)

Max Pain = argmin_K total_pain(K)
```

### 6.6 PCR Calculation

```
PCR_OI  = Total Put OI / Total Call OI
PCR_Vol = Total Put Volume / Total Call Volume

Interpretation:
PCR > 1.5 → extreme fear (contrarian bullish)
PCR 1.2-1.5 → elevated puts (mild contrarian bullish)
PCR 0.8-1.2 → balanced (neutral)
PCR 0.5-0.8 → call buying (mild contrarian bearish)
PCR < 0.5 → extreme complacency (contrarian bearish)
```

---

## 7. Data Sources & Formats

### 7.1 Option Chain JSON (downloaded from niftytrader.in)

```json
{
  "symbol": "NIFTY",
  "timestamp": "2026-07-13T16:08:04",
  "cron_run_time": "2026-07-13T10:15:22",
  "cron_run_label": "10:15",
  "spot_price": 24211.0,
  "vix": 13.28,
  "vix_change": 1.03,
  "max_pain": 24200,
  "lot_size": 65,
  "expected_range": "24080.55 ~ 24341.45",
  "pcr": 1.6221,
  "pcr_change": 29.4878,
  "strikes": [
    {
      "strike": 24200,
      "expiry": "2026-07-14T00:00:00",
      "pcr": 1.344,
      "CE": {
        "oi": 9105850,
        "chg_oi": -299585,
        "ltp": 91.4,
        "iv": 0,
        "volume": 695565325,
        "buildup": "Call Long Covering"
      },
      "PE": {
        "oi": 12237810,
        "chg_oi": 1942525,
        "ltp": 72.7,
        "iv": 0,
        "volume": 453006320,
        "buildup": "Put Writing"
      }
    }
  ]
}
```

Note: `iv` from niftytrader.in is 0 — computed by `convert_cron_to_app.py` using Black-Scholes.

### 7.2 Historical JSON (Yahoo Finance)

```json
{
  "symbol": "^NSEI",
  "currency": "INR",
  "exchange": "NSI",
  "source": "Yahoo Finance",
  "downloaded": "2026-07-13 10:15:00",
  "records": [
    {
      "date": "2025-07-14",
      "open": 25149.5,
      "high": 25151.1,
      "low": 25001.95,
      "close": 25082.3,
      "volume": 259500
    }
  ]
}
```

### 7.3 App CSV Formats (for `real_data_loader.py`)

#### Historical CSV (NSE format)
```
Date,Open,High,Low,Close,Shares Traded,Turnover (₹ Cr)
14-JUL-2025,25149.5,25151.1,25001.95,25082.3,259500,0
```
Date format: `DD-MON-YYYY` (uppercase month abbreviation)

#### Option Chain CSV (NSE format — 2 header rows)
```
CALLS,,,,,,,,,,,,,,,,,,,,,PUTS
,OI,CHNG IN OI,VOLUME,IV,LTP,CHNG,BID QTY,BID,ASK,ASK QTY,STRIKE,BID QTY,BID,ASK,ASK QTY,CHNG,LTP,IV,VOLUME,CHNG IN OI,OI,
,9105850,-299585,27822613,16.61,91.4,0,0,0,0,0,24200,0,0,0,0,0,72.7,15.78,18120253,1942525,12237810,
```
Column positions (0-indexed): 0=blank, 1=CE_OI, 2=CE_CHNG_OI, 3=CE_Vol, 4=CE_IV, 5=CE_LTP, 6=CE_CHNG, 7-10=CE Bid/Ask, 11=STRIKE, 12-15=PE Bid/Ask, 16=PE_CHNG, 17=PE_LTP, 18=PE_IV, 19=PE_Vol, 20=PE_CHNG_OI, 21=PE_OI, 22=blank

#### PCR CSV (NSE format)
```
TIME,CREATED-AT,PCR,CHG IN OI PCR,VPCR
09:15:00,2026-07-13T00:00:00,1.2726,0.0000,0
09:16:01,2026-07-13T00:00:00,1.2635,-0.0091,0
```
364 rows distributed evenly from 09:15 to 15:30.

---

## 8. UI Tabs — Feature Specification

### Tab 1 — Institutional Trader View 🏦

**Purpose:** Full market analysis dashboard mimicking a futures desk.

**Inputs:** Symbol selector, date range, option chain date selector  
**Real data:** Toggleable (loads 3 CSV files)

**Panels:**
1. **Sentiment Banner** — 4 metrics: Sentiment label, Last close ₹, ATR(14), PCR(5d avg)
2. **Candlestick chart** — OHLCV with SMA-20, SMA-50, SMA-200 overlays
3. **Volume/OI chart** — Volume bars + OI line (dual axis)
4. **PCR chart** — daily PCR series with 1.25/0.75/1.0 reference lines
5. **OI/Price signal table** — last 7 days with `oi_price_signal` column
6. **Option Chain table** — colour-coded (ATM=orange, ITM=green, OTM=red), ATM highlighted
7. **OI Distribution chart** — CE vs PE OI bar chart per strike, Max Pain vline, Spot vline
8. **IV Smile chart** — CE_IV and PE_IV vs strike
9. **Bullish/Bearish Signal lists** — from sentiment analysis
10. **Key Levels table** — current price, SMA-20/50/200, Max Pain, CE/PE OI walls
11. **Risk Factors expander** — from sentiment analysis

---

### Tab 2 — Options Trader View ⚙️

**Purpose:** Interactive strategy payoff explorer.

**Inputs:** Strategy selector (10 strategies), Days to Expiry, dynamic strike selectors  
**Outputs:**
1. **Payoff diagram** — P&L at expiry across ±25% spot range, with breakeven vlines
2. **Risk/Reward summary table** — Net premium, Max profit, Max loss, R:R ratio, Breakevens
3. **Greeks table** — Delta, Gamma, Theta (₹/day), Vega (₹/1% IV) per lot
4. **Per-leg Greeks expander**
5. **Strategy explanation** — context-aware text based on sentiment, PCR, IV

**Strike selectors auto-default:**
- `strike_buy_ce` / `strike_buy_pe` / `strike_atm` → ATM
- `strike_sell_pe` → ATM − 4 ticks
- `strike_sell_ce` → ATM + 4 ticks
- `strike_pe_wing_buy` → ATM − 8 ticks
- `strike_ce_wing_buy` → ATM + 8 ticks

---

### Tab 3 — Backtesting Lab 🧪

**Purpose:** Historical strategy simulation on synthetic data.

**Inputs:** Strategy (MA Crossover | PCR Contrarian), parameters, Lots  
**Outputs:**
1. **5 metric cards** — Total Return%, CAGR%, Max Drawdown%, Sharpe, Win Rate
2. **3 metric cards** — Total Trades, Avg Win ₹, Avg Loss ₹
3. **Equity curve chart** — portfolio value with peak line
4. **Drawdown chart** — % drawdown from peak
5. **Regime performance table** — returns by market regime
6. **Trade log table** — Entry date, Exit date, Entry ₹, Exit ₹, P&L ₹

---

### Tab 4 — Strategy Builder 🧭

**Purpose:** Auto-generate rule-based trade ideas from loaded data.

**3 engines run simultaneously:**

**A) Option Seller Engine**
- 4 regime metrics cards: Detected regime, PCR, ATM IV, Trend Strength
- OI Walls caption
- Strategy ideas table (5–8 ideas) with all details
- Detailed risks expander
- OI Distribution chart with CE/PE wall lines
- PCR chart

**B) Institutional Futures Engine**
- 4 structure metrics: Market structure, Bias, Volume confirmation, Vol regime
- Swing High/Low + ATR caption
- Futures strategy ideas table
- Market structure chart with swing levels

**C) Strategy Summary Panel**
- 3 metric cards: Market regime, Institutional structure, Top suggested strategy
- Code block: Entry / SL / Target / Risk

---

### Tab 5 — Option Buyers & Hedging 🛒

**Purpose:** Detailed presentation of buyer and hedging setups.

**A) Option Buyer Strategies (6 strategies)**
For each: expandable card with:
- Entry, SL, Max Loss, Max Gain metrics
- Strikes description, breakeven move%, win condition
- SL rule, Target rule, Margin required
- When to use, IV preference, Greeks note, Main risks
- Log trade form (qty + notes → Trade Journal)

**B) Hedging / Conservative Strategies (5 strategies)**
For each: expandable card with:
- Credit/Debit amount, Max Gain, Max Loss
- Win Probability note, Entry description, SL/Target rules
- Market conditions, IV preference, Greeks note
- Log trade form

**Buyer vs Seller vs Hedger comparison table** (expander)

---

### Tab 6 — Final Trade Decision 🎯

**Purpose:** Single clean setup from all 3 logics simultaneously.

**A) Institutional Logic**
- Sentiment score, Direction, Risk level
- Entry ₹, SL ₹, Target 1 ₹, Target 2 ₹, Margin, R:R, Expected time
- Options alternative: type, strike, premium, SL, target
- Entry reason text
- Invalidation conditions expander
- Log form with budget-auto-sized lot recommendation

**B) Option Seller Logic**
- Strategy name, Total credit, Risk level
- Credit/unit, Credit/lot, Target (50% decay), Margin
- SL rule, Target rule, Profit zone, Expected time
- Entry reason, Invalidation conditions
- Log form

**C) Option Buyer Logic**
- Best auto-selected buyer idea matching sentiment + IV
- All trade details (see Tab 5)
- Conservative hedge alternative (⭐ strategy)
- Log form for both

**Side-by-side comparison table** — all 3 logics in one row

---

### Tab 7 — Trade Journal 📓

**Purpose:** Paper-trade log management.

**Open Positions section (per-symbol filter):**
- For each open trade: Symbol, Instrument+Strike, Entry, Current P&L, HOLD/EXIT suggestion
- Suggestion icons: 🟢 HOLD, 🟡 MONITOR, 🟠 EXIT partial, 🔴 Near SL, ⛔ SL Hit, ✅ Target
- Trade details expander: SL, Target, Strategy, Regime, Timestamp, Reason, Notes
- Close trade form (manual exit price + notes)

**Trade History section:**
- Symbol filter
- Summary metrics: Total closed P&L, Open count, Closed count, Win rate
- Full history table
- Delete trade form (by ID)

---

### Tab 8 — Learn / Help 📚

5 expandable sections:
1. **PCR basics** — definition, interpretation table, NSE context
2. **Option Chain basics** — column meanings, ATM/ITM/OTM, Max Pain, IV skew
3. **Futures basics** — contract specs, MTM, OI signals, rollover
4. **Backtesting** — what it is, golden rules, 7 common pitfalls
5. **Greeks quick reference** — Delta/Gamma/Theta/Vega table with practical examples
6. **Risk Disclaimer** — 7-point educational disclaimer

---

### Tab 9 — Auto Trade Log 🤖

**Purpose:** View and manage automatically logged paper-trades.

**Manual engine controls (expander):**
- ▶ Log Today's Trades → `python src/auto_trade_engine.py --mode=entry`
- 🔄 Update P&L → `--mode=update`
- 🔒 Close All EOD → `--mode=eod`

**KPI row (7 metrics):**
Open | Closed | Win Rate | Invested ₹ | Realised P&L | Live P&L | Total P&L

**In-Progress Today section:**
Cards for each open position: Strategy icon, Instrument, Strike, Entry, Current LTP, Live P&L %, Invested  
Details expander: SL/Target, PCR, VIX, Sentiment, Regime, Validation flags

**Full trades table (filterable by Date / Strategy / Status):**
Date | Time | Strategy | Instrument | Strike | Entry ₹ | SL ₹ | Target ₹ | Exit ₹ | Invested ₹ | P&L ₹ (coloured) | P&L % | Status | VIX | PCR | Sentiment | Skip/Flag

**Strategy Performance Summary:**
Per strategy: #Trades, Open, Win Rate, SL Hits, Target Hits, Invested ₹, Realised P&L, Live P&L, Total P&L

---

## 9. Auto Trade Engine — Logic Flow

### 9.1 Trigger Schedule

| Cron Time | Mode | Action |
|---|---|---|
| 09:15 | skip | Download only, no trade logging |
| **10:15** | **entry** | **Log 4 trades for today** |
| 11:15–14:15 | update | Refresh P&L on open positions |
| 15:30 | eod | Close all open positions with EOD prices |
| 18:30 | eod | Final settlement, bhavcopy prices available |

### 9.2 Entry Logic (mode=entry)

```
1. load_morning_data()
   → loads app_historical_NIFTY.csv
   → loads app_option_chain_NIFTY-{expiry}.csv
   → loads app_pcr_NIFTY.csv
   → reads VIX from option_chain_NIFTY_{date}.json

2. validate_conditions(oc_df, oc_json, vix, require_cron_run="10:15")
   Checks:
   a. weekday (Mon-Fri)
   b. data age < 3 hours
   c. data_timestamp = today
   d. cron_run_label ≈ "10:15" (±65 min)
   e. ATM OI > 100,000 (liquidity check)
   f. VIX ≤ 25 (safety for sellers)
   
   Flags produced:
   HOLIDAY | STALE_DATA | DATA_FROM_WRONG_DATE | DATA_TOO_EARLY |
   WRONG_CRON_RUN | CRON_LABEL_MISSING | NO_OC | LOW_LIQUIDITY | HIGH_VIX

3. generate_sentiment() → sentiment score + label

4. For each of 4 strategy types:
   a. Institutional  → institutional_trade()
   b. OptionSeller   → detect_regime() + generate_ideas() + option_seller_trade()
                       [skipped if VIX > 25]
   c. OptionBuyer    → generate_buyer_strategies() + pick best
                       [skipped if sentiment score = 0]
   d. Hedging        → generate_hedging_strategies() + pick ⭐ strategy

5. For each strategy:
   - Check duplicate (id = "{date}_{symbol}_{strategy}" must not exist)
   - If HOLIDAY flag → status = "Skipped"
   - Else → status = "Open"
   - Write to data/auto_trade_log.json

6. Record in each trade:
   - entry_time, cron_run, cron_run_label
   - data_timestamp (when market data was captured)
   - validation_flags
   - spot_at_entry, sentiment, PCR, VIX, max_pain, regime
```

### 9.3 P&L Update Logic (mode=update / eod)

```
For each Open trade from today:
  1. Get current LTP from option chain
  2. Check exit trigger:
     Buyer:  SL hit if LTP ≤ stop_loss
             Target if LTP ≥ target
     Seller: SL hit if LTP ≥ stop_loss  (premium rose)
             Target if LTP ≤ target      (premium decayed)
  
  3. Compute P&L:
     Buyer:  pnl = (exit - entry) × lot_size × qty
     Seller: pnl = (entry - exit) × lot_size × qty
     pnl_pct = pnl / investment_amount × 100

  4. Update: current_ltp, current_pnl, current_pnl_pct, last_updated
  
  5. If mode=eod OR trigger hit:
     → set status = "Closed" / "SL_Hit" / "Target_Hit"
     → set exit_price, exit_time, exit_trigger
     → set final pnl_amount, pnl_pct
```

---

## 10. Trade Journal & P&L Tracking

### 10.1 Trade Record Schema

```json
{
  "id": "20260714_10:15:22",
  "timestamp": "2026-07-14 10:15:22",
  "symbol": "NIFTY",
  "instrument": "CE",
  "direction": "buy",
  "strike": 24200,
  "entry_price": 91.4,
  "stop_loss": 45.7,
  "target": 182.8,
  "qty_lots": 1,
  "lot_size": 25,
  "strategy_type": "Institutional",
  "regime": "Sideways Range",
  "structure": "Higher Highs / Higher Lows",
  "reason": "Price above 20-day SMA...",
  "expected_time": "1-2 days",
  "margin_approx": "₹2,285",
  "notes": "",
  "status": "Open",
  "total_pnl": null,
  "suggestion": "HOLD",
  "suggestion_reason": "Trade within expected range"
}
```

### 10.2 Suggestion Logic (`update_all_open`)

```
current_ltp obtained from chain_df or futures_df

For Buyers (buy):
  pnl_pct = (current - entry) / entry × 100
  if current ≤ stop_loss   → suggestion = "EXIT — Stop-Loss Hit"
  if current ≥ target       → suggestion = "EXIT — Target Reached"
  if pnl_pct < -30%         → suggestion = "REVIEW — Near Stop-Loss"
  if pnl_pct > 50%          → suggestion = "EXIT (partial/full)"
  if pnl_pct > 20%          → suggestion = "MONITOR"
  else                       → suggestion = "HOLD"

For Sellers (sell):
  pnl_pct = (entry - current) / entry × 100  (profit when premium decays)
  if pnl_pct >= 50%          → suggestion = "EXIT — Target Reached"
  if current > entry × 1.5   → suggestion = "EXIT — Stop-Loss Hit"
```

---

## 11. Cron / Scheduler Design

### 11.1 Windows Task Scheduler

3 separate tasks:
```
NSE_DataDownload_Hourly  → Mon-Fri 09:15, repeat /RI 60 /ET 15:30
NSE_DataDownload_Close   → Mon-Fri 15:30
NSE_DataDownload_EOD     → Mon-Fri 18:30
```

### 11.2 Script Call Chain

```
Task Scheduler
  → run_download.bat
    → powershell -File download_nse_data.ps1 -Mode auto
      1. Download historical (Yahoo Finance, period1/period2 timestamps)
      2. Download live market (NSE allIndices API)
      3. Download option chain (niftytrader.in Next.js SSR, extracts __NEXT_DATA__)
      4. Download PCR series (niftytrader.in PCR page)
      5. python convert_cron_to_app.py
         - Filters zero-price holiday rows
         - Computes IV via Black-Scholes bisection
         - Converts volume: raw ÷ lot_size
         - Writes NSE-format CSVs
      6. python src/auto_trade_engine.py --mode={auto-detected}
         - 09:15 → skip
         - 10:15 → entry
         - 11:15-14:15 → update
         - 15:30/18:30 → eod
```

### 11.3 Mode Auto-Detection Logic

```python
ISTHour = current_hour (local IST)
ISTMinute = current_minute

if   ISTHour == 10 and ISTMinute >= 14: mode = "entry"
elif ISTHour >= 15 and ISTHour <= 18:  mode = "eod"
elif ISTHour >= 11 and ISTHour <= 14:  mode = "update"
else:                                   mode = "skip"
```

---

## 12. Key Constants & Thresholds

### Trading Parameters
| Constant | Value | Used in |
|---|---|---|
| RISK_FREE_RATE | 6.5% | Black-Scholes, Greeks |
| DIVIDEND_YIELD | 1.2% | Black-Scholes with q |
| VIX_SELL_MAX | 25.0 | Auto trade: skip sellers |
| MIN_OI_ATM | 100,000 | Liquidity check |
| DATA_FRESH_HRS | 3.0 | Stale data flag |
| ATR_CAP_PCT | 3.0% | ATR safety cap |
| FUTURES_MARGIN_PCT | 21% | SPAN+exposure approx |
| OPTIONS_SELL_MARGIN_PCT | 20% | Short option SPAN |
| INTRADAY_MARGIN_DISCOUNT | 40% | Intraday margin |

### PCR Interpretation
| PCR | Signal | Action |
|---|---|---|
| > 1.5 | Extreme fear | Contrarian: potential buy |
| 1.2–1.5 | High puts | Mild contrarian bullish |
| 0.8–1.2 | Balanced | Neutral |
| 0.5–0.8 | Call heavy | Mild contrarian bearish |
| < 0.5 | Extreme calls | Contrarian: potential sell |

### IV Interpretation
| ATM IV | Regime | Buyer/Seller preference |
|---|---|---|
| < 12% | Low | Buy options (cheap) |
| 12–18% | Normal | Either |
| 18–22% | Elevated | Prefer selling |
| > 22% | High | Sell premium aggressively |
| > 25% | Very High | Widen spreads, risk-off |

### Sentiment Scoring
| Score | Label |
|---|---|
| 5–7 | Strongly Bullish |
| 3–4 | Moderately Bullish |
| -2 to +2 | Neutral / Sideways |
| -4 to -3 | Moderately Bearish |
| -7 to -5 | Strongly Bearish |

---

## 13. Data Schema Reference

### Auto Trade Log Record
```json
{
  "id":               "20260714_NIFTY_Institutional",
  "date":             "2026-07-14",
  "entry_time":       "10:15",
  "cron_run":         "10:15",
  "cron_run_label":   "10:15",
  "data_timestamp":   "2026-07-14T10:08:04",
  "symbol":           "NIFTY",
  "strategy_type":    "Institutional",
  "instrument":       "CE",
  "direction":        "buy",
  "strike":           "24200",
  "expiry":           "2026-07-14",
  "entry_price":      91.4,
  "stop_loss":        45.7,
  "target":           182.8,
  "qty_lots":         1,
  "lot_size":         25,
  "investment_amount": 2285.0,
  "margin_type":      "Premium",
  "spot_at_entry":    24211.0,
  "sentiment_score":  3,
  "sentiment_label":  "Strongly Bullish",
  "pcr":              1.6221,
  "vix":              13.28,
  "max_pain":         24200.0,
  "regime":           "Sideways Range",
  "reason":           "Price above 20-day SMA...",
  "validation_flags": ["CRON_LABEL_MISSING"],
  "status":           "Open",
  "skip_reason":      null,
  "current_ltp":      91.4,
  "current_pnl":      0.0,
  "current_pnl_pct":  0.0,
  "last_updated":     "10:15",
  "exit_price":       null,
  "exit_time":        null,
  "exit_trigger":     null,
  "pnl_amount":       null,
  "pnl_pct":          null
}
```

### Internal DataProvider Schema

**futures_df columns:**
`date (datetime), open, high, low, close, volume, oi (all float/int)`

**chain_df columns:**
`date (datetime), strike (int), CE_LTP, CE_IV, CE_OI, CE_Volume, PE_LTP, PE_IV, PE_OI, PE_Volume (float/int), spot (float)`

**pcr_df columns:**
`date (datetime), pcr_oi (float), pcr_vol (float), total_ce_oi (int), total_pe_oi (int)`

---

## Build Notes for Mobile / Other Apps

### Minimum viable data requirements
1. **OHLCV** — 200+ days daily candles (for SMA-200)
2. **Option Chain** — CE/PE OI + LTP for 50+ strikes, current expiry
3. **PCR** — at least current day's value; ideally 5+ days for averaging

### Offline / mobile-friendly simplifications
- Replace scipy for Black-Scholes: implement pure N(d1) using error function `erf`
- Replace pandas: use simple arrays/dicts for OHLCV
- PCR + sentiment can run with just 5 fields: `spot, atm_ce_oi, atm_pe_oi, pcr, vix`
- Full option chain needed only for Max Pain calculation

### API endpoints used (all free, no auth)
```
Yahoo Finance (historical):
  GET https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI
      ?interval=1d&period1={unix_ts}&period2={unix_ts}

NSE Live Index:
  GET https://www.nseindia.com/api/allIndices
  (requires NSE cookies — set via browser session)

niftytrader.in (option chain, live, no auth):
  GET https://www.niftytrader.in/nse-option-chain/nifty
  Extract: window.__NEXT_DATA__.props.pageProps.initialOptionChainData

niftytrader.in (PCR series, no auth):
  GET https://www.niftytrader.in/nifty-put-call-ratio
  Extract: regex '"[Pp]cr":\s*([\d.]+)'

NSE Archives (EOD bhavcopy, no auth):
  GET https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip
```

---

*Last updated: 2026-07-13 | Version: 1.0 | This document covers the complete codebase as of the above date.*

<!-- doc_agent:start:app.py -->

> *Auto-updated by doc_agent on 2026-08-04 21:47*

### Current UI Tabs

1. `🏦 Institutional View`
2. `⚙️ Options Trader View`
3. `🧪 Backtesting Lab`
4. `🧭 Strategy Builder`
5. `🛒 Option Buyers & Hedging`
6. `🎯 Final Trade Decision`
7. `📓 Trade Journal`
8. `📚 Learn / Help`
9. `🤖 Auto Trade Log`
10. `📊 Mutual Fund Tracker`
11. `🎰 Market Microstructure`
12. `🤖 Logic Optimization Agent`
13. `🚀 Live Algo Trade`
14. `🤖 Auto Algo Trader`

**Key action buttons:**
- `Load Real Data`
- `🔄`
- `▶ Run Backtest`
- `Generate Groww Ticket (Institutional)`
- `Generate Groww Ticket (Option Seller)`
- `Generate Groww Ticket (Buyer)`
- `Generate Groww Ticket (Hedge)`
- `Delete Trade`
- `Delete selected strategy records`
- `📊 Run Comparison`
<!-- doc_agent:end:app.py -->

<!-- doc_agent:start:src/institutional_view.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/institutional_view.py — Institutional-style market analytics*


#### `InstitutionalAnalyzer`
> Runs institutional-style analytics on futures and options data.

**Public methods:**

| Method | Args | Description |
|---|---|---|
| `compute_moving_averages()` | `futures_df, windows` | Add Simple Moving Average (SMA) columns to the futures DataF… |
| `compute_atr()` | `futures_df, period` | Compute the Average True Range (ATR). |
| `compute_volume_oi_analysis()` | `futures_df` | Classify each day's price + volume + OI combination. |
| `compute_max_pain()` | `chain_df` | Calculate the Max Pain strike price. |
| `compute_iv_skew()` | `chain_df` | Analyse the implied volatility skew. |
| `compute_oi_concentration()` | `chain_df` | Find the strikes with highest call and put OI — these often … |
| `generate_sentiment()` | `futures_df, chain_df, pcr_df` | Aggregate multiple signals into a single market sentiment su… |
<!-- doc_agent:end:src/institutional_view.py -->

<!-- doc_agent:start:src/options_view.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/options_view.py — Options strategy analytics for the Study Tool*


#### `OptionsAnalyzer`
> Computes payoff diagrams, Greeks, and explanations for options strategies.

**Public methods:**

| Method | Args | Description |
|---|---|---|
| `build_legs()` | `strategy_name, strikes, chain_df, T` | Build a list of option legs for the given strategy and strik… |
| `compute_payoff()` | `legs, spot_range` | Calculate strategy P&L at expiry across a range of spot pric… |
| `compute_strategy_greeks()` | `legs, spot, T, sigma` | Calculate aggregate Greeks for the strategy at the current s… |
| `risk_reward_summary()` | `legs, lot_size, spot` | Calculate max profit, max loss, and breakeven points. |
| `get_strategy_explanation()` | `strategy_name, sentiment_label, pcr_5d_avg, atm_iv` | Generate a plain-English explanation of the strategy and its |

**`STRATEGY_CATALOGUE` keys (10 strategies):**
`Long Call`, `Long Put`, `Covered Call`, `Bull Call Spread`, `Bear Put Spread`, `Long Straddle`, `Long Strangle`, `Short Straddle`, `Short Strangle`, `Iron Condor`

**Key constants:**

- `STRATEGY_CATALOGUE = {'Long Call': {'legs': 1, 'description': 'Buy one call option. Profit when spot `
<!-- doc_agent:end:src/options_view.py -->

<!-- doc_agent:start:src/strategy_builder.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/strategy_builder.py — Real-World Strategy Builder (study-only)*


#### `StrategyIdea`

#### `StrategyBuilder`
> Generate learning-focused rule-based strategy ideas from market features.

**Public methods:**

| Method | Args | Description |
|---|---|---|
| `detect_option_seller_regime()` | `futures_df, chain_df, pcr_df, sentiment` | Detect a practical regime for option selling strategies. |
| `generate_option_seller_strategies()` | `chain_df, regime` | Generate 2-4 educational option-selling strategies based on … |
| `detect_market_structure()` | `futures_df` | Detect HH/HL or LL/LH structure with volume and volatility c… |
| `generate_institutional_strategies()` | `structure, chain_df` | Generate educational futures/instrumental direction strategi… |
| `build_strategy_summary()` | `regime, option_ideas, structure, fut_ideas` | Build compact one-block summary for quick learning review. |
| `to_dataframe()` | `ideas` | — |
<!-- doc_agent:end:src/strategy_builder.py -->

<!-- doc_agent:start:src/backtesting.py -->

> *Auto-updated by doc_agent on 2026-07-15 22:20*

*src/backtesting.py — Simple historical backtesting engine*


#### `Trade`
> Represents a single completed round-trip trade.

#### `BacktestResult`
> Holds all outputs of a backtest run.

#### `BacktestEngine`
> Simple single-instrument futures backtesting engine.

**Public methods:**

| Method | Args | Description |
|---|---|---|
| `run_ma_crossover()` | `futures_df, short_window, long_window, initial_capital, lot_size` | Run a simple moving-average crossover strategy on futures. |
| `run_pcr_strategy()` | `futures_df, pcr_df, bullish_threshold, bearish_threshold, pcr_smoothing_days, initial_capital, lot_size` | Run a PCR-based contrarian strategy. |
| `compute_metrics()` | `equity_df, trades, initial_capital, risk_free_rate` | Calculate standard performance metrics for a completed backt… |
| `identify_regimes()` | `signals_df, equity_df` | Classify the backtest period into market regimes and analyse |
| `run_rsi_strategy()` | `futures_df, rsi_period, oversold, overbought, initial_capital, lot_size` | RSI mean-reversion strategy. |
| `run_bollinger_strategy()` | `futures_df, bb_period, num_std, initial_capital, lot_size` | Bollinger Band breakout / reversion strategy. |
| `run_macd_strategy()` | `futures_df, fast, slow, signal, initial_capital, lot_size` | MACD (Moving Average Convergence Divergence) signal crossove… |
| `compute_extended_metrics()` | `equity_df, trades, initial_capital, risk_free_rate` | Additional risk-adjusted performance metrics beyond the basi… |
<!-- doc_agent:end:src/backtesting.py -->

<!-- doc_agent:start:src/auto_trade_engine.py -->

> *Auto-updated by doc_agent on 2026-08-04 21:47*

*src/auto_trade_engine.py*


**`validate_conditions(oc_df, json_path, vix, require_cron_run)`**
  — Run all pre-trade safety checks.

**`load_morning_data()`**
  — Load the latest cron-converted CSV files. Returns (hist, oc, pcr, vix, json_path).

**`update_open_trades(mode)`**
  — Update all open trades from today with latest prices and P&L.

**`run_auto_trade_entry()`**
  — Run at 10:15 — log today's auto-trade entries for all 4 strategies.

**Key constants:**

- `ROOT = Attribute(value=Attribute(value=Call(func=Name(id='Path', ctx=Load()), args=[Nam`
- `DOWNLOADS = BinOp(left=Name(id='ROOT', ctx=Load()), op=Div(), right=Constant(value='download`
- `LOG_PATH = BinOp(left=BinOp(left=Name(id='ROOT', ctx=Load()), op=Div(), right=Constant(valu`
- `SYMBOL = 'NIFTY'`
- `LOT_SIZE = 65`
- `BUDGET = 150000`
- `VIX_SELL_MAX = 25.0`
- `MIN_OI_ATM = 100000`
<!-- doc_agent:end:src/auto_trade_engine.py -->

<!-- doc_agent:start:src/trade_tracker.py -->

> *Auto-updated by doc_agent on 2026-08-04 21:47*

*src/trade_tracker.py — Paper-Trade Journal & P&L Tracker*


#### `TradeTracker`
> Manages the paper-trade journal stored in data/trade_journal.json.

**Public methods:**

| Method | Args | Description |
|---|---|---|
| `get_risk_controls()` | `—` | Return currently active risk-control values. |
| `set_risk_controls()` | `overrides` | Apply runtime risk-control overrides (does not edit config.y… |
| `add_trade()` | `symbol, instrument, direction, strike, entry_price, stop_loss, target, qty_lots, lot_size, strategy_type, regime, structure, reason, expected_time, margin_approx, notes` | Log a new paper trade. Returns the trade ID. |
| `load_trades()` | `symbol_filter` | Return all trades, optionally filtered by symbol. |
| `get_open_trades()` | `symbol` | Return only open (active) trades. |
| `get_history_df()` | `symbol` | Return all trades as a tidy DataFrame. |
| `update_all_open()` | `chain_df, futures_df, symbol` | Recalculate P&L and generate HOLD/EXIT/REVERSE for every ope… |
| `close_trade()` | `trade_id, exit_price, notes` | Manually close a trade at exit_price. |
| `delete_trade()` | `trade_id` | Remove a trade from the journal (use carefully). |

**Key constants:**

- `JOURNAL_PATH = Call(func=Name(id='Path', ctx=Load()), args=[Constant(value='data/trade_journal.`
- `GAP_SHOCK_PCT = 1.2`
- `BASE_STOP_SLIPPAGE_PCT = 0.2`
- `EXTRA_SLIPPAGE_PER_GAP_PCT = 0.25`
- `MAX_STOP_SLIPPAGE_PCT = 3.0`
- `TRAILING_LOCK_PCT = 0.35`
- `TRAILING_ACTIVATION_PCT_TO_TARGET = 40`
- `DAILY_MAX_LOSS_INR = -15000`
<!-- doc_agent:end:src/trade_tracker.py -->

<!-- doc_agent:start:src/real_data_loader.py -->

> *Auto-updated by doc_agent on 2026-07-14 21:57*

*src/real_data_loader.py — Parse real NSE market data files*


**`load_option_chain(path)`**
  — Parse an NSE option chain CSV into a tidy DataFrame.

**`load_price_history(path)`**
  — Parse NSE NIFTY 50 historical data CSV.

**`load_pcr_data(path, option_chain_df)`**
  — Load PCR data.

**`validate_files(futures_path, chain_path, pcr_path)`**
  — Check which real data files exist and are readable.

**Key constants:**

- `COL_NAMES = ['_row', 'CE_OI', 'CE_CHNG_OI', 'CE_Volume', 'CE_IV', 'CE_LTP', 'CE_CHNG', 'CE_B`
- `NUMERIC = ['CE_OI', 'CE_CHNG_OI', 'CE_Volume', 'CE_IV', 'CE_LTP', 'CE_BID', 'CE_ASK', 'str`
<!-- doc_agent:end:src/real_data_loader.py -->

<!-- doc_agent:start:config.yaml -->

> *Auto-updated by doc_agent on 2026-08-04 21:47*

### Current Configuration Values

- **Default symbol**: `NIFTY`
- **Indices**: NIFTY, BANKNIFTY, FINNIFTY
- **Stocks (sample)**: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK...
- **Risk-free rate**: 0.07
- **Dividend yield**: N/A
- **Initial backtest capital**: ₹1,000,000

**Lot sizes:**

| NIFTY | 65 |
| BANKNIFTY | 15 |
| FINNIFTY | 40 |
| RELIANCE | 250 |
| TCS | 150 |
| INFY | 300 |
| HDFCBANK | 550 |
| ICICIBANK | 700 |
| SBIN | 1500 |
| WIPRO | 1500 |
| BAJFINANCE | 125 |
| TATASTEEL | 5500 |
| ADANIENT | 625 |
<!-- doc_agent:end:config.yaml -->
