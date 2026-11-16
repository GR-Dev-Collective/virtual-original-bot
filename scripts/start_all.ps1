#requires -Version 5.1
<#
.SYNOPSIS
    Start the virtual-original-bot stack: IndexTTS sidecar, backend, desktop.

.PARAMETER Mock
    Start the sidecar with MockEngine (no GPU/model).

.PARAMETER NoDesktop
    Only start sidecar + backend.

.PARAMETER ModelDir
    Sidecar model directory relative to INDEXTTS_HOME (checkpoints / checkpoints_murasama).

.PARAMETER OllamaModel
    Ollama chat model (default qwen3:8b; on 8GB use qwen3:4b).

.PARAMETER OllamaNumGpu
    -1 keeps Ollama defaults; 0 forces CPU (recommended when IndexTTS uses the GPU).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1 -Mock -NoDesktop

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1 -OllamaModel qwen3:4b -OllamaNumGpu 0
#>
[CmdletBinding()]
param(
    [switch]$Mock,
    [switch]$NoDesktop,
    [string]$ModelDir = "checkpoints",
    [int]$SidecarPort = 9882,
    [int]$BackendPort = 8090,
    [string]$OllamaModel = "qwen3:8b",
    [int]$OllamaNumGpu = -1
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$backendPython = Join-Path $repo "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw "backend venv not found: $backendPython`nCreate it with: cd backend; python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements-dev.txt"
}

$logs = Join-Path $repo "backend\runtime\logs"
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Test-PortInUse {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Http {
    param([string]$Url, [int]$TimeoutSeconds, [string]$Name)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 5
            if ($response) { return $response }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "$Name did not become ready: $Url"
}

if (Test-PortInUse $SidecarPort) { throw "port $SidecarPort is already in use" }
if (Test-PortInUse $BackendPort) { throw "port $BackendPort is already in use" }

# 1. IndexTTS sidecar
$sidecarArgs = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "start_indextts.ps1"),
    "-Port", $SidecarPort,
    "-ModelDir", $ModelDir
)
if ($Mock) { $sidecarArgs += "-Mock" }

$sidecarOut = Join-Path $logs "sidecar-$stamp.log"
$sidecarErr = Join-Path $logs "sidecar-$stamp.err.log"
$sidecar = Start-Process -FilePath "powershell.exe" -ArgumentList $sidecarArgs `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $sidecarOut -RedirectStandardError $sidecarErr
Write-Host "sidecar starting (pid $($sidecar.Id)), log: $sidecarOut"

$null = Wait-Http -Url "http://127.0.0.1:$SidecarPort/health" -TimeoutSeconds 240 -Name "sidecar"
Write-Host "sidecar ready: http://127.0.0.1:$SidecarPort"

# 2. Backend
$backendCmd = "`$env:TTS_PROVIDER = 'index_tts'`n"
$backendCmd += "`$env:INDEX_TTS_BASE_URL = 'http://127.0.0.1:$SidecarPort'`n"
$backendCmd += "`$env:OLLAMA_MODEL = '$OllamaModel'`n"
$backendCmd += "`$env:OLLAMA_NUM_CTX = '4096'`n"
if ($OllamaNumGpu -ge 0) {
    $backendCmd += "`$env:OLLAMA_NUM_GPU = '$OllamaNumGpu'`n"
}
$backendCmd += "Set-Location '$repo\backend'`n& '$backendPython' -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort"

$backendOut = Join-Path $logs "backend-$stamp.log"
$backendErr = Join-Path $logs "backend-$stamp.err.log"
$backend = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-Command", $backendCmd) `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
Write-Host "backend starting (pid $($backend.Id)), log: $backendOut"

$null = Wait-Http -Url "http://127.0.0.1:$BackendPort/health" -TimeoutSeconds 120 -Name "backend"
Write-Host "backend ready: http://127.0.0.1:$BackendPort"

# 3. Desktop (optional)
$desktopPid = $null
if (-not $NoDesktop) {
    $desktopCmd = "Set-Location '$repo\apps\desktop'; npm run dev"
    $desktop = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-NoProfile", "-Command", $desktopCmd) -PassThru
    $desktopPid = $desktop.Id
    Write-Host "desktop starting (pid $desktopPid); close that window or run stop_all.ps1 to stop"
}

$state = [ordered]@{
    started_at = (Get-Date).ToString("o")
    sidecar_pid = $sidecar.Id
    backend_pid = $backend.Id
    desktop_pid = $desktopPid
    sidecar_port = $SidecarPort
    backend_port = $BackendPort
    logs = $logs
}
$statePath = Join-Path $logs "start_all.json"
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

Write-Host ""
Write-Host "Stack is running:"
Write-Host "  sidecar : http://127.0.0.1:$SidecarPort/health"
Write-Host "  backend : http://127.0.0.1:$BackendPort/health"
if (-not $NoDesktop) { Write-Host "  desktop : npm run dev (separate window)" }
Write-Host "Stop with: powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1"
