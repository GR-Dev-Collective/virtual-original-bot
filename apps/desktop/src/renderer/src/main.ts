import './ui/styles.css'

import { AudioPlayer } from './audio/player'
import { AudioRecorder } from './audio/recorder'
import { cloneVoice, deleteVoice, httpBaseFromControlUrl, listVoices, renameVoice, type VoiceProfile } from './api/voices'
import { listSessions } from './api/sessions'
import { addMemoryNote, deleteMemoryNote, getMemory } from './api/memory'
import { Live2DController } from './live2d/controller'
import { ControlClient } from './transport/control-client'
import type {
  AgentTextPayload,
  CharacterStatePayload,
  SessionOpenedPayload,
  SessionStatePayload,
  TtsReadyPayload
} from './transport/protocol'
import { createChatView } from './ui/chat'
import { createVoiceView } from './ui/voices'
import { createMemoryView } from './ui/memory'

const DEFAULT_CONTROL_URL = 'ws://127.0.0.1:8090/ws/control'
const SESSION_STORAGE_KEY = 'vob.session_id'
const CURSOR_STORAGE_KEY = 'vob.cursor'

// ------------------------------------------------------------------ 本地持久化

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
  } catch {
    // 隐私模式或存储被禁用：只影响断线恢复，忽略即可。
  }
}

function readStoredCursor(): number | null {
  const raw = readStorage(CURSOR_STORAGE_KEY)
  if (raw === null || raw === '') {
    return null
  }
  const value = Number(raw)
  return Number.isInteger(value) && value >= 0 ? value : null
}

// ------------------------------------------------------------------ 视图与运行时

const chat = createChatView()
const voiceView = createVoiceView()
const memoryView = createMemoryView()
const player = new AudioPlayer()
const recorder = new AudioRecorder()
const live2d = new Live2DController()

const live2dCanvas = document.getElementById('live2d-canvas') as HTMLCanvasElement
const live2dStatus = document.getElementById('live2d-status') as HTMLElement
const live2dExpression = document.getElementById('live2d-expression') as HTMLSelectElement
const live2dMotion = document.getElementById('live2d-motion') as HTMLButtonElement
const sessionSelect = document.getElementById('session-select') as HTMLSelectElement
const sessionNew = document.getElementById('session-new') as HTMLButtonElement
let ignoreSessionChange = false

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

// ------------------------------------------------------------------ 后端地址

const controlUrl = window.vob?.controlUrl
if (!controlUrl) {
  chat.appendMessage('system', '未读到 preload 桥，回退到默认后端地址。')
}
const resolvedControlUrl = controlUrl ?? DEFAULT_CONTROL_URL
const httpBase = httpBaseFromControlUrl(resolvedControlUrl)

// ------------------------------------------------------------------ 音色与播放状态

type PlaybackKind = 'tts' | 'replay'

let voices: VoiceProfile[] = []
let voicesLoaded = false
let currentVoiceId: string | null = null
let voiceSelectSupported = true
let activeTurnId: string | null = null
let activeTtsId: string | null = null
let activePlayback: PlaybackKind | null = null

/** 已渲染的 agent 消息 id：快照 + 实时事件去重。 */
const renderedAgentMessages = new Set<string>()
/** 快照重建前收到的实时 agent 消息，用于补齐竞态漏掉的内容。 */
const pendingAgentMessages = new Map<string, { text: string; audioUrl: string | null }>()
/** reply_to（user.text 命令 id）→ agent 消息 id，实时 tts.ready 用于找到对应气泡。 */
const messageIdByReplyTo = new Map<string, string>()
/** session.opened 的提示；等 hydrate 快照重建聊天区后再显示，避免被重建清掉。 */
let pendingSessionNotice: string | null = null

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

function resolveAudioUrl(audioUrl: string): string {
  try {
    return new URL(audioUrl, `${httpBase}/`).toString()
  } catch {
    return audioUrl
  }
}

// ------------------------------------------------------------------ 音频播放

function stopPlayback(): string | null {
  const ttsId = player.stop()
  activePlayback = null
  activeTtsId = null
  live2d.setMouthLevel(0)
  chat.setAudioPlaying(false)
  live2d.setSpeaking(false)
  return ttsId
}

function startPlayback(kind: PlaybackKind, playbackId: string, audioUrl: string): void {
  activePlayback = kind
  player.play(playbackId, resolveAudioUrl(audioUrl), {
    onStarted: () => {
      live2d.setSpeaking(true)
      chat.setAudioPlaying(true)
    },
    onEnded: () => {
      const wasTts = kind === 'tts'
      activePlayback = null
      activeTtsId = null
      chat.setAudioPlaying(false)
      live2d.setSpeaking(false)
      chat.setCharacterPhase('idle')
      if (wasTts) {
        // 播放结束回报，服务端据此把角色状态投影回 idle。
        client.sendTtsFinished(playbackId)
      }
    },
    onError: () => {
      const wasTts = kind === 'tts'
      activePlayback = null
      activeTtsId = null
      chat.setAudioPlaying(false)
      live2d.setSpeaking(false)
      chat.setCharacterPhase('error')
      chat.appendMessage('system', '语音播放失败，请检查后端音频地址是否可访问。')
      if (wasTts) {
        // 播放端失败也要结束这次 TTS，避免服务端一直停留在 speaking。
        client.sendTtsFinished(playbackId)
      }
    }
  })
  chat.setAudioPlaying(true)
}

function replayHistoryAudio(messageId: string, audioUrl: string): void {
  const interrupted = activePlayback
  const previousTtsId = player.stop()
  if (interrupted === 'tts' && previousTtsId) {
    client.sendTtsCancel(previousTtsId)
  }
  startPlayback('replay', `history:${messageId}`, audioUrl)
}

function auditionVoice(voiceId: string): void {
  const interrupted = activePlayback
  const previousTtsId = player.stop()
  if (interrupted === 'tts' && previousTtsId) {
    client.sendTtsCancel(previousTtsId)
  }
  const url = `${httpBase}/voices/${encodeURIComponent(voiceId)}/sample`
  startPlayback('replay', `voice:${voiceId}`, url)
  voiceView.setHint('正在试听参考音频…')
}

function removeVoice(voiceId: string): void {
  const voice = findVoice(voiceId)
  if (!voice || voice.builtin) {
    return
  }
  if (!window.confirm(`删除音色「${voice.display_name}」？参考音频会一并删除。`)) {
    return
  }
  voiceView.setHint('正在删除音色…')
  void deleteVoice(httpBase, voiceId)
    .then(async () => {
      voiceView.setHint(`已删除音色：${voice.display_name}`)
      if (currentVoiceId === voiceId) {
        currentVoiceId = null
      }
      await refreshVoices({ selectDefault: currentVoiceId === null })
    })
    .catch((error: unknown) => {
      voiceView.setHint(`删除失败：${describeError(error)}`, 'error')
    })
}

function renameVoiceAction(voiceId: string): void {
  const voice = findVoice(voiceId)
  if (!voice || voice.builtin) {
    return
  }
  const nextName = window.prompt('新的音色名称', voice.display_name)?.trim()
  if (!nextName || nextName === voice.display_name) {
    return
  }
  voiceView.setHint('正在重命名…')
  void renameVoice(httpBase, voiceId, nextName)
    .then(async () => {
      voiceView.setHint(`已重命名为：${nextName}`)
      await refreshVoices({ preferredId: voiceId })
    })
    .catch((error: unknown) => {
      voiceView.setHint(`重命名失败：${describeError(error)}`, 'error')
    })
}

