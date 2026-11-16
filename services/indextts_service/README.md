# IndexTTS-2.5 语音克隆 sidecar 服务

本服务把 `default-workspace/index-tts` 中的 IndexTTS-2.5 模型封装成独立的 HTTP
sidecar，供后端通过 HTTP 调用「丛雨」克隆音色。服务只依赖本机 index-tts 虚拟环境，
不修改模型仓库，也不写入仓库目录。

包名刻意使用 `indextts_service` **而不是** `indextts`：如果仓库根目录出现
`indextts/` 包，会遮蔽真实模型库，导致 `from indextts.infer_v2_5 import IndexTTS2`
导入到错误位置。

## 目录

```text
services/
  __init__.py
  indextts_service/
    __init__.py
    __main__.py          # python -m services.indextts_service
    app.py               # FastAPI 应用，/health 与 /synthesize
    engine.py            # MockEngine / IndexTts2Engine
    errors.py            # ServiceError 与错误码
    schemas.py           # 请求模型与校验
    settings.py          # 环境变量配置
    README.md
    tests/               # 不依赖 GPU/torch
scripts/
  start_indextts.ps1
  wait_for_indextts.ps1
```

## 快速启动

在仓库根目录打开 PowerShell：

```powershell
# Mock 模式：不需要 GPU / 模型，用于联调后端与脚本自检
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -Mock

# 默认真实模式：checkpoints + cuda:0 + bf16
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1

# 使用微调后的丛雨 checkpoint，换端口
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 `
  -ModelDir checkpoints_murasame -Port 9885

# 模型已单独加载/只想先起服务（此时 /synthesize 返回 503）
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -NoPreload
```

脚本会：

1. 解析 `INDEXTTS_HOME`（默认
   `C:\Users\chen\Documents\deepseek-harness\default-workspace\index-tts`）；
2. 校验 `<ModelDir>\config.yaml` 及 `gpt.pth`、`s2mel.pth`、`codec.pth` 等关键文件；
3. 使用 `<INDEXTTS_HOME>\.venv\Scripts\python.exe`；
4. 把 `TEMP`/`TMP`、`HF_HOME`、`TORCH_HOME`、`INDEXTTS_WORK_DIR` 全部指向
   `<INDEXTTS_HOME>\.runtime\*`，并创建目录；
5. 设置 `PYTHONPATH=<仓库根>` 后前台运行 `python -m services.indextts_service`；
6. 打印健康检查地址。

另开一个终端等待模型加载完成：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\wait_for_indextts.ps1 -Port 9882 -TimeoutSeconds 180
```

成功时输出 `{"status":"ready",...}` 并以 0 退出；超时输出
`{"status":"timeout",...}` 并以 1 退出。

## 直接运行（不经过脚本）

真实模式必须用 index-tts 的虚拟环境解释器，并在仓库根目录执行：

```powershell
$env:INDEXTTS_HOME = "C:\Users\chen\Documents\deepseek-harness\default-workspace\index-tts"
$env:INDEXTTS_MODEL_DIR = "$env:INDEXTTS_HOME\checkpoints"
$env:INDEXTTS_WORK_DIR = "$env:INDEXTTS_HOME\.runtime\indextts_service"
$env:PYTHONPATH = (Get-Location).Path
& "$env:INDEXTTS_HOME\.venv\Scripts\python.exe" -m services.indextts_service
```

`backend\.venv` 只用于跑单元测试和 ruff，其中没有 torch，不能加载真实模型。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INDEXTTS_ENGINE` | `indextts2` | `indextts2` 或 `mock` |
| `INDEXTTS_HOME` | `C:\Users\chen\Documents\deepseek-harness\default-workspace\index-tts` | index-tts 项目根目录 |
| `INDEXTTS_MODEL_DIR` | `<INDEXTTS_HOME>\checkpoints` | 模型目录（可指向 `checkpoints_murasame`） |
| `INDEXTTS_CFG_PATH` | `<INDEXTTS_MODEL_DIR>\config.yaml` | 模型配置 |
| `INDEXTTS_DEVICE` | `cuda:0` | torch 设备；无 GPU 时可设 `cpu`（很慢） |
| `INDEXTTS_USE_BF16` | `true` | 是否使用 bf16 |
| `INDEXTTS_HOST` | `127.0.0.1` | 监听地址 |
| `INDEXTTS_PORT` | `9882` | 监听端口 |
| `INDEXTTS_PRELOAD` | `true` | 启动时后台加载模型 |
| `INDEXTTS_WORK_DIR` | `<INDEXTTS_HOME>\.runtime\indextts_service` | 推理临时 WAV 目录 |
| `INDEXTTS_REQUEST_TIMEOUT_SECONDS` | `180` | 单次合成超时（秒） |

说明：

- `INDEXTTS_PRELOAD=true` 时模型在后台加载，加载期间 `/health` 返回
  `loaded=false`，`/synthesize` 返回 503；加载失败会打印真实异常并以非零码退出。
- 推理与加载共用一把全局锁，同一进程内串行执行，避免 8GB 显存被并发请求撑爆。

## API

### `GET /health`

```json
{
  "status": "ok",
  "engine": "index_tts_2",
  "loaded": true,
  "device": "cuda:0",
  "model_dir": "C:\\Users\\chen\\Documents\\deepseek-harness\\default-workspace\\index-tts\\checkpoints"
}
```

Mock 模式返回 `"engine": "mock"`、`"device": "cpu"`、`"model_dir": "mock"`。

### `POST /synthesize`

请求体：

```json
{
  "text": "ご主人様、今日もお疲れ様でした。",
  "reference_audio": "C:\\Users\\chen\\Documents\\deepseek-harness\\default-workspace\\index-tts\\murasame_ref.wav",
  "language": "JA",
  "emotion": { "mode": "vector", "vector": [0.2, 0, 0, 0, 0, 0, 0, 0], "alpha": 0.6 },
  "duration_factor": 1.0,
  "text_normalization": true,
  "max_text_tokens_per_segment": 120,
  "request_id": "optional-trace-id"
}
```

- `text`：1..2000 字符，不能全为空白。
- `reference_audio`：**绝对路径**、文件存在且可读。
- `language`：`ZH`（默认）/`EN`/`JA`/`ES`/`AR`，大小写不敏感。
- `emotion`：三种模式互斥：
  - `vector`：必须正好 8 个 0..1 浮点数，总和 ≤ 0.8；
  - `text`：非空文本，需要 QwenEmotion 资源；缺失时返回 400
    `emotion_unavailable`；
  - `audio`：绝对路径且文件存在。
  - 三种模式都支持 `alpha`（0..1，默认 1.0）。
- `duration_factor`：0.5..2.0，默认 1.0。
- `max_text_tokens_per_segment`：正整数，默认 120。

成功：`200`，`Content-Type: audio/wav`，`X-Sample-Rate: 22050`，响应体为 WAV 字节。

失败统一返回：

```json
{ "detail": { "code": "invalid_request", "message": "请求参数无效: ..." } }
```

| 状态码 | code | 场景 |
| --- | --- | --- |
| 400 | `invalid_request` | 模型侧参数错误（例如参考音频无法被 soundfile 读取） |
| 400 | `emotion_unavailable` | 模型缺少 QwenEmotion 资源却请求文本情感 |
| 422 | `invalid_request` | 请求体校验失败（路径/范围/枚举/互斥等） |
| 500 | `synthesis_failed` | 推理异常或超时 |
| 503 | `model_loading` | 模型未加载完成，带 `Retry-After: 5` |

PowerShell 调用示例：

```powershell
$body = @{
  text = "ご主人様、おはようございます。"
  reference_audio = "C:\Users\chen\Documents\deepseek-harness\default-workspace\index-tts\murasame_ref.wav"
  language = "JA"
} | ConvertTo-Json

