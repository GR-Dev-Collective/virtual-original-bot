# 控制通道协议 v2（`vob/1`）

控制通道是 Electron 渲染进程与 FastAPI 角色运行时之间唯一的消息入口。会话、回合、事件账本与状态投影都归后端所有，客户端只消费协议。

- 地址：`ws://<host>:<port>/ws/control?protocol=vob/1&session_id=<可选>&after=<可选 seq>`
- 编码：UTF-8 JSON，每帧一条消息
- 权威定义：[`control-message.schema.json`](./control-message.schema.json)
- 后端镜像：`backend/app/transport/messages.py`（pydantic）
- 桌面镜像：`apps/desktop/src/renderer/src/transport/protocol.ts`（TypeScript）

## 1. 消息信封

所有消息共用同一个信封，`payload` 的形状由 `type` 决定。

```json
{
  "protocol": "vob/1",
  "id": "b5a4c1...",
  "ts": 1790000000000,
  "type": "agent.text",
  "reply_to": "5f2c1a...",
  "seq": 42,
  "payload": {
    "text": "我が輩 在此。",
    "reply_to": "5f2c1a...",
    "message_id": "8f3e...",
    "audio_url": "/tts/9a7c..."
  }
}
```

- `protocol`：固定 `vob/1`。字段**存在但不等于** `vob/1` 时，服务端回 `error{code:"protocol_mismatch"}` 并以 close code `1008` 关闭连接；字段**缺失**属于信封校验失败，回 `invalid_message`（不关闭）。
- `id`：发送方生成的消息 id，非空字符串。
- `ts`：Unix 毫秒时间戳。
- `type`：见下方命令/通知表。
- `reply_to`：可选，回指触发本通知的入站消息 id。
- `seq`：仅服务端通知携带，表示该事件在会话事件账本中的位置（从 1 单调递增）；命令与连接级消息（`server.ready`/`session.opened`/`session.state`/`error`）不带 `seq`。
- `payload`：`additionalProperties: false`，形状由 `type` 唯一决定；未知字段会被拒绝。

## 2. 握手与恢复

```text
客户端                                      服务端
  │ ── WebSocket /ws/control?... ─────────▶ │
  │ ◀── server.ready ────────────────────── │  协议版本 + 能力协商
  │ ◀── （after 命中时）事件重放 ─────────── │  与实时通知同形，带 seq
  │ ◀── session.opened ─────────────────── │  session_id / cursor / replayed
  │ ── session.hydrate ───────────────────▶ │
  │ ◀── session.state ──────────────────── │  权威快照
```

1. 连接建立后服务端先发 `server.ready`：

   ```json
   {
     "protocol_version": "vob/1",
     "capabilities": {
       "methods": ["session.open", "session.hydrate", "user.text", "voice.select", "tts.cancel", "tts.finished"],
       "notifications": ["server.ready", "session.opened", "session.state", "turn.started", "agent.text", "tts.started", "tts.ready", "tts.failed", "tts.cancelled", "tts.finished", "voice.selected", "character.state", "turn.completed", "turn.cancelled", "turn.error", "error"],
       "features": ["replay", "hydrate", "session-persistence", "history"]
     }
   }
   ```

2. 连接 URL 的处理：
   - 不带 `session_id`：创建新会话；此时即使带 `after` 也会被忽略（新会话没有历史）。
   - 带已有 `session_id`：恢复会话；`after=N` 时按 `seq > N` 重放账本事件，事件信封与实时通知一致（含 `seq`）。
   - `session_id` 不匹配 `[A-Za-z0-9_-]{1,64}`、或 `after` 不是非负整数：回 `error{code:"invalid_message"}` 并关闭连接。
   - `session_id` 格式合法但不存在：回 `error{code:"session_not_found"}` 并关闭连接。
3. 服务端发 `session.opened`：

   ```json
   { "session_id": "a1b2...", "cursor": 12, "replayed": 3, "voice_id": "murasame" }
   ```

   - `cursor` 是服务端当前账本位置（最新 `seq`；空会话为 0），可直接作为下次重连的 `after`。
   - `replayed` 是本次重放的事件条数。

4. 客户端可发 `session.hydrate` 获取权威快照 `session.state`（见第 5 节）。
5. 客户端应把 `session_id` 与 `cursor` 存到本地（Electron 用 `localStorage`），重连时回填 `session_id` + `after`；按 `seq` 去重，避免重放与实时通知重复应用。

## 3. 命令（客户端 → 服务端）

