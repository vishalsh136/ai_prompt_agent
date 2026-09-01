https://www.nseindia.com/reports-indices-historical-index-data

https://www.niftytrader.in/nifty-put-call-ratio

https://www.nseindia.com/option-chain

schtasks /Run /TN "NSE_DataDownload_Hourly"          ← run now
schtasks /Query /TN "NSE_DataDownload_Hourly" /FO LIST /V  ← view details


# Run cronjob to download all files
powershell -ExecutionPolicy Bypass -File "C:\apps\ai_prompt_agent\download_nse_data.ps1"


# Log today's trades (run once at 10:15)
python src/auto_trade_engine.py --mode=entry

# Refresh live P&L on open positions (run hourly)
python src/auto_trade_engine.py --mode=update

# Close all open positions at end of day (run at 15:30 / 18:30)
python src/auto_trade_engine.py --mode=eod