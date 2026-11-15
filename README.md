# virtual-original-bot

虚拟角色桌面原型：Electron 渲染角色与聊天界面，FastAPI 后端负责会话、回合、事件账本与模型编排，本地 Ollama 生成回复，IndexTTS-2.5 完成零样本音色克隆与语音合成。

当前版本是 **v2 运行时**：控制通道升级为版本化协议 `vob/1`，会话可以持久化、断线重放与 `hydrate` 恢复；TTS 默认走 IndexTTS-2.5 sidecar，GPT-SoVITS 保留为 legacy 可选实现。

> 文档以代码为准。协议字段的权威定义见 [`shared/contracts/control-message.schema.json`](shared/contracts/control-message.schema.json) 与 [`shared/contracts/protocol.md`](shared/contracts/protocol.md)。本文只描述已经实现并验证过的行为。

## 当前状态

### 已完成并验证

- **后端 v2 运行时**（`backend/`）
  - `vob/1` 控制协议：`server.ready` / `capabilities`、`session.opened`、`session.state`、`turn.*`、`agent.text`、`tts.started|ready|failed|cancelled|finished`、`voice.selected`、`character.state`、`error`。
  - 命令：`session.open`、`session.hydrate`、`user.text`、`voice.select`、`tts.cancel`、`tts.finished`。
  - `SessionStore`：`backend/runtime/sessions/<session_id>/` 下持久化 `meta.json`、`messages.jsonl`、`events.jsonl`，事件带单调 `seq`，支持 `after` 重放与 `hydrate` 快照。
  - `ReplyPipeline`：单会话单 active turn、新输入打断旧 turn、最近历史窗口、回复截断到 300 字。
  - `character.state` 完全由事件账本投影（`idle` / `thinking` / `speaking` / `error`）。
  - `GET /health`、`GET/POST/DELETE /voices`、`POST /tts`、`GET /tts/{audio_id}`、`POST /asr`。
- **TTS**
  - 默认 provider：`index_tts`，指向 `http://127.0.0.1:9882` 的 IndexTTS-2.5 sidecar。
  - legacy provider：`TTS_PROVIDER=gpt_sovits`，指向 `http://127.0.0.1:9880/`。
  - 音色档案：`backend/config/voices.json` 内置 `murasame`（丛雨），参考音频 `assets/voices/murasame/murasame_ref.wav`；用户克隆档案存 `backend/runtime/voices/`。
- **桌面端**（`apps/desktop/`）
  - `vob/1` 客户端：握手、`localStorage` 保存 `session_id`/`cursor`、断线重连与 `after` 重放、`session.hydrate` 快照恢复、`voice.select` 音色下拉、克隆面板、CSP 修正、播放结束回报 `tts.finished`。
  - `npm run typecheck` 与 `npm run build` 通过。

### 验证记录

| 项目 | 结果 |
| --- | --- |
| 后端测试 | `108 passed`（`backend/`） |
| 后端 ruff | 通过 |
| sidecar 测试 | `56 passed`（`services/indextts_service/`） |
| sidecar ruff | 通过 |
| 桌面 typecheck / build | 通过 |
| 真实 GPU 合成 | 已跑通，22050Hz，单句约 2.23s / 7.5s 等 |
| 后端 HTTP | `/voices`、`/tts`、克隆与删除已跑通 |
| WebSocket 全链路 | LLM → TTS → `audio_url` → `hydrate` → 重连重放 9 条 → `voice.select` 已跑通 |
| Electron 截图验收 | 通过：Mao 模型加载、角色渲染、音色/克隆/输入控件齐全 |
| ASR | 通过：faster-whisper-large-v3（CPU int8）转写真实 TTS 音频 |
| sidecar mock | 启动/等待脚本已跑通 |

### 尚未自动验证

- **Electron 窗口内的实际音频播放、自动播放策略、停止语音与克隆面板交互**没有自动化验收。协议链路、构建产物、Live2D 渲染截图已验证；播放与表单交互仍需人工过一遍。
- 真实麦克风采集 → `/asr` → 对话 → TTS 的完整人工操作链路未自动化（`/asr` 接口本身已用真实模型验证）。

### 尚未实现

