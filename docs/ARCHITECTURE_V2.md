# virtual-original-bot v2 架构（定稿）

> 状态：与当前实现一致（2026-11）
> 参考：`octos-ts` 的「内核 + 协议边界 + 事件账本 + 投影 + 覆盖清单」设计
> 范围：文本/语音 → Agent → TTS → 播放、音色档案/零样本克隆，以及 Memory MVP（显式指令 + 关系值）；Vision / Action / World 仍为后续阶段。

## 1. 目标

1. 把 FastAPI 后端从「transport 里直接编排模型调用」改造成**角色运行时（Character Runtime）**：会话、回合、事件账本与状态投影归后端所有。
2. 控制通道升级为**版本化协议 `vob/1`**：能力协商、命令/通知分离、持久事件 `seq`、断线重放（`after` 游标）与 `hydrate` 恢复。
3. 用 **Ports & Adapters** 隔离模型：LLM（Ollama）、ASR（faster-whisper）、TTS（IndexTTS-2.5 sidecar 默认，GPT-SoVITS legacy）、AudioStore。
4. 把 `default-workspace/index-tts` 中的 IndexTTS-2.5 零样本克隆接入为默认 TTS，并支持音色档案与参考音频克隆。
5. 让契约可验证：同一份协议在 JSON Schema、pydantic、TypeScript 三处镜像，并用测试强制一致；文档提供覆盖清单与差异表。

## 2. 非目标

- 不做通用 coding agent：不引入工具调用、审批、MCP、工作流、子代理、上下文压缩、代码工作区。
- 不实现 Memory 的自动抽取/向量检索/长期关系事件；不实现 Vision / OCR / Action Controller / World（保留目录与文档规划）。
- 不把 GPT-SoVITS 训练流程搬进本仓库；legacy 推理适配器保留。
- 不承诺 Electron 窗口内的音频播放与克隆面板交互可自动化验收；由人工验收并如实记录。
- 不做公网部署、鉴权、多租户；当前是 `127.0.0.1` 本地单用户原型。

## 3. 与 v1 的关系

原仓库 README 已经写了 Modular Monolith / Layered / Event-driven / Ports and Adapters 的目标，但重构前的代码只实现了其中一小部分：

| 目标能力 | v1 实现 | v2 实现 |
| --- | --- | --- |
| Ports & Adapters | LLM/ASR/TTS 适配器雏形；TTS 参考路径硬编码在 `control_ws.py` | `app/models/tts/base.py` 定义 `TtsProvider`/`SynthesisRequest`；`factory.py` 选择 Provider；音色档案解耦路径与 prompt |
| 事件驱动 | 一次性 WebSocket 消息，无持久账本 | `events.jsonl` + `seq`；turn/character 状态由事件推导 |
| 会话状态 | `SessionState` 只记 active_task / tts | `SessionStore` 持久化 meta/messages/events，支持重连、重放、hydrate |
| 控制协议 | 无版本、无能力协商、payload 无闭合校验 | `vob/1` 信封、capabilities、命令/通知、错误码、schema 一致性测试 |
| 状态投影 | 前端各自维护布尔量 | `character.state` 投影 + hydrate 快照 |
| 覆盖清单 | 无 | [`PROTOCOL_COVERAGE.md`](./PROTOCOL_COVERAGE.md)（实现/未实现/差异） |

结论：v2 不是重复原 README，而是把目标落成可运行、可验证的最小内核；**旧桌面客户端不兼容**，本次同步升级，不保留 v1 兼容层。

## 4. 架构

```text
┌──────────────────────── Electron Renderer（协议客户端） ────────────────────────┐
│ 聊天 / Live2D / 音频播放 / 录音 / 音色下拉 / 克隆面板                              │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ WebSocket /ws/control?protocol=vob/1&session_id=&after=
                                │ vob/1：server.ready / 命令 / 通知 / seq / replay
┌───────────────────────────────▼─────────────────────────────────────────────────┐
│ Control Gateway（backend/app/transport/control_ws.py）                            │
│  能力协商 · 命令表 · 会话绑定 · 事件扇出 · after 重放 · 错误映射                     │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────────────┐
│ CharacterRuntime（backend/app/runtime/runtime.py）                               │
│  SessionStore(JSONL) · ReplyPipeline(turn) · AgentCore(人设/历史)                 │
│  VoiceRegistry(音色档案/克隆) · AudioStore · CharacterProjection(状态投影)          │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Ports
┌───────────────────────────────▼─────────────────────────────────────────────────┐
│ OllamaChat · IndexTtsProvider / GptSovitsProvider · FasterWhisperAsr · AudioStore │
└─────────────────────────────────────────────────────────────────────────────────┘
```

