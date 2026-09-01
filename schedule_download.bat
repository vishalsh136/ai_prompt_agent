@echo off
:: schedule_download.bat -- Register Windows Task Scheduler jobs for NSE data.
:: Run this ONCE as Administrator to create/update all scheduled tasks.
::
:: Schedule created (Mon-Fri):
::   09:15  Market open
::   10:15, 11:15, 12:15, 13:15, 14:15, 15:15  -- hourly  (via /RI repeat)
::   15:30  Market close snapshot
::   18:30  After-hours / bhavcopy available
::
:: Engine mode mapping (auto-detected in download_nse_data.ps1):
::   09:15 / 10:15 / 11:15 --> "update" mode (data download only, no new trades)
::   12:15                  --> "entry"  mode (new trade entries logged at noon)
::   13:15 / 14:15          --> "update" mode (P&L refresh)
::   15:30 / 18:30          --> "eod"    mode (close open positions)
::
:: To change times: edit /ST (start), /ET (end), /RI (interval minutes) below.

setlocal

set "APP_DIR=C:\apps\ai_prompt_agent"
set "SCRIPT=%APP_DIR%\download_nse_data.ps1"
set "CMD=powershell -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File \"%SCRIPT%\""

set "TASK1=NSE_DataDownload_Hourly"
set "TASK2=NSE_DataDownload_Close"
set "TASK3=NSE_DataDownload_EOD"

:: --- Check for Administrator rights ---
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Please run this script as Administrator.
    pause
    exit /b 1
)

:: --- Remove old tasks ---
schtasks /Delete /TN "%TASK1%" /F >nul 2>&1
schtasks /Delete /TN "%TASK2%" /F >nul 2>&1
schtasks /Delete /TN "%TASK3%" /F >nul 2>&1
:: Also remove old single-task name if it exists
schtasks /Delete /TN "NSE_DataDownload" /F >nul 2>&1

:: ---------------------------------------------------------------
:: Task 1: Hourly during market hours
::   /ST 09:15  -- first run at 09:15
::   /RI 60     -- repeat every 60 minutes
::   /ET 15:30  -- stop repeating at 15:30
::   /K         -- terminate if still running at end time
:: ---------------------------------------------------------------
schtasks /Create ^
    /TN "%TASK1%" ^
    /TR "%CMD%" ^
    /SC WEEKLY ^
    /D MON,TUE,WED,THU,FRI ^
    /ST 09:15 ^
    /RI 60 ^
    /ET 15:30 ^
    /K ^
    /RL HIGHEST ^
    /F

if %ERRORLEVEL% equ 0 (
    echo [OK] %TASK1%  -- 09:15 / 10:15 / 11:15 / 12:15 / 13:15 / 14:15 / 15:15  ^(Mon-Fri^)
) else (
    echo [FAIL] %TASK1%
)

:: ---------------------------------------------------------------
:: Task 2: Market close snapshot at 15:30
:: ---------------------------------------------------------------
schtasks /Create ^
    /TN "%TASK2%" ^
    /TR "%CMD%" ^
    /SC WEEKLY ^
    /D MON,TUE,WED,THU,FRI ^
    /ST 15:30 ^
    /RL HIGHEST ^
    /F

if %ERRORLEVEL% equ 0 (
    echo [OK] %TASK2%   -- 15:30  market close  ^(Mon-Fri^)
) else (
    echo [FAIL] %TASK2%
)

:: ---------------------------------------------------------------
:: Task 3: After-hours at 18:30 (bhavcopy is published by then)
:: ---------------------------------------------------------------
schtasks /Create ^
    /TN "%TASK3%" ^
    /TR "%CMD%" ^
    /SC WEEKLY ^
    /D MON,TUE,WED,THU,FRI ^
    /ST 18:30 ^
    /RL HIGHEST ^
    /F

if %ERRORLEVEL% equ 0 (
    echo [OK] %TASK3%      -- 18:30  after-hours / bhavcopy  ^(Mon-Fri^)
) else (
    echo [FAIL] %TASK3%
)

echo.
echo =====================================================
echo  All tasks registered.
echo  Logs: %APP_DIR%\downloads\download.log
echo.
echo  Run immediately:
echo    schtasks /Run /TN "%TASK1%"
echo.
echo  View tasks:
echo    schtasks /Query /TN "%TASK1%" /FO LIST /V
echo    schtasks /Query /TN "%TASK2%" /FO LIST /V
echo    schtasks /Query /TN "%TASK3%" /FO LIST /V
echo.
echo  Remove all:
echo    schtasks /Delete /TN "%TASK1%" /F
echo    schtasks /Delete /TN "%TASK2%" /F
echo    schtasks /Delete /TN "%TASK3%" /F
echo =====================================================

endlocal
pause