- Memory / Relationship / Vision / OCR / Action Controller / World。
- VAD、实时音频流、流式 TTS。
- 情绪状态机：`character.state.emotion` 目前恒为 `null`，字段保留。
- 丛雨专属 Live2D 资源与正式表情映射；仓库只带 Mao 示例的验证界面，模型资源需本地准备。
- GPT-SoVITS 训练流程（legacy 推理仅保留）。

## 架构

```text
Electron Renderer（协议客户端）
  聊天 / Live2D / 音频播放 / 录音 / 音色下拉 / 克隆面板
        │
        │  WebSocket /ws/control?protocol=vob/1&session_id=&after=
        │  vob/1：server.ready / 命令 / 通知 / seq / replay / hydrate
        ▼
Control Gateway（backend/app/transport）
  能力协商 · 命令分发 · 事件扇出 · after 重放 · 错误映射
        │
        ▼
CharacterRuntime（backend/app/runtime）
  SessionStore(JSONL) · ReplyPipeline(turn) · AgentCore(人设/历史)
  VoiceRegistry(音色档案/克隆) · AudioStore · CharacterProjection
        │ Ports
        ▼
OllamaChat · IndexTtsProvider / GptSovitsProvider · FasterWhisperAsr · AudioStore
```

关键边界：

- Renderer 只消费协议，不直接调用模型；后端崩溃或断线后可从会话账本恢复。
- Gateway 只做协议编解码、连接、重放与命令分发；回合编排在 `ReplyPipeline`。
- 会话状态归后端所有；`session.state` 是权威快照，实时通知只是增量。
- 音色是**会话级**选择（`meta.json.voice_id`），音色档案是**进程级**资源（`VoiceRegistry`）。
- 模型通过 Port/Adapter 注入；测试用 Fake/Mock，真实 GPU 只用于端到端验证。

### 主要目录

```text
virtual-original-bot/
├─ apps/desktop/                 # Electron（electron-vite）
│  ├─ src/main/                  # 主进程、窗口与自动播放策略
│  ├─ src/preload/               # contextBridge，注入 VOB_CONTROL_URL
│  └─ src/renderer/              # 聊天、音色、录音、播放、Live2D、协议客户端
│     └─ src/transport/          # protocol.ts / control-client.ts
├─ backend/
│  ├─ app/
│  │  ├─ transport/              # /ws/control、/tts、/voices、/asr
│  │  ├─ runtime/                # CharacterRuntime、ReplyPipeline、投影
│  │  ├─ session/                # SessionStore 与持久化模型
│  │  ├─ voices/                 # 音色档案、参考音频规范化、合成请求
│  │  ├─ models/                 # LLM / TTS / ASR 适配器
│  │  ├─ agent/                  # 人设与回复截断
│  │  └─ config.py               # pydantic-settings 配置
│  ├─ config/voices.json         # 内置音色档案
│  ├─ runtime/                   # 运行期产物（git 忽略）
│  └─ tests/
├─ services/indextts_service/    # IndexTTS-2.5 HTTP sidecar（56 tests）
├─ scripts/                      # sidecar 启停、ASR 下载、Live2D 资源准备
├─ shared/contracts/             # vob/1 schema + protocol.md（三处契约之一）
├─ docs/                         # 架构、协议覆盖、音色克隆
├─ docker/gpt-sovits/            # legacy GPT-SoVITS 推理
└─ assets/voices/                # 随仓库分发的参考音频
```

## 快速开始

以下命令默认在**仓库根目录**打开 PowerShell。后端起在 `127.0.0.1:8090`，IndexTTS sidecar 在 `127.0.0.1:9882`，Ollama 在 `127.0.0.1:11434`；标注「另开终端」的步骤需要保持前一个进程继续运行。

### 0. 前置条件

- Windows + PowerShell 5.1+。
- Python 3.11+（后端只跑 HTTP/协议；真实 TTS 需要 index-tts 自带 `.venv`，其中才有 torch）。
- Node.js 20+ 与 npm（桌面端）。
- 已安装 Ollama，并已拉取对话模型（默认 `qwen3:8b`）。
- 本地已有一份 `index-tts` 检出（通常位于 `default-workspace/index-tts`），包含 `.venv` 与 `checkpoints`。
- NVIDIA GPU 与可用驱动；8GB 显存机器请阅读「排障」中的显存争用一节。