关键边界：

- Renderer 只看到协议，不直接调用模型；后端崩溃/重连后可从账本恢复。
- Gateway 只负责协议编解码、连接、重放与命令分发；回合编排在 `ReplyPipeline`。
- TTS/LLM/ASR 通过 Port 注入，测试用 Fake/Mock，真实环境用真实适配器。
- 音色是**会话级**选择（`meta.json.voice_id`）；音色档案是**进程级**资源（`VoiceRegistry`）。
- 连接断开不取消回合；回合继续写账本，重连后通过 replay/hydrate 观察。进程退出时 `CharacterRuntime.shutdown()` 以 `shutdown` 取消所有回合。

### 4.1 实际目录结构

```text
backend/
├─ app/
│  ├─ main.py                    # 应用装配、CORS、/health、/tts/{audio_id}
│  ├─ config.py                  # pydantic-settings
│  ├─ transport/
│  │  ├─ control_ws.py           # /ws/control：握手、命令分发、重放、扇出
│  │  ├─ messages.py             # vob/1 pydantic 镜像
│  │  ├─ tts_http.py             # POST /tts
│  │  ├─ voices_http.py          # GET/POST/PATCH/DELETE /voices、/voices/{id}/sample
│  │  ├─ sessions_http.py        # GET /sessions 会话列表
│  │  └─ voice_http.py           # POST /asr
│  ├─ runtime/
│  │  ├─ runtime.py              # CharacterRuntime：会话注册、订阅、音色、回合入口
│  │  ├─ pipeline.py             # ReplyPipeline：单 active turn、取消/打断、TTS 生命周期
│  │  ├─ projection.py           # derive_turns / derive_character / active turn
│  │  └─ tts_port.py             # 旧 TtsPort 名称的别名兼容层
│  ├─ session/
│  │  ├─ models.py               # SessionMeta / MessageRecord / EventRecord / 校验
│  │  └─ store.py                # JSONL 持久化、replay、hydrate、裁剪
│  ├─ voices/
│  │  ├─ models.py               # VoiceProfile / VoiceNotFound / BuiltinVoiceProtected
│  │  ├─ registry.py             # 内置+用户档案、id 分配、持久化
│  │  ├─ audio.py                # PyAV 解码 + 1–60s + 16-bit mono WAV
│  │  └─ synthesis.py            # VoiceProfile → SynthesisRequest
│  ├─ models/
│  │  ├─ llm/ollama.py           # OllamaChat
│  │  ├─ tts/base.py             # TtsProvider / SynthesisRequest / EmotionSpec
│  │  ├─ tts/index_tts.py        # IndexTTS sidecar 适配器（默认）
│  │  ├─ tts/gpt_sovits.py       # legacy 适配器
│  │  ├─ tts/factory.py          # TTS_PROVIDER 选择
│  │  └─ tts/audio_store.py      # runtime/audio 落盘
│  └─ agent/agent_core.py        # 人设 prompt、历史、300 字截断
├─ config/voices.json            # 内置音色档案
├─ runtime/                      # 运行期产物（git 忽略）
└─ tests/                        # 108 tests
```

桌面端（`apps/desktop/`）：

```text
src/main/index.ts                # 窗口、autoplayPolicy: no-user-gesture-required
src/preload/index.ts             # contextBridge 注入 controlUrl（VOB_CONTROL_URL）
src/renderer/src/
├─ transport/protocol.ts         # vob/1 TypeScript 镜像
├─ transport/control-client.ts   # 重连、after 重放、hydrate、seq 去重、命令队列
├─ api/voices.ts                 # GET/POST/PATCH/DELETE /voices、sample
├─ api/sessions.ts               # GET /sessions
├─ ui/chat.ts, ui/voices.ts      # 聊天与音色/克隆 UI
├─ audio/player.ts, recorder.ts  # 播放与录音
└─ live2d/controller.ts          # Cubism 4 渲染、ParamA 口型
```

