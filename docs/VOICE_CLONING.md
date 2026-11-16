# 音色克隆与 IndexTTS-2.5 sidecar

本文描述当前实现的零样本（zero-shot）音色克隆链路：参考音频如何进入系统、音色档案有哪些字段、后端如何调用 sidecar、情感与语速怎么设置，以及模板权重与微调权重、许可与合规的边界。

> 结论先行：这是**参考音频驱动的零样本克隆**，不是训练。克隆只改变音色，不改变模型权重；参考音频与音色档案的授权由使用者负责。

## 1. 组件与数据流

```text
Electron 克隆面板
  │  multipart: name / audio / language
  ▼
POST /voices（backend/app/transport/voices_http.py）
  │  PyAV 解码 → 16-bit mono WAV → 校验 1–60s
  ▼
backend/runtime/voices/<voice_id>/reference.wav
backend/runtime/voices/profiles.json            # VoiceProfile
  │
  │  GET /voices / voice.select
  ▼
ReplyPipeline（backend/app/runtime/pipeline.py）
  │  build_synthesis_request(text, profile)
  ▼
IndexTtsProvider（backend/app/models/tts/index_tts.py）
  │  POST http://127.0.0.1:9882/synthesize
  ▼
services/indextts_service（IndexTTS-2.5 sidecar）
  │  真实模型推理（GPU），返回 audio/wav
  ▼
AudioStore → backend/runtime/audio/<audio_id>.wav
  │
  └─ tts.ready{audio_url:"/tts/<audio_id>"}
```

关键边界：

- **克隆档案**是进程级资源，由 `VoiceRegistry` 管理；**当前音色**是会话级状态，存在 `sessions/<id>/meta.json.voice_id`。
- 后端只把参考音频的**绝对路径**交给 sidecar；sidecar 不读取仓库配置，也不写仓库目录。
- 克隆不训练、不更新任何 `.pth` 权重；同一套权重可以服务任意多个音色档案。

## 2. HTTP 接口

### `GET /voices`

```json
{
  "default_voice_id": "murasame",
  "voices": [
    {
      "id": "murasame",
      "display_name": "丛雨",
      "language": "ZH",
      "description": "内置音色：IndexTTS-2.5 零样本克隆……",
      "is_builtin": true
    }
  ]
}
```

- 用户档案排在后面；同 id 时用户档案覆盖内置档案。
- `is_builtin` 对应前端展示的「（内置）」标签。

### `POST /voices`

`multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 展示名，去除首尾空白后不能为空（桌面端输入框限制 64 字符） |
| `audio` | 是 | 参考音频文件，任意 PyAV 可解码的容器 |
| `language` | 否 | `ZH`（默认）/`EN`/`JA`/`ES`/`AR`，大小写不敏感 |

处理步骤：

1. 校验名称、语种、文件非空；
2. 由展示名生成 id（小写、空格转 `-`；中文等无法 slug 时生成 `voice-<8位hex>`；重名追加 `-2`、`-3`）；
3. PyAV 解码为 16-bit 单声道 WAV：
   - WAV 源保留原采样率；
   - 非 WAV 源统一 44.1kHz；
4. 校验时长 **1–60 秒**；
5. 原子写入 `backend/runtime/voices/<voice_id>/reference.wav`；
6. 写 `profiles.json`；
7. 返回 `201` 与音色对象。

状态码：

| 状态 | 场景 |
| --- | --- |
| `201` | 克隆成功 |
| `400` | 名称为空、语种不支持、文件为空、无法解码、时长不在 1–60 秒 |
| `422` | 缺少 multipart 字段（FastAPI 校验） |

### `GET /voices/{voice_id}/sample`

返回该档案的参考音频（`audio/wav`），用于桌面端“试听”按钮；未知音色 `404`。只返回注册表里已存在的档案路径，不接受任意文件路径。

### `DELETE /voices/{voice_id}`

| 状态 | 场景 |
| --- | --- |
| `204` | 删除成功；同时删除 `runtime/voices/<voice_id>/` |
| `404` | 用户档案不存在 |
| `409` | 目标是内置音色（`murasame`），受保护不可删除 |

### `POST /tts`

单次合成，便于脚本/调试：

```json
{ "text": "ご主人様、おはようございます。", "voice_id": "murasame" }
```

- `voice_id` 省略时使用 `default_voice_id`；
- 成功返回 `200`、`Content-Type: audio/wav`、WAV 字节；
- 未知音色 `404`；sidecar 不可用 `503`；空文本 `422`。

### WebSocket `voice.select`

```json
{ "protocol": "vob/1", "id": "...", "ts": 0, "type": "voice.select", "payload": { "voice_id": "murasame" } }
```

成功广播：

```json
{ "type": "voice.selected", "payload": { "voice_id": "murasame", "display_name": "丛雨" } }
```

未知音色回 `error{code:"voice_not_found"}`，连接保持。选择立即影响**下一次**合成；已经在合成中的 TTS 使用开始时解析出的音色。

## 3. 音色档案字段

`VoiceProfile`（`backend/app/voices/models.py`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | `[a-z0-9_-]{1,64}`，同时是目录名 |
| `display_name` | string | 展示名，非空 |
| `language` | string | `ZH` / `EN` / `JA` / `ES` / `AR` |
| `reference_audio` | string | 内置档案相对仓库根；用户档案优先相对仓库根，仓库外路径保留绝对路径 |
| `description` | string | 展示用描述，默认空 |
| `emotion` | object \| null | 默认情感，见第 6 节 |
| `duration_factor` | float | 语速系数，`>0`，实际可用范围 0.5–2.0 |
| `builtin` | bool | 内置标记；内置档案不可删除 |
| `gpt_sovits` | object \| null | 仅 legacy GPT-SoVITS 使用，见第 9 节 |

内置档案文件：`backend/config/voices.json`；用户档案文件：`backend/runtime/voices/profiles.json`。两者格式相同：

```json
{
  "default_voice_id": "murasame",
  "voices": [
    {
      "id": "my-voice",
      "display_name": "我的声音",
      "language": "ZH",
      "reference_audio": "runtime/voices/my-voice/reference.wav",
      "description": "",
      "emotion": { "mode": "vector", "vector": [0.3, 0, 0, 0, 0, 0, 0, 0.2], "alpha": 0.6 },
      "duration_factor": 1.0,
      "builtin": false,
      "gpt_sovits": null
    }
  ]
}
```

> 当前 `POST /voices` 只设置名称、语种、参考音频和描述；`emotion` / `duration_factor` 需要直接编辑档案 JSON，然后重启后端（注册表在启动时加载）。不要通过 HTTP 上传未授权的参考音频。

## 4. 参考音频要求

后端强制：

- **1–60 秒**；不足 1 秒或超过 60 秒直接 `400`；
- 必须包含音频轨道、可被 PyAV/FFmpeg 解码；
- 统一转为 16-bit 单声道 PCM WAV。

建议：

- 单人、干净、无背景音乐/噪声/明显混响；
- 3–15 秒通常足够；过短音色不稳，过长会增加处理时间且不一定更好；
- 16-bit PCM WAV 最稳妥；MP3/M4A/OGG 也可；
- 避免削波（爆音）、避免多人对话、避免笑声/喊叫等非语音片段；
- 参考音频的语言不必与合成文本一致：音色来自参考音频，发音语言由档案的 `language` 决定；
- 参考音频只影响音色，不会被写入模型或训练数据。

## 5. 调用 sidecar（IndexTTS-2.5）

默认地址 `http://127.0.0.1:9882`（`INDEX_TTS_BASE_URL`），超时 `INDEX_TTS_TIMEOUT_SECONDS=180`。

### `GET /health`

```json
{
  "status": "ok",
  "engine": "index_tts_2",
  "loaded": true,
  "device": "cuda:0",
  "model_dir": "<INDEXTTS_MODEL_DIR>"
}
```

