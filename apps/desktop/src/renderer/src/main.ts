import './ui/styles.css'

import { AudioPlayer } from './audio/player'
import { AudioRecorder } from './audio/recorder'
import { Live2DController } from './live2d/controller'
import { ControlClient } from './transport/control-client'
import { createChatView } from './ui/chat'

const DEFAULT_CONTROL_URL = 'ws://127.0.0.1:8090/ws/control'

const chat = createChatView()
const player = new AudioPlayer()
const recorder = new AudioRecorder()
const live2d = new Live2DController()
const live2dCanvas = document.getElementById('live2d-canvas') as HTMLCanvasElement
const live2dStatus = document.getElementById('live2d-status') as HTMLElement
const live2dExpression = document.getElementById('live2d-expression') as HTMLSelectElement
const live2dMotion = document.getElementById('live2d-motion') as HTMLButtonElement

void live2d.mount(live2dCanvas).then(() => {
  live2dStatus.textContent = 'Mao PRO 示例模型已加载'
}).catch((error: unknown) => {
  live2dStatus.textContent = `Live2D 加载失败：${error instanceof Error ? error.message : String(error)}`
})

live2dMotion.addEventListener('click', () => {
  void live2d.playExampleMotion().then((played) => {
    live2dStatus.textContent = played ? '示例动作已播放' : '示例动作未能启动'
  }).catch((error: unknown) => {
    live2dStatus.textContent = `动作播放失败：${error instanceof Error ? error.message : String(error)}`
  })
})

live2dExpression.addEventListener('change', () => {
  if (!live2dExpression.value) return
  void live2d.setExpression(live2dExpression.value).then((applied) => {
    live2dStatus.textContent = applied ? `表情 ${live2dExpression.value} 已应用` : '表情未能应用'
  }).catch((error: unknown) => {
    live2dStatus.textContent = `表情应用失败：${error instanceof Error ? error.message : String(error)}`
  })
})

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
  onTtsStarted: () => {
    chat.appendMessage('system', '正在生成语音…')
  },
  onTtsReady: (payload) => {
    const baseUrl = (controlUrl ?? DEFAULT_CONTROL_URL).replace(/^ws/, 'http').replace(/\/ws\/control$/, '')
    player.play(payload.tts_id, new URL(payload.audio_url, `${baseUrl}/`).toString(), {
      onStarted: () => live2d.setSpeaking(true),
      onEnded: () => {
        chat.setAudioPlaying(false)
        live2d.setSpeaking(false)
      },
      onError: () => {
        chat.setAudioPlaying(false)
        live2d.setSpeaking(false)
        chat.appendMessage('system', '语音播放失败。')
      }
    })
    chat.setAudioPlaying(true)
  },
  onTtsCancelled: () => {
    player.stop()
    live2d.setSpeaking(false)
    chat.setAudioPlaying(false)
  },
  onError: (payload) => {
    chat.setAudioPlaying(false)
    live2d.setSpeaking(false)
    chat.appendMessage('system', `错误 ${payload.code}：${payload.message}`)
  }
})

chat.onSend((text) => {
  client.sendUserText(text)
})

chat.onStopAudio(() => {
  const ttsId = player.stop()
  live2d.setSpeaking(false)
  if (ttsId) {
    client.sendTtsCancel(ttsId)
  }
  chat.setAudioPlaying(false)
})

chat.onRecord(async (recording) => {
  try {
    if (recording) {
      await recorder.start()
      chat.setRecording(true)
      chat.appendMessage('system', '正在录音…')
      return
    }

    chat.setRecording(false)
    chat.appendMessage('system', '正在转写…')
    const audio = await recorder.stop()
    const baseUrl = (controlUrl ?? DEFAULT_CONTROL_URL).replace(/^ws/, 'http').replace(/\/ws\/control$/, '')
    const form = new FormData()
    form.append('audio', audio, 'recording.webm')
    const response = await fetch(`${baseUrl}/asr`, { method: 'POST', body: form })
    if (!response.ok) throw new Error(`ASR HTTP ${response.status}`)
    const result = (await response.json()) as { text: string }
    chat.appendMessage('user', result.text)
    client.sendUserText(result.text)
  } catch (error) {
    chat.setRecording(false)
    chat.appendMessage('system', `录音失败：${error instanceof Error ? error.message : String(error)}`)
  }
})

client.connect()