Invoke-WebRequest -Uri http://127.0.0.1:9882/synthesize -Method Post `
  -ContentType "application/json" -Body $body -OutFile out.wav
```

## Mock 模式

`INDEXTTS_ENGINE=mock` 或脚本参数 `-Mock`：

- 不导入 torch / indextts，不需要 GPU 和模型文件；
- `/health` 在加载后返回 `engine=mock`、`loaded=true`；
- `/synthesize` 返回 0.5 秒、22050Hz、16-bit 单声道正弦 WAV；
- 用于后端联调、启动/等待脚本自检和 CI。

## `checkpoints` 与 `checkpoints_murasame`

- `checkpoints`：IndexTTS-2.5 原始权重，脚本默认值。
- `checkpoints_murasame`：基于丛雨数据微调后的权重，目录结构相同，可直接
  `-ModelDir checkpoints_murasame` 或设置 `INDEXTTS_MODEL_DIR`。
- 两个目录各自带 `config.yaml` 与 `hf_cache/`，可以独立切换，不要混用文件。
- 当前两个 checkpoint 都**没有** `qwen0.6bemo4-merge/`（QwenEmotion 资源），
  因此 `emotion.mode=text` 会返回 400；`vector` / `audio` 模式不受影响。
  若后续补齐该目录，服务会自动检测并加载。

## 8GB 显存（RTX 4060 Laptop）提示

- 默认 bf16 + `cuda:0`。IndexTTS-2.5 会检测到显存 < 10GB 并自动开启低显存模式，
  长文本按标点切段合成。
- 合成期间不要同时跑其他占用显存的程序（本地 LLM、Stable Diffusion 等）。
- 文本建议按句拆分后逐段请求；`max_text_tokens_per_segment` 可适当调低。
- 若出现 OOM，可尝试设置 `INDEXTTS_USE_BF16=false`（显存占用更高，不推荐）或
  缩短文本；不建议并发调用（服务本身已串行化）。
- 首次加载约需数十秒，属于正常现象，用 `wait_for_indextts.ps1` 等待。

## 参考音频要求

- 建议 3–15 秒、单人、干净、无明显背景音乐/噪声的 WAV。
- 16-bit PCM WAV 最稳妥；必须能被 `soundfile` 读取（不支持的文件会在推理阶段
  返回 400 `invalid_request`）。
- 绝对路径传给 `reference_audio`；`murasame_ref.wav` 是现成的丛雨参考音频。
- 参考音频只影响音色，不要求与合成文本同语言；跨语言克隆由 `language` 控制。

## Windows 沙箱注意事项

本机 DSH 沙箱限制下，index-tts 虚拟环境的解释器只能写
`default-workspace` 内的路径。因此：

- 服务不会向仓库目录写任何文件；
- 推理临时 WAV 固定写到 `INDEXTTS_WORK_DIR`（默认
  `<INDEXTTS_HOME>\.runtime\indextts_service`），读取后立即删除；
- 启动脚本把 `TEMP`/`TMP`、`HF_HOME`、`TORCH_HOME` 也重定向到
  `<INDEXTTS_HOME>\.runtime\` 下；
- 不要把 `INDEXTTS_WORK_DIR` 指向仓库或系统临时目录，否则可能被沙箱拒绝。

## 测试与静态检查

使用 backend 虚拟环境（含 fastapi/httpx/pytest/ruff，不含 torch）：

```powershell
cd D:\重构\virtual-original-bot
backend\.venv\Scripts\python.exe -m pytest services\indextts_service\tests -q
backend\.venv\Scripts\python.exe -m ruff check services\indextts_service
```

测试覆盖：health、mock WAV 头/采样率、全部参数校验分支、未知情感模式、
503 未加载、400/422/500 错误映射、超时映射、引擎参数映射与临时文件清理。
