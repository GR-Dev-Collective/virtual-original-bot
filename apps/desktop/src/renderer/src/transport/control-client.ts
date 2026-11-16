import {
  buildMessage,
  MESSAGE_TYPE,
  parseMessage,
  type AgentTextPayload,
  type Capabilities,
  type CharacterStatePayload,
  type ErrorPayload,
  type ServerReadyPayload,
  type SessionOpenedPayload,
  type SessionStatePayload,
  type TtsCancelledPayload,
  type TtsFailedPayload,
  type TtsFinishedPayload,
  type TtsReadyPayload,
  type TtsStartedPayload,
  type TurnCancelledPayload,
  type TurnCompletedPayload,
  type TurnErrorPayload,
  type TurnStartedPayload,
  type VoiceSelectedPayload
} from './protocol'

export type ConnectionStatus = 'connecting' | 'online' | 'offline'

export interface ControlClientHandlers {
  onStatus(status: ConnectionStatus): void
  onReady(capabilities: Capabilities): void
  onOpened(payload: SessionOpenedPayload): void
  onSessionState(payload: SessionStatePayload): void
  onCharacterState(payload: CharacterStatePayload): void
  onTurnStarted(payload: TurnStartedPayload): void
  onTurnCompleted(payload: TurnCompletedPayload): void
  onTurnCancelled(payload: TurnCancelledPayload): void
  onTurnError(payload: TurnErrorPayload): void
  onAgentText(payload: AgentTextPayload): void
  onTtsStarted(payload: TtsStartedPayload): void
  onTtsReady(payload: TtsReadyPayload): void
  onTtsFailed(payload: TtsFailedPayload): void
  onTtsCancelled(payload: TtsCancelledPayload): void
  onTtsFinished(payload: TtsFinishedPayload): void
  onVoiceSelected(payload: VoiceSelectedPayload): void
  onError(payload: ErrorPayload): void
  /** 会话账本 cursor 前进时回调，调用方可写回 localStorage 供下次 after 重放。 */
  onCursor?(cursor: number): void
}

export interface ControlClientOptions {
  /** 上次的 session_id；恢复同一会话，缺省则让服务端新建。 */
  sessionId?: string | null
  /** 上次收到的最大 seq；重连时服务端重放 seq > after 的事件。 */
  after?: number | null
  reconnectDelayMs?: number
  /** session.opened 之后自动补发 session.hydrate 请求权威快照（默认 true）。 */
  hydrateOnOpen?: boolean
}

const RECONNECT_DELAY_MS = 2000

/**
 * 控制通道客户端。
 *
 * - 连接 URL 由调用方给出，`session_id` / `after` 查询参数由本类按最新状态补齐；
 * - 断线后自动重连：保留最新 cursor，重连时带 `after` 重放，并在 session.opened 后补发 hydrate；
 * - 断线期间发出的命令进入队列，连上后按序补发；
 * - 重放事件按 seq 去重，避免恢复快照与实时通知重复渲染。
 */
export class ControlClient {
  private socket: WebSocket | null = null
  private disposed = false
  private readonly queue: string[] = []
  private reconnectTimer: number | null = null

  private sessionId: string | null
  private cursor: number
  private lastSeq: number

  private readonly reconnectDelayMs: number
  private readonly hydrateOnOpen: boolean

  constructor(
    private readonly url: string,
    private readonly handlers: ControlClientHandlers,
    options: ControlClientOptions = {}
  ) {
    this.sessionId = options.sessionId ?? null
    this.cursor = Math.max(0, options.after ?? 0)
    this.lastSeq = this.cursor
    this.reconnectDelayMs = options.reconnectDelayMs ?? RECONNECT_DELAY_MS
    this.hydrateOnOpen = options.hydrateOnOpen ?? true
  }

  get currentCursor(): number {
    return this.cursor
  }

  get currentSessionId(): string | null {
    return this.sessionId
  }

  connect(): void {
    this.disposed = false
    this.open()
  }

  // ------------------------------------------------------------------ 命令