| type | payload | 说明 |
| --- | --- | --- |
| `session.open` | `{session_id?, after?}` | 不带 `session_id` 时沿用当前连接会话；带 id 时切换/恢复会话。会重新发送 `session.opened`；`after` 命中时先重放。切换到不存在的会话回 `session_not_found`（不关闭连接）。 |
| `session.hydrate` | `{sections?, after?}` | 请求权威快照，服务端回 `session.state`。**当前实现忽略 `sections` 与 `after`**，总是返回全量快照。 |
| `user.text` | `{text}` | 提交文本。先取消当前 turn（`reason:"interrupted"`）再开新 turn；命令的 `id` 成为用户消息 id 与后续通知的 `reply_to`。 |
| `voice.select` | `{voice_id}` | 校验音色注册表，更新会话音色并广播 `voice.selected`；未知音色回 `voice_not_found`。不影响已开始的 TTS。 |
| `tts.cancel` | `{tts_id}` | 只取消匹配的 active TTS，turn 继续收尾为 `turn.completed`（若尚未完成）。没有匹配项时静默忽略。 |
| `tts.finished` | `{tts_id}` | 播放结束回报，驱动 `character.state` 回到 `idle`；仅对处于 `ready` 的匹配 TTS 生效。 |

补充：

- 命令的可选字段（`session_id`、`sections`、`after`）显式传 `null` 与省略等价：后端 pydantic 模型允许 `None`，schema 也允许 `null`；桌面 TS 客户端只发送省略形式。
- 对未知 `type`（不在枚举中）返回 `invalid_message`；对枚举内但属于服务端通知的类型返回 `unsupported_type`。两者都不关闭连接。
- 连接断开不会取消正在执行的回合；回合继续写账本，重连后通过 `after` 或 `hydrate` 观察结果。进程退出时以 `reason:"shutdown"` 取消所有回合。

## 4. 通知（服务端 → 客户端）

| type | payload | 说明 |
| --- | --- | --- |
| `server.ready` | `{protocol_version, capabilities}` | 握手；不带 `seq` |
| `session.opened` | `{session_id, cursor, replayed, voice_id}` | 会话就绪/恢复；不带 `seq` |
| `session.state` | `{session_id, cursor, messages, turns, voice, character, active_turn_id?}` | 权威快照；不带 `seq` |
| `turn.started` | `{turn_id, reply_to}` | 回合开始 |
| `agent.text` | `{text, reply_to, message_id, audio_url?}` | 回复文本（先于 TTS）；`message_id` 是 assistant 消息 id |
| `tts.started` | `{tts_id, reply_to, voice_id}` | 合成开始 |
| `tts.ready` | `{tts_id, reply_to, voice_id, audio_url}` | 音频可播 |
| `tts.failed` | `{tts_id, reply_to, voice_id, code, message}` | 合成失败；`code` 当前为 `tts_unavailable` |
| `tts.cancelled` | `{tts_id, reply_to, reason}` | TTS 已取消 |
| `tts.finished` | `{tts_id, reply_to?}` | 播放结束（客户端回报后广播） |
| `voice.selected` | `{voice_id, display_name}` | 音色切换确认 |
| `character.state` | `{phase, emotion, tts_id, audio_url}` | 状态投影；未使用的字段为 `null` |
| `turn.completed` | `{turn_id, reply_to}` | 回合完成 |
| `turn.cancelled` | `{turn_id, reply_to, reason}` | 回合取消 |
| `turn.error` | `{turn_id, reply_to, code, message}` | 回合失败 |
| `error` | `{code, message, reply_to?}` | 协议/业务错误；不带 `seq` |

`character.state.phase` 取值：`idle` / `thinking` / `speaking` / `error`。`emotion` 为后续情绪状态机预留，当前恒为 `null`。

### 错误码

| code | 含义 | 是否关闭连接 |
| --- | --- | --- |
| `invalid_message` | 信封或 payload 不符合协议（JSON 非法、额外字段、空文本、非法 `session_id`/`after` 等） | 连接初始化阶段关闭；运行期命令不关闭 |
| `unsupported_type` | 信封合法，但该类型不应由客户端发送（例如服务端通知） | 否 |
| `protocol_mismatch` | `protocol` 字段存在但不是 `vob/1`；服务端发送后关闭连接（close code 1008） | 是 |
| `session_not_found` | 请求的会话不存在 | 连接阶段关闭；`session.open` 不关闭 |
| `turn_in_progress` | 预留：需要显式拒绝并发回合时使用；当前不会发出 | — |
| `llm_unavailable` | 对话模型不可达/超时/响应无法解析（出现在 `turn.error`） | 否 |
| `tts_unavailable` | TTS 不可用（出现在 `tts.failed`；HTTP `/tts` 为 503） | 否 |
| `voice_not_found` | 音色档案不存在（`voice.select`） | 否 |
| `internal_error` | 未预期异常（出现在 `turn.error` 或 `error`） | 否 |

## 5. 快照与事件

`session.state` 是从持久层重建的权威快照：

- `messages`：已提交消息（append-only；同一 `message_id` 的修订取最新值），元素为
  `{id, seq, role: "user"|"assistant", text, ts, audio_url?, turn_id?, reply_to?}`。
  - 这里的 `seq` 是**消息记录序号**（消息账本内递增），不是事件账本的 `seq`。
  - 用户消息的 `id` 等于触发它的 `user.text` 命令 `id`；assistant 消息的 `id` 是 `agent.text.message_id`。
