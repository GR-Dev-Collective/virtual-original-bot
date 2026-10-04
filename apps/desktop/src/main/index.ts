import { join } from 'node:path'

import { app, BrowserWindow, ipcMain, shell } from 'electron'

const DEFAULT_CONTROL_URL = 'ws://127.0.0.1:8090/ws/control'

function getBackendHttpBaseUrl(): URL {
  const backendUrl = new URL(process.env.VOB_CONTROL_URL ?? DEFAULT_CONTROL_URL)
  if (backendUrl.protocol === 'ws:') {
    backendUrl.protocol = 'http:'
  } else if (backendUrl.protocol === 'wss:') {
    backendUrl.protocol = 'https:'
  } else {
    throw new Error(`不支持的后端协议：${backendUrl.protocol}`)
  }

  backendUrl.pathname = backendUrl.pathname.replace(/\/ws\/control\/?$/, '') || '/'
  backendUrl.search = ''
  backendUrl.hash = ''
  return backendUrl
}

ipcMain.handle(
  'asr:transcribe',
  async (_event, payload: { audio: Uint8Array; mimeType: string }): Promise<{ text: string }> => {
    if (!(payload?.audio instanceof Uint8Array) || payload.audio.byteLength === 0) {
      throw new Error('录音为空')
    }

    const form = new FormData()
    const audioBuffer = new ArrayBuffer(payload.audio.byteLength)
    new Uint8Array(audioBuffer).set(payload.audio)
    form.append(
      'audio',
      new Blob([audioBuffer], { type: payload.mimeType || 'audio/webm' }),
      'recording.webm'
    )

    const response = await fetch(new URL('/asr', getBackendHttpBaseUrl()), {
      method: 'POST',
      body: form
    })
    if (!response.ok) {
      const errorPayload = (await response.json().catch(() => null)) as { detail?: unknown } | null
      const detail =
        typeof errorPayload?.detail === 'string'
          ? errorPayload.detail
          : `ASR HTTP ${response.status}`
      throw new Error(detail)
    }

    const result = (await response.json()) as { text?: unknown }
    if (typeof result.text !== 'string') {
      throw new Error('ASR 响应缺少转写文本')
    }
    return { text: result.text }
  }
)

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1100,
    height: 760,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#0f1116',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      autoplayPolicy: 'no-user-gesture-required'
    }
  })

  window.on('ready-to-show', () => {
    window.show()
  })

  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  const devServerUrl = process.env.ELECTRON_RENDERER_URL
  if (devServerUrl) {
    void window.loadURL(devServerUrl)
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

void app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