  sendUserText(text: string): void {
    this.send(buildMessage(MESSAGE_TYPE.USER_TEXT, { text }))
  }

  sendVoiceSelect(voiceId: string): void {
    this.send(buildMessage(MESSAGE_TYPE.VOICE_SELECT, { voice_id: voiceId }))
  }

  sendTtsCancel(ttsId: string): void {
    this.send(buildMessage(MESSAGE_TYPE.TTS_CANCEL, { tts_id: ttsId }))
  }

  sendTtsFinished(ttsId: string): void {
    this.send(buildMessage(MESSAGE_TYPE.TTS_FINISHED, { tts_id: ttsId }))
  }

  sendHydrate(sections?: string[]): void {
    const payload: Record<string, unknown> = {}
    if (sections && sections.length > 0) {
      payload.sections = [...sections]
    }
    this.send(buildMessage(MESSAGE_TYPE.SESSION_HYDRATE, payload))
  }

  sendSessionOpen(sessionId?: string | null, after?: number | null): void {
    const payload: Record<string, unknown> = {}
    const target = sessionId ?? this.sessionId
    if (target) {
      payload.session_id = target
    }
    const cursor = after ?? this.cursor
    if (typeof cursor === 'number' && Number.isInteger(cursor) && cursor > 0) {
      payload.after = cursor
    }
    this.send(buildMessage(MESSAGE_TYPE.SESSION_OPEN, payload))
  }

  /** 丢弃当前会话身份并重连；服务端会新建会话。 */
  startNewSession(): void {
    this.sessionId = null
    this.cursor = 0
    this.lastSeq = 0
    this.socket?.close()
  }

  dispose(): void {
    this.disposed = true
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
    this.socket = null
  }

  // ------------------------------------------------------------------ 连接

  private buildUrl(): string {
    let base: URL
    try {
      base = new URL(this.url)
    } catch {
      // 非绝对地址时退化为字符串拼接，保持旧行为可用。
      const separator = this.url.includes('?') ? '&' : '?'
      const params = new URLSearchParams()
      if (this.sessionId) params.set('session_id', this.sessionId)
      if (this.cursor > 0) params.set('after', String(this.cursor))
      const query = params.toString()
      return query ? `${this.url}${separator}${query}` : this.url
    }

    base.searchParams.delete('session_id')
    base.searchParams.delete('after')
    base.searchParams.set('protocol', 'vob/1')
    if (this.sessionId) {
      base.searchParams.set('session_id', this.sessionId)
    }
    if (this.cursor > 0) {
      base.searchParams.set('after', String(this.cursor))
    }
    return base.toString()
  }

  private open(): void {
    if (this.disposed) {
      return
    }
    this.handlers.onStatus('connecting')

    let socket: WebSocket
    try {
      socket = new WebSocket(this.buildUrl())
    } catch {
      this.handlers.onStatus('offline')
      this.scheduleReconnect()
      return
    }
    this.socket = socket

    socket.addEventListener('open', () => {
      if (this.socket !== socket) return
      this.handlers.onStatus('online')
      this.flush()
    })

    socket.addEventListener('message', (event: MessageEvent<unknown>) => {
      if (this.socket !== socket) return
      if (typeof event.data === 'string') {
        this.handle(event.data)
      }
    })

    socket.addEventListener('close', () => {
      if (this.socket === socket) {
        this.socket = null
      }
      this.handlers.onStatus('offline')
      this.scheduleReconnect()
    })

    // error 之后浏览器会跟着触发 close，重连逻辑统一放在 close 里
    socket.addEventListener('error', () => {
      socket.close()
    })
  }