function enqueueTtsSegment(payload: TtsReadyPayload): void {
  const messageId = messageIdByReplyTo.get(payload.reply_to) ?? null
  if (payload.segment_index === 0) {
    if (messageId) {
      // agent.text 先于 tts.ready；用首段音频给历史消息补重播按钮。
      chat.attachReplay(messageId, () => replayHistoryAudio(messageId, payload.audio_url))
    }
    activePlayback = 'tts'
    activeTtsId = payload.tts_id
  }

  player.enqueue(
    {
      ttsId: payload.tts_id,
      index: payload.segment_index,
      url: resolveAudioUrl(payload.audio_url),
      final: payload.final
    },
    {
      onStarted: () => {
        live2d.setSpeaking(true)
        chat.setAudioPlaying(true)
      },
      onAllEnded: () => {
        if (activeTtsId !== payload.tts_id) {
          return
        }
        activePlayback = null
        activeTtsId = null
        chat.setAudioPlaying(false)
        live2d.setSpeaking(false)
        chat.setCharacterPhase('idle')
        // 最后一段播完再回报，服务端据此把投影切回 idle。
        client.sendTtsFinished(payload.tts_id)
      },
      onError: () => {
        if (activeTtsId !== payload.tts_id) {
          return
        }
        activePlayback = null
        activeTtsId = null
        chat.setAudioPlaying(false)
        live2d.setSpeaking(false)
        chat.setCharacterPhase('error')
        chat.appendMessage('system', '语音播放失败，请检查后端音频地址是否可访问。')
        client.sendTtsFinished(payload.tts_id)
      }
    }
  )
  chat.setAudioPlaying(true)
}

// ------------------------------------------------------------------ 角色状态

const EMOTION_EXPRESSIONS: Record<string, string> = {
  happy: 'exp_01',
  angry: 'exp_02',
  sad: 'exp_03',
  afraid: 'exp_04',
  disgusted: 'exp_05',
  melancholic: 'exp_06',
  surprised: 'exp_07',
  calm: 'exp_08'
}

function applyCharacterState(payload: CharacterStatePayload): void {
  chat.setCharacterPhase(payload.phase)
  live2d.setSpeaking(payload.phase === 'speaking')
  const expression = payload.emotion ? EMOTION_EXPRESSIONS[payload.emotion] : undefined
  if (expression) {
    void live2d.setExpression(expression).catch(() => undefined)
  }
}

// ------------------------------------------------------------------ 聊天渲染

function renderAgentMessage(
  messageId: string | null,
  text: string,
  audioUrl: string | null
): void {
  if (messageId) {
    if (renderedAgentMessages.has(messageId)) {
      return
    }
    renderedAgentMessages.add(messageId)
    pendingAgentMessages.set(messageId, { text, audioUrl })
  }

  chat.appendMessage('agent', text, {
    messageId,
    audioUrl,
    onReplay: audioUrl && messageId ? () => replayHistoryAudio(messageId, audioUrl) : null
  })
}

function renderSnapshot(payload: SessionStatePayload): void {
  chat.clearMessages()
  renderedAgentMessages.clear()

  if (pendingSessionNotice) {
    chat.appendMessage('system', pendingSessionNotice)
    pendingSessionNotice = null
  }

  for (const message of payload.messages) {
    if (message.role === 'user') {
      chat.appendMessage('user', message.text)
      continue
    }

    renderedAgentMessages.add(message.id)
    const audioUrl = message.audio_url ?? null
    chat.appendMessage('agent', message.text, {
      messageId: message.id,
      audioUrl,
      onReplay: audioUrl ? () => replayHistoryAudio(message.id, audioUrl) : null
    })
  }

  // 快照与实时事件存在竞态：补齐快照里还没有、但已经通过实时事件渲染过的消息。
  for (const [messageId, pending] of pendingAgentMessages) {
    if (renderedAgentMessages.has(messageId)) {
      continue
    }
    renderedAgentMessages.add(messageId)
    chat.appendMessage('agent', pending.text, {
      messageId,
      audioUrl: pending.audioUrl,
      onReplay: pending.audioUrl ? () => replayHistoryAudio(messageId, pending.audioUrl as string) : null
    })
  }
  pendingAgentMessages.clear()
  // reply_to → message_id 的映射不清空：hydrate 可能落在 agent.text 与 tts.ready 之间，
  // 保留映射才能给实时到达的 tts.ready 找到对应气泡。

  if (payload.messages.length === 0 && renderedAgentMessages.size === 0) {
    chat.appendMessage('system', '会话暂无历史消息，直接输入文本开始对话。')
  }

  applyCharacterState(payload.character)

  if (payload.voice && payload.voice.voice_id) {
    currentVoiceId = payload.voice.voice_id
    voiceView.setSelected(currentVoiceId)
  }
  activeTurnId = payload.active_turn_id ?? null
}

