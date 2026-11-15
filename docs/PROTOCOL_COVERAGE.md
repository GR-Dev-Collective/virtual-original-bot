# 协议覆盖清单（`vob/1`）

本文件回答三个问题：

1. 控制通道 `vob/1` 现在**实现了什么**；
2. 与**旧 v1** 协议有哪些不兼容变化；
3. 与 `octos-ts` 的「内核 + 协议边界 + 事件账本 + 投影 + 覆盖清单」是什么关系，以及本项目**不是什么**。

事实基线：`backend/` 108 tests 通过、`services/indextts_service/` 56 tests 通过、桌面 `npm run typecheck` / `npm run build` 通过；真实 GPU sidecar、HTTP `/voices` / `/tts`、WebSocket 全链路（LLM → TTS → `audio_url` → `hydrate` → 重连重放 → `voice.select`）已手工跑通。Electron 窗口内的播放与克隆面板交互**未自动验证**。

字段级权威定义：[`../shared/contracts/control-message.schema.json`](../shared/contracts/control-message.schema.json)；协议说明：[`../shared/contracts/protocol.md`](../shared/contracts/protocol.md)。

## 1. 已实现的通知（服务端 → 客户端）

| type | payload | 是否进事件账本 | 说明 |
| --- | --- | --- | --- |
| `server.ready` | `{protocol_version, capabilities}` | 否 | 连接级握手；首个通知，不带 `seq` |
| `session.opened` | `{session_id, cursor, replayed, voice_id}` | 否 | 连接级；重放完成后发送，不带 `seq` |
| `session.state` | `{session_id, cursor, messages, turns, voice, character, active_turn_id?}` | 否 | 连接级；`session.hydrate` 的响应，不带 `seq` |
| `turn.started` | `{turn_id, reply_to}` | 是 | 新回合开始 |
| `agent.text` | `{text, reply_to, message_id, audio_url?}` | 是 | 回复文本；`message_id` 是 assistant 消息 id |
| `tts.started` | `{tts_id, reply_to, voice_id}` | 是 | 合成开始 |
| `tts.ready` | `{tts_id, reply_to, voice_id, audio_url, segment_index, segment_count, final}` | 是 | 分段 WAV 已落盘，可播放；按 `segment_index` 顺序播 |
| `tts.failed` | `{tts_id, reply_to, voice_id, code, message}` | 是 | 合成失败；`code` 当前为 `tts_unavailable` |
| `tts.cancelled` | `{tts_id, reply_to, reason}` | 是 | `reason` 见第 6 节 |
| `tts.finished` | `{tts_id, reply_to?}` | 是 | 播放结束；由客户端命令 `tts.finished` 触发 |
| `voice.selected` | `{voice_id, display_name}` | 是 | `voice.select` 成功后的广播 |
| `character.state` | `{phase, emotion, tts_id, audio_url}` | 是 | 投影相位；`emotion` 来自 Agent 标签，可能为 `null` |
| `turn.completed` | `{turn_id, reply_to}` | 是 | 回合完成（文本已产出；音频可能仍在播） |
| `turn.cancelled` | `{turn_id, reply_to, reason}` | 是 | 回合被新输入或关闭取消 |
| `turn.error` | `{turn_id, reply_to, code, message}` | 是 | 回合失败；`code` 为 `llm_unavailable` / `internal_error` |
| `error` | `{code, message, reply_to?}` | 否 | 协议/业务错误；连接级，不带 `seq` |

`character.state.phase` 取值：`idle` / `thinking` / `speaking` / `error`。`emotion` 来自 Agent 的结构化回复（happy/angry/sad/afraid/disgusted/melancholic/surprised/calm），用于 Live2D 示例表情与 IndexTTS 情感向量；解析失败时为 `null`。

## 2. 已实现的命令（客户端 → 服务端）

