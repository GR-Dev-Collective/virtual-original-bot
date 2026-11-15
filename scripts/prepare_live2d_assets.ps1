#requires -Version 5.1
<#
.SYNOPSIS
    Prepare Live2D runtime assets for the Electron renderer.

.DESCRIPTION
    Extracts the bundled Mao sample model into apps/desktop/public/live2d/mao and
    copies the Live2D Cubism Core runtime (not committed to Git, Live2D license).
    The extracted assets and Core are gitignored; only the model zip is tracked.

.PARAMETER ZipPath
    Model zip. Default: apps/desktop/src/renderer/public/live2d/mao_zh-Hans.zip

.PARAMETER Target
    Output directory. Default: apps/desktop/public/live2d/mao

.PARAMETER CorePath
    Path to live2dcubismcore.min.js. Env var VOB_LIVE2D_CORE is used as fallback.

.PARAMETER OutfitSource
    Optional: directory with Murasame outfit folders (legacy). Skipped when absent.

.EXAMPLE
    $env:VOB_LIVE2D_CORE = "D:\path\to\live2dcubismcore.min.js"
    powershell -ExecutionPolicy Bypass -File scripts\prepare_live2d_assets.ps1
#>
[CmdletBinding()]
param(
    [string]$ZipPath = "",
    [string]$Target = "",
    [string]$CorePath = "",
    [string]$OutfitSource = $env:VOB_LIVE2D_SOURCE
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ZipPath) {
    $ZipPath = Join-Path $projectRoot "apps\desktop\src\renderer\public\live2d\mao_zh-Hans.zip"
}
if (-not $Target) {
    $Target = Join-Path $projectRoot "apps\desktop\public\live2d\mao"
}

if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    throw "Live2D model zip not found: $ZipPath"
}
New-Item -ItemType Directory -Path $Target -Force | Out-Null

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("vob-live2d-" + [guid]::NewGuid().ToString("N"))
try {
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $tempRoot -Force
    $runtime = Join-Path $tempRoot "runtime"
    if (-not (Test-Path -LiteralPath $runtime -PathType Container)) {
        throw "Unexpected zip layout (missing runtime/): $ZipPath"
    }
    Copy-Item -Path (Join-Path $runtime "*") -Destination $Target -Recurse -Force
    Write-Host "Extracted model to $Target"
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$candidates = @()
if ($CorePath) { $candidates += $CorePath }
if ($env:VOB_LIVE2D_CORE) { $candidates += $env:VOB_LIVE2D_CORE }
$candidates += (Join-Path $Target "live2dcubismcore.min.js")

$core = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if ($core) {
    Copy-Item -LiteralPath $core -Destination (Join-Path $Target "live2dcubismcore.min.js") -Force
    Write-Host "Copied Cubism Core from $core"
}
else {
    Write-Warning "live2dcubismcore.min.js not found. The model is ready but the renderer cannot load it."
    Write-Warning "Get Cubism Core from the Live2D Cubism SDK for Web and place it at:"
    Write-Warning "  $Target\live2dcubismcore.min.js"
    Write-Warning "or set VOB_LIVE2D_CORE and rerun. Core is licensed by Live2D; do not commit it."
}

if ($OutfitSource -and (Test-Path -LiteralPath $OutfitSource -PathType Container)) {
    $outfitRoot = Join-Path $projectRoot "apps\desktop\public\live2d\murasame"
    $index = 0
    foreach ($source in (Get-ChildItem -LiteralPath $OutfitSource -Directory)) {
        $index += 1
        $target = Join-Path $outfitRoot ("outfit-{0:D2}" -f $index)
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        Get-ChildItem $source.FullName -File -Include *.model3.json,*.moc3,*.physics3.json,*.cdi3.json |
            Copy-Item -Destination $target -Force
        Get-ChildItem $source.FullName -Directory -Filter *.4096 |
            Copy-Item -Destination $target -Recurse -Force
    }
    Write-Host "Prepared Murasame outfits in $outfitRoot"
}

$files = Get-ChildItem $Target -Recurse -File
$total = ($files | Measure-Object Length -Sum).Sum
Write-Host ("Done: {0} files, {1:N1} MB" -f $files.Count, ($total / 1MB))
Write-Host "Next: cd apps\desktop; npm run build (or npm run dev)"
