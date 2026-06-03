# Start a SEPARATE xbot Chrome with CDP port 9222 (does NOT close your daily Chrome).
#
# Usage: .\scripts\start_chrome_cdp.ps1
#        .\scripts\start_chrome_cdp.ps1 -RestoreSession

param(
    [switch]$RestoreSession,
    [switch]$NoProxy
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
Set-Location $projectDir

$chromePaths = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Host "[xbot] ERROR: Chrome not found." -ForegroundColor Red
    exit 1
}

$userDataDir = if ($env:CHROME_USER_DATA_DIR) {
    $env:CHROME_USER_DATA_DIR
} else {
    Join-Path $env:LOCALAPPDATA "xbot-chrome-profile"
}
# Chrome 136+ blocks CDP on the system default profile; xbot uses its own directory.
if (-not (Test-Path $userDataDir)) {
    New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null
}
$userDataMarker = $userDataDir.TrimEnd('\').ToLower()
$cdpBase = "http://127.0.0.1:9222"
$cdpUrl = "$cdpBase/json/version"
$startUrl = "https://x.com/home"
$waitSeconds = 45
$proxy = $null

$envFile = Join-Path $projectDir ".env"
if (-not $NoProxy -and (Test-Path $envFile)) {
    $lines = Get-Content $envFile
    foreach ($key in @("CHROME_PROXY", "HTTPS_PROXY", "ALL_PROXY")) {
        $line = $lines | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
        if ($line) {
            $val = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
            if ($val) { $proxy = $val; break }
        }
    }
}

$profileDir = "Default"

function Test-Cdp {
    try {
        Invoke-RestMethod -Uri $cdpUrl -TimeoutSec 2 | Out-Null
        return $true
    } catch { return $false }
}

function Test-IsXbotChromeCommandLine {
    param([string]$CommandLine)
    if (-not $CommandLine) { return $false }
    return $CommandLine.ToLower().Contains($userDataMarker)
}

function Get-XbotChromeProcesses {
    Get-CimInstance Win32_Process -Filter "name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { Test-IsXbotChromeCommandLine $_.CommandLine }
}

function Get-XbotChromeProcessCount {
    return @(Get-XbotChromeProcesses).Count
}

function Stop-XbotChromeOnly {
    $procs = @(Get-XbotChromeProcesses)
    if ($procs.Count -eq 0) { return $true }
    Write-Host "[xbot] Closing previous xbot CDP Chrome only (your daily Chrome stays open)..."
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 8; $i++) {
        Start-Sleep -Seconds 1
        if ((Get-XbotChromeProcessCount) -eq 0) {
            Start-Sleep -Seconds 1
            return $true
        }
    }
    return (Get-XbotChromeProcessCount) -eq 0
}

function Remove-StaleChromeLocks {
    if ((Get-XbotChromeProcessCount) -gt 0) { return }
    foreach ($name in @("SingletonLock", "SingletonCookie", "SingletonSocket")) {
        $path = Join-Path $userDataDir $name
        if (Test-Path $path) {
            Remove-Item $path -Force -ErrorAction SilentlyContinue
            Write-Host "[xbot] Removed stale lock: $name"
        }
    }
}

function Clear-ChromeSessionTabs {
    if ($RestoreSession) { return }
    $profilePath = Join-Path $userDataDir $profileDir
    foreach ($name in @("Last Session", "Last Tabs", "Current Session", "Current Tabs")) {
        $path = Join-Path $profilePath $name
        if (Test-Path $path) {
            Remove-Item $path -Force -ErrorAction SilentlyContinue
        }
    }
    $sessionsDir = Join-Path $profilePath "Sessions"
    if (Test-Path $sessionsDir) {
        Remove-Item "$sessionsDir\*" -Force -ErrorAction SilentlyContinue
    }
}

function Test-IsJunkTabUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $false }
    if ($Url -like 'chrome-error://*') { return $true }
    if ($Url -match '^https?://(data|default)/?$') { return $true }
    if ($Url -like 'file:///*') {
        $path = ([Uri]$Url).LocalPath
        if ($path -match '\\Google\\Chrome\\User\\?$') { return $true }
    }
    return $false
}

function Close-JunkTabs {
    try {
        $tabs = Invoke-RestMethod -Uri "$cdpBase/json/list" -TimeoutSec 3
        $closed = 0
        foreach ($tab in $tabs) {
            if ($tab.type -ne "page") { continue }
            $url = [string]$tab.url
            if ((Test-IsJunkTabUrl $url) -and $tab.id) {
                Invoke-RestMethod -Uri "$cdpBase/json/close/$($tab.id)" -TimeoutSec 3 | Out-Null
                $closed++
            }
        }
        return $closed
    } catch { return 0 }
}