| type | payload | 行为 | 可能的错误 |
| --- | --- | --- | --- |
| `session.open` | `{session_id?, after?}` | 不带 `session_id` 时沿用当前连接会话；带 id 时切换/恢复并重新发 `session.opened`；`after` 命中时先重放。会重建发送循环。 | `invalid_message`、`session_not_found` |
| `session.hydrate` | `{sections?, after?}` | 返回权威快照 `session.state`。**当前忽略 `sections` 与 `after`**，总是全量快照。 | `invalid_message` |
| `user.text` | `{text}` | 先取消当前 turn（`reason:"interrupted"`），把用户消息写入 transcript，再异步开新 turn。 | `invalid_message`；失败经 `turn.error` 返回 |
| `voice.select` | `{voice_id}` | 校验注册表，更新会话音色并广播 `voice.selected`；不影响已开始的 TTS。 | `voice_not_found`、`invalid_message` |
| `tts.cancel` | `{tts_id}` | 只取消匹配的 active TTS；没有匹配项时静默忽略。合成中取消会让回合以 `turn.completed` 收尾。 | `invalid_message` |
| `tts.finished` | `{tts_id}` | 播放结束回报；仅当匹配的 TTS 处于 `ready` 时生效，发 `tts.finished` + `character.state(idle)`。 | `invalid_message` |

补充：

- `capabilities.methods` 实际包含上表 6 个命令；`notifications` 包含第 1 节除命令外的全部通知；`features` 为 `["replay", "hydrate", "session-persistence", "history"]`。
- 命令的 `id` 会被用作 `reply_to`。`user.text` 的 `id` 同时是用户消息 id，因此 hydrate 后用户消息的 `id` 等于当时命令 id。
- 对未知 `type`（不在枚举里）返回 `invalid_message`；对枚举内但属于服务端通知的类型返回 `unsupported_type`。两者都不关闭连接。
- 连接断开**不会**取消正在执行的回合：`ReplyPipeline` 是进程级、按会话复用的，回合继续写账本；重连后用 `after` 或 `hydrate` 观察结果。进程退出时 `CharacterRuntime.shutdown()` 以 `reason:"shutdown"` 取消所有回合。

## 3. 事件账本

只有第 1 节标记「是」的 12 种事件写入 `events.jsonl`。服务端先 `append_event` 落盘，再扇出到订阅者；因此实时通知与 replay 事件同形，只差发送时机。

事件记录形状：

```json
{
  "seq": 42,
  "id": "8f3e...",
  "ts": 1790000000000,
  "type": "agent.text",
  "payload": { "text": "我が輩 在此。", "reply_to": "...", "message_id": "..." },
  "reply_to": "..."
}
```

- `seq` 从 1 开始，单会话单调递增。
- `reply_to` 只在非空时写入记录。
- 单会话默认最多 2000 条，超出时从最旧裁剪；裁剪后 replay 的起点会大于 1。
- 消息账本 `messages.jsonl` 与事件账本分离：assistant 消息会以同一 `message_id` 追加第二次（补 `audio_url`），hydrate 时取同一 id 的最新记录。

## 4. 未实现 / 未定义

以下能力**没有**对应的协议消息，也没有运行时实现。文档中不应把它们写成已完成。

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Memory / Relationship | 未实现 | `backend/app/memory/` 只有空包；没有读写消息、长期记忆或关系状态 |
| Vision / OCR / Video | 未实现 | `backend/app/models/vision/`、`ocr/` 只有空包 |
| Action Controller | 未实现 | `backend/app/actions/` 只有空包；没有 action 注册、参数校验或结果回传 |
| World | 未实现 | 没有时间、环境、主动行为循环 |
| 情绪状态机 | 部分实现 | Agent 标签已接入 `character.state.emotion`、Live2D 示例表情与 TTS 情感向量；复杂情绪建模/长期情绪未做 |
| VAD / 实时音频流 / 语音 WebSocket | 未实现 | 只有 `POST /asr` 单次上传；没有音频流通道 |
| 分句级流式 TTS | 已实现 | 回复按句切分，逐段 `tts.ready`，桌面端边播边等；网络级音频流未做 |
| 多 active turn / 多会话并行 | 未实现 | 每会话最多一个 active turn；一个连接绑定一个会话 |
| Action schema / 外部设备控制 | 未实现 | `shared/contracts/` 目前只有控制消息 schema |
| 工具调用 / 审批 / MCP / 子代理 / 上下文压缩 | 未实现（也非目标） | 这是角色应用，不是通用 coding agent |

`turn_in_progress` 是错误码表里的**预留值**，当前实现不会发出：并发 `user.text` 的选择是「取消旧 turn、开新 turn」，不是拒绝。

## 5. 与旧 v1 协议的差异

旧协议（重构前 `HEAD`）只有 8 种消息，连接级 `session.ready` 携带 `session_id`，没有版本、`seq`、账本或恢复。

