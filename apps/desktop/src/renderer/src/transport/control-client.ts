import {
  buildMessage,
  MESSAGE_TYPE,
  parseMessage,
  type AgentTextPayload,
  type ErrorPayload,
  type SessionReadyPayload
} from './protocol'

export type ConnectionStatus = 'connecting' | 'online' | 'offline'

export interface ControlClientHandlers {
  onStatus(status: ConnectionStatus): void
  onSessionReady(payload: SessionReadyPayload): void
  onAgentText(payload: AgentTextPayload): void
  onError(payload: ErrorPayload): void
}

const RECONNECT_DELAY_MS = 2000

/**
 * 控制通道客户端。断线后会自动重连，重连期间发出的文本会排队，连上后补发。
 */
export class ControlClient {
  private socket: WebSocket | null = null
  private disposed = false
  private readonly queue: string[] = []

  constructor(
    private readonly url: string,
    private readonly handlers: ControlClientHandlers
  ) {}

  connect(): void {
    this.disposed = false
    this.open()
  }

  sendUserText(text: string): void {
    const message = JSON.stringify(buildMessage(MESSAGE_TYPE.USER_TEXT, { text }))

    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(message)
    } else {
      this.queue.push(message)
    }
  }

  dispose(): void {
    this.disposed = true
    this.socket?.close()
    this.socket = null
  }

  private open(): void {
    this.handlers.onStatus('connecting')

    const socket = new WebSocket(this.url)
    this.socket = socket

    socket.addEventListener('open', () => {
      this.handlers.onStatus('online')
      for (const message of this.queue.splice(0)) {
        socket.send(message)
      }
    })

    socket.addEventListener('message', (event: MessageEvent<unknown>) => {
      if (typeof event.data === 'string') {
        this.handle(event.data)
      }
    })

    socket.addEventListener('close', () => {
      this.handlers.onStatus('offline')
      if (!this.disposed) {
        window.setTimeout(() => this.open(), RECONNECT_DELAY_MS)
      }
    })

    // error 之后浏览器会跟着触发 close，重连逻辑统一放在 close 里
    socket.addEventListener('error', () => {
      socket.close()
    })
  }

  private handle(raw: string): void {
    const message = parseMessage(raw)
    if (!message) {
      return
    }

    switch (message.type) {
      case MESSAGE_TYPE.SESSION_READY:
        this.handlers.onSessionReady(message.payload as unknown as SessionReadyPayload)
        break
      case MESSAGE_TYPE.AGENT_TEXT:
        this.handlers.onAgentText(message.payload as unknown as AgentTextPayload)
        break
      case MESSAGE_TYPE.ERROR:
        this.handlers.onError(message.payload as unknown as ErrorPayload)
        break
      default:
        break
    }
  }
}