### 4.2 进程与并发

- 一个 uvicorn 进程内一个 `CharacterRuntime`；`SessionStore` 用 `threading.RLock` 保护文件读写。
- 每个会话最多一个 `ReplyPipeline` 和一个 active turn；pipeline 懒创建、跨连接复用。
- 每个连接一个发送协程从 `asyncio.Queue` 消费事件；`publish` 先落盘再 `put_nowait` 给所有订阅者。
- `_last_seq` 防止重放与实时事件重复发送；客户端也按 `seq` 去重。
- sidecar 是独立进程，内部一把全局锁串行「加载 + 推理」。

## 5. 领域模型

```text
Session  1 ── n Turn  1 ── n Message
   │                 └── n Event（账本，seq）
   └── meta：persona、voice_id、created_at
VoiceProfile：id、display_name、language、reference_audio、description、emotion、duration_factor、builtin、gpt_sovits
CharacterState：phase(idle/thinking/speaking/error)、emotion、tts_id、audio_url
```

- `Turn` 不单独存状态机，由 `turn.started/completed/cancelled/error` 事件推导。
- 每个会话同一时刻最多一个 active turn；新的 `user.text` 先取消旧 turn 再开新 turn。
- Agent 回复携带最近历史（默认最近 12 条 / 4000 字符预算），并截断到 300 字。

## 6. 协议 v2（`vob/1`）

### 6.1 连接与信封

- 地址：`ws://127.0.0.1:8090/ws/control?protocol=vob/1&session_id=<可选>&after=<可选 seq>`
- 信封：

```json
{
  "protocol": "vob/1",
  "id": "uuid",
  "ts": 1790000000000,
  "type": "agent.text",
  "reply_to": "触发它的命令 id（可选）",
  "seq": 42,
  "payload": {}
}
```

- 服务端通知带 `seq`（该会话事件账本位置，单调递增）；命令不带 `seq`。
- 连接级消息（`server.ready`/`session.opened`/`session.state`/`error`）不带 `seq`。
- `protocol` 字段存在但不等于 `vob/1`：`error{code:"protocol_mismatch"}` + close `1008`；字段缺失属于 `invalid_message`。

### 6.2 握手与恢复

1. 连接建立后服务端发送 `server.ready`：
   `{protocol_version, capabilities:{methods, notifications, features}}`。
2. 若 URL 带已有 `session_id` 且带 `after=N`，服务端按 `seq > N` 重放事件（与实时通知同形）。
3. 服务端发送 `session.opened`：
   `{session_id, cursor, replayed, voice_id}`。无 `session_id` 创建新会话；已有 id 恢复；不存在则 `session_not_found` 并关闭。
4. 客户端可发 `session.hydrate` 请求权威快照，服务端回 `session.state`：
   `{session_id, cursor, messages, turns, voice, character, active_turn_id?}`。
   `sections`/`after` 当前被忽略。
5. 客户端把 `session_id` 与 `cursor` 存在本地（Electron localStorage），重连时回填；收到 `session_not_found` 清空本地 id 并新建。

### 6.3 命令

| type | payload | 说明 |
| --- | --- | --- |
| `session.open` | `{session_id?, after?}` | 切换/恢复会话；缺省沿用当前连接会话；`after` 命中时先重放 |
| `session.hydrate` | `{sections?, after?}` | 请求快照；当前忽略两个可选字段 |
| `user.text` | `{text}` | 提交文本；先取消当前 turn 再开新 turn |
| `voice.select` | `{voice_id}` | 校验后改会话音色并广播 `voice.selected` |
| `tts.cancel` | `{tts_id}` | 取消匹配的 TTS，turn 保持并收尾 |
| `tts.finished` | `{tts_id}` | 播放结束回报，驱动状态回到 idle |

### 6.4 通知

