#requires -Version 5.1
<#
.SYNOPSIS
    启动 IndexTTS-2.5 语音克隆 sidecar 服务（Windows）。

.DESCRIPTION
    - 使用 index-tts 项目自带的 .venv 解释器（backend\.venv 没有 torch）。
    - 把 TEMP/TMP、HF_HOME、TORCH_HOME、INDEXTTS_WORK_DIR 全部重定向到
      <INDEXTTS_HOME>\.runtime 下，满足本机沙箱只能写 default-workspace 的限制。
    - 前台运行 `python -m services.indextts_service`。

.PARAMETER ModelDir
    模型目录，默认 checkpoints；相对路径按 INDEXTTS_HOME 解析，也可传绝对路径，
    例如 checkpoints_murasame。

.PARAMETER Port
    监听端口，默认 9882。

.PARAMETER Host
    监听地址，默认 127.0.0.1。该参数以别名方式实现，避免与 PowerShell 只读
    自动变量 $Host 冲突。

.PARAMETER Mock
    使用 MockEngine：不加载真实模型、不需要 GPU，返回合成好的测试 WAV。

.PARAMETER NoPreload
    启动时不加载模型（/synthesize 会返回 503），适合先起服务再手动加载。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -Mock

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -ModelDir checkpoints_murasame -Port 9885
#>
[CmdletBinding()]
param(
    [string]$ModelDir = "checkpoints",
    [int]$Port = 9882,
    [Alias("Host")]
    [string]$BindHost = "127.0.0.1",
    [switch]$Mock,
    [switch]$NoPreload
)

$ErrorActionPreference = "Stop"

function Write-ErrorAndExit {
    param([string]$Message)
    Write-Host "[错误] $Message" -ForegroundColor Red
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "services\indextts_service"))) {
    Write-ErrorAndExit "未找到 services\indextts_service，请在 virtual-original-bot 仓库内运行本脚本。"
}

$defaultHome = "C:\Users\chen\Documents\deepseek-harness\default-workspace\index-tts"
if ($env:INDEXTTS_HOME) {
    $indexttsHome = $env:INDEXTTS_HOME
} else {
    $indexttsHome = $defaultHome
}

try {
    $indexttsHome = [System.IO.Path]::GetFullPath($indexttsHome)
} catch {
    Write-ErrorAndExit "INDEXTTS_HOME 路径无效: $indexttsHome"
}

if (-not (Test-Path -LiteralPath $indexttsHome -PathType Container)) {
    Write-ErrorAndExit @"
IndexTTS 目录不存在: $indexttsHome
请确认 default-workspace/index-tts 已就位，或设置环境变量 INDEXTTS_HOME。
"@
}

$python = Join-Path $indexttsHome ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-ErrorAndExit @"
找不到 index-tts 虚拟环境解释器: $python
请先在 index-tts 目录创建 .venv 并安装依赖（不要使用 backend\.venv，它没有 torch）。
"@
}

if ([System.IO.Path]::IsPathRooted($ModelDir)) {
    $resolvedModelDir = $ModelDir
} else {
    $resolvedModelDir = Join-Path $indexttsHome $ModelDir
}
try {
    $resolvedModelDir = [System.IO.Path]::GetFullPath($resolvedModelDir)
} catch {
    Write-ErrorAndExit "模型目录路径无效: $ModelDir"
}

if (-not $Mock) {
    if (-not (Test-Path -LiteralPath $resolvedModelDir -PathType Container)) {
        Write-ErrorAndExit "模型目录不存在: $resolvedModelDir`n可用值示例: checkpoints、checkpoints_murasame"
    }
    $cfgPath = Join-Path $resolvedModelDir "config.yaml"
    if (-not (Test-Path -LiteralPath $cfgPath -PathType Leaf)) {
        Write-ErrorAndExit "缺少模型配置: $cfgPath"
    }
    $requiredFiles = @(
        "gpt.pth",
        "s2mel.pth",
        "codec.pth",
        "feat1.pt",
        "feat2.pt",
        "wav2vec2bert_stats.pt"
    )
    foreach ($name in $requiredFiles) {
        $filePath = Join-Path $resolvedModelDir $name
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            Write-ErrorAndExit "模型文件不完整，缺少: $filePath`n请检查 -ModelDir 或重新下载模型。"
        }
    }
} else {
    $cfgPath = Join-Path $resolvedModelDir "config.yaml"
}

$runtimeRoot = Join-Path $indexttsHome ".runtime"
$tmpDir = Join-Path $runtimeRoot "tmp"
$hfDir = Join-Path $runtimeRoot "hf"
$torchDir = Join-Path $runtimeRoot "torch"
$workDir = Join-Path $runtimeRoot "indextts_service"
foreach ($dir in @($runtimeRoot, $tmpDir, $hfDir, $torchDir, $workDir)) {
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

$env:INDEXTTS_HOME = $indexttsHome
$env:INDEXTTS_MODEL_DIR = $resolvedModelDir
$env:INDEXTTS_CFG_PATH = $cfgPath
$env:INDEXTTS_WORK_DIR = $workDir
$env:INDEXTTS_HOST = $BindHost
$env:INDEXTTS_PORT = "$Port"
$env:INDEXTTS_DEVICE = if ($env:INDEXTTS_DEVICE) { $env:INDEXTTS_DEVICE } else { "cuda:0" }
$env:INDEXTTS_ENGINE = if ($Mock) { "mock" } else { "indextts2" }
$env:INDEXTTS_PRELOAD = if ($NoPreload) { "false" } else { "true" }

$env:TEMP = $tmpDir
$env:TMP = $tmpDir
$env:HF_HOME = $hfDir
$env:TORCH_HOME = $torchDir

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$repoRoot;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $repoRoot
}

$modeLabel = if ($Mock) { "mock" } else { "indextts2" }
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host " IndexTTS-2.5 sidecar" -ForegroundColor Cyan
Write-Host "   仓库根目录 : $repoRoot"
Write-Host "   解释器     : $python"
Write-Host "   引擎       : $modeLabel"
Write-Host "   模型目录   : $resolvedModelDir"
Write-Host "   设备       : $($env:INDEXTTS_DEVICE)"
Write-Host "   预加载     : $($env:INDEXTTS_PRELOAD)"
Write-Host "   临时目录   : $tmpDir"
Write-Host "   工作目录   : $workDir"
Write-Host "   健康检查   : http://$($BindHost):$Port/health"
Write-Host "   等待就绪   : powershell -ExecutionPolicy Bypass -File scripts\wait_for_indextts.ps1 -Port $Port"
Write-Host "==============================================================" -ForegroundColor Cyan

$exitCode = 0
try {
    Push-Location -LiteralPath $repoRoot
    & $python -m services.indextts_service
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host "[错误] 启动服务失败: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Host @"
[错误] IndexTTS 服务已退出，退出码: $exitCode
排查建议:
  1. 确认使用的是 index-tts\.venv 解释器，而不是 backend\.venv；
  2. 确认 -ModelDir 指向完整模型（config.yaml、gpt.pth、s2mel.pth 等）；
  3. 显存不足时关闭其他 GPU 程序，或缩短文本；
  4. 查看上方服务日志中的真实异常（预加载失败会打印 traceback）。
"@ -ForegroundColor Red
    exit $exitCode
}

exit 0