```powershell
# 终端 A：保持 Ollama 服务运行
ollama serve

# 终端 B：首次拉取模型
ollama pull qwen3:8b
```

### 1. 启动 IndexTTS-2.5 sidecar

先指定 index-tts 检出目录（脚本不会修改模型仓库）：

```powershell
$env:INDEXTTS_HOME = "C:\path\to\default-workspace\index-tts"
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1
```

脚本会校验 `config.yaml`、`gpt.pth`、`s2mel.pth`、`codec.pth` 等文件，使用 `<INDEXTTS_HOME>\.venv\Scripts\python.exe`，并把 `TEMP`/`TMP`、`HF_HOME`、`TORCH_HOME`、`INDEXTTS_WORK_DIR` 重定向到 `<INDEXTTS_HOME>\.runtime\`（见「排障」的 Windows 沙箱一节）。终端保持打开，首次加载模型需要数十秒。

可选参数：

```powershell
# 微调权重 + 换端口（后端 INDEX_TTS_BASE_URL 要同步改）
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -ModelDir checkpoints_murasame -Port 9885

# 无 GPU 联调：MockEngine 返回 0.5s/22050Hz 测试 WAV
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -Mock

# 先起服务、不预加载（/synthesize 在加载前返回 503）
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -NoPreload
```

### 2. 等待模型就绪

另开一个终端（仍在仓库根）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\wait_for_indextts.ps1 -Port 9882 -TimeoutSeconds 300
```

就绪时输出 `{"status":"ready",...}` 并以 0 退出；超时输出 `{"status":"timeout",...}` 并以 1 退出。也可以直接看 `http://127.0.0.1:9882/health` 的 `loaded` 字段。

### 3. 启动后端

首次运行：

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

编辑 `backend/.env`（或直接设置环境变量），关键项：

```dotenv
TTS_PROVIDER=index_tts
INDEX_TTS_BASE_URL=http://127.0.0.1:9882
OLLAMA_MODEL=qwen3:8b
# 8GB 显存与 IndexTTS 共用时让 LLM 走 CPU，把显存留给 TTS
OLLAMA_NUM_GPU=0
```

启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

健康检查：`http://127.0.0.1:8090/health` 返回 `{"status":"ok"}`。

> 端口默认是 8090 而不是 8080：本机 8080 曾被系统占用且无法绑定（WinError 10013）。可用 `PORT` 或 `--port` 覆盖。

### 4. 启动桌面端

另开终端，在仓库根执行：

```powershell
Set-Location apps\desktop
npm install
npm run dev
```

窗口内可以输入文本并回车，后端会依次推送 `agent.text`、`tts.ready` 和音频 URL。后端地址由 preload 注入，默认 `ws://127.0.0.1:8090/ws/control`，可用环境变量覆盖：

```powershell
$env:VOB_CONTROL_URL = "ws://127.0.0.1:8090/ws/control"
npm run dev
```

Live2D 资源准备（可选；窗口内要看到角色才需要）：

- 仓库只带模型压缩包 `apps/desktop/src/renderer/public/live2d/mao_zh-Hans.zip`，解压后的资源写入被 `.gitignore` 忽略的 `apps/desktop/public/live2d/mao/`。
- 从 Live2D Cubism SDK for Web 取得 `live2dcubismcore.min.js`（受 Live2D 许可约束，不入库），设置 `VOB_LIVE2D_CORE` 后运行准备脚本：

```powershell
$env:VOB_LIVE2D_CORE = "C:\path\to\live2dcubismcore.min.js"
powershell -ExecutionPolicy Bypass -File scripts\prepare_live2d_assets.ps1
```

脚本会解压模型并复制 Core；之后 `npm run build` / `npm run dev`，控制器从 `live2d/mao/mao_pro.model3.json` 加载。缺少 Core 或模型时画布会提示加载失败，但控制通道、聊天和 TTS 不受影响。