| type | payload | 说明 |
| --- | --- | --- |
| `server.ready` | `{protocol_version, capabilities}` | 握手 |
| `session.opened` | `{session_id, cursor, replayed, voice_id}` | 会话就绪/恢复 |
| `session.state` | 见 hydrate | 权威快照 |
| `turn.started` | `{turn_id, reply_to}` | 回合开始 |
| `agent.text` | `{text, reply_to, message_id, audio_url?}` | 回复文本（先于 TTS） |
| `tts.started` | `{tts_id, reply_to, voice_id}` | 合成开始 |
| `tts.ready` | `{tts_id, reply_to, voice_id, audio_url, segment_index, segment_count, final}` | 分段音频可播；按 `segment_index` 递增，`final=true` 为最后一段 |
| `tts.failed` | `{tts_id, reply_to, voice_id, code, message}` | 合成失败 |
| `tts.cancelled` | `{tts_id, reply_to, reason}` | 取消 |
| `tts.finished` | `{tts_id, reply_to?}` | 播放结束（客户端回报后广播） |
| `voice.selected` | `{voice_id, display_name}` | 音色切换确认 |
| `character.state` | `{phase, emotion, tts_id, audio_url}` | 投影；未使用字段为 `null` |
| `turn.completed` | `{turn_id, reply_to}` | 回合完成 |
| `turn.cancelled` | `{turn_id, reply_to, reason}` | 回合取消 |
| `turn.error` | `{turn_id, reply_to, code, message}` | 回合失败 |
| `error` | `{code, message, reply_to?}` | 协议/业务错误 |

### 6.5 错误码

| code | 场景 | 是否关闭连接 |
| --- | --- | --- |
| `invalid_message` | JSON 非法、信封/payload 校验失败、非法 `session_id`/`after` | 初始化阶段关闭；命令不关闭 |
| `unsupported_type` | 枚举内但方向不对（客户端发服务端通知） | 否 |
| `protocol_mismatch` | `protocol` 值不是 `vob/1` | 是（1008） |
| `session_not_found` | 会话不存在 | 连接阶段关闭；`session.open` 不关闭 |
| `turn_in_progress` | 预留，当前不会发出 | — |
| `llm_unavailable` | Ollama 失败（`turn.error`） | 否 |
| `tts_unavailable` | sidecar 失败（`tts.failed` / HTTP 503） | 否 |
| `voice_not_found` | `voice.select` 的 id 未注册 | 否 |
| `internal_error` | 未预期异常（`turn.error`/`error`） | 否 |

## 7. 持久化布局

```text
backend/runtime/
├── audio/<audio_id>.wav              # TTS 产物（可被 /tts/{id} 取回）
├── voices/
│   ├── profiles.json                 # 用户克隆档案
│   └── <voice_id>/reference.wav      # 规范化后的参考音频
└── sessions/<session_id>/
    ├── meta.json                     # session_id / created_at / persona / voice_id
    ├── messages.jsonl                # 已提交消息（append-only，带 id/seq/audio_url）
    └── events.jsonl                  # 持久事件账本（seq/type/payload/ts/reply_to）
```

- 追加写同步落盘，先写账本再发通知，保证「重放得到的 == 当时发出的」。
- 事件保留上限：单会话最多 2000 条，超出时从最旧裁剪（裁剪只影响 replay，hydrate 仍从 messages 重建）。
- `hydrate` 从 messages 重建 transcript、从 events 推导 turns/character，返回 `cursor`。
- 会话 id 使用 `[A-Za-z0-9_-]{1,64}`，目录名直接使用该 id；`validate_session_id` 阻止路径穿越。
- JSONL 读取容忍末尾半行（截断并记录日志）与中间非法行（跳过并记录日志）；写 `meta.json` / 裁剪事件时用临时文件 + `os.replace`。
- 注意：消息账本的 `seq` 与事件账本的 `seq` 是两套独立序号。

## 8. 音色、TTS 与克隆

