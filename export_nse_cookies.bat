@echo off
:: export_nse_cookies.bat
:: =========================================================
:: Guides you to export NSE session cookies from your browser
:: so the download script can access the option chain API.
::
:: After exporting, run download_nse_data.ps1 as usual.
:: The script will auto-load the cookie file.
::
:: Cookies from a browser session typically last 1-4 hours.
:: Re-export if the option chain download starts failing again.
:: =========================================================

echo.
echo =====================================================
echo  NSE Cookie Export Guide
echo =====================================================
echo.
echo Step 1: Install the "Cookie-Editor" browser extension
echo         Chrome : https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
echo         Edge   : https://microsoftedge.microsoft.com/addons/detail/cookieeditor/neaplmfkghagebokkhpjpoebhdledlfi
echo.
echo Step 2: Open your browser and go to:
echo         https://www.nseindia.com/option-chain
echo         Wait for the option chain table to fully load.
echo.
echo Step 3: Click the Cookie-Editor icon in your toolbar.
echo         Click the "Export" button (bottom of the panel).
echo         Choose "Export as Netscape" (curl-compatible format).
echo         Copy the exported text.
echo.
echo Step 4: Paste the copied cookies into this file:
echo         C:\apps\ai_prompt_agent\nse_cookies.txt
echo         (Overwrite the entire file contents with the paste)
echo.
echo Step 5: Run the download script:
echo         powershell -ExecutionPolicy Bypass -File download_nse_data.ps1
echo.
echo =====================================================
echo  The critical cookies NSE needs are:
echo    nsit       - NSE session token
echo    nseappid   - NSE app identifier
echo    _abck      - Akamai bot verification (key one!)
echo    bm_sz      - Akamai bot manager size token
echo =====================================================
echo.
echo Opening NSE option chain in your default browser...
start "" "https://www.nseindia.com/option-chain"
echo.
pause
