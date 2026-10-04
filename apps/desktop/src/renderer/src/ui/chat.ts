import type { ConnectionStatus } from '../transport/control-client'

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  connecting: '连接中…',
  online: '已连接',
  offline: '已断开，重连中…'
}

export type MessageRole = 'user' | 'agent' | 'system'
export type RecorderUiState = 'idle' | 'requesting' | 'recording' | 'transcribing'

export interface ChatView {
  onSend(handler: (text: string) => void): void
  onStopAudio(handler: () => void): void
  onRecord(handler: (recording: boolean) => void): void
  appendMessage(role: MessageRole, text: string): void
  setStatus(status: ConnectionStatus): void
  setAudioPlaying(playing: boolean): void
  setRecordingState(state: RecorderUiState): void
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
  const stopAudio = requireElement<HTMLButtonElement>('stop-audio')
  const record = requireElement<HTMLButtonElement>('record')

  let send: (text: string) => void = () => {}
  let recordHandler: (recording: boolean) => void = () => {}
  let stop: () => void = () => {}

  function appendMessage(role: MessageRole, text: string): void {
    const item = document.createElement('div')
    item.className = `message message--${role}`

    const bubble = document.createElement('p')
    bubble.className = 'message__bubble'
    bubble.textContent = text

    item.append(bubble)
    messages.append(item)
    messages.scrollTop = messages.scrollHeight
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
    setStatus(next) {
      status.textContent = STATUS_TEXT[next]
      status.className = `status status--${next}`
    },
    setAudioPlaying(playing) {
      stopAudio.disabled = !playing
    },
    setRecordingState(state) {
      record.dataset.recording = String(state === 'recording')
      record.textContent = {
        idle: '开始录音',
        requesting: '请求麦克风中…',
        recording: '停止录音',
        transcribing: '转写中…'
      }[state]
      record.disabled = state === 'requesting' || state === 'transcribing'
    }
  }
}