| 维度 | v1 | `vob/1` |
| --- | --- | --- |
| 信封 | `{type, id, ts, payload}` | `{protocol:"vob/1", id, ts, type, reply_to?, seq?, payload}`，payload 闭合 |
| 握手 | `session.ready{session_id}` | `server.ready{protocol_version, capabilities}` + `session.opened{session_id, cursor, replayed, voice_id}` |
| 会话恢复 | 无；重连即新会话，内存态 | `after` 重放 + `session.hydrate` → `session.state`；`meta/messages/events` 持久化 |
| 幂等/去重 | 无 | 每条通知带 `seq`，客户端按 `seq` 去重 |
| 回合 | 无显式回合通知 | `turn.started/completed/cancelled/error`，turns 由账本投影 |
| TTS 失败 | 通用 `error{code:"tts_unavailable"}` | `tts.failed{code,message}` + `character.state(error)` + `turn.completed` |
| TTS 播放结束 | 无回报 | 客户端 `tts.finished` → 服务端广播 `tts.finished` + `idle` |
| 角色状态 | 前端自己维护布尔量 | `character.state` 投影 |
| 音色 | 硬编码 GPT-SoVITS 参考路径/prompt | `VoiceRegistry` + `voice.select` + `voice.selected` + `/voices` 克隆 |
| TTS 默认实现 | GPT-SoVITS（容器 9880） | IndexTTS-2.5 sidecar（9882）；GPT-SoVITS 为 legacy 可选 |
| 历史 | `AgentCore` 无历史 | `ReplyPipeline` 传最近 12 条 / 4000 字符预算 |
| 错误码 | `invalid_message` / `unsupported_type` / `llm_unavailable` / `tts_unavailable` | 增加 `protocol_mismatch`、`session_not_found`、`voice_not_found`、`turn.error`/`tts.failed` 通道；`turn_in_progress` 预留 |
| 兼容性 | — | 旧桌面客户端不兼容；本次同步升级桌面端，未保留 v1 兼容层 |

保留项：`POST /tts` 仍可用（新增可选 `voice_id`），便于脚本/调试；GPT-SoVITS 推理目录与 compose 保留。

## 6. 取消与打断语义

| 触发 | 前提 | 产生的通知（按顺序） |
| --- | --- | --- |
| 新 `user.text` | 旧 turn 正在 LLM 或 TTS 阶段 | `tts.cancelled{interrupted}`（若在合成）→ `turn.cancelled{interrupted}` → `character.state(idle)` → 新 `turn.started` |
| 新 `user.text` | 旧 turn 已完成，仅音频在播 | `tts.cancelled{interrupted}` → `character.state(idle)` → 新 `turn.started`（不会再有旧 turn 的 `turn.cancelled`） |
| `tts.cancel` | TTS 正在合成 | `tts.cancelled{cancelled}` → `character.state(idle)` → `turn.completed` |
| `tts.cancel` | TTS 已 `ready`、等待播放结束 | `tts.cancelled{cancelled}` → `character.state(idle)`（回合此前已 `turn.completed`） |
| `tts.finished` | TTS 处于 `ready` | `tts.finished` → `character.state(idle)` |
| 进程退出 | 任意 active 回合 | `tts.cancelled{shutdown}`（若在合成）→ `turn.cancelled{shutdown}` → `character.state(idle)` |

`tts.cancel` / `tts.finished` 对不匹配的 `tts_id` 静默忽略，不返回错误。

## 7. 错误码

| code | 何时出现 | 是否关闭连接 |
| --- | --- | --- |
| `invalid_message` | JSON 非法、非对象、信封缺字段/类型错、payload 多余字段、空文本、非法 `session_id`/`after` | 连接初始化阶段（query）会关闭；运行期命令不关闭 |
| `protocol_mismatch` | URL 的 `protocol` 或消息的 `protocol` 不是 `vob/1` | 是，close code 1008 |
| `unsupported_type` | 枚举内但方向不对的类型（如客户端发 `agent.text`） | 否 |
| `session_not_found` | 连接时或 `session.open` 指定的会话不存在 | 连接时关闭；`session.open` 不关闭 |
| `voice_not_found` | `voice.select` 的音色 id 未注册 | 否 |
| `llm_unavailable` | Ollama 不可达/超时/空回复/无法解析；出现在 `turn.error` | 否 |
| `tts_unavailable` | sidecar 不可达、返回非音频、HTTP 错误、超时；出现在 `tts.failed` 或 HTTP 503 | 否 |
| `internal_error` | 未预期异常；出现在 `turn.error` 或 `error` | 否 |
| `turn_in_progress` | 预留，当前不会发出 | — |

