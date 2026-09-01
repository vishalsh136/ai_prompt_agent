# download_nse_data.ps1
# Downloads 3 NSE market data files and saves them to the downloads/ folder.
#
# Sources:
#   1. Historical Index Data  ->  Yahoo Finance API  (open, no auth required)
#   2. NSE Option Chain       ->  nseindia.com API   (session-cookie approach)
#   3. Put-Call Ratio (PCR)   ->  derived from option chain (PUT OI / CALL OI)
#
# NOTE: NSE uses Akamai bot-protection on some IPs/TLS fingerprints.
#       If the option-chain download fails, the script still saves historical
#       data (from Yahoo) and a PCR stub file.
#
# Schedule via Task Scheduler: run schedule_download.bat as Administrator.
# Manual run: powershell -ExecutionPolicy Bypass -File download_nse_data.ps1

param(
    [string]$Symbol   = "NIFTY",
    [int]   $DaysBack = 365,
    [string]$Mode     = "auto"   # auto | entry | update | eod
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
$AppDir      = $PSScriptRoot
$DownloadDir = Join-Path $AppDir "downloads"
$LogFile     = Join-Path $DownloadDir "download.log"
$DateStamp   = Get-Date -Format "yyyyMMdd"
$TimeStamp   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
# Define IST time variables early so they are available throughout the script
$ISTHour     = [int](Get-Date -Format "HH")
$ISTMinute   = [int](Get-Date -Format "mm")

if (-not (Test-Path $DownloadDir)) { New-Item -ItemType Directory -Path $DownloadDir | Out-Null }

function Write-Log {
    param([string]$Level, [string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Save-Json {
    param([object]$Data, [string]$Path)
    $Data | ConvertTo-Json -Depth 20 | Set-Content -Path $Path -Encoding UTF8
}

Write-Log "INFO" ("=" * 60)
Write-Log "INFO" "NSE Data Download -- $TimeStamp"
Write-Log "INFO" "Symbol: $Symbol   Downloads: $DownloadDir"
Write-Log "INFO" ("=" * 60)

# ---------------------------------------------------------------------------
# Download 1: Historical Index Data via Yahoo Finance
# ---------------------------------------------------------------------------
# Yahoo Finance maps:  NIFTY -> ^NSEI,  BANKNIFTY -> ^NSEBANK,  FINNIFTY -> ^CNXFIN
# No API key or session cookie needed.
# ---------------------------------------------------------------------------
$HistResult = "FAILED"
try {
    $YahooTickerMap = @{
        "NIFTY"     = "%5ENSEI"
        "BANKNIFTY" = "%5ENSEBANK"
        "FINNIFTY"  = "%5ECNXFIN"
    }
    $Ticker = if ($YahooTickerMap.ContainsKey($Symbol.ToUpper())) {
        $YahooTickerMap[$Symbol.ToUpper()]
    } else {
        "$Symbol.NS"
    }

    # Use period1/period2 Unix timestamps for exact 1-year window
    # period2 = today midnight UTC, period1 = exactly 1 year ago
    $epoch     = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $epochYear = $epoch - ($DaysBack * 86400)     # DaysBack calendar days ago
    $YahooUrl  = "https://query1.finance.yahoo.com/v8/finance/chart/$Ticker" +
                 "?interval=1d&period1=${epochYear}&period2=${epoch}&includePrePost=false"

    $YahooHeaders = @{
        "User-Agent"   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        "Accept"       = "application/json"
        "Accept-Language" = "en-US,en;q=0.9"
    }

    Write-Log "INFO" "Downloading historical data for $Symbol from Yahoo Finance..."
    $Response = Invoke-WebRequest -Uri $YahooUrl -Headers $YahooHeaders -UseBasicParsing -TimeoutSec 30
    $Data = $Response.Content | ConvertFrom-Json

    $Chart     = $Data.chart.result[0]
    $Meta      = $Chart.meta
    $Timestamps = $Chart.timestamp
    $OHLCV     = $Chart.indicators.quote[0]

    # Build records array for readability
    $Records = for ($i = 0; $i -lt $Timestamps.Count; $i++) {
        $dt = [System.DateTimeOffset]::FromUnixTimeSeconds($Timestamps[$i]).LocalDateTime
        [PSCustomObject]@{
            date   = $dt.ToString("yyyy-MM-dd")
            open   = [math]::Round($OHLCV.open[$i],  2)
            high   = [math]::Round($OHLCV.high[$i],  2)
            low    = [math]::Round($OHLCV.low[$i],   2)
            close  = [math]::Round($OHLCV.close[$i], 2)
            volume = $OHLCV.volume[$i]
        }
    }

    $Output = @{
        symbol     = $Meta.symbol
        currency   = $Meta.currency
        exchange   = $Meta.exchangeName
        source     = "Yahoo Finance"
        downloaded = $TimeStamp
        records    = $Records
    }

    $OutPath = Join-Path $DownloadDir "historical_${Symbol}_${DateStamp}.json"
    Save-Json $Output $OutPath
    Write-Log "INFO" "Saved historical data -> $OutPath  ($($Records.Count) daily records)"
    $HistResult = $OutPath
}
catch {
    Write-Log "ERROR" "Historical data (Yahoo Finance) FAILED: $_"
}

# ---------------------------------------------------------------------------
# Download 1b: Live Market Snapshot -- NSE allIndices (real-time, no auth)
# ---------------------------------------------------------------------------
# Returns current spot price, advances/declines, PE, PB, DY for all indices.
# This endpoint is open and returns HTTP 200 without any authentication.
# ---------------------------------------------------------------------------
$LiveResult = "FAILED"
try {
    $UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    $CurlJar = Join-Path $DownloadDir "nse_curl_cookies.txt"

    # Warm up a minimal NSE cookie session (the OC page returns 200 which sets nsit)
    & curl.exe -s -c $CurlJar -o NUL "https://www.nseindia.com/" -H "User-Agent: $UA" 2>$null
    & curl.exe -s -b $CurlJar -c $CurlJar -o NUL "https://www.nseindia.com/option-chain" -H "User-Agent: $UA" 2>$null

    Write-Log "INFO" "Fetching live market snapshot from NSE allIndices..."
    $IdxRaw = (& curl.exe -s -b $CurlJar "https://www.nseindia.com/api/allIndices" `
        -H "User-Agent: $UA" -H "Accept: application/json" -H "Referer: https://www.nseindia.com/")
    $IdxData = $IdxRaw | ConvertFrom-Json

    # Filter to requested symbol + a few key indices always included
    $WantedKeys = @{
        "NIFTY"     = "NIFTY 50"
        "BANKNIFTY" = "NIFTY BANK"
        "FINNIFTY"  = "NIFTY FIN SERVICE"
    }
    $KeyIndex = if ($WantedKeys.ContainsKey($Symbol.ToUpper())) { $WantedKeys[$Symbol.ToUpper()] } else { $Symbol }
    $AllWanted = ($WantedKeys.Values) + @($KeyIndex) | Select-Object -Unique

    $Snapshots = $IdxData.data | Where-Object { $AllWanted -contains $_.index } | ForEach-Object {
        [PSCustomObject]@{
            index         = $_.index
            last          = $_.last
            open          = $_.open
            high          = $_.high
            low           = $_.low
            previousClose = $_.previousClose
            change        = $_.variation
            changePct     = $_.percentChange
            pe            = $_.pe
            pb            = $_.pb
            dy            = $_.dy
            advances      = $_.advances
            declines      = $_.declines
            yearHigh      = $_.yearHigh
            yearLow       = $_.yearLow
        }
    }

    $LiveOut = [PSCustomObject]@{
        timestamp = $TimeStamp
        source    = "NSE allIndices (live)"
        indices   = $Snapshots
    }

    $LivePath = Join-Path $DownloadDir "live_market_${DateStamp}.json"
    Save-Json $LiveOut $LivePath
    $Primary = $Snapshots | Where-Object { $_.index -eq $KeyIndex }
    Write-Log "INFO" "Live market saved -> $LivePath"
    Write-Log "INFO" "$KeyIndex  Last=$($Primary.last)  Chg=$($Primary.change) ($($Primary.changePct)%)  H=$($Primary.high)  L=$($Primary.low)"
    $LiveResult = $LivePath
}
catch {
    Write-Log "WARN" "Live market snapshot FAILED: $_"
}

# ---------------------------------------------------------------------------
# Download 2: Real-time Option Chain -- niftytrader.in (no auth, Next.js SSR)
# ---------------------------------------------------------------------------
# niftytrader.in renders the full option chain server-side and embeds it in
# the page as __NEXT_DATA__ JSON. One HTTP GET gives us:
#   - CE/PE OI, Change in OI, LTP, IV, volume per strike (99 strikes)
#   - Spot price, VIX, max pain, expected range
#   - Overall PCR and PCR change
# Updated throughout market hours. No auth, no cookies required.
# Fallback: NSE Archives bhavcopy (previous day EOD) when market is closed.
# ---------------------------------------------------------------------------
$OcResult  = "FAILED"
$PcrResult = "FAILED"
$UA        = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
$NtHeaders = @{
    "User-Agent"      = $UA
    "Accept"          = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    "Accept-Language" = "en-US,en;q=0.9"
    "Referer"         = "https://www.google.com"
}

$OcPageMap = @{
    "NIFTY"     = "https://www.niftytrader.in/nse-option-chain/nifty"
    "BANKNIFTY" = "https://www.niftytrader.in/nse-option-chain/banknifty"
    "FINNIFTY"  = "https://www.niftytrader.in/nse-option-chain/finnifty"
}
$OcPageUrl = if ($OcPageMap.ContainsKey($Symbol.ToUpper())) { $OcPageMap[$Symbol.ToUpper()] } else { $OcPageMap["NIFTY"] }

$NtOcHtml = $null
try {
    Write-Log "INFO" "Fetching real-time option chain from $OcPageUrl..."
    $NtResp   = Invoke-WebRequest -Uri $OcPageUrl -Headers $NtHeaders -UseBasicParsing -TimeoutSec 25
    $NtOcHtml = $NtResp.Content
    Write-Log "INFO" "Page received: $([math]::Round($NtOcHtml.Length/1KB,1)) KB"
}
catch {
    Write-Log "WARN" "niftytrader.in option chain page failed: $_"
}

if ($NtOcHtml) {
    try {
        # Extract Next.js server-side data block
        $ndMatch = [regex]::Match($NtOcHtml, '<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>')
        if (-not $ndMatch.Success) { throw "__NEXT_DATA__ block not found in page" }

        $nd   = $ndMatch.Groups[1].Value | ConvertFrom-Json
        $pp   = $nd.props.pageProps
        $spot = $pp.initialSpot
        $rows = $pp.initialOptionChainData

        if (-not $rows -or $rows.Count -eq 0) { throw "initialOptionChainData is empty" }

        # --- Save Option Chain ---
        $CronRunTime = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
        $OcOutput = [PSCustomObject]@{
            symbol         = $Symbol.ToUpper()
            timestamp      = $spot.timestamp        # niftytrader.in market data time
            cron_run_time  = $CronRunTime           # when THIS cron download happened
            cron_run_label = "${ISTHour}:${ISTMinute}"  # human-readable e.g. "10:15"
            source         = "niftytrader.in (live, no-auth)"
            source_url    = $OcPageUrl
            spot_price    = [double]$spot.last_trade_price
            open          = [double]$spot.open
            high          = [double]$spot.high
            low           = [double]$spot.low
            vix           = [double]$spot.vix_value
            vix_change    = [double]$spot.vix_change
            max_pain      = [double]$spot.max_pain
            lot_size      = [int]$spot.lot_size
            expected_range = $pp.ExpectedRange
            pcr           = [double]$pp.pcrVal
            pcr_change    = if ($pp.chngPcrValue) { [double]$pp.chngPcrValue } else { $null }
            strikes       = $rows | Sort-Object { [double]$_.strike_price } | ForEach-Object {
                [PSCustomObject]@{
                    strike      = [double]$_.strike_price
                    expiry      = $_.expiry_date
                    CE = [PSCustomObject]@{
                        oi       = [long]$_.calls_oi
                        chg_oi   = [long]$_.calls_change_oi
                        ltp      = [double]$_.calls_ltp
                        iv       = [double]$_.calls_iv
                        volume   = [long]$_.calls_volume
                        buildup  = $_.calls_builtup
                    }
                    PE = [PSCustomObject]@{
                        oi       = [long]$_.puts_oi
                        chg_oi   = [long]$_.puts_change_oi
                        ltp      = [double]$_.puts_ltp
                        iv       = [double]$_.puts_iv
                        volume   = [long]$_.puts_volume
                        buildup  = $_.puts_builtup
                    }
                    pcr         = if ($_.pcr) { [double]$_.pcr } else { $null }
                }
            }
        }

        $OcOut = Join-Path $DownloadDir "option_chain_${Symbol}_${DateStamp}.json"
        $OcOutput | ConvertTo-Json -Depth 10 | Set-Content -Path $OcOut -Encoding UTF8
        Write-Log "INFO" "Saved LIVE option chain -> $OcOut  ($($rows.Count) strikes, spot=$($spot.last_trade_price), VIX=$($spot.vix_value), MaxPain=$($spot.max_pain))"
        $OcResult = $OcOut

        # --- Save PCR (reuse the same page data -- no second request needed) ---
        $PcrPageMap2 = @{
            "NIFTY"     = "https://www.niftytrader.in/nifty-put-call-ratio"
            "BANKNIFTY" = "https://www.niftytrader.in/bank-nifty-put-call-ratio"
            "FINNIFTY"  = "https://www.niftytrader.in/fin-nifty-put-call-ratio"
        }
        $PcrUrl = if ($PcrPageMap2.ContainsKey($Symbol.ToUpper())) { $PcrPageMap2[$Symbol.ToUpper()] } else { $PcrPageMap2["NIFTY"] }

        Write-Log "INFO" "Scraping PCR intraday series from $PcrUrl..."
        $PcrResp    = Invoke-WebRequest -Uri $PcrUrl -Headers $NtHeaders -UseBasicParsing -TimeoutSec 25
        $overallMatch = [regex]::Match($PcrResp.Content, 'PCR is at ([\d.]+)')
        $overallPCR   = if ($overallMatch.Success) { [double]$overallMatch.Groups[1].Value } else { [double]$pp.pcrVal }
        $pcrSeries    = [regex]::Matches($PcrResp.Content, '"[Pp]cr"\s*:\s*([\d.]+)') | ForEach-Object { [double]$_.Groups[1].Value } | Select-Object -Unique

        $PcrData = [PSCustomObject]@{
            symbol       = $Symbol.ToUpper()
            timestamp    = $TimeStamp
            source       = "niftytrader.in (scraped)"
            pcr_overall  = $overallPCR
            pcr_current  = if ($pcrSeries.Count -gt 0) { $pcrSeries[-1] } else { [double]$pp.pcrVal }
            pcr_change   = if ($pp.chngPcrValue) { [double]$pp.chngPcrValue } else { $null }
            pcr_series   = $pcrSeries
        }
        $PcrOut = Join-Path $DownloadDir "pcr_${Symbol}_${DateStamp}.json"
        $PcrData | ConvertTo-Json -Depth 5 | Set-Content -Path $PcrOut -Encoding UTF8
        Write-Log "INFO" "Saved PCR -> $PcrOut  (Overall=$overallPCR  Series=$($pcrSeries.Count) pts)"
        $PcrResult = $PcrOut
    }
    catch {
        Write-Log "WARN" "niftytrader.in parse failed: $_"
    }
}

# Fallback: bhavcopy (previous trading day EOD) if live scrape failed
if ($OcResult -eq "FAILED") {
    Write-Log "INFO" "Falling back to NSE Archives bhavcopy (previous day EOD)..."
    $ArchiveBase = "https://nsearchives.nseindia.com/content/fo"
    try {
        $BhavDate = $null; $BhavUrl = $null
        for ($i = 1; $i -le 7; $i++) {
            $d    = (Get-Date).AddDays(-$i).ToString("yyyyMMdd")
            $url  = "$ArchiveBase/BhavCopy_NSE_FO_0_0_0_${d}_F_0000.csv.zip"
            $code = (& curl.exe -s -o NUL -w "%{http_code}" -m 8 $url -H "User-Agent: $UA")
            if ($code -eq "200") { $BhavDate = $d; $BhavUrl = $url; break }
        }
        if (-not $BhavDate) { throw "No bhavcopy found for last 7 days" }

        Write-Log "INFO" "Bhavcopy for $BhavDate -- downloading..."
        $ZipPath = Join-Path $DownloadDir "bhavcopy_${BhavDate}.zip"
        $ExtDir  = Join-Path $DownloadDir "bhav_tmp"
        & curl.exe -s -o $ZipPath $BhavUrl -H "User-Agent: $UA"
        Expand-Archive -Path $ZipPath -DestinationPath $ExtDir -Force
        $CsvFile   = Get-ChildItem "$ExtDir\*.csv" | Select-Object -First 1
        $InstrType = if (@("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY") -contains $Symbol.ToUpper()) { "IDO" } else { "STO" }
        $AllRows   = Import-Csv $CsvFile.FullName
        $OptRows   = $AllRows | Where-Object { $_.FinInstrmTp -eq $InstrType -and $_.TckrSymb -eq $Symbol.ToUpper() }
        Write-Log "INFO" "Bhavcopy: $($OptRows.Count) rows for $Symbol"

        $Index = @{}
        foreach ($row in $OptRows) { $Index["$($row.XpryDt)|$($row.StrkPric)|$($row.OptnTp)"] = $row }
        $Expiries   = $OptRows | Select-Object -ExpandProperty XpryDt -Unique | Sort-Object
        $BhavChain  = foreach ($exp in $Expiries) {
            $expStrikes = ($OptRows | Where-Object { $_.XpryDt -eq $exp } | Select-Object -ExpandProperty StrkPric -Unique | Sort-Object { [double]$_ })
            $strikData  = foreach ($k in $expStrikes) {
                $ce = $Index["$exp|$k|CE"]; $pe = $Index["$exp|$k|PE"]
                [PSCustomObject]@{
                    strike = [double]$k
                    expiry = $exp
                    CE = if ($ce) { [PSCustomObject]@{ oi=[long]$ce.OpnIntrst; chg_oi=[long]$ce.ChngInOpnIntrst; ltp=[double]$ce.LastPric; volume=[long]$ce.TtlTradgVol } } else { $null }
                    PE = if ($pe) { [PSCustomObject]@{ oi=[long]$pe.OpnIntrst; chg_oi=[long]$pe.ChngInOpnIntrst; ltp=[double]$pe.LastPric; volume=[long]$pe.TtlTradgVol } } else { $null }
                }
            }
            [PSCustomObject]@{ expiry=$exp; strikes=$strikData }
        }
        $SpotPrice = if ($OptRows) { [double]($OptRows | Select-Object -First 1 -ExpandProperty UndrlygPric) } else { 0 }
        $BhavOutput = [PSCustomObject]@{ symbol=$Symbol.ToUpper(); date=$BhavDate; source="NSE Archives bhavcopy (EOD)"; spot_price=$SpotPrice; expiries=$Expiries; chain=$BhavChain }
        $OcOut = Join-Path $DownloadDir "option_chain_${Symbol}_${DateStamp}.json"
        $BhavOutput | ConvertTo-Json -Depth 10 | Set-Content -Path $OcOut -Encoding UTF8
        Write-Log "INFO" "Bhavcopy option chain saved -> $OcOut  ($($Expiries.Count) expiries)"
        $OcResult = $OcOut
        Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $ExtDir  -Recurse -Force -ErrorAction SilentlyContinue
    }
    catch { Write-Log "ERROR" "Bhavcopy fallback FAILED: $_" }
}

# ---------------------------------------------------------------------------
# PCR Fallback: if PCR scrape failed, derive it from the option chain JSON
# ---------------------------------------------------------------------------
if ($PcrResult -eq "FAILED" -and $OcResult -ne "FAILED") {
    Write-Log "INFO" "Deriving PCR from option chain as fallback..."
    try {
        $OcJson = Get-Content $OcResult -Raw -Encoding UTF8 | ConvertFrom-Json

        # Try top-level pcr field (niftytrader.in format)
        $pcrVal = if ($OcJson.pcr -and [double]$OcJson.pcr -gt 0) { [double]$OcJson.pcr } else { $null }

        # If missing, compute from strikes (niftytrader.in format: $.strikes[])
        if (-not $pcrVal) {
            if ($OcJson.strikes -and $OcJson.strikes.Count -gt 0) {
                $callOI = 0; $putOI = 0
                foreach ($s in $OcJson.strikes) {
                    if ($s.CE) { $callOI += [long]($s.CE.oi) }
                    if ($s.PE) { $putOI  += [long]($s.PE.oi) }
                }
                if ($callOI -gt 0) { $pcrVal = [math]::Round($putOI / $callOI, 4) }
            }
        }

        # If still missing, compute from bhavcopy format: $.chain[].strikes[]
        if (-not $pcrVal) {
            if ($OcJson.chain -and $OcJson.chain.Count -gt 0) {
                $callOI = 0; $putOI = 0
                foreach ($exp in $OcJson.chain) {
                    foreach ($s in $exp.strikes) {
                        if ($s.CE) { $callOI += [long]($s.CE.oi) }
                        if ($s.PE) { $putOI  += [long]($s.PE.oi) }
                    }
                }
                if ($callOI -gt 0) { $pcrVal = [math]::Round($putOI / $callOI, 4) }
            }
        }

        if (-not $pcrVal) { $pcrVal = 1.0; Write-Log "WARN" "Could not compute PCR, using default 1.0" }

        $PcrFallback = [PSCustomObject]@{
            symbol      = $Symbol
            timestamp   = (Get-Date -Format "o")
            source      = "derived_from_option_chain"
            pcr_overall = $pcrVal
            pcr_current = $pcrVal
            pcr_change  = if ($OcJson.PSObject.Properties['pcr_change']) { $OcJson.pcr_change } else { $null }
            pcr_series  = @($pcrVal)
        }
        $PcrOut = Join-Path $DownloadDir "pcr_${Symbol}_${DateStamp}.json"
        $PcrFallback | ConvertTo-Json -Depth 5 | Set-Content -Path $PcrOut -Encoding UTF8
        Write-Log "INFO" "PCR fallback saved -> $PcrOut  (derived PCR = $pcrVal)"
        $PcrResult = $PcrOut
    }
    catch { Write-Log "WARN" "PCR fallback also failed: $_" }
}
# ---------------------------------------------------------------------------
Write-Log "INFO" "Converting JSON downloads to app-compatible CSV format..."
try {
    $ConvertOut = & python "$AppDir\convert_cron_to_app.py" 2>&1
    $ConvertOut | ForEach-Object { Write-Log "INFO" "  [convert] $_" }
    Write-Log "INFO" "CSV conversion complete."
}
catch {
    Write-Log "WARN" "CSV conversion failed: $_  (app will use previous CSVs)"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Log "INFO" ("-" * 60)
Write-Log "INFO" "Download summary:"
@(
    [PSCustomObject]@{ Name = "live_market       (NSE) "; Result = $LiveResult  }
    [PSCustomObject]@{ Name = "historical_index (Yahoo)"; Result = $HistResult }
    [PSCustomObject]@{ Name = "option_chain     (NSE)  "; Result = $OcResult   }
    [PSCustomObject]@{ Name = "pcr              (derived)"; Result = $PcrResult }
) | ForEach-Object {
    $status = if ($_.Result -eq "FAILED") { "FAILED" } else { "OK    " }
    Write-Log "INFO" "  $($_.Name)  $status  ->  $($_.Result)"
}
Write-Log "INFO" "App CSV files: $DownloadDir\app_historical_NIFTY.csv | app_option_chain_NIFTY.csv | app_pcr_NIFTY.csv"

# ---------------------------------------------------------------------------
# Auto Trade Engine
# ---------------------------------------------------------------------------
# Determine which engine mode to run based on current IST time or $Mode param
#
# Normal days  : entry at 12:00 (market has stabilised, trend is clear)
# Expiry days  : entry at 10:15 (need early entry to benefit from theta decay
#                before gamma risk dominates in last 2-3 hours)
#
# Expiry day is detected by reading the latest option_chain JSON and
# checking if its expiry date matches today.
# ---------------------------------------------------------------------------
$EngineMode = $Mode

# Detect if today is expiry day (option chain expiry == today)
$IsExpiryDay = $false
try {
    $LatestOC = Get-ChildItem "$DownloadDir\option_chain_NIFTY_*.json" |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($LatestOC) {
        $OCData = Get-Content $LatestOC.FullName -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
        $ExpiryDate = $OCData.expiry
        $TodayStr   = (Get-Date).ToString("yyyy-MM-dd")
        if ($ExpiryDate -and $ExpiryDate -eq $TodayStr) {
            $IsExpiryDay = $true
            Write-Log "INFO" "Expiry day detected (expiry=$ExpiryDate) — entry window moved to 10:15 IST"
        }
    }
} catch {
    Write-Log "WARN" "Could not detect expiry day: $_"
}

if ($EngineMode -eq "auto") {
    if ($IsExpiryDay) {
        # Expiry day: enter at 10:15 to capture full theta decay before gamma risk
        if     ($ISTHour -eq 10 -and $ISTMinute -ge 14)  { $EngineMode = "entry"  }
        elseif ($ISTHour -ge 15 -and $ISTHour -le 18)    { $EngineMode = "eod"    }
        elseif ($ISTHour -ge 11 -and $ISTHour -le 14)    { $EngineMode = "update" }
        else                                              { $EngineMode = "skip"   }
    } else {
        # Normal day: enter at 12:00 (opening range + trend fully established)
        if     ($ISTHour -eq 12 -and $ISTMinute -ge 0)   { $EngineMode = "entry"  }
        elseif ($ISTHour -ge 15 -and $ISTHour -le 18)    { $EngineMode = "eod"    }
        elseif ($ISTHour -ge 11 -and $ISTHour -le 14)    { $EngineMode = "update" }
        else                                              { $EngineMode = "skip"   }
    }
}

if ($EngineMode -ne "skip") {
    Write-Log "INFO" "Running auto trade engine in mode: $EngineMode"
    try {
        $EngineOut = & python "$AppDir\src\auto_trade_engine.py" --mode=$EngineMode 2>&1
        $EngineOut | ForEach-Object { Write-Log "INFO" "  [engine] $_" }
        Write-Log "INFO" "Auto trade engine complete."
    }
    catch {
        Write-Log "WARN" "Auto trade engine failed: $_"
    }
} else {
    Write-Log "INFO" "Auto trade engine skipped (outside trading hours or before 2nd cron)."
}

Write-Log "INFO" ("=" * 60)

# Exit code 1 only if historical data also failed (that's the critical one)
if ($HistResult -eq "FAILED") { exit 1 }
