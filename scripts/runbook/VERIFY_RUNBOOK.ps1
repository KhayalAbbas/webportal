param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$runbookPath = Join-Path $PSScriptRoot 'LOCAL_COMMANDS.ps1'
$templatePath = Join-Path $PSScriptRoot 'LOCAL_COMMANDS.template.ps1'
$loadedPath = $null
$requireLocalCopy = $false
if (Test-Path $runbookPath) {
    $loadedPath = $runbookPath
} elseif (Test-Path $templatePath) {
    $loadedPath = $templatePath
    $requireLocalCopy = $true
} else {
    throw 'Runbook missing: expected LOCAL_COMMANDS.ps1 or LOCAL_COMMANDS.template.ps1 under scripts/runbook/.'
}

# Paths
$ArtifactsDir = Join-Path -Path 'scripts/proofs/_artifacts' -ChildPath ''
New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
$logPath = Join-Path $ArtifactsDir 'runbook_verify_log.txt'
$excerptPath = Join-Path $ArtifactsDir 'runbook_verify_runbook_excerpt.txt'
$healthPath = Join-Path $ArtifactsDir 'runbook_verify_health.txt'
$openapiPath = Join-Path $ArtifactsDir 'runbook_verify_openapi.json'
$consolePath = Join-Path $ArtifactsDir 'runbook_verify_server_console.txt'

$proc = $null
$started = $false
$logLines = @()
function Write-Log($msg) {
    $ts = (Get-Date).ToString('s')
    $line = "$ts $msg"
    $logLines += $line
    Write-Host $line
}

function Redact($value) {
    if (-not $value) { return $value }
    $lower = $value.ToLowerInvariant()
    $tokens = @('secret','token','key','pwd','pass')
    foreach ($t in $tokens) {
        if ($lower -like "*${t}*") { return '<redacted>' }
    }
    return $value
}

function Get-PathHead([string]$value) {
    $trimmed = $value.Trim().Trim('"')
    if (Test-Path $trimmed) { return $trimmed }
    $head = ($trimmed -split '\s+', 2)[0]
    return $head
}

try {
    Write-Log "Loading runbook file: $loadedPath"
    . $loadedPath
    if ($requireLocalCopy) {
        throw 'LOCAL_COMMANDS.ps1 is missing. Copy scripts/runbook/LOCAL_COMMANDS.template.ps1 to scripts/runbook/LOCAL_COMMANDS.ps1 and edit for your machine.'
    }

    $required = @('ATS_API_BASE_URL','ATS_PYTHON_EXE','ATS_GIT_EXE','ATS_ALEMBIC_EXE','ATS_START_API_CMD')
    foreach ($name in $required) {
        $val = (Get-Variable -Name $name -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Value)
        if (-not $val) { throw "Missing required variable: $name" }
        if ($name -match 'EXE') {
            $checkPath = Get-PathHead $val
            $exists = (Test-Path $checkPath) -or (Get-Command -ErrorAction SilentlyContinue $checkPath)
            if (-not $exists) { throw "$name path not found: $checkPath" }
        } elseif ($name -eq 'ATS_START_API_CMD') {
            $head = Get-PathHead $val
            if (-not (Get-Command -ErrorAction SilentlyContinue $head)) { throw "ATS_START_API_CMD head not found: $head" }
        }
    }

    $excerpt = @{}
    foreach ($name in $required) {
        $excerpt[$name] = Redact((Get-Variable -Name $name).Value)
    }
    ($excerpt | ConvertTo-Json -Depth 3) | Set-Content -Path $excerptPath -Encoding UTF8

    $uri = [Uri]$ATS_API_BASE_URL
    $apiHost = $uri.Host
    $apiPort = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq 'https') { 443 } else { 80 }
    Write-Log "Target base URL: $ATS_API_BASE_URL (host=$apiHost port=$apiPort)"

    $listenerUp = Test-NetConnection -ComputerName $apiHost -Port $apiPort -InformationLevel Quiet

    if (-not $listenerUp) {
        Write-Log "No listener detected; starting API via ATS_START_API_CMD"
        $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $ATS_START_API_CMD -PassThru -RedirectStandardOutput $consolePath -RedirectStandardError $consolePath -WindowStyle Hidden
        $started = $true
    } else {
        Write-Log 'Listener already up; will not start a new server'
    }

    $healthOk = $false
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri "$ATS_API_BASE_URL/health" -TimeoutSec 5
            $healthOk = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthOk) { throw 'Health check did not return 200 within timeout' }

    try {
        $healthRaw = Invoke-WebRequest -Method Get -Uri "$ATS_API_BASE_URL/health" -TimeoutSec 10 -UseBasicParsing
        $healthRaw.Content | Set-Content -Path $healthPath -Encoding UTF8
        Write-Log "Health status: $($healthRaw.StatusCode)"
    } catch {
        throw "Failed to fetch /health: $($_.Exception.Message)"
    }

    try {
        $openapiRaw = Invoke-WebRequest -Method Get -Uri "$ATS_API_BASE_URL/openapi.json" -TimeoutSec 15 -UseBasicParsing
        $openapiRaw.Content | Set-Content -Path $openapiPath -Encoding UTF8
        Write-Log "OpenAPI status: $($openapiRaw.StatusCode) length=$($openapiRaw.Content.Length)"
    } catch {
        throw "Failed to fetch /openapi.json: $($_.Exception.Message)"
    }

    Write-Log 'RUNBOOK VERIFY PASS'
    $logLines + 'RESULT=PASS' | Set-Content -Path $logPath -Encoding UTF8
}
catch {
    $msg = $_.Exception.Message
    Write-Log "RUNBOOK VERIFY FAIL: $msg"
    $logLines + "RESULT=FAIL: $msg" | Set-Content -Path $logPath -Encoding UTF8
    if ($proc -and $started) {
        Try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } Catch {}
    }
    exit 1
}
finally {
    if ($proc -and $started -and $env:KEEP_API_RUNNING -ne '1') {
        Write-Log 'Stopping started API process'
        Try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } Catch {}
    }
}

exit 0