// ------------------------------------------------------------------ 音色列表

function findVoice(voiceId: string | null): VoiceProfile | null {
  if (!voiceId) return null
  return voices.find((voice) => voice.id === voiceId) ?? null
}

function requestVoiceSelect(voiceId: string): void {
  currentVoiceId = voiceId
  voiceView.setHint('正在切换音色…')
  client.sendVoiceSelect(voiceId)
}

async function refreshVoices(options: { preferredId?: string | null; selectDefault?: boolean } = {}): Promise<VoiceProfile[] | null> {
  try {
    const result = await listVoices(httpBase)
    voices = result.voices
    voicesLoaded = true

    const candidates = [
      options.preferredId ?? null,
      options.selectDefault ? result.default_voice_id : null,
      currentVoiceId,
      result.default_voice_id,
      voices.length > 0 ? voices[0].id : null
    ]
    const target = candidates.find((candidate): candidate is string => {
      return typeof candidate === 'string' && candidate.length > 0 && findVoice(candidate) !== null
    }) ?? null

    voiceView.setVoices(voices, target)

    if (!target) {
      voiceView.setHint('后端暂未提供可用音色', 'error')
      return voices
    }
    if (target !== currentVoiceId) {
      if (voiceSelectSupported) {
        requestVoiceSelect(target)
      } else {
        currentVoiceId = target
        voiceView.setHint('后端未声明 voice.select 能力，音色切换可能不可用。')
      }
    } else {
      voiceView.setSelected(target)
    }
    return voices
  } catch (error) {
    voices = []
    voicesLoaded = false
    voiceView.setVoices([], null)
    voiceView.setHint(`音色列表加载失败：${describeError(error)}`, 'error')
    return null
  }
}

async function refreshSessionList(selectedId: string | null): Promise<void> {
  try {
    const sessions = await listSessions(httpBase)
    ignoreSessionChange = true
    sessionSelect.replaceChildren()
    if (sessions.length === 0) {
      const option = document.createElement('option')
      option.value = ''
      option.textContent = '（暂无会话）'
      sessionSelect.append(option)
      sessionSelect.disabled = true
      ignoreSessionChange = false
      return
    }

    sessionSelect.disabled = false
    for (const session of sessions) {
      const option = document.createElement('option')
      option.value = session.session_id
      option.textContent = `${session.title}（${session.message_count}）`
      sessionSelect.append(option)
    }
    const target = selectedId && sessions.some((session) => session.session_id === selectedId)
      ? selectedId
      : sessions[0]?.session_id ?? ''
    sessionSelect.value = target
    ignoreSessionChange = false
  } catch {
    ignoreSessionChange = false
  }
}

async function refreshMemory(): Promise<void> {
  try {
    memoryView.setState(await getMemory(httpBase))
  } catch (error) {
    memoryView.setError(`记忆加载失败：${describeError(error)}`)
  }
}

// ------------------------------------------------------------------ 控制通道

