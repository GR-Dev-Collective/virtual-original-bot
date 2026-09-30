/**
 * 控制通道协议 —— shared/contracts/control-message.schema.json 的前端镜像。
 * 改动需与 shared/contracts/protocol.md 和后端 app/transport/messages.py 同步。
 */

export const MESSAGE_TYPE = {
  SESSION_READY: 'session.ready',
  USER_TEXT: 'user.text',
  AGENT_TEXT: 'agent.text',
  ERROR: 'error'
} as const

export type MessageType = (typeof MESSAGE_TYPE)[keyof typeof MESSAGE_TYPE]

export interface SessionReadyPayload {
  session_id: string
}

export interface UserTextPayload {
  text: string
}

export interface AgentTextPayload {
  text: string
  reply_to: string
}

export interface ErrorPayload {
  code: string
  message: string
  reply_to?: string | null
}

export interface ControlMessage {
  type: MessageType
  id: string
  ts: number
  payload: Record<string, unknown>
}

const KNOWN_TYPES: readonly string[] = Object.values(MESSAGE_TYPE)

export function buildMessage(type: MessageType, payload: object): ControlMessage {
  return {
    type,
    id: crypto.randomUUID().replaceAll('-', ''),
    ts: Date.now(),
    payload: { ...payload }
  }
}

/**
 * 解析入站消息。信封不合法时返回 null，由调用方决定如何提示，
 * 不在这里抛异常打断 WebSocket 的 message 回调。
 */
export function parseMessage(raw: string): ControlMessage | null {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }

  if (typeof value !== 'object' || value === null) {
    return null
  }

  const candidate = value as Partial<ControlMessage>
  if (
    typeof candidate.type !== 'string' ||
    !KNOWN_TYPES.includes(candidate.type) ||
    typeof candidate.id !== 'string' ||
    typeof candidate.ts !== 'number' ||
    typeof candidate.payload !== 'object' ||
    candidate.payload === null
  ) {
    return null
  }

  return candidate as ControlMessage
}
