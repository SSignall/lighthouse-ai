# ═══════════════════════════════════════════════════════════════
# Open Claw Session Manager - Windows Installer
# https://github.com/Lightheartdevs/Open-Claw-Session-Manager
#
# Usage:
#   .\install.ps1                     # Interactive install
#   .\install.ps1 -Config my.yaml     # Use custom config
#   .\install.ps1 -CleanupOnly        # Only install session cleanup
#   .\install.ps1 -ProxyOnly          # Only install tool proxy
#   .\install.ps1 -Uninstall          # Remove everything
# ═══════════════════════════════════════════════════════════════

param(
    [string]$Config = "",
    [switch]$CleanupOnly,
    [switch]$ProxyOnly,
    [switch]$Uninstall,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Config) { $Config = Join-Path $ScriptDir "config.yaml" }

# ── Colors ─────────────────────────────────────────────────────
function Info($msg)  { Write-Host "[INFO] $msg" -ForegroundColor Blue }
function Ok($msg)    { Write-Host "[  OK] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }

# ── Banner ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  Open Claw Session Manager - Windows Installer" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

if ($Help) {
    Write-Host "Usage: .\install.ps1 [options]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Config FILE      Use custom config file (default: config.yaml)"
    Write-Host "  -CleanupOnly      Only install session cleanup"
    Write-Host "  -ProxyOnly        Only install vLLM tool proxy"
    Write-Host "  -Uninstall        Remove all installed components"
    Write-Host "  -Help             Show this help"
    exit 0
}

# ── Parse YAML (minimal parser) ───────────────────────────────
function Parse-Yaml {
    param([string]$Key, [string]$Default)
    if (-not (Test-Path $Config)) { return $Default }
    $match = Select-String -Path $Config -Pattern "^\s*${Key}:" | Select-Object -First 1
    if ($match) {
        $value = ($match.Line -split ":\s*", 2)[1].Trim().Trim('"').Trim("'")
        $value = ($value -split "\s*#")[0].Trim()
        if ($value -and $value -ne '""' -and $value -ne "''") { return $value }
    }
    return $Default
}

# ── Load config ────────────────────────────────────────────────
if (-not (Test-Path $Config)) {
    Err "Config file not found: $Config"
    Info "Copy config.yaml and edit it for your setup"
    exit 1
}

Info "Loading config from $Config"

$OpenClawDir = Parse-Yaml "openclaw_dir" "$env:USERPROFILE\.openclaw"
$OpenClawDir = $OpenClawDir -replace "^~", $env:USERPROFILE
$SessionsPath = Parse-Yaml "sessions_path" "agents\main\sessions"
$MaxSessionSize = Parse-Yaml "max_session_size" "256000"
$IntervalMinutes = Parse-Yaml "interval_minutes" "60"
$ProxyPort = Parse-Yaml "port" "8003"
$VllmUrl = Parse-Yaml "vllm_url" "http://localhost:8000"

$SessionsDir = Join-Path $OpenClawDir $SessionsPath

Write-Host ""
Info "Configuration:"
Info "  OpenClaw dir:     $OpenClawDir"
Info "  Max session size: $MaxSessionSize bytes"
Info "  Cleanup interval: ${IntervalMinutes}min"
Write-Host ""

# ── Task Name ──────────────────────────────────────────────────
$CleanupTaskName = "OpenClawSessionCleanup"
$ProxyTaskName = "OpenClawToolProxy"

# ── Uninstall ──────────────────────────────────────────────────
if ($Uninstall) {
    Info "Uninstalling Open Claw Session Manager..."

    # Remove scheduled task
    if (Get-ScheduledTask -TaskName $CleanupTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $CleanupTaskName -Confirm:$false
        Ok "Removed cleanup scheduled task"
    }
    if (Get-ScheduledTask -TaskName $ProxyTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $ProxyTaskName -Confirm:$false
        Ok "Removed proxy scheduled task"
    }

    # Stop proxy if running
    Get-Process python* | Where-Object { $_.CommandLine -like "*vllm-tool-proxy*" } | Stop-Process -Force -ErrorAction SilentlyContinue

    # Remove scripts
    $CleanupScript = Join-Path $OpenClawDir "session-cleanup.ps1"
    $ProxyScript = Join-Path $OpenClawDir "vllm-tool-proxy.py"
    if (Test-Path $CleanupScript) { Remove-Item $CleanupScript; Ok "Removed $CleanupScript" }
    if (Test-Path $ProxyScript) { Remove-Item $ProxyScript; Ok "Removed $ProxyScript" }

    Ok "Uninstall complete"
    exit 0
}

# ── Preflight ──────────────────────────────────────────────────
Info "Running preflight checks..."

if (-not (Test-Path $OpenClawDir)) {
    Err "OpenClaw directory not found: $OpenClawDir"
    exit 1
}
Ok "OpenClaw directory found: $OpenClawDir"

# Check Python
try {
    $pyVer = python --version 2>&1
    Ok "Python found: $pyVer"
} catch {
    try {
        $pyVer = python3 --version 2>&1
        Ok "Python found: $pyVer"
    } catch {
        Err "Python not found. Install Python 3 first."
        exit 1
    }
}

# ── Install Session Cleanup (Windows Task Scheduler) ──────────
if (-not $ProxyOnly) {
    Info "Installing session cleanup..."

    # Create PowerShell version of cleanup script
    $CleanupScript = Join-Path $OpenClawDir "session-cleanup.ps1"

    $cleanupContent = @"
# Open Claw Session Manager - Session Cleanup (Windows)
# Auto-generated by install.ps1

`$SessionsDir = "$SessionsDir"
`$SessionsJson = Join-Path `$SessionsDir "sessions.json"
`$MaxSize = $MaxSessionSize

Write-Output "[`$(Get-Date)] Session cleanup starting"

if (-not (Test-Path `$SessionsJson)) {
    Write-Output "[`$(Get-Date)] No sessions.json found, skipping"
    exit 0
}

# Parse active session IDs
`$jsonContent = Get-Content `$SessionsJson -Raw | ConvertFrom-Json
`$activeIds = @()
`$jsonContent.PSObject.Properties | ForEach-Object {
    if (`$_.Value -is [PSCustomObject] -and `$_.Value.sessionId) {
        `$activeIds += `$_.Value.sessionId
    }
}

Write-Output "[`$(Get-Date)] Active sessions: `$(`$activeIds.Count)"

# Clean debris
Get-ChildItem `$SessionsDir -Filter "*.deleted.*" -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem `$SessionsDir -Filter "*.bak*" -ErrorAction SilentlyContinue | Where-Object { `$_.Name -notlike "*.bak-cleanup" } | Remove-Item -Force

`$removedInactive = 0
`$removedBloated = 0
`$wipeIds = @()

Get-ChildItem `$SessionsDir -Filter "*.jsonl" -ErrorAction SilentlyContinue | ForEach-Object {
    `$basename = `$_.BaseName
    `$isActive = `$activeIds -contains `$basename

    if (-not `$isActive) {
        Write-Output "[`$(Get-Date)] Removing inactive session: `$basename (`$([math]::Round(`$_.Length/1KB))KB)"
        Remove-Item `$_.FullName -Force
        `$removedInactive++
    } else {
        if (`$_.Length -gt `$MaxSize) {
            Write-Output "[`$(Get-Date)] Session `$basename is bloated (`$([math]::Round(`$_.Length/1KB))KB), deleting to force fresh session"
            Remove-Item `$_.FullName -Force
            `$wipeIds += `$basename
            `$removedBloated++
        }
    }
}

# Remove wiped sessions from sessions.json
if (`$wipeIds.Count -gt 0) {
    Write-Output "[`$(Get-Date)] Clearing session references for: `$(`$wipeIds -join ', ')"
    `$jsonContent = Get-Content `$SessionsJson -Raw | ConvertFrom-Json

    foreach (`$id in `$wipeIds) {
        `$keysToRemove = @()
        `$jsonContent.PSObject.Properties | ForEach-Object {
            if (`$_.Value -is [PSCustomObject] -and `$_.Value.sessionId -eq `$id) {
                `$keysToRemove += `$_.Name
            }
        }
        foreach (`$key in `$keysToRemove) {
            `$jsonContent.PSObject.Properties.Remove(`$key)
            Write-Output "  Removed session key: `$key"
        }
    }

    `$jsonContent | ConvertTo-Json -Depth 10 | Set-Content `$SessionsJson -Encoding UTF8
}

Write-Output "[`$(Get-Date)] Cleanup complete: removed `$removedInactive inactive, `$removedBloated bloated"
"@

    Set-Content -Path $CleanupScript -Value $cleanupContent -Encoding UTF8
    Ok "Cleanup script installed: $CleanupScript"

    # Create scheduled task
    if (Get-ScheduledTask -TaskName $CleanupTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $CleanupTaskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$CleanupScript`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

    Register-ScheduledTask -TaskName $CleanupTaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Open Claw Session Manager - Cleanup every ${IntervalMinutes}min" | Out-Null
    Ok "Scheduled task created: $CleanupTaskName (every ${IntervalMinutes}min)"
}

# ── Install Tool Proxy ────────────────────────────────────────
if (-not $CleanupOnly) {
    Info "Installing vLLM tool proxy..."

    $ProxyScript = Join-Path $OpenClawDir "vllm-tool-proxy.py"
    Copy-Item (Join-Path $ScriptDir "scripts\vllm-tool-proxy.py") $ProxyScript -Force
    Ok "Proxy script installed: $ProxyScript"

    # Check Python deps
    $missingDeps = @()
    try { python -c "import flask" 2>$null } catch { $missingDeps += "flask" }
    try { python -c "import requests" 2>$null } catch { $missingDeps += "requests" }
    if ($missingDeps.Count -gt 0) {
        Info "Installing Python packages: $($missingDeps -join ', ')"
        pip install @missingDeps --quiet 2>$null
    }

    # Create scheduled task to run proxy at logon
    if (Get-ScheduledTask -TaskName $ProxyTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $ProxyTaskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction -Execute "python" -Argument "`"$ProxyScript`" --port $ProxyPort --vllm-url $VllmUrl"
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Days 365)

    Register-ScheduledTask -TaskName $ProxyTaskName -Action $action -Trigger $trigger -Settings $settings -Description "Open Claw - vLLM Tool Call Proxy on :$ProxyPort" | Out-Null
    Ok "Scheduled task created: $ProxyTaskName (starts at logon)"

    # Start it now
    Start-ScheduledTask -TaskName $ProxyTaskName
    Start-Sleep -Seconds 2

    try {
        $health = Invoke-RestMethod "http://localhost:$ProxyPort/health" -TimeoutSec 5
        Ok "Proxy is running: $($health.status)"
    } catch {
        Warn "Proxy may still be starting. Test with: curl http://localhost:${ProxyPort}/health"
    }
}

# ── Done ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $CleanupOnly) {
    Info "IMPORTANT: Update your openclaw.json model providers to use the proxy:"
    Write-Host ""
    Write-Host "  Change your provider baseUrl from:"
    Write-Host "    `"baseUrl`": `"http://localhost:8000/v1`""
    Write-Host ""
    Write-Host "  To:"
    Write-Host "    `"baseUrl`": `"http://localhost:${ProxyPort}/v1`""
    Write-Host ""
}

Info "Useful commands:"
if (-not $ProxyOnly) {
    Write-Host "  Get-ScheduledTask -TaskName '$CleanupTaskName'    # Check cleanup task"
    Write-Host "  Start-ScheduledTask -TaskName '$CleanupTaskName'  # Run cleanup now"
}
if (-not $CleanupOnly) {
    Write-Host "  Get-ScheduledTask -TaskName '$ProxyTaskName'      # Check proxy task"
    Write-Host "  curl http://localhost:${ProxyPort}/health                    # Test proxy"
}
Write-Host ""