- `VoiceProfile`：`id`、`display_name`、`language`（ZH/EN/JA/ES/AR）、`reference_audio`、`description`、`emotion`（mode/vector/text/audio/alpha）、`duration_factor`、`builtin`、`gpt_sovits`。
- 内置档案：`murasame`（`assets/voices/murasame/murasame_ref.wav`，ZH，零样本克隆）。
- 克隆：`POST /voices`（multipart：name/audio/language）→ PyAV 解码并规范化为 16-bit mono WAV（WAV 保留源采样率；非 WAV 统一 44.1kHz）→ 校验 1–60s → 存 `runtime/voices/<id>/reference.wav` → 写 `profiles.json` → 201。`PATCH /voices/{id}` 重命名、`GET /voices/{id}/sample` 试听、`DELETE /voices/{id}` 只删用户档案；内置档案 409。
- 会话列表：`GET /sessions` 扫描 `runtime/sessions/*`，标题取首条用户消息，按最近消息倒序；桌面端用它做会话切换/新建。
- Memory（MVP）：`backend/app/memory/store.py` 持久化 `runtime/memory/memory.json`；识别“记住…”“叫我…”“我喜欢/讨厌…”显式指令，每回合累计好感度并映射关系阶段；`context_text()` 在每回合注入 system prompt。`GET/POST/DELETE/PATCH /memory` 供桌面面板查看/增删备注与改称呼。不做自动抽取或向量检索。
- TTS Port 请求：`text`、`reference_audio`（绝对路径）、`language`、`emotion`（可选）、`duration_factor`、`provider_options`。
  - `IndexTtsProvider` 转 sidecar 契约（`POST /synthesize`），只发送非空字段；`provider_options` 不发给 IndexTTS。
  - `GptSovitsProvider` 用档案 `gpt_sovits` 段的容器内路径/prompt；缺省退回请求里的绝对路径。
- 默认 `TTS_PROVIDER=index_tts`；`INDEX_TTS_BASE_URL=http://127.0.0.1:9882`；切 legacy 用 `TTS_PROVIDER=gpt_sovits`。
- 情感向量 8 维，顺序为喜/怒/哀/惧/厌恶/低落/惊喜/平静，总和 ≤ 0.8；`duration_factor` 0.5–2.0。当前 `emotion.mode=text` 因缺 QwenEmotion 资源不可用。
- IndexTTS sidecar 是单卡串行：加载与推理共用一把锁。sidecar 侧请求超时（默认 180s）会返回 500 `synthesis_failed`，但推理线程无法中止，锁持有到推理真正结束，后续请求排队；因此后端超时不会造成两个推理并发，只会看到排队。8GB 显存与 Ollama 共用 GPU 会显著变慢，推荐 `OLLAMA_NUM_GPU=0`。
- 细节见 [`VOICE_CLONING.md`](./VOICE_CLONING.md)。

## 9. 契约与一致性

- 权威：`shared/contracts/control-message.schema.json`（信封、type 枚举、闭合 payload 定义）。
- 镜像：`backend/app/transport/messages.py`（pydantic）与 `apps/desktop/src/renderer/src/transport/protocol.ts`（TS）。
- 一致性测试：`backend/tests/test_contract_consistency.py` 校验 schema ↔ pydantic 的 type 枚举、required、字段集合、`additionalProperties:false`、嵌套定义，并检查 `protocol.md` 覆盖所有类型。
- TS 由 `npm run typecheck` 覆盖；不逐字段读取 schema，改字段仍需人工同步三处。
- `PROTOCOL_COVERAGE.md` 记录已实现消息、未实现能力、与 v1/octos-ts 的差异；文档不得宣称未实现能力。

## 10. CORS

Renderer 在 Electron 中通过 `file://` 加载（`Origin: null`），Vite dev 则是 `http://127.0.0.1:5173`。后端只放行本机来源：

```python
allow_origins=["null"]
allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
allow_methods=["*"]
allow_headers=["*"]
```

- 不允许任意远端来源；测试覆盖 `Origin: null`、`http://127.0.0.1:5173` 放行与 `https://evil.example` 拒绝。
- WebSocket 不走 CORS，但控制通道使用同一 HTTP 端口；CSP 由 Renderer 的 `index.html` 限制。
- 绑定非本机地址或换 host 时需要同步调整正则；不要直接改成 `*`。

## 11. Ollama 参数

后端通过一个共享 `httpx.AsyncClient(timeout=..., trust_env=False)` 调用 Ollama：

