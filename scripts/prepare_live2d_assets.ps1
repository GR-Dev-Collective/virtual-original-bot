$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = if ($env:VOB_LIVE2D_SOURCE) { $env:VOB_LIVE2D_SOURCE } else { 'C:\Users\chen\Desktop\07_Games\SenrenBanka\live2d_murasame_work\cubism_a_v1\outfits' }
$targetRoot = Join-Path $projectRoot 'apps\desktop\public\live2d\murasame'

if (-not (Test-Path $sourceRoot -PathType Container)) { throw "Live2D source directory not found: $sourceRoot" }
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

$mapping = @{
  '01_裸' = '01_bare'
  '02_私服' = '02_private'
  '03_制服' = '03_uniform'
  '04_洋装' = '04_western'
  '05_寝間着' = '05_sleepwear'
}

foreach ($entry in $mapping.GetEnumerator()) {
  $source = Join-Path $sourceRoot $entry.Key
  $target = Join-Path $targetRoot $entry.Value
  if (-not (Test-Path $source -PathType Container)) { throw "Missing outfit directory: $source" }
  New-Item -ItemType Directory -Path $target -Force | Out-Null

  Get-ChildItem $source -File -Include *.model3.json,*.moc3,*.physics3.json,*.cdi3.json | Copy-Item -Destination $target -Force
  Get-ChildItem $source -Directory -Filter *.4096 | Copy-Item -Destination $target -Recurse -Force
}

"Prepared Live2D assets in $targetRoot"
Get-ChildItem $targetRoot -Recurse -File | Measure-Object Length -Sum | ForEach-Object {
  "files=$($_.Count) sizeGB={0:N2}" -f ($_.Sum / 1GB)
}