### 5. 端口一览

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| `8090` | FastAPI 后端 | HTTP API + `ws://127.0.0.1:8090/ws/control` |
| `9882` | IndexTTS-2.5 sidecar | 默认 TTS，`GET /health`、`POST /synthesize` |
| `9880` | GPT-SoVITS | legacy 可选，`TTS_PROVIDER=gpt_sovits` 时使用 |
| `11434` | Ollama | 对话模型 |
| `5173` | Vite dev server | `npm run dev` 时的 Renderer |
| `9872` | GPT-SoVITS WebUI | 仅 legacy 的 `webui` profile，默认不启动 |

### 可选：ASR

`POST /asr` 需要本地 faster-whisper 模型。默认路径是 `docker/gpt-sovits/models/asr_models/faster-whisper-large-v3`（相对 `backend/`），可用 `ASR_MODEL_PATH` 覆盖。缺失时后端仍能启动、文本聊天不受影响，但 `/asr` 会失败。下载脚本：

```powershell
backend\.venv\Scripts\python.exe scripts\fetch_asr_model.py
```

## 协议与会话恢复

控制通道地址：

```text
ws://127.0.0.1:8090/ws/control?protocol=vob/1&session_id=<可选>&after=<可选 seq>
```

### 握手

```text
客户端                                      服务端
  │ ── WebSocket /ws/control?... ─────────▶ │
  │ ◀── server.ready ────────────────────── │  协议版本 + capabilities
  │ ◀── （after 命中时）事件重放 ─────────── │  与实时通知同形，带 seq
  │ ◀── session.opened ─────────────────── │  session_id / cursor / replayed
  │ ── session.hydrate ───────────────────▶ │
  │ ◀── session.state ──────────────────── │  权威快照
```

- `server.ready` 的 `payload.capabilities` 给出可用方法、通知与特性（`replay`、`hydrate`、`session-persistence`、`history`）。
- URL 带已有 `session_id` 且带 `after=N` 时，服务端按 `seq > N` 重放该会话账本事件，再发 `session.opened`；`replayed` 是本次重放条数。新建会话（不带 `session_id`）会忽略 `after`。
- 不带 `session_id` 会新建会话；带不存在的 id 会收到 `error{code:"session_not_found"}` 并关闭连接。
- 客户端发 `session.hydrate` 获得 `session.state`：transcript、turns、voice、character、`active_turn_id` 和 `cursor`。
- 桌面端把 `session_id` 与 `cursor` 写入 `localStorage`（`vob.session_id` / `vob.cursor`），重连时回填 `session_id` + `after`；收到 `session_not_found` 会清掉本地 id 并新建会话。

### 命令与通知

| 方向 | type |
| --- | --- |
| 客户端 → 服务端 | `session.open`、`session.hydrate`、`user.text`、`voice.select`、`tts.cancel`、`tts.finished` |
| 服务端 → 客户端 | `server.ready`、`session.opened`、`session.state`、`turn.started`、`agent.text`、`tts.started`、`tts.ready`、`tts.failed`、`tts.cancelled`、`tts.finished`、`voice.selected`、`character.state`、`turn.completed`、`turn.cancelled`、`turn.error`、`error` |

`tts.finished` 同时是命令与通知：客户端播放结束回报 `{tts_id}`，服务端把 `character.state` 投影回 `idle` 并广播。

一次 `user.text` 的正常时序：

```text
turn.started → character.state(thinking) → agent.text
             → tts.started → tts.ready → character.state(speaking)
             → turn.completed
             → （客户端播放结束）tts.finished → character.state(idle)
```

同一会话同时最多一个 active turn。新的 `user.text` 会取消旧 turn：合成中会先发 `tts.cancelled{reason:"interrupted"}` 与 `turn.cancelled{reason:"interrupted"}`；如果旧 turn 已经完成、只剩音频在播，则只补 `tts.cancelled` 与 `character.state(idle)`。`tts.cancel` 只取消 TTS：若仍在合成，回合随后以 `turn.completed` 收尾；若已 `ready`，回合此前已完成，只补 `tts.cancelled` 与 `idle`。

### 持久化布局