注意：信封**缺少** `protocol` 字段走 `invalid_message`（pydantic 必填校验），只有字段存在但值不等于 `vob/1` 才走 `protocol_mismatch`。这一点与旧版 protocol.md 的表述不同，以代码为准。

## 8. 与 octos-ts 设计的关系

借鉴的是**内核与协议边界**，不是代码或产品形态：

| octos-ts 概念 | 本项目的对应实现 |
| --- | --- |
| 内核持有状态，客户端只消费协议 | `CharacterRuntime` + `SessionStore`；Renderer 不直接调用模型 |
| 协议边界与能力协商 | `vob/1` 信封、`server.ready.capabilities`、命令/通知分离 |
| 事件账本即事实 | `events.jsonl` + `seq`；turn 与 character 由事件推导 |
| 投影 | `app/runtime/projection.py`：`derive_turns` / `derive_character` / `derive_active_turn_id` |
| 重放 + 权威快照分工 | `after` 游标重放增量；`session.hydrate` 返回 `session.state` |
| 覆盖清单 | 本文件；明确已实现、未实现、与旧版差异 |
| Mock 适配器/E2E 分离 | `FakeChat`/`FakeTts`、`MockEngine`、`httpx.MockTransport`；真实 GPU 只做 E2E |
| 明确写出与上游差异 | 第 5 节 + 各文档的限制章节 |

**不是** coding agent：没有工具调用、审批、MCP、工作流、子代理、代码工作区、上下文压缩，也没有把「会话账本」扩展成任务/补丁/工具结果账本。这里的领域对象是角色、回合、消息、音色和音频。

## 9. 三处契约的一致性

同一份协议有三处表达：

1. `shared/contracts/control-message.schema.json`（权威 JSON Schema）
2. `backend/app/transport/messages.py`（pydantic 镜像）
3. `apps/desktop/src/renderer/src/transport/protocol.ts`（TypeScript 镜像）

`backend/tests/test_contract_consistency.py` 强制校验：

- 信封字段集合、required、`protocol` 常量与 pydantic `ControlMessage` 一致；
- schema 的 `type` 枚举与 `MessageType` 完全一致，且每个类型都有 payload 模型；
- 每个 payload 的 required 字段、字段集合、`additionalProperties:false` 与 pydantic 一致；
- `capabilities` / `messageView` / `turnView` / `voiceState` / `characterStatePayload` 等嵌套定义一致；
- `protocol.md` 提到每一种消息类型。

桌面端由 `npm run typecheck`（`tsc --noEmit`）覆盖 TypeScript 镜像；它不逐字段读取 schema，因此改字段时仍需人工同步三处。

核对结论（本次文档修订时）：

- schema ↔ pydantic：字段名、required、枚举一致（测试通过）。
- schema/pydantic ↔ TS：字段名与必填性一致；`ControlMessage.seq` 在 TS 为可选，命令不发送，通知解析时保留。
- 唯一的有意差异：schema 对命令的可选字段（`session_id`/`sections`/`after`）允许显式 `null`，与后端 pydantic 的 `| None` 一致；TS 客户端只发送省略形式，不发送 `null`。这不影响线上互通，已写入 `protocol.md`。
- 一个**注释层面的差异**：`protocol.ts` 的 `NotificationType` 注释说「只有服务端才会发送的通知；`tts.finished` 同时是命令，因此不算进来」，但该类型实际上包含 `tts.finished`。代码行为是正确的（它确实既可命令也可通知），文档按代码记录，不去改动只读的前端文件。
- 文档曾经过期的表述已修正：`voice.select` 不再是「未实现/回 unsupported_type」；capabilities 的 methods 补上 `voice.select`；`session.hydrate` 的 `sections`/`after` 明确为忽略；`protocol` 缺失与不匹配的区别；ready 状态打断的额外分支。

## 10. 明确不宣称的内容

- 不宣称 Electron 窗口内播放、停止、自动播放、克隆表单交互已验收。
- 不宣称 Memory / Vision / Action / World / VAD / 实时音频 / 网络级流式 TTS 已实现；分句级流式与情绪标签已实现。
- 不宣称 GPT-SoVITS 训练流程已迁移；仅保留 legacy 推理。
- 不宣称 Live2D 丛雨模型或正式口型同步已完成；仓库不附带模型资源。
- 不宣称多用户、多会话并发、鉴权或公网部署已支持；当前是 `127.0.0.1` 本地单用户原型。