function Close-JunkTabsUntilClean {
    for ($i = 0; $i -lt 6; $i++) {
        if ((Close-JunkTabs) -eq 0) { return }
        Start-Sleep -Milliseconds 400
    }
}

function Wait-CdpReady {
    for ($i = 1; $i -le $waitSeconds; $i++) {
        if (Test-Cdp) { return $i }
        if ((Get-XbotChromeProcessCount) -eq 0) {
            Write-Host ""
            Write-Host "[xbot] xbot CDP Chrome exited unexpectedly at ${i}s" -ForegroundColor Red
            return 0
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }
    return 0
}

function Build-ChromeArgumentString {
    param([string]$ProxyArg)
    $parts = @(
        "--remote-debugging-port=9222",
        "--remote-allow-origins=*",
        "--user-data-dir=`"$userDataDir`"",
        "--profile-directory=$profileDir",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        "--disable-session-crashed-bubble",
        "--disable-restore-session-state"
    )
    if ($ProxyArg) {
        $parts += "--proxy-server=$ProxyArg"
    }
    if ($RestoreSession) {
        $parts += "--restore-last-session"
    } else {
        $parts += "`"$startUrl`""
    }
    return ($parts -join " ")
}

function Start-ChromeCdp {
    param([string]$ProxyArg)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $chrome
    $psi.Arguments = Build-ChromeArgumentString -ProxyArg $ProxyArg
    $psi.UseShellExecute = $false
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Minimized
    [void][System.Diagnostics.Process]::Start($psi)
}

Write-Host "[xbot] xbot CDP profile: $userDataDir"
Write-Host "[xbot] Your daily Chrome will NOT be closed."

if (Test-Cdp) {
    Write-Host "[xbot] xbot CDP Chrome already on port 9222 (reusing)." -ForegroundColor Green
    Close-JunkTabsUntilClean
    Write-Host "[xbot] Run: python scripts/auto_browse_comment.py"
    exit 0
}

if ((Get-XbotChromeProcessCount) -gt 0) {
    Write-Host "[xbot] Found stale xbot Chrome without CDP, restarting xbot instance only..."
    if (-not (Stop-XbotChromeOnly)) {
        Write-Host "[xbot] ERROR: Cannot close stale xbot Chrome. End chrome.exe with user-data-dir xbot-chrome-profile manually." -ForegroundColor Red
        exit 1
    }
}

Remove-StaleChromeLocks
Clear-ChromeSessionTabs

if ($proxy) {
    Write-Host "[xbot] Proxy (CLI): $proxy"
} else {
    Write-Host "[xbot] WARNING: No proxy in .env" -ForegroundColor Yellow
}

Write-Host "[xbot] Starting separate xbot CDP Chrome (minimized, $startUrl)..."
Start-ChromeCdp -ProxyArg $proxy

Start-Sleep -Seconds 2
if ((Get-XbotChromeProcessCount) -eq 0) {
    Write-Host "[xbot] xbot CDP Chrome exited immediately. Retrying once..."
    Remove-StaleChromeLocks
    Start-ChromeCdp -ProxyArg $proxy
    Start-Sleep -Seconds 2
}

if ((Get-XbotChromeProcessCount) -eq 0) {
    Write-Host "[xbot] ERROR: xbot CDP Chrome keeps closing. Try:" -ForegroundColor Red
    Write-Host "  1. Open Clash/V2Ray (SOCKS5 port 1080 must be running)"
    Write-Host "  2. Run: .\scripts\start_chrome_cdp.ps1 -NoProxy"
    exit 1
}

Write-Host "[xbot] xbot CDP Chrome running ($((Get-XbotChromeProcessCount)) processes). Waiting for CDP..."
$sec = Wait-CdpReady
if ($sec -gt 0) {
    Write-Host ""
    Write-Host "[xbot] CDP ready in ${sec}s!" -ForegroundColor Green
    Close-JunkTabsUntilClean
    Write-Host "[xbot] Next: python scripts/auto_browse_comment.py"
    exit 0
}

Write-Host ""
if ((Get-XbotChromeProcessCount) -gt 0) {
    Write-Host "[xbot] ERROR: xbot CDP Chrome running but port 9222 not open." -ForegroundColor Red
} else {
    Write-Host "[xbot] ERROR: xbot CDP Chrome closed before CDP was ready." -ForegroundColor Red
}
Write-Host "[xbot] Your daily Chrome was not affected."
exit 1