```text
backend/runtime/
├── audio/<audio_id>.wav                 # TTS 产物，GET /tts/{audio_id} 取回
├── voices/
│   ├── profiles.json                    # 用户克隆档案
│   └── <voice_id>/reference.wav         # 规范化后的参考音频
└── sessions/<session_id>/
    ├── meta.json                        # session_id / created_at / persona / voice_id
    ├── messages.jsonl                   # 已提交消息（append-only，含 audio_url 修订）
    └── events.jsonl                     # 事件账本（seq/type/payload/ts/reply_to）
```

- 先落盘账本再广播，保证「重放得到的 == 当时发出的」。
- 单会话事件上限默认 2000，超出从最旧裁剪；裁剪只影响 replay，hydrate 从 messages 重建 transcript。
- 会话 id 只允许 `[A-Za-z0-9_-]{1,64}`，目录名直接使用该 id，禁止路径穿越。

字段级定义、错误码与重放细节见 [`shared/contracts/protocol.md`](shared/contracts/protocol.md)；已实现/未实现覆盖与 v1 差异见 [`docs/PROTOCOL_COVERAGE.md`](docs/PROTOCOL_COVERAGE.md)。

## 音色与克隆

### 内置音色

`backend/config/voices.json` 内置 `murasame`（丛雨）：

```json
{
  "id": "murasame",
  "display_name": "丛雨",
  "language": "ZH",
  "reference_audio": "assets/voices/murasame/murasame_ref.wav",
  "duration_factor": 1.0,
  "builtin": true
}
```

参考音频路径相对**仓库根**解析；用户档案优先于同名内置档案。

### HTTP 接口

```text
GET    /voices                 列出音色与 default_voice_id
POST   /voices                 上传参考音频克隆音色（multipart: name, audio, language）
DELETE /voices/{voice_id}      删除用户克隆音色（内置音色 409）
POST   /tts                    单次合成 {text, voice_id?}，返回 audio/wav
GET    /tts/{audio_id}         取回已保存的 WAV
```

克隆示例：

```powershell
curl.exe -X POST http://127.0.0.1:8090/voices `
  -F "name=我的声音" `
  -F "language=ZH" `
  -F "audio=@C:\path\to\reference.wav"
```

成功返回 `201` 与音色对象；后端用 PyAV 解码并规范化为 16-bit 单声道 WAV，时长必须在 **1–60 秒**。`POST /voices` 失败返回 `400`（无法解码、时长越界、语种不支持）或 `422`（缺少 multipart 字段）；`DELETE /voices/{voice_id}` 返回 `204`，删除内置音色为 `409`，不存在为 `404`。

细节与请求/响应示例见 [`docs/VOICE_CLONING.md`](docs/VOICE_CLONING.md)。

### WebSocket 选音色

发送：

```json
{ "protocol": "vob/1", "id": "...", "ts": 0, "type": "voice.select", "payload": { "voice_id": "murasame" } }
```

服务端校验后更新会话 `meta.json.voice_id` 并广播 `voice.selected{voice_id, display_name}`；未知音色回 `error{code:"voice_not_found"}`，连接保持。该选择立即影响下一次合成。

### 参考音频要求

- 1–60 秒、单人、干净人声，尽量无背景音乐、混响和噪声。
- 16-bit PCM 单声道 WAV 最稳妥；MP3/M4A/OGG 等也可，后端会解码并统一为 44.1kHz（WAV 源保留原采样率）。
- 不需要和合成文本同语言：音色由参考音频决定，发音语言由音色档案的 `language`（`ZH`/`EN`/`JA`/`ES`/`AR`）决定。
- 参考音频只用于零样本克隆，不用于训练；上传前必须确认你拥有声音本人的授权。

### 情感与语速

音色档案支持 `emotion` 与 `duration_factor` 默认值（写在 `backend/config/voices.json` 或 `backend/runtime/voices/profiles.json`；当前 HTTP 克隆接口不暴露这两个字段）。

- IndexTTS 情感向量固定 **8 维**，顺序为 **喜、怒、哀、惧、厌恶、低落、惊喜、平静**；每维 0–1，**总和必须 ≤ 0.8**。`alpha` 是情感强度，0–1。
- `emotion.mode` 可为 `vector` / `text` / `audio`。当前 `checkpoints` 与 `checkpoints_murasama` 都没有 QwenEmotion 资源，`text` 模式会被 sidecar 以 400 拒绝（后端表现为 `tts.failed`）；`vector` 与 `audio` 可用。
- `duration_factor` 范围 **0.5–2.0**，默认 1.0；小于 1 更快，大于 1 更慢。

### 切换 base / 微调权重

```powershell
# 原始 IndexTTS-2.5 权重（默认）
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -ModelDir checkpoints

