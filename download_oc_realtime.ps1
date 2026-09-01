# download_oc_realtime.ps1
# ============================================================
# OPTIONAL: Real-time option chain via Angel One SmartAPI
# ============================================================
# Angel One offers a FREE demat account + free SmartAPI access.
# This script fetches the LIVE option chain (CE/PE OI per strike)
# during market hours and merges it with the bhavcopy download.
#
# SETUP (one-time):
#   1. Open a free account at https://www.angelone.in/
#   2. Go to https://smartapi.angelone.in/ -> Create an App -> get API_KEY
#   3. In your Angel One app, enable TOTP:
#      Profile -> Security Settings -> Enable TOTP -> scan QR with Google Auth
#      Save the TOTP SECRET (32-char string) shown during setup.
#   4. Fill in the credentials below in nse_api_config.json (see template).
#
# Run standalone:
#   powershell -ExecutionPolicy Bypass -File download_oc_realtime.ps1
#
# Or the main cron script (download_nse_data.ps1) will auto-call this
# if nse_api_config.json exists and market is open.
# ============================================================

param(
    [string]$Symbol   = "NIFTY",
    [string]$ConfigFile = "$PSScriptRoot\nse_api_config.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DownloadDir = Join-Path $PSScriptRoot "downloads"
$DateStamp   = Get-Date -Format "yyyyMMdd"
$TimeStamp   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log {
    param([string]$Level, [string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Level] $Message"
    Write-Host $line
    Add-Content -Path (Join-Path $DownloadDir "download.log") -Value $line -Encoding UTF8
}

# ---------------------------------------------------------------------------
# Check config file
# ---------------------------------------------------------------------------
if (-not (Test-Path $ConfigFile)) {
    Write-Log "WARN" "nse_api_config.json not found. Create it with Angel One credentials."
    Write-Log "WARN" "Template: { `"api_key`": `"`", `"client_id`": `"`", `"password`": `"`", `"totp_secret`": `"`" }"
    exit 1
}

$Config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
if (-not $Config.api_key -or -not $Config.client_id) {
    Write-Log "ERROR" "nse_api_config.json is missing api_key or client_id."
    exit 1
}

# ---------------------------------------------------------------------------
# Check market hours (NSE: Mon-Fri 09:15-15:30 IST)
# ---------------------------------------------------------------------------
$Now      = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, "India Standard Time")
$DayOfWk  = $Now.DayOfWeek
$MarketOpen  = [TimeSpan]"09:15:00"
$MarketClose = [TimeSpan]"15:35:00"
$IsMarketDay = ($DayOfWk -ne "Saturday" -and $DayOfWk -ne "Sunday")
$IsMarketHrs = ($Now.TimeOfDay -ge $MarketOpen -and $Now.TimeOfDay -le $MarketClose)

Write-Log "INFO" "IST: $($Now.ToString('yyyy-MM-dd HH:mm:ss'))  Market day: $IsMarketDay  Market hours: $IsMarketHrs"

if (-not $IsMarketDay -or -not $IsMarketHrs) {
    Write-Log "WARN" "Market is closed. Real-time option chain not available. Bhavcopy (EOD) is the best source now."
    exit 0
}