`loaded=false` 时 `/synthesize` 返回 `503 model_loading`（带 `Retry-After: 5`）。

### `POST /synthesize`

```json
{
  "text": "ご主人様、今日もお疲れ様でした。",
  "reference_audio": "<绝对路径>/reference.wav",
  "language": "JA",
  "emotion": { "mode": "vector", "vector": [0.2, 0, 0, 0, 0, 0, 0, 0], "alpha": 0.6 },
  "duration_factor": 1.0,
  "text_normalization": true,
  "max_text_tokens_per_segment": 120,
  "request_id": "optional-trace-id"
}
```

| 字段 | 规则 |
| --- | --- |
| `text` | 1–2000 字符，不能全为空白 |
| `reference_audio` | **绝对路径**，文件存在、是普通文件、可读 |
| `language` | `ZH`（默认）/`EN`/`JA`/`ES`/`AR`，大小写不敏感 |
| `emotion` | 可选，三种模式互斥，见第 6 节 |
| `duration_factor` | 0.5–2.0，默认 1.0 |
| `text_normalization` | 默认 `true` |
| `max_text_tokens_per_segment` | 正整数，默认 120 |
| `request_id` | 可选，原样用于排查 |

成功：`200`、`Content-Type: audio/wav`、`X-Sample-Rate: 22050`，响应体为完整 WAV。

失败：

```json
{ "detail": { "code": "invalid_request", "message": "请求参数无效: ..." } }
```

| 状态 | code | 场景 |
| --- | --- | --- |
| `400` | `invalid_request` | 参考音频无法读取、模型侧参数错误 |
| `400` | `emotion_unavailable` | 请求 `emotion.mode=text`，但模型缺少 QwenEmotion 资源 |
| `422` | `invalid_request` | 请求体校验失败（路径、范围、枚举、长度等） |
| `500` | `synthesis_failed` | 推理异常或超时 |
| `503` | `model_loading` | 模型未加载完成 |

### 单卡串行与超时语义（重要）

sidecar 内部用**一把全局锁**串行化「模型加载」与「推理」，同一进程不会出现两次推理并发。由此带来两个可观察行为：

- 请求超时（sidecar 侧默认 `INDEXTTS_REQUEST_TIMEOUT_SECONDS=180`）时，`/synthesize` 返回 `500 synthesis_failed`，但**推理线程无法被真正中止**；锁会一直持有到该次推理实际结束，后续请求在锁上排队。
- 后端/客户端先超时断开，也不会让 sidecar 开始第二次推理；你看到的是「排队等待」而不是并发争抢显存。

在 8GB 显卡上，这通常表现为：第一句很慢 → 后端先报 `tts_unavailable` → sidecar 仍在算 → 下一句继续排队。处理方式是缩短回复、关闭其他 GPU 程序，并让 Ollama 走 CPU（`OLLAMA_NUM_GPU=0`）。后端已把角色回复截断到 **300 字**，以降低单次合成时长。

## 6. 情感控制

`EmotionSpec`（`backend/app/models/tts/base.py`）与 sidecar 的 `emotion` 字段：

```json
{ "mode": "vector", "vector": [0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1], "alpha": 0.6 }
```

### 向量顺序

IndexTTS-2.5 的情感向量固定 8 维，顺序为：

| 下标 | 情感 |
| --- | --- |
| 0 | 喜 |
| 1 | 怒 |
| 2 | 哀 |
| 3 | 惧 |
| 4 | 厌恶 |
| 5 | 低落 |
| 6 | 惊喜 |
| 7 | 平静 |

规则：

- 每维 `0.0–1.0`；
- **8 维总和必须 ≤ 0.8**（sidecar 会拒绝更大的值）；
- `alpha` 是情感强度，`0.0–1.0`，默认 1.0。

例：温柔平静 → `[0,0,0,0,0,0,0,0.5]`；轻微喜悦 → `[0.3,0,0,0,0,0,0,0.2]`（总和 0.5）。

### 三种模式