- `turns`：由事件账本推导，元素为
  `{turn_id, reply_to, status: "active"|"completed"|"cancelled"|"error", started_seq?, ended_seq?, tts_id?, audio_url?}`。
  - `started_seq` / `ended_seq` 是事件账本的 `seq`。
  - `audio_url` 来自该 turn 最近一次 `tts.ready`；`tts.failed` / `turn.error` 会把它清空。
- `voice`：`{voice_id, display_name}`；hydrate 时 `display_name` 当前为 `null`（会话只存 `voice_id`，展示名由 `voice.selected` 或 `/voices` 提供）。
- `character`：`{phase, emotion, tts_id, audio_url}`；`emotion` 当前恒为 `null`。
- `active_turn_id`：当前 active turn（无则 `null`）。
- `cursor`：快照对应的账本位置，可直接作为重连 `after`。

## 6. 持久化与重放

```text
backend/runtime/
├── audio/<audio_id>.wav
├── voices/
│   ├── profiles.json
│   └── <voice_id>/reference.wav
└── sessions/<session_id>/
    ├── meta.json      # session_id / created_at / persona / voice_id
    ├── messages.jsonl # 已提交消息（含 audio_url 修订）
    └── events.jsonl   # 事件账本（seq/type/payload/ts/reply_to）
```

- 追加写同步落盘；先写账本再广播，保证「重放得到的 == 当时发出的」。
- 只有 12 种事件进入账本：`turn.started`、`agent.text`、`tts.started`、`tts.ready`、`tts.failed`、`tts.cancelled`、`tts.finished`、`voice.selected`、`character.state`、`turn.completed`、`turn.cancelled`、`turn.error`。`server.ready`/`session.opened`/`session.state`/`error` 是连接级消息，不持久化。
- 单会话事件上限默认 2000，超出时从最旧裁剪（只影响 replay；hydrate 从 messages 重建 transcript）。
- 会话 id 只允许 `[A-Za-z0-9_-]{1,64}`，目录名直接使用该 id，禁止路径穿越。
- JSONL 加载器容忍末尾半行（丢弃并记录日志）与中间非法行（跳过并记录日志）。

## 7. turn 与打断语义

一个会话同时最多一个 active turn：

```text
user.text ─▶ turn.started ─▶ character.state(thinking) ─▶ agent.text
          ─▶ tts.started ─▶ tts.ready ─▶ character.state(speaking) ─▶ turn.completed
                                                       └─▶（等待 tts.finished）character.state(idle)
```

- 新的 `user.text` 先取消旧 turn：
  - 旧 turn 正在 LLM 或 TTS 阶段：`tts.cancelled{reason:"interrupted"}`（若在合成）→ `turn.cancelled{reason:"interrupted"}` → `character.state(idle)`，然后新 turn 开始。
  - 旧 turn 已完成、仅音频在播：只补 `tts.cancelled{reason:"interrupted"}` + `character.state(idle)`，不会再有旧 turn 的 `turn.cancelled`。
- `tts.cancel` 只取消 TTS：
  - 合成中：`tts.cancelled{reason:"cancelled"}` + `character.state(idle)` + `turn.completed`（回合已产出的文本保留）。
  - 已 `ready`：`tts.cancelled` + `character.state(idle)`；回合此前已 `turn.completed`。
- TTS 失败：`tts.failed` + `character.state(error)` + `turn.completed`；文本消息仍在 transcript 中。
- LLM 失败：`character.state(error)` + `turn.error{code:"llm_unavailable"}`。
- 未预期异常：`character.state(error)` + `turn.error{code:"internal_error"}`。
- 音频保存在本地后，`audio_url` 同时写入 assistant 消息（追加修订）与 `tts.ready` 事件；用 `GET /tts/{audio_id}` 取回。
- 回合完成不等待播放结束：`turn.completed` 在 `tts.ready` 之后发出，`tts.finished` 由客户端播放结束时回报。

## 8. 契约同步

同一份契约有三处表达，改动必须同步：

1. `shared/contracts/control-message.schema.json` —— 权威定义
2. `backend/app/transport/messages.py` —— pydantic 镜像
3. `apps/desktop/src/renderer/src/transport/protocol.ts` —— TypeScript 镜像

后端 `tests/test_contract_consistency.py` 强制校验 schema ↔ pydantic 的 type 枚举、required 字段、字段集合、`additionalProperties:false` 与嵌套定义，并检查本文件提到每一种消息类型；TS 由桌面端 `npm run typecheck` 覆盖。禁止只改一处。

已知的注释级差异：`protocol.ts` 的 `NotificationType` 注释称 `tts.finished` 不算通知，但该类型实际包含 `tts.finished`，因为它在协议中既是命令也是通知。以代码与 schema 为准。
