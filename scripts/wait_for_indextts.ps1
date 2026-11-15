#requires -Version 5.1
<#
.SYNOPSIS
    等待 IndexTTS sidecar 加载完成（/health 的 loaded=true）。

.DESCRIPTION
    轮询 http://127.0.0.1:<Port>/health，直到 loaded=true 或超时。
    成功输出 JSON 并以 0 退出；超时输出 JSON 并以 1 退出。

.PARAMETER Port
    服务端口，默认 9882。

.PARAMETER TimeoutSeconds
    最长等待秒数，默认 180。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\wait_for_indextts.ps1 -Port 9882
#>
[CmdletBinding()]
param(
    [int]$Port = 9882,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

if ($TimeoutSeconds -le 0) {
    Write-Host "[错误] TimeoutSeconds 必须大于 0。" -ForegroundColor Red
    exit 1
}

$url = "http://127.0.0.1:$Port/health"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$lastError = $null
$lastHealth = $null

while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    try {
        $lastHealth = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5
        $lastError = $null
        if ($lastHealth.loaded -eq $true) {
            $elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
            $result = [ordered]@{
                status = "ready"
                port = $Port
                elapsed_seconds = $elapsed
                health = $lastHealth
            }
            $result | ConvertTo-Json -Depth 5 -Compress
            exit 0
        }
        $lastError = "health.loaded 仍为 false"
    } catch {
        $lastError = $_.Exception.Message
    }
    Start-Sleep -Seconds 1
}

$elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
$result = [ordered]@{
    status = "timeout"
    port = $Port
    elapsed_seconds = $elapsed
    timeout_seconds = $TimeoutSeconds
    last_error = $lastError
    last_health = $lastHealth
}
$result | ConvertTo-Json -Depth 5 -Compress
exit 1