| `mode` | 字段 | 当前可用性 |
| --- | --- | --- |
| `vector` | `vector`（8 维） | 可用 |
| `text` | `text`（如「开心地说话」） | **当前不可用**：`checkpoints` 与 `checkpoints_murasama` 都没有 QwenEmotion 资源，返回 `400 emotion_unavailable` |
| `audio` | `audio`（绝对路径） | 可用；需要可读的参考情感音频 |

如果后续把 `qwen0.6bemo4-merge/` 放入模型目录，sidecar 会自动检测并允许 `text` 模式。当前不要依赖它。

### 配置位置

`emotion` 只来自音色档案（`config/voices.json` / `runtime/voices/profiles.json`），并由 `build_synthesis_request` 原样传给 sidecar。HTTP `/voices` 与 WebSocket `voice.select` 不接收情感参数；需要默认情感时编辑档案并重启后端。

## 7. 语速：`duration_factor`

- 范围 **0.5–2.0**，默认 `1.0`；
- 小于 1 更快，大于 1 更慢；
- 超出范围时 sidecar 返回 `422 invalid_request`，后端映射为 `tts.failed{code:"tts_unavailable"}`，文本仍保留在 transcript；
- 它只影响时长，不改变音高（具体听感由模型决定，不要承诺「不变调」之外的细节）。

## 8. base 权重 vs 微调权重

IndexTTS-2.5 的模型目录由 `INDEXTTS_MODEL_DIR` 指定，脚本默认 `checkpoints`：

```powershell
# 原始权重
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -ModelDir checkpoints

# 丛雨数据微调的权重
powershell -ExecutionPolicy Bypass -File scripts\start_indextts.ps1 -ModelDir checkpoints_murasama -Port 9885

# 后端切换到 9885
# backend/.env
# INDEX_TTS_BASE_URL=http://127.0.0.1:9885
```

- 两个目录结构相同，各自带 `config.yaml` 与 `hf_cache/`，可以独立切换，不要混用文件。
- 微调只改变「模型本身对丛雨音色的先验」；仍然需要参考音频做零样本克隆，仍然受参考音频质量影响。
- 微调权重的相似度是否更好取决于训练数据与标注质量，不能用「已微调」替代听感验收。
- 当前两个目录都没有 QwenEmotion 资源，因此 `emotion.mode=text` 都不可用；`vector` / `audio` 不受影响。
- 切换权重不会自动迁移运行中的 sidecar；需要重启 sidecar 并确认 `/health.model_dir` 与 `loaded`。

## 9. 与 legacy GPT-SoVITS 的关系

- 默认 `TTS_PROVIDER=index_tts`；GPT-SoVITS 只在显式设置 `TTS_PROVIDER=gpt_sovits` 时启用。
- legacy 的容器路径/prompt 来自音色档案的 `gpt_sovits` 段，例如内置丛雨档案：

```json
"gpt_sovits": {
  "refer_wav_path": "/workspace/data/references/murasame_ref.ogg",
  "prompt_text": "はっはっはっは",
  "prompt_language": "ja"
}
```

- 这些是**容器内路径**，只在 Docker compose 的 `/workspace` 挂载下有效；IndexTTS 会忽略这个段。
- `text_language` 由档案 `language` 映射（`ZH→zh`、`JA→ja` 等），也可以在 `gpt_sovits` 里显式覆盖。
- 启动与路径映射见 [`../docker/gpt-sovits/README.md`](../docker/gpt-sovits/README.md)。
- GPT-SoVITS 训练流程不在本仓库；这里只保留 legacy 推理适配。

## 10. 与 `default-workspace/index-tts` 的关系

IndexTTS 模型与推理代码来自仓库外的 `index-tts` 检出（通常位于 `default-workspace/index-tts`），本仓库**不复制、不修改**它：

