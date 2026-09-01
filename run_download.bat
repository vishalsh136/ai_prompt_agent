@echo off
:: run_download.bat — Wrapper called by Windows Task Scheduler
:: Runs the PowerShell downloader (no extra Python packages needed).

setlocal

set "APP_DIR=C:\apps\ai_prompt_agent"

cd /d "%APP_DIR%"

echo [%DATE% %TIME%] Starting NSE data download...
powershell -ExecutionPolicy Bypass -NonInteractive -File "%APP_DIR%\download_nse_data.ps1"

if %ERRORLEVEL% neq 0 (
    echo [%DATE% %TIME%] Download finished with errors. Check downloads\download.log
) else (
    echo [%DATE% %TIME%] Download completed successfully.
)

endlocal