# 丛雨微调权重（目录结构相同，端口示例 9885）
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -ModelDir checkpoints_murasama -Port 9885
```

切到 9885 后，后端 `.env` 需要同步：

```dotenv
INDEX_TTS_BASE_URL=http://127.0.0.1:9885
```

两个目录各自带 `config.yaml` 与 `hf_cache/`，不要混用文件。微调权重仍需参考音频做零样本克隆；音色相似度是否优于 base 权重取决于微调数据质量，不要把「微调」当成「免参考音频」。

## 测试

```powershell
# 后端 108 tests + ruff
backend\.venv\Scripts\python.exe -m pytest backend -q
backend\.venv\Scripts\python.exe -m ruff check backend\app backend\tests services\indextts_service

# IndexTTS sidecar 56 tests（不需要 GPU/torch）
backend\.venv\Scripts\python.exe -m pytest services\indextts_service\tests -q

# 桌面 typecheck / build
Set-Location apps\desktop
npm run typecheck
npm run build

# 端到端 smoke（需先启动 sidecar + 后端 + Ollama）
# sidecar 可用 scripts\start_indextts.ps1 -Mock 做无 GPU 联调
backend\.venv\Scripts\python.exe scripts\e2e_ws_smoke.py

# Electron 渲染截图（可选，需先准备 Live2D 资源）
# 1) 静态服务 out/renderer；2) 用本地 Electron 截图
python -m http.server 4173 --bind 127.0.0.1 --directory out\renderer
node_modules\electron\dist\electron.exe ..\scripts\capture_ui.cjs
```

说明：

- `backend\.venv` 里有 fastapi/httpx/pytest/ruff/av，但**没有 torch**，不能用来加载真实 IndexTTS。
- sidecar 测试全部用 MockEngine 与 `httpx.MockTransport`，不依赖 GPU。
- 真实 GPU 合成、HTTP `/tts`、`/voices` 与 WebSocket 全链路属于端到端验证，不在默认测试集内。

## 排障

### 8GB 显存争用（IndexTTS 与 Ollama）

IndexTTS-2.5 与 `qwen3:8b` 同时占 GPU 时，8GB 显存会明显变慢，甚至 OOM。优先让 LLM 走 CPU：

```dotenv
OLLAMA_NUM_GPU=0
OLLAMA_NUM_CTX=4096
```

- `OLLAMA_NUM_GPU` 不设置时由 Ollama 自动分配；设为 `0` 强制 CPU。设为 `0` 后 LLM 首字会变慢，但 TTS 更稳定。
- 不建议为了「更快」把 `OLLAMA_NUM_CTX` 调大：Ollama 默认上下文可能分配过大的 KV cache，本项目显式使用 4096。
- 合成期间关闭其他占用显存的程序（Stable Diffusion、其他推理服务、游戏）。
- 如果 TTS 报 `tts_unavailable` / `model_loading` / 超时，先看 sidecar `/health` 的 `loaded` 与终端日志。

### `httpx` 代理环境变量导致 `InvalidURL`

后端在 `app/main.py` 创建 `httpx.AsyncClient` 时显式使用 `trust_env=False`。如果你在本机设置了 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`，httpx 0.28 在解析 `NO_PROXY` 时可能抛 `InvalidURL`。不要通过删除 `trust_env=False` 来「修复」；新增的 httpx 客户端也应显式关闭环境代理，或确保代理变量与 `NO_PROXY` 一致。

### Windows 沙箱：index-tts venv 只能写 `default-workspace`

本机 DSH 沙箱限制下，index-tts 虚拟环境的解释器只能写 `default-workspace` 内的路径。因此：

