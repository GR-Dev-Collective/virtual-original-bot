#requires -Version 5.1
<#
.SYNOPSIS
    Stop the stack started by scripts/start_all.ps1.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $repo "backend\runtime\logs\start_all.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    Write-Host "No start_all.json found; nothing to stop."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$pids = @($state.sidecar_pid, $state.backend_pid, $state.desktop_pid) | Where-Object { $_ }
foreach ($processId in $pids) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "stopping $processId ($($process.ProcessName))"
        Stop-Process -Id $processId -Force
    }
}

# Process trees (powershell wrapper -> python/electron) may outlive the wrapper.
foreach ($port in @($state.sidecar_port, $state.backend_port)) {
    $connections = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($owner in ($connections | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $process = Get-Process -Id $owner -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "stopping port $port owner $owner ($($process.ProcessName))"
            Stop-Process -Id $owner -Force
        }
    }
}

Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
Write-Host "stopped."