- `OLLAMA_BASE_URL` 默认 `http://127.0.0.1:11434`。
- `OLLAMA_MODEL` 默认 `qwen3:8b`。
- `OLLAMA_TIMEOUT_SECONDS` 默认 300（CPU 回退或冷启动时首次生成可能超过 120 秒）。
- `OLLAMA_NUM_CTX` 默认 4096：显式限制上下文，避免 Ollama 默认值在本机分配过大的 KV cache（qwen3 上出现过 36GB 分配失败）。
- `OLLAMA_NUM_GPU` 默认不设置（交给 Ollama 自动分配）；设为 `0` 强制 CPU，用于 8GB 显存下把 GPU 留给 IndexTTS。
- 请求固定 `stream=false`、`think=false`；返回内容会再剥离 `<｜end▁of▁thinking｜>` / `</think>` 残留，空回复视为 `llm_unavailable`。
- `trust_env=False`：本机代理环境变量会让 httpx 0.28 解析 `NO_PROXY` 时抛 `InvalidURL`，因此不复用环境代理；新增客户端也应显式关闭。

## 12. 测试策略

- 单元：`SessionStore`（append/replay/hydrate/裁剪/路径安全）、`CharacterProjection`、`VoiceRegistry`、音频规范化、TTS/LLM/ASR 适配器（MockTransport）。
- 协议：TestClient WS 握手、capabilities、`session.open`/replay、hydrate、`voice.select`、turn 生命周期、`tts.cancel`/`tts.finished`、错误码、契约一致性。
- HTTP：`/health`、`/tts`、`/voices`、`/asr`、CORS。
- sidecar：`/health`、`/synthesize` 全参数校验、错误映射、超时映射、引擎参数、Mock WAV。
- 集成：真实 sidecar（IndexTTS GPU）合成；后端 HTTP `/tts`、`/voices` 克隆/删除；WS 全链路（Ollama 可用时）。
- 桌面：`npm run typecheck` + `npm run build`；运行时播放与克隆面板交互标注为人工验收。
- 当前基线：backend 108 tests、sidecar 56 tests、ruff 通过、desktop typecheck/build 通过。

## 13. 迁移与兼容

- 旧桌面客户端（只认 `session.ready`/`tts.started`/`tts.ready`）会因 `protocol` 与握手变化而不兼容；本次同步升级桌面端，不保留旧协议兼容层。
- 旧 `POST /tts` 保留（新增可选 `voice_id`），便于脚本/调试。
- GPT-SoVITS 推理目录与 docker compose 保留，降级为 legacy；训练流程不迁移。
- 首版不做多会话并行打开（一个连接一个会话；`session.open` 可切换，桌面端提供会话列表/新建）。
- `app/runtime/tts_port.py` 仅保留旧 `TtsPort` 名称别名，避免既有导入失效。

## 14. 已知限制

- 会话事件不做 WAL/事务恢复；进程崩溃可能丢最后一条正在写的行（JSONL 截断由加载器容错）。
- 不做 LLM 摘要压缩，只做历史窗口裁剪（12 条 / 4000 字符）与回复截断（300 字）。
- 分句级 TTS：回复按句末标点切分（单段 ≤80 字），逐段合成、逐段 `tts.ready`，桌面端边播边等；不做网络级流式与实时音频流。
- sidecar 单卡串行；超时不会中止推理线程，后续请求排队（见第 8 节）。
- 8GB 显存下 IndexTTS 与 Ollama 同时占 GPU 会显著变慢，建议 `OLLAMA_NUM_GPU=0`。
- `emotion.mode=text` 因缺 QwenEmotion 资源不可用；`character.state.emotion` 来自 Agent 结构化回复的情绪标签（可能为 `null`）。
- Live2D 模型资源（`apps/desktop/public/live2d/mao/`）不随仓库分发；当前仅 Mao 示例，丛雨专属模型与正式口型映射未完成；振幅口型已接入示例。
- Electron 窗口内播放/停止/克隆交互未自动验证。
- 仅支持本机 `127.0.0.1` / `localhost` 来源；无鉴权、无公网部署。
- ASR 模型需本地准备；缺失时 `/asr` 失败但文本链路可用。

## 15. 借鉴点（来自 octos-ts）

- 内核状态归运行时，客户端只消费协议。
- 事件账本即事实，turn/character 状态由事件推导。
- `after` 游标重放 + `hydrate` 权威快照，两者分工明确。
- capabilities/feature 协商 + 覆盖清单 + 一致性 lint。
- Mock provider/engine 让全链路离线可测；真实模型只做 E2E。
- 明确写出「与上游/旧版本的差异」，避免把子集实现宣传成完整实现。
- 同样明确边界：本项目是角色应用，不是 coding agent，不引入工具调用/审批/子代理等内核外设。
