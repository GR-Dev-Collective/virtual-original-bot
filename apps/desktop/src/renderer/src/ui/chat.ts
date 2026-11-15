import type { ConnectionStatus } from '../transport/control-client'
import type { CharacterPhase } from '../transport/protocol'

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  connecting: '连接中…',
  online: '已连接',
  offline: '已断开，重连中…'
}

const PHASE_TEXT: Record<CharacterPhase, string> = {
  idle: '空闲',
  thinking: '思考中…',
  speaking: '说话中…',
  error: '出错了'
}

export type MessageRole = 'user' | 'agent' | 'system'

export interface MessageOptions {
  /** 服务端消息 id，用于快照与实时事件去重。 */
  messageId?: string | null
  /** 有音频时展示「重播」按钮。 */
  audioUrl?: string | null
  onReplay?: (() => void) | null
}

export interface ChatView {
  onSend(handler: (text: string) => void): void
  onStopAudio(handler: () => void): void
  onRecord(handler: (recording: boolean) => void): void
  appendMessage(role: MessageRole, text: string, options?: MessageOptions): void
  /** 给已渲染的 agent 消息补一个「重播」按钮（实时 tts.ready 先于快照到达时用）。 */
  attachReplay(messageId: string, onReplay: () => void): void
  clearMessages(): void
  setStatus(status: ConnectionStatus): void
  setCharacterPhase(phase: CharacterPhase): void
  setAudioPlaying(playing: boolean): void
  setRecording(recording: boolean): void
}

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id)
  if (!element) {
    throw new Error(`页面缺少元素 #${id}`)
  }
  return element as T
}

export function createChatView(): ChatView {
  const messages = requireElement<HTMLElement>('messages')
  const composer = requireElement<HTMLFormElement>('composer')
  const input = requireElement<HTMLInputElement>('input')
  const status = requireElement<HTMLElement>('status')
  const characterStatus = requireElement<HTMLElement>('character-status')
  const stopAudio = requireElement<HTMLButtonElement>('stop-audio')
  const record = requireElement<HTMLButtonElement>('record')

  let send: (text: string) => void = () => {}
  let recordHandler: (recording: boolean) => void = () => {}
  let stop: () => void = () => {}

  function appendMessage(role: MessageRole, text: string, options: MessageOptions = {}): void {
    const item = document.createElement('div')
    item.className = `message message--${role}`
    if (options.messageId) {
      item.dataset.messageId = options.messageId
    }

    const body = document.createElement('div')
    body.className = 'message__body'

    const bubble = document.createElement('p')
    bubble.className = 'message__bubble'
    bubble.textContent = text
    body.append(bubble)

    if (role === 'agent' && options.audioUrl && options.onReplay) {
      body.append(createReplayButton(options.onReplay))
    }

    item.append(body)
    messages.append(item)
    messages.scrollTop = messages.scrollHeight
  }

  function clearMessages(): void {
    messages.replaceChildren()
  }

  function createReplayButton(onReplay: () => void): HTMLButtonElement {
    const replay = document.createElement('button')
    replay.type = 'button'
    replay.className = 'message__replay'
    replay.textContent = '重播'
    replay.title = '重播这条语音'
    replay.addEventListener('click', () => onReplay())
    return replay
  }

  function attachReplay(messageId: string, onReplay: () => void): void {
    const item = messages.querySelector<HTMLElement>(`.message[data-message-id="${CSS.escape(messageId)}"]`)
    if (!item) {
      return
    }
    const body = item.querySelector('.message__body')
    if (!body || body.querySelector('.message__replay')) {
      return
    }
    body.append(createReplayButton(onReplay))
  }

  stopAudio.addEventListener('click', () => stop())
  record.addEventListener('click', () => recordHandler(record.dataset.recording !== 'true'))

  composer.addEventListener('submit', (event) => {
    event.preventDefault()

    const text = input.value.trim()
    if (text.length === 0) {
      return
    }

    input.value = ''
    appendMessage('user', text)
    send(text)
  })

  return {
    onSend(handler) {
      send = handler
    },
    onStopAudio(handler) {
      stop = handler
    },
    onRecord(handler) {
      recordHandler = handler
    },
    appendMessage,
    attachReplay,
    clearMessages,
    setStatus(next) {
      status.textContent = STATUS_TEXT[next]
      status.className = `status status--${next}`
    },
    setCharacterPhase(phase) {
      characterStatus.textContent = PHASE_TEXT[phase]
      characterStatus.className = `status status--character-${phase}`
    },
    setAudioPlaying(playing) {
      stopAudio.disabled = !playing
    },
    setRecording(recording) {
      record.dataset.recording = String(recording)
      record.textContent = recording ? '停止录音' : '开始录音'
      record.disabled = false
    }
  }
}