- sidecar 不向仓库目录写文件；推理临时 WAV 写到 `INDEXTTS_WORK_DIR`（默认 `<INDEXTTS_HOME>\.runtime\indextts_service`），读取后立即删除。
- `scripts/start_indextts.ps1` 把 `TEMP`/`TMP`、`HF_HOME`、`TORCH_HOME`、`INDEXTTS_WORK_DIR` 都重定向到 `<INDEXTTS_HOME>\.runtime\`。
- 不要把 `INDEXTTS_WORK_DIR` 指向仓库、系统临时目录或其他受限路径，否则可能被沙箱拒绝。
- 遇到 `Permission denied` / `Access is denied` 时，先确认 `INDEXTTS_HOME` 在可写工作区内。

### ASR 模型缺失

`/asr` 使用 `ASR_MODEL_PATH`，默认指向 `docker/gpt-sovits/models/asr_models/faster-whisper-large-v3`。模型缺失时：

- 后端仍能启动，文本聊天与 TTS 不受影响；
- `POST /asr` 失败（转写层抛 `AsrUnavailable`），桌面端显示录音失败；
- 运行 `backend\.venv\Scripts\python.exe scripts\fetch_asr_model.py` 下载，或把 `ASR_MODEL_PATH` 指向已有的 CTranslate2 模型目录；
- 默认 `ASR_DEVICE=cpu`、`ASR_COMPUTE_TYPE=int8`，不依赖主机 CUDA 库；改用 GPU 需要 CUDA 12.x 与对应 cuDNN。

### Sidecar 起不来、一直 503 或请求排队

- `/health` 的 `loaded=false` 且 `/synthesize` 返回 `503 model_loading`：模型仍在加载，用 `wait_for_indextts.ps1` 等待；加载失败会打印 traceback 并以非零码退出。
- `start_indextts.ps1` 提示缺少 `config.yaml` / `gpt.pth` / `s2mel.pth` / `codec.pth`：`-ModelDir` 指错了，或模型未下载完整。
- 提示找不到解释器：必须使用 `<INDEXTTS_HOME>\.venv\Scripts\python.exe`，不要用 `backend\.venv`（没有 torch）。
- 端口冲突：默认 9882；换端口时同步 `INDEX_TTS_BASE_URL`。
- **合成超时后下一句一直排队**：sidecar 用一把全局锁串行「加载 + 推理」，单卡不会并发推理。sidecar 侧超时（默认 180s）会返回 `500 synthesis_failed`，但推理线程无法被中止，锁会一直持有到该次推理真正结束，后续请求在锁上排队。后端/客户端先超时也不会让它开始第二次推理。处理方式：等当前推理结束或重启 sidecar；同时缩短回复（后端已截断到 300 字）、关闭其他 GPU 程序，并让 Ollama 走 CPU（`OLLAMA_NUM_GPU=0`）。

### 协议/连接问题

- `protocol_mismatch`：URL 的 `protocol` 或消息信封的 `protocol` 字段存在但不是 `vob/1`。连接会以 close code `1008` 关闭；字段**缺失**属于 `invalid_message`。
- `session_not_found`：本地保存的会话已被清理；桌面端会自动新建。也可以在连接 URL 中去掉 `session_id`。
- `invalid_message`：JSON 非法、payload 多余字段、空文本、非法 `session_id`/`after` 等。
- `unsupported_type`：把服务端通知（如 `agent.text`）当成命令发给了服务端。
- CORS：后端只放行 `Origin: null`（Electron `file://`）与 `http://127.0.0.1|localhost:*`。改用其他主机名/端口访问时，需要同步调整 `backend/app/main.py` 的 `allow_origin_regex`，不要直接改成 `*`。
- 连不上 `8090`：确认 uvicorn 已启动、端口未被占用、Windows 防火墙未拦截本机回环。

### 参考音频/克隆失败

- `400 参考音频时长必须在 1–60 秒之间`：裁剪或补足音频。
- `400 无法解码参考音频`：换 WAV/MP3 等常见格式；损坏文件或非音频文件会被拒绝。
- `409 内置音色不可删除`：`murasame` 由 `backend/config/voices.json` 提供，只能删除用户克隆档案。
- 克隆成功但合成不像：参考音频太短、噪声大、混响重，或音色档案的 `language` 与你要合成的语言不一致。先用较干净的单人片段（5–15 秒）验证。

