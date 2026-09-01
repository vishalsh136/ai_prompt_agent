You are an expert Python developer and quantitative trading researcher.

Your task is to build a STUDY-ONLY, NON-LIVE-TRADING desktop/web application in Python that helps a learner understand trading strategies for the Indian markets. The app must NOT place real trades, connect to broker APIs for execution, or give guaranteed profit advice. It is only for analysis, education, and backtesting with historical or paper data.

High-level requirements:
1. Overall architecture:
   - Use a clean, modular structure (e.g., src/ with separate modules for data, analytics, strategies, backtesting, and UI).
   - Prefer robust, well-known libraries: pandas, numpy, matplotlib/plotly, and a simple UI framework (Streamlit, Dash, or a minimal PyQt/Tkinter interface).
   - Include clear docstrings, comments, and a README explaining how to run the app and what each part does.
   - Design everything so it is easy to extend with new strategies later.

2. Tabs / main sections:
   Tab 1: "Institutional Trader View"
   - Load and display:
     - Option chain data for Indian indices/stocks (assume data is provided via CSV/JSON or a simple API stub).
     - Put-Call Ratio (PCR) data.
     - Futures historical data (price, volume, open interest).
   - Implement analytics that mimic an institutional-style approach, for STUDY PURPOSE ONLY:
     - Trend analysis on futures (e.g., moving averages, volatility, volume/oi shifts).
     - Option chain structure: ITM/OTM concentration, max pain, skew, PCR interpretation.
     - Market sentiment summary (bullish/bearish/neutral) based on configurable rules.
   - Output:
     - A structured textual explanation of the institutional-style view:
       - What the data suggests.
       - Key levels.
       - Risk factors.
     - Visuals: charts for futures price, open interest, PCR over time, and option chain distribution.

   Tab 2: "Options Trader View"
   - Focus on options strategies for STUDY ONLY:
     - Support common strategies: covered call, vertical spreads, straddles/strangles, iron condor, etc.
     - Use the same option chain and PCR data, but interpret it from an options trader’s perspective.
   - For each selected strategy:
     - Show payoff diagrams at expiry.
     - Show Greeks (Delta, Gamma, Theta, Vega) using approximate calculations.
     - Explain in plain language:
       - When this strategy is typically used.
       - What market conditions (trend, volatility, PCR, option chain structure) make it more or less attractive.
       - Main risks and what can go wrong.
   - Allow the user to:
     - Select underlying, strike(s), expiry, and quantity.
     - See a summary of risk/reward, breakeven points, and max loss/max gain (all hypothetical).

   Tab 3: "Backtesting Lab"
   - Implement a simple backtesting engine:
     - Use historical futures and/or options data (assume CSV/JSON input).
     - Allow the user to choose:
       - Strategy type (e.g., trend-following on futures, simple options strategy rules).
       - Parameters (e.g., moving average lengths, PCR thresholds, volatility filters).
     - Run backtests over a selected date range.
   - Output:
     - Equity curve.
     - Basic metrics: total return, max drawdown, win rate, average win/loss, Sharpe-like ratio (approximate).
     - A textual explanation of:
       - How the strategy behaved in different regimes (trending, sideways, high volatility).
       - Limitations of the backtest (slippage, transaction costs, data quality, survivorship bias).
   - Emphasize that results are hypothetical and NOT predictive of future performance.

3. Data handling (Indian market context):
   - Assume data sources are abstracted behind a DataProvider class:
     - Methods like: get_option_chain(symbol, date), get_pcr(symbol, date_range), get_futures_history(symbol, date_range).
   - For now, implement these using local CSV/JSON files and mock/stub functions so the app is self-contained.
   - Make it easy to later plug in real APIs (e.g., NSE/BSE data vendors) but DO NOT implement live trading or broker connectivity.

4. Robustness and safety:
   - Add input validation and error handling:
     - Gracefully handle missing data, invalid dates, or symbols.
     - Show user-friendly error messages instead of crashing.
   - Include configuration files (e.g., config.yaml) for:
     - Default symbols (e.g., NIFTY, BANKNIFTY).
     - Data paths.
     - Strategy parameter defaults.
   - Log important events (e.g., backtest runs, parameter choices) to a log file for debugging and learning.
   - Make sure the app can run on a typical student laptop without special hardware.

5. Educational focus:
   - Every strategy and view must include:
     - Clear, plain-English explanations of what is being calculated.
     - Why institutional traders or options traders might look at these metrics.
     - What assumptions are being made.
   - Add a "Learn" or "Help" section:
     - Short tutorials on PCR, option chain basics, futures, and backtesting.
     - Warnings about risk, leverage, and why this tool is NOT a signal service or financial advice.

6. Implementation details:
   - Provide:
     - A main entry point (e.g., app.py) that launches the UI with the three tabs.
     - Separate modules:
       - data_provider.py
       - institutional_view.py
       - options_view.py
       - backtesting.py
       - utils.py (for common helpers).
   - Include sample dummy data files and show how they are used.
   - Write the code in a clean, readable style suitable for a learner to study and modify.

Finally:
- Generate the full Python code for this application, including:
  - All modules.
  - Sample data stubs.
  - Instructions in comments on how to extend it.
- Do NOT include any code that connects to real brokers or executes trades.
- Add clear disclaimers in the UI and README that this is for EDUCATIONAL PURPOSES ONLY and NOT financial advice.