- sidecar 启动时必须使用 `<INDEXTTS_HOME>\.venv\Scripts\python.exe`（其中才有 torch）；`backend\.venv` 没有 torch，只能跑测试与 ruff。
- sidecar 导入 `indextts.infer_v2_5`。包名刻意叫 `services.indextts_service`，避免仓库根出现 `indextts/` 包遮蔽真实模型库。
- 模型目录、配置、临时文件全部在 `INDEXTTS_HOME` 下；`INDEXTTS_WORK_DIR` 默认 `<INDEXTTS_HOME>\.runtime\indextts_service`。
- 本机 Windows 沙箱下，index-tts 的 venv 只能写 `default-workspace` 内的路径；因此不要把握手目录指向仓库或系统临时目录，启动脚本已把 `TEMP`/`TMP`、`HF_HOME`、`TORCH_HOME`、`INDEXTTS_WORK_DIR` 重定向到 `<INDEXTTS_HOME>\.runtime\`。
- 模型权重（`*.pth` / `*.ckpt`）与 `docker/gpt-sovits/models/` 都在 `.gitignore` 中，不随仓库分发。

## 11. 许可与合规

- **IndexTTS-2.5**：模型与代码受上游 index-tts 仓库与模型卡许可约束。使用、商用、再分发前请阅读上游许可；本仓库只提供本地 sidecar 封装，不附带权重。
- **GPT-SoVITS（legacy）**：镜像、预训练权重、微调权重和训练数据各自受其许可约束；本仓库不附带权重。训练数据审计见 [`murasame-dataset-audit.md`](murasame-dataset-audit.md)。
- **声音授权**：只克隆你拥有明确授权的声音。未经本人同意克隆真实人物（尤其是公众人物）可能侵犯人格权/声音权益，或违反平台条款。上传者应自行保存授权证明。
- **参考音频**：`assets/voices/murasame/murasame_ref.wav` 仅作为本地技术原型的示例；其权利归原权利人，不构成对外分发授权。用户上传的参考音频保存在 `backend/runtime/voices/`，该目录被 git 忽略。
- **Live2D**：与克隆无关，但同属素材合规范围；Cubism Core/SDK 与示例模型受 Live2D 许可约束，模型不随仓库分发。

## 12. 常见问题

| 现象 | 排查 |
| --- | --- |
| 克隆返回 `400 时长` | 参考音频不足 1 秒或超过 60 秒 |
| 克隆返回 `400 无法解码` | 文件损坏、不是音频、或 FFmpeg 不支持的容器；换 WAV/MP3 |
| 克隆成功但声音不像 | 参考音频噪声大/混响重/太短；换 5–15 秒干净单人片段 |
| 合成 `tts.failed{tts_unavailable}` | 先看 sidecar `/health` 与终端日志；常见原因是未加载完成（503）、超时（500）、显存不足 |
| 第一句后一直排队 | sidecar 单卡串行；上一次推理未结束（超时也不会中止线程），等它结束或重启 sidecar |
| 合成很慢 | 8GB 显存与 Ollama 争用；设 `OLLAMA_NUM_GPU=0`，缩短回复，关闭其他 GPU 程序 |
| 文本情感报 `emotion_unavailable` | 当前没有 QwenEmotion 资源；改用 `vector` / `audio` |
| `voice.select` 返回 `voice_not_found` | 音色 id 不在 `GET /voices` 列表；克隆后先刷新列表 |
| 删除内置音色 `409` | `murasame` 受保护；只能删除用户克隆档案 |
| 重启后克隆档案还在但列表为空 | 检查 `backend/runtime/voices/profiles.json` 是否损坏；注册表会忽略无效用户档案并记录日志 |

## 13. 相关文档

- [`../README.md`](../README.md)：快速开始、端口、排障与限制。
- [`../shared/contracts/protocol.md`](../shared/contracts/protocol.md)：`voice.select` / `voice.selected` / `tts.*` 的字段级协议。
- [`../services/indextts_service/README.md`](../services/indextts_service/README.md)：sidecar 环境变量、Mock 模式与 API 细节。
- [`../docker/gpt-sovits/README.md`](../docker/gpt-sovits/README.md)：legacy 容器路径映射。
- [`../assets/voices/README.md`](../assets/voices/README.md)：参考音频目录约定与授权。
