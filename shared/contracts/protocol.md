# 控制通道协议

控制通道是一条 WebSocket，承载用户输入、Agent 回复、状态与错误。它是 Electron 与 FastAPI 之间唯一的前端入口。

- 地址：`ws://<host>:<port>/ws/control`
- 编码：UTF-8 JSON，每条消息一个文本帧
- 权威定义：[`control-message.schema.json`](./control-message.schema.json)

## 消息信封

所有消息共用同一个信封，`payload` 的形状由 `type` 决定。

```json
{
  "type": "user.text",
  "id": "5f2c1a...",
  "ts": 1790682389711,
  "payload": { "text": "你好" }
}
```

- `id` 由发送方生成，接收方用 `reply_to` 回指。
- `ts` 是 Unix 毫秒时间戳。

## 消息类型

| type | 方向 | payload | 说明 |
|---|---|---|---|
| `session.ready` | 后端 → 前端 | `{ session_id }` | 连接建立后由后端首先发出 |
| `user.text` | 前端 → 后端 | `{ text }` | 用户提交的文本 |
| `agent.text` | 后端 → 前端 | `{ text, reply_to }` | Agent 回复，`reply_to` 指向对应的 `user.text` |
| `tts.started` | 后端 → 前端 | `{ tts_id, reply_to }` | TTS 任务开始 |
| `tts.ready` | 后端 → 前端 | `{ tts_id, reply_to, audio_url }` | 音频已生成，可播放 |
| `tts.cancel` | 前端 → 后端 | `{ tts_id }` | 请求取消当前 TTS |
| `tts.cancelled` | 后端 → 前端 | `{ tts_id, reply_to, reason }` | TTS 任务已取消 |
| `error` | 后端 → 前端 | `{ code, message, reply_to? }` | 入站消息非法或处理失败；`reply_to` 可能为 `null` |

### error 的 code

| code | 含义 |
|---|---|
| `invalid_message` | 信封或 payload 不符合本协议 |
| `unsupported_type` | 信封合法，但该类型不应由前端发送 |
| `llm_unavailable` | 对话模型不可达、超时或返回无法解析的响应 |

收到 `error` 不会关闭连接，前端可以继续发送后续消息。

## 时序

```text
前端                                后端
 │  ── WebSocket 连接 ─────────────▶ │
 │  ◀── session.ready ────────────── │
 │  ── user.text ──────────────────▶ │
 │  ◀── agent.text (reply_to=...) ── │
 │  ── user.text ──────────────────▶ │
 │  ◀── error ───────────────────── │
```

## 同步要求

同一份契约有三处表达，改动必须同步：

1. `shared/contracts/control-message.schema.json` —— 权威定义
2. `backend/app/transport/messages.py` —— 后端的 pydantic 镜像
3. `apps/desktop/src/renderer/src/transport/protocol.ts` —— 前端的 TypeScript 镜像

## 后续计划

Phase 2 会在此基础上增加 ASR 中间/最终结果、TTS 播放状态、情绪与 Live2D 状态、Action 请求与结果。音频流不进这条通道，将另开独立的语音 WebSocket，避免阻塞控制消息。