const client = new ControlClient(
  resolvedControlUrl,
  {
    onStatus: (status) => {
      chat.setStatus(status)
    },
    onReady: (capabilities) => {
      const methods = Array.isArray(capabilities.methods) ? capabilities.methods : []
      voiceSelectSupported = methods.includes('voice.select')
      if (!voiceSelectSupported) {
        voiceView.setHint('后端未声明 voice.select，切换音色可能不可用。')
      }
    },
    onOpened: (payload: SessionOpenedPayload) => {
      currentVoiceId = payload.voice_id
      writeStorage(SESSION_STORAGE_KEY, payload.session_id)
      writeStorage(CURSOR_STORAGE_KEY, String(payload.cursor))

      const shortId = payload.session_id.slice(0, 8)
      // 快照会把聊天区整体重建，提示先存起来，等 session.state 到达后再显示。
      pendingSessionNotice = payload.replayed > 0
        ? `会话 ${shortId} 已恢复，重放 ${payload.replayed} 条事件。`
        : `会话 ${shortId} 已就绪。`

      if (voicesLoaded) {
        voiceView.setSelected(currentVoiceId)
      }
      // 首次连接按后端 default_voice_id 选定音色；重连只刷新列表。
      void refreshVoices({ selectDefault: !voicesLoaded })
      void refreshSessionList(payload.session_id)
    },
    onCursor: (cursor) => {
      writeStorage(CURSOR_STORAGE_KEY, String(cursor))
    },
    onSessionState: (payload) => {
      writeStorage(CURSOR_STORAGE_KEY, String(payload.cursor))
      renderSnapshot(payload)
      if (voicesLoaded) {
        voiceView.setSelected(currentVoiceId)
      }
    },
    onCharacterState: (payload) => {
      applyCharacterState(payload)
    },
    onTurnStarted: (payload) => {
      activeTurnId = payload.turn_id
      chat.setCharacterPhase('thinking')
    },
    onTurnCompleted: (payload) => {
      if (activeTurnId === payload.turn_id) {
        activeTurnId = null
      }
      if (activePlayback === null) {
        chat.setCharacterPhase('idle')
      }
      if (memoryView.isOpen()) {
        void refreshMemory()
      }
    },
    onTurnCancelled: (payload) => {
      if (activeTurnId === payload.turn_id) {
        activeTurnId = null
      }
      if (activePlayback === 'tts') {
        stopPlayback()
      }
      chat.setCharacterPhase('idle')
    },
    onTurnError: (payload) => {
      activeTurnId = null
      chat.setCharacterPhase('error')
      chat.appendMessage('system', `回合失败 ${payload.code}：${payload.message}`)
    },
    onAgentText: (payload: AgentTextPayload) => {
      messageIdByReplyTo.set(payload.reply_to, payload.message_id)
      renderAgentMessage(payload.message_id, payload.text, payload.audio_url ?? null)
    },
    onTtsStarted: () => {
      chat.setCharacterPhase('thinking')
    },
    onTtsReady: (payload) => {
      enqueueTtsSegment(payload)
    },
    onTtsFailed: (payload) => {
      if (activePlayback === 'tts') {
        stopPlayback()
      }
      activeTtsId = null
      chat.setCharacterPhase('error')
      chat.setAudioPlaying(false)
      live2d.setSpeaking(false)
      chat.appendMessage('system', `语音合成失败 ${payload.code}：${payload.message}`)
    },
    onTtsCancelled: () => {
      if (activePlayback === 'tts') {
        stopPlayback()
      }
      chat.setCharacterPhase('idle')
    },
    onTtsFinished: (payload) => {
      if (activeTtsId === payload.tts_id) {
        stopPlayback()
        chat.setCharacterPhase('idle')
      }
    },
    onVoiceSelected: (payload) => {
      currentVoiceId = payload.voice_id
      voiceView.setSelected(payload.voice_id)
      voiceView.setHint(`当前音色：${payload.display_name}`)
    },
    onError: (payload) => {
      if (payload.code === 'session_not_found') {
        // 本地会话已被后端清理：丢掉，重连时新建会话。
        writeStorage(SESSION_STORAGE_KEY, null)
        writeStorage(CURSOR_STORAGE_KEY, null)
        void refreshSessionList(null)
        chat.appendMessage('system', `会话已失效，将新建会话：${payload.message}`)
        return
      }
      if (payload.code === 'voice_not_found' || payload.code === 'unsupported_type') {
        voiceView.setHint(`音色操作失败 ${payload.code}：${payload.message}`, 'error')
        if (payload.code === 'voice_not_found') {
          void refreshVoices({ preferredId: currentVoiceId })
        }
        return
      }
      if (payload.code === 'protocol_mismatch') {
        chat.appendMessage('system', `协议版本不匹配：${payload.message}`)
        return
      }
      chat.appendMessage('system', `错误 ${payload.code}：${payload.message}`)
    }
  },
  {
    sessionId: readStorage(SESSION_STORAGE_KEY),
    after: readStoredCursor()
  }
)

// ------------------------------------------------------------------ 交互接线

chat.onSend((text) => {
  client.sendUserText(text)
})

