import type { ConnectionStatus } from '../transport/control-client'

const STATUS_TEXT: Record<ConnectionStatus, string> = {
  connecting: '连接中…',
  online: '已连接',
  offline: '已断开，重连中…'
}

export type MessageRole = 'user' | 'agent' | 'system'

export interface ChatView {
  onSend(handler: (text: string) => void): void
  appendMessage(role: MessageRole, text: string): void
  setStatus(status: ConnectionStatus): void
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

  let send: (text: string) => void = () => {}

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
    appendMessage,
    setStatus(next) {
      status.textContent = STATUS_TEXT[next]
      status.className = `status status--${next}`
    }
  }
}
