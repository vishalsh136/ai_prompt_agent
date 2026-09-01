# Documentation Changelog

## 2026-08-04 21:47 — Auto-updated by doc_agent

### Changed Files

- `app.py` — functions: init_app, save_risk_controls_to_config
- `src/auto_trade_engine.py` — functions: validate_conditions, load_morning_data, update_open_trades, run_auto_trade_entry
- `src/trade_tracker.py` — classes: TradeTracker
- `config.yaml`

### Sections Updated

- app.py
- src/auto_trade_engine.py
- src/trade_tracker.py
- config.yaml

## 2026-07-17 20:00 — Auto-updated by doc_agent

### Changed Files

- `app.py` — functions: init_app
- `src/auto_trade_engine.py` — functions: validate_conditions, load_morning_data, update_open_trades, run_auto_trade_entry

### Sections Updated

- app.py
- src/auto_trade_engine.py

## 2026-07-15 22:20 — Auto-updated by doc_agent

### Changed Files

- `app.py` — functions: init_app
- `src/backtesting.py` — classes: Trade, BacktestResult, BacktestEngine

### Sections Updated

- app.py
- src/backtesting.py

## 2026-07-14 21:57 — Auto-updated by doc_agent

### Changed Files

- `app.py` — functions: init_app
- `src/institutional_view.py` — classes: InstitutionalAnalyzer
- `src/options_view.py` — classes: OptionsAnalyzer
- `src/strategy_builder.py` — classes: StrategyIdea, StrategyBuilder
- `src/backtesting.py` — classes: Trade, BacktestResult, BacktestEngine
- `src/auto_trade_engine.py` — functions: validate_conditions, load_morning_data, update_open_trades, run_auto_trade_entry
- `src/trade_tracker.py` — classes: TradeTracker
- `src/final_trade_decision.py` — functions: institutional_trade, option_seller_trade
- `src/option_buyer_strategies.py` — classes: BuyerStrategyIdea, HedgingStrategyIdea; functions: generate_buyer_strategies, generate_hedging_strategies, assess_buyer_regime
- `src/real_data_loader.py` — functions: load_option_chain, load_price_history, load_pcr_data, validate_files
- `config.yaml`
- `download_nse_data.ps1`
- `convert_cron_to_app.py` — functions: latest_json, load_json, implied_vol, convert_historical
- `src/utils.py` — functions: setup_logging, get_config, black_scholes_price, compute_greeks

### Sections Updated

- app.py
- src/institutional_view.py
- src/options_view.py
- src/strategy_builder.py
- src/backtesting.py
- src/auto_trade_engine.py
- src/trade_tracker.py
- src/final_trade_decision.py
- src/option_buyer_strategies.py
- src/real_data_loader.py
- config.yaml
- download_nse_data.ps1
- convert_cron_to_app.py
- src/utils.py

## 2026-07-14 21:54 — Auto-updated by doc_agent

### Changed Files

- `app.py` — functions: init_app
- `src/institutional_view.py` — classes: InstitutionalAnalyzer
- `src/options_view.py` — classes: OptionsAnalyzer
- `src/strategy_builder.py` — classes: StrategyIdea, StrategyBuilder
- `src/backtesting.py` — classes: Trade, BacktestResult, BacktestEngine
- `src/auto_trade_engine.py` — functions: validate_conditions, load_morning_data, update_open_trades, run_auto_trade_entry
- `src/trade_tracker.py` — classes: TradeTracker
- `src/final_trade_decision.py` — functions: institutional_trade, option_seller_trade
- `src/option_buyer_strategies.py` — classes: BuyerStrategyIdea, HedgingStrategyIdea; functions: generate_buyer_strategies, generate_hedging_strategies, assess_buyer_regime
- `src/real_data_loader.py` — functions: load_option_chain, load_price_history, load_pcr_data, validate_files
- `config.yaml`
- `download_nse_data.ps1`
- `convert_cron_to_app.py` — functions: latest_json, load_json, implied_vol, convert_historical
- `src/utils.py` — functions: setup_logging, get_config, black_scholes_price, compute_greeks

### Sections Updated

- app.py (appended)
- src/institutional_view.py (appended)
- src/options_view.py (appended)
- src/strategy_builder.py (appended)
- src/backtesting.py (appended)
- src/auto_trade_engine.py (appended)
- src/trade_tracker.py (appended)
- src/final_trade_decision.py -> ### 5.4 Institutional / Futures Strategies
- src/option_buyer_strategies.py -> ### 5.1 Option Buyer Strategies
- src/real_data_loader.py (appended)
- config.yaml (appended)
- download_nse_data.ps1 -> ## 2. Data Pipeline
- convert_cron_to_app.py -> ## 2. Data Pipeline
- src/utils.py -> ## 6. Mathematical Models