# ---------------------------------------------------------------------------
# Generate TOTP (time-based one-time password) from the secret
# ---------------------------------------------------------------------------
function Get-TOTP {
    param([string]$Base32Secret)
    # Decode base32
    $alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    $bits = ""
    foreach ($c in $Base32Secret.ToUpper().ToCharArray()) {
        $idx = $alphabet.IndexOf($c)
        if ($idx -ge 0) { $bits += [Convert]::ToString($idx, 2).PadLeft(5, "0") }
    }
    $bytes = [byte[]]@()
    for ($i = 0; $i + 8 -le $bits.Length; $i += 8) {
        $bytes += [Convert]::ToByte($bits.Substring($i, 8), 2)
    }
    # HMAC-SHA1 with Unix epoch / 30
    $epoch   = [long]([DateTime]::UtcNow - [DateTime]::new(1970,1,1,0,0,0,0,"Utc")).TotalSeconds / 30
    $msg     = [byte[]]@(0,0,0,0) + [BitConverter]::GetBytes([long]$epoch)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($msg) }
    $hmac    = [System.Security.Cryptography.HMACSHA1]::new($bytes)
    $hash    = $hmac.ComputeHash($msg)
    $offset  = $hash[-1] -band 0x0F
    $code    = (($hash[$offset] -band 0x7F) -shl 24) -bor `
               (($hash[$offset+1] -band 0xFF) -shl 16) -bor `
               (($hash[$offset+2] -band 0xFF) -shl  8) -bor `
               ($hash[$offset+3] -band 0xFF)
    return ($code % 1000000).ToString("D6")
}

# ---------------------------------------------------------------------------
# Login to Angel One SmartAPI
# ---------------------------------------------------------------------------
$AngelBase = "https://apiconnect.angelone.in"
$Totp      = Get-TOTP -Base32Secret $Config.totp_secret

$LoginBody = @{
    clientcode = $Config.client_id
    password   = $Config.password
    totp       = $Totp
} | ConvertTo-Json

$LoginHeaders = @{
    "Content-Type"       = "application/json"
    "Accept"             = "application/json"
    "X-UserType"         = "USER"
    "X-SourceID"         = "WEB"
    "X-ClientLocalIP"    = "127.0.0.1"
    "X-ClientPublicIP"   = "127.0.0.1"
    "X-MACAddress"       = "00:00:00:00:00:00"
    "X-PrivateKey"       = $Config.api_key
}

Write-Log "INFO" "Logging into Angel One SmartAPI..."
$LoginResp = Invoke-WebRequest -Uri "$AngelBase/rest/auth/angelbroking/user/v1/loginByPassword" `
    -Method POST -Body $LoginBody -Headers $LoginHeaders -UseBasicParsing -TimeoutSec 20
$LoginData = $LoginResp.Content | ConvertFrom-Json

if (-not $LoginData.data.jwtToken) {
    Write-Log "ERROR" "Angel One login failed: $($LoginData.message)"
    exit 1
}

$JwtToken   = $LoginData.data.jwtToken
$FeedToken  = $LoginData.data.feedToken
Write-Log "INFO" "Angel One login successful."

# ---------------------------------------------------------------------------
# Fetch NIFTY option chain (nearest weekly expiry)
# ---------------------------------------------------------------------------
$AuthHeaders = @{
    "Authorization"      = "Bearer $JwtToken"
    "Content-Type"       = "application/json"
    "Accept"             = "application/json"
    "X-UserType"         = "USER"
    "X-SourceID"         = "WEB"
    "X-ClientLocalIP"    = "127.0.0.1"
    "X-ClientPublicIP"   = "127.0.0.1"
    "X-MACAddress"       = "00:00:00:00:00:00"
    "X-PrivateKey"       = $Config.api_key
}

# Angel One option chain endpoint returns expiry list + OI data
$OcUrl  = "$AngelBase/rest/secure/angelbroking/market/v1/optionGreeks?name=$($Symbol.ToUpper())&expirydate=&strikePrice=&optiontype="
Write-Log "INFO" "Fetching real-time option chain for $Symbol from Angel One..."

try {
    $OcResp = Invoke-WebRequest -Uri $OcUrl -Headers $AuthHeaders -UseBasicParsing -TimeoutSec 20
    $OcData = $OcResp.Content | ConvertFrom-Json

    $OutPath = Join-Path $DownloadDir "option_chain_realtime_${Symbol}_${DateStamp}.json"
    $OcData | ConvertTo-Json -Depth 15 | Set-Content -Path $OutPath -Encoding UTF8
    Write-Log "INFO" "Real-time option chain saved -> $OutPath"
    Write-Log "INFO" "Records: $($OcData.data.Count)"
}
catch {
    Write-Log "ERROR" "Angel One option chain fetch failed: $_"
    exit 1
}

Write-Log "INFO" "Real-time option chain download complete."