  private scheduleReconnect(): void {
    if (this.disposed || this.reconnectTimer !== null) {
      return
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.open()
    }, this.reconnectDelayMs)
  }

  private flush(): void {
    const socket = this.socket
    if (socket?.readyState !== WebSocket.OPEN) {
      return
    }
    for (const message of this.queue.splice(0)) {
      socket.send(message)
    }
  }

  private send(message: ReturnType<typeof buildMessage>): void {
    const serialized = JSON.stringify(message)
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(serialized)
    } else {
      this.queue.push(serialized)
    }
  }

  // ------------------------------------------------------------------ 收包

  private handle(raw: string): void {
    const message = parseMessage(raw)
    if (!message) {
      return
    }

    const seq = typeof message.seq === 'number' ? message.seq : null
    if (seq !== null) {
      // 重放/重复事件：已经应用过就跳过。
      if (seq <= this.lastSeq) {
        return
      }
      this.lastSeq = seq
      this.touchCursor(seq)
    }

    switch (message.type) {
      case MESSAGE_TYPE.SERVER_READY: {
        const payload = message.payload as unknown as ServerReadyPayload
        this.handlers.onReady(payload.capabilities)
        break
      }
      case MESSAGE_TYPE.SESSION_OPENED: {
        const payload = message.payload as unknown as SessionOpenedPayload
        this.sessionId = payload.session_id
        // session.opened 的 cursor 是服务端权威位置：重放已在此之前完成，
        // 用它对齐可以自愈本地存下的过期/超前 cursor。
        this.lastSeq = payload.cursor
        this.handlers.onOpened(payload)
        this.touchCursor(payload.cursor)
        if (this.hydrateOnOpen) {
          this.sendHydrate()
        }
        break
      }
      case MESSAGE_TYPE.SESSION_STATE:
        this.handlers.onSessionState(message.payload as unknown as SessionStatePayload)
        break
      case MESSAGE_TYPE.CHARACTER_STATE:
        this.handlers.onCharacterState(message.payload as unknown as CharacterStatePayload)
        break
      case MESSAGE_TYPE.TURN_STARTED:
        this.handlers.onTurnStarted(message.payload as unknown as TurnStartedPayload)
        break
      case MESSAGE_TYPE.TURN_COMPLETED:
        this.handlers.onTurnCompleted(message.payload as unknown as TurnCompletedPayload)
        break
      case MESSAGE_TYPE.TURN_CANCELLED:
        this.handlers.onTurnCancelled(message.payload as unknown as TurnCancelledPayload)
        break
      case MESSAGE_TYPE.TURN_ERROR:
        this.handlers.onTurnError(message.payload as unknown as TurnErrorPayload)
        break
      case MESSAGE_TYPE.AGENT_TEXT:
        this.handlers.onAgentText(message.payload as unknown as AgentTextPayload)
        break
      case MESSAGE_TYPE.TTS_STARTED:
        this.handlers.onTtsStarted(message.payload as unknown as TtsStartedPayload)
        break
      case MESSAGE_TYPE.TTS_READY:
        this.handlers.onTtsReady(message.payload as unknown as TtsReadyPayload)
        break
      case MESSAGE_TYPE.TTS_FAILED:
        this.handlers.onTtsFailed(message.payload as unknown as TtsFailedPayload)
        break
      case MESSAGE_TYPE.TTS_CANCELLED:
        this.handlers.onTtsCancelled(message.payload as unknown as TtsCancelledPayload)
        break
      case MESSAGE_TYPE.TTS_FINISHED:
        this.handlers.onTtsFinished(message.payload as unknown as TtsFinishedPayload)
        break
      case MESSAGE_TYPE.VOICE_SELECTED:
        this.handlers.onVoiceSelected(message.payload as unknown as VoiceSelectedPayload)
        break
      case MESSAGE_TYPE.ERROR: {
        const payload = message.payload as unknown as ErrorPayload
        if (payload.code === 'session_not_found') {
          // 本地存的会话在服务端已不存在：丢掉它，重连时让服务端新建。
          this.sessionId = null
          this.cursor = 0
          this.lastSeq = 0
        }
        this.handlers.onError(payload)
        break
      }
      default:
        break
    }
  }

  private touchCursor(cursor: number): void {
    if (!Number.isInteger(cursor) || cursor < 0) {
      return
    }
    this.cursor = cursor
    this.handlers.onCursor?.(cursor)
  }
}
