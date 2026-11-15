/**
 * 控制通道协议 v2（`vob/1`）—— shared/contracts/control-message.schema.json 的前端镜像。
 * 改动需与 shared/contracts/protocol.md 和后端 app/transport/messages.py 同步。
 */

export const PROTOCOL_VERSION = 'vob/1'

export type ProtocolVersion = typeof PROTOCOL_VERSION

/**
 * 命令（客户端 → 服务端）与通知（服务端 → 客户端）的全部类型。
 * `tts.finished` 同时是命令（播放结束回报）与通知（服务端广播）。
 */
export const MESSAGE_TYPE = {
  // 命令
  SESSION_OPEN: 'session.open',
  SESSION_HYDRATE: 'session.hydrate',
  USER_TEXT: 'user.text',
  VOICE_SELECT: 'voice.select',
  TTS_CANCEL: 'tts.cancel',
  TTS_FINISHED: 'tts.finished',

  // 通知
  SERVER_READY: 'server.ready',
  SESSION_OPENED: 'session.opened',
  SESSION_STATE: 'session.state',
  TURN_STARTED: 'turn.started',
  AGENT_TEXT: 'agent.text',
  TTS_STARTED: 'tts.started',
  TTS_READY: 'tts.ready',
  TTS_FAILED: 'tts.failed',
  TTS_CANCELLED: 'tts.cancelled',
  VOICE_SELECTED: 'voice.selected',
  CHARACTER_STATE: 'character.state',
  TURN_COMPLETED: 'turn.completed',
  TURN_CANCELLED: 'turn.cancelled',
  TURN_ERROR: 'turn.error',
  ERROR: 'error'
} as const

export type MessageType = (typeof MESSAGE_TYPE)[keyof typeof MESSAGE_TYPE]

export type CommandType =
  | typeof MESSAGE_TYPE.SESSION_OPEN
  | typeof MESSAGE_TYPE.SESSION_HYDRATE
  | typeof MESSAGE_TYPE.USER_TEXT
  | typeof MESSAGE_TYPE.VOICE_SELECT
  | typeof MESSAGE_TYPE.TTS_CANCEL
  | typeof MESSAGE_TYPE.TTS_FINISHED

/** 只有服务端才会发送的通知；tts.finished 同时是命令，因此不算进来。 */
export type NotificationType = Exclude<
  MessageType,
  | typeof MESSAGE_TYPE.SESSION_OPEN
  | typeof MESSAGE_TYPE.SESSION_HYDRATE
  | typeof MESSAGE_TYPE.USER_TEXT
  | typeof MESSAGE_TYPE.VOICE_SELECT
  | typeof MESSAGE_TYPE.TTS_CANCEL
>

export type CharacterPhase = 'idle' | 'thinking' | 'speaking' | 'error'
export type TurnStatus = 'active' | 'completed' | 'cancelled' | 'error'
export type MessageRole = 'user' | 'assistant'

// ------------------------------------------------------------------ 信封与能力

export interface Capabilities {
  methods: string[]
  notifications: string[]
  features: string[]
}

export interface ControlMessage {
  protocol: ProtocolVersion
  id: string
  ts: number
  type: MessageType
  reply_to?: string | null
  /** 服务端通知在会话事件账本中的位置；命令不带 seq。 */
  seq?: number | null
  payload: Record<string, unknown>
}

// ------------------------------------------------------------------ 服务端通知

export interface ServerReadyPayload {
  protocol_version: string
  capabilities: Capabilities
}

export interface SessionOpenedPayload {
  session_id: string
  cursor: number
  replayed: number
  voice_id: string
}

export interface MessageView {
  id: string
  seq: number
  role: MessageRole
  text: string
  ts: number
  audio_url?: string | null
  turn_id?: string | null
  reply_to?: string | null
}

export interface TurnView {
  turn_id: string
  reply_to: string
  status: TurnStatus
  started_seq?: number | null
  ended_seq?: number | null
  tts_id?: string | null
  audio_url?: string | null
}

