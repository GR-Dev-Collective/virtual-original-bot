import './ui/styles.css'

import { ControlClient } from './transport/control-client'
import { createChatView } from './ui/chat'

const DEFAULT_CONTROL_URL = 'ws://127.0.0.1:8090/ws/control'

const chat = createChatView()

const controlUrl = window.vob?.controlUrl
if (!controlUrl) {
  chat.appendMessage('system', '未读到 preload 桥，回退到默认后端地址。')
}

const client = new ControlClient(controlUrl ?? DEFAULT_CONTROL_URL, {
  onStatus: (status) => {
    chat.setStatus(status)
  },
  onSessionReady: (payload) => {
    chat.appendMessage('system', `会话已建立：${payload.session_id.slice(0, 8)}`)
  },
  onAgentText: (payload) => {
    chat.appendMessage('agent', payload.text)
  },
  onError: (payload) => {
    chat.appendMessage('system', `错误 ${payload.code}：${payload.message}`)
  }
})

chat.onSend((text) => {
  client.sendUserText(text)
})

client.connect()