chat.onStopAudio(() => {
  const kind = activePlayback
  const ttsId = player.stop()
  activePlayback = null
  activeTtsId = null
  live2d.setSpeaking(false)
  chat.setAudioPlaying(false)
  chat.setCharacterPhase('idle')
  if (kind === 'tts' && ttsId) {
    client.sendTtsCancel(ttsId)
  }
})

voiceView.onSelect((voiceId) => {
  requestVoiceSelect(voiceId)
})

voiceView.onAudition((voiceId) => {
  auditionVoice(voiceId)
})

voiceView.onDelete((voiceId) => {
  removeVoice(voiceId)
})

voiceView.onRename((voiceId) => {
  renameVoiceAction(voiceId)
})

memoryView.onOpen(() => {
  void refreshMemory()
})

memoryView.onAdd((text) => {
  void addMemoryNote(httpBase, text)
    .then(() => refreshMemory())
    .catch((error: unknown) => {
      memoryView.setError(`添加记忆失败：${describeError(error)}`)
    })
})

memoryView.onDelete((noteId) => {
  void deleteMemoryNote(httpBase, noteId)
    .then(() => refreshMemory())
    .catch((error: unknown) => {
      memoryView.setError(`删除记忆失败：${describeError(error)}`)
    })
})

function interruptPlayback(): void {
  const previous = activePlayback === 'tts' ? player.stop() : null
  if (previous) {
    client.sendTtsCancel(previous)
  }
  activePlayback = null
  activeTtsId = null
  chat.setAudioPlaying(false)
  live2d.setSpeaking(false)
}

sessionSelect.addEventListener('change', () => {
  if (ignoreSessionChange) {
    return
  }
  const sessionId = sessionSelect.value
  if (!sessionId || sessionId === client.currentSessionId) {
    return
  }
  interruptPlayback()
  writeStorage(SESSION_STORAGE_KEY, null)
  writeStorage(CURSOR_STORAGE_KEY, null)
  client.sendSessionOpen(sessionId, 0)
  chat.appendMessage('system', '正在切换会话…')
})

sessionNew.addEventListener('click', () => {
  interruptPlayback()
  writeStorage(SESSION_STORAGE_KEY, null)
  writeStorage(CURSOR_STORAGE_KEY, null)
  client.startNewSession()
  chat.appendMessage('system', '正在新建会话…')
})

voiceView.onCloneCancel(() => {
  voiceView.setCloneError(null)
})

voiceView.onCloneSubmit(({ name, language, file }) => {
  voiceView.setCloneBusy(true)
  voiceView.setCloneError(null)
  void cloneVoice(httpBase, { name, language, audio: file })
    .then(async (created) => {
      const newVoiceId = created ? created.id : null
      voiceView.setCloneBusy(false)
      voiceView.closeClonePanel()
      voiceView.setHint(created ? `已克隆音色：${created.display_name}` : '克隆成功，正在刷新音色列表…')
      const refreshed = await refreshVoices({ preferredId: newVoiceId })
      if (newVoiceId) {
        voiceView.setSelected(newVoiceId)
        return
      }
      // 后端没回 voice 对象时按名称匹配刚克隆的音色。
      const matched = refreshed?.find((voice) => voice.display_name === name) ?? null
      if (matched) {
        voiceView.setSelected(matched.id)
        requestVoiceSelect(matched.id)
      }
    })
    .catch((error: unknown) => {
      voiceView.setCloneBusy(false)
      voiceView.setCloneError(`克隆失败：${describeError(error)}`)
    })
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
    const form = new FormData()
    form.append('audio', audio, 'recording.webm')
    const response = await fetch(`${httpBase}/asr`, { method: 'POST', body: form })
    if (!response.ok) throw new Error(`ASR HTTP ${response.status}`)
    const result = (await response.json()) as { text: string }
    chat.appendMessage('user', result.text)
    client.sendUserText(result.text)
  } catch (error) {
    chat.setRecording(false)
    chat.appendMessage('system', `录音失败：${describeError(error)}`)
  }
})

function animateMouth(): void {
  if (player.isPlaying) {
    live2d.setMouthLevel(player.getMouthLevel())
  }
  window.requestAnimationFrame(animateMouth)
}

window.requestAnimationFrame(animateMouth)

client.connect()