## 已知限制

- **Electron 窗口内的播放、停止、克隆面板交互未自动验证**；本文不宣称这些 UI 行为已经验收。
- Live2D 解压后的模型与 Cubism Core 不随仓库分发（`apps/desktop/public/live2d/` 被忽略）；用 `scripts/prepare_live2d_assets.ps1` 准备。缺少资源时角色画布不可用，但协议与 TTS 链路不受影响。
- 仅 Mao 示例模型用于加载/动作/表情验证；丛雨专属 Live2D、正式表情映射与自然口型同步未完成。口型由播放状态驱动 `ParamA`，不做音频振幅分析。
- Memory / Relationship / Vision / OCR / Action Controller / World 未实现。
- 情绪状态机未实现：`character.state.emotion` 恒为 `null`。
- 无 VAD、实时音频流、流式 TTS；必须等完整 WAV 就绪后播放。
- IndexTTS sidecar 单卡串行；合成超时不会中止推理线程，后续请求会排队（见「排障」）。
- 单会话同时只允许一个 active turn；一个连接同一时刻只绑定一个会话（`session.open` 可切换）。
- 事件不做 WAL/事务恢复；进程崩溃可能丢最后一条正在写的行，JSONL 加载器会丢弃末尾半行并记录日志。
- 会话事件上限 2000，超出后 replay 无法回到更早事件；transcript 仍从 messages 重建。
- 不做 LLM 摘要压缩，只做历史窗口裁剪（默认最近 12 条 / 4000 字符）。
- GPT-SoVITS 训练流程不搬入本仓库；legacy 推理仍依赖原 Docker 镜像与本地权重。
- 8GB 显存下 IndexTTS 与 Ollama 同时占 GPU 会显著变慢；建议 `OLLAMA_NUM_GPU=0`。

## 许可与授权

- **项目代码**：本仓库为 MIT（见 `LICENSE`）。
- **IndexTTS-2.5**：模型与推理代码来自上游 index-tts 项目，使用前请阅读其仓库与模型卡许可；本仓库不重新分发模型权重。`services/indextts_service` 只是本地 sidecar 封装。
- **GPT-SoVITS（legacy）**：镜像、预训练/微调权重与数据集各自受上游许可约束；本仓库不携带权重。训练数据审计见 [`docs/murasame-dataset-audit.md`](docs/murasame-dataset-audit.md)。
- **参考音频与声音克隆**：只能使用你拥有授权的声音。未经本人同意克隆真实人物声音可能违法或违反平台条款。`assets/voices/README.md` 记录目录约定与授权要求；用户上传的参考音频保存在 `backend/runtime/voices/`（git 忽略）。
- **Live2D**：Cubism Core / SDK 受 Live2D 许可约束；示例模型受其压缩包内的 Free Material License Agreement 与 Terms of Use 约束。模型与 Core 不随仓库分发，使用前自行确认许可。
- **角色与素材**：丛雨及相关作品素材的权利归原权利人；本仓库仅用于本地技术原型，不用于商业分发。

## 相关文档

- [`docs/ARCHITECTURE_V2.md`](docs/ARCHITECTURE_V2.md)：v2 架构定稿、目录、持久化、错误码、CORS、Ollama 参数与限制。
- [`docs/PROTOCOL_COVERAGE.md`](docs/PROTOCOL_COVERAGE.md)：已实现命令/通知、未实现能力、与 v1 的差异、与 octos-ts 设计的关系。
- [`docs/VOICE_CLONING.md`](docs/VOICE_CLONING.md)：克隆流程、sidecar API、音色档案字段、情感/语速、base vs 微调、许可。
- [`shared/contracts/protocol.md`](shared/contracts/protocol.md)：`vob/1` 字段级协议。
- [`services/indextts_service/README.md`](services/indextts_service/README.md)：sidecar 环境变量、API 与 Mock 模式。
- [`docker/gpt-sovits/README.md`](docker/gpt-sovits/README.md)：legacy GPT-SoVITS 的容器路径映射。