export interface VoiceState {
  voice_id: string
  display_name?: string | null
}

export interface CharacterStatePayload {
  phase: CharacterPhase
  emotion?: string | null
  tts_id?: string | null
  audio_url?: string | null
}

export interface SessionStatePayload {
  session_id: string
  cursor: number
  messages: MessageView[]
  turns: TurnView[]
  voice: VoiceState
  character: CharacterStatePayload
  active_turn_id?: string | null
}

export interface TurnStartedPayload {
  turn_id: string
  reply_to: string
}

export interface AgentTextPayload {
  text: string
  reply_to: string
  message_id: string
  audio_url?: string | null
}

export interface TtsStartedPayload {
  tts_id: string
  reply_to: string
  voice_id: string
}

export interface TtsReadyPayload {
  tts_id: string
  reply_to: string
  voice_id: string
  audio_url: string
  segment_index: number
  segment_count: number
  final: boolean
}

export interface TtsFailedPayload {
  tts_id: string
  reply_to: string
  voice_id: string
  code: string
  message: string
}

export interface TtsCancelledPayload {
  tts_id: string
  reply_to: string
  reason: string
}

export interface TtsFinishedPayload {
  tts_id: string
  reply_to?: string | null
}

export interface VoiceSelectedPayload {
  voice_id: string
  display_name: string
}

export interface TurnCompletedPayload {
  turn_id: string
  reply_to: string
}

export interface TurnCancelledPayload {
  turn_id: string
  reply_to: string
  reason: string
}

export interface TurnErrorPayload {
  turn_id: string
  reply_to: string
  code: string
  message: string
}

export interface ErrorPayload {
  code: string
  message: string
  reply_to?: string | null
}

// ------------------------------------------------------------------ 客户端命令

export interface SessionOpenPayload {
  session_id?: string
  after?: number
}

export interface SessionHydratePayload {
  sections?: string[]
  after?: number
}

export interface UserTextPayload {
  text: string
}

export interface VoiceSelectPayload {
  voice_id: string
}

export interface TtsCancelPayload {
  tts_id: string
}

// ------------------------------------------------------------------ 构建与解析

const KNOWN_TYPES: ReadonlySet<string> = new Set<string>(Object.values(MESSAGE_TYPE))

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function newMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replaceAll('-', '')
  }
  return `msg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** 组装一条待发送的命令；命令不带 seq。 */
export function buildMessage(type: CommandType, payload: Record<string, unknown> = {}): ControlMessage {
  return {
    protocol: PROTOCOL_VERSION,
    id: newMessageId(),
    ts: Date.now(),
    type,
    payload: { ...payload }
  }
}

/**
 * 解析入站消息。信封不合法（protocol/type/id/ts/payload）时返回 null，
 * 未知 type 同样返回 null，不抛异常打断 WebSocket 的 message 回调。
 */
export function parseMessage(raw: string): ControlMessage | null {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }

  if (!isRecord(value)) {
    return null
  }

  const { protocol, id, ts, type, reply_to, seq, payload } = value

  if (protocol !== PROTOCOL_VERSION) {
    return null
  }
  if (typeof type !== 'string' || !KNOWN_TYPES.has(type)) {
    return null
  }
  if (typeof id !== 'string' || id.length === 0) {
    return null
  }
  if (typeof ts !== 'number' || !Number.isInteger(ts) || ts < 0) {
    return null
  }
  if (!isRecord(payload)) {
    return null
  }

  const message: ControlMessage = {
    protocol: PROTOCOL_VERSION,
    id,
    ts,
    type: type as MessageType,
    payload
  }

  if (typeof reply_to === 'string') {
    message.reply_to = reply_to
  } else if (reply_to === null) {
    message.reply_to = null
  }

  if (typeof seq === 'number' && Number.isInteger(seq) && seq >= 1) {
    message.seq = seq
  } else if (seq === null) {
    message.seq = null
  }

  return message
}
