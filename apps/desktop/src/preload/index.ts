import { contextBridge, ipcRenderer } from 'electron'

const DEFAULT_CONTROL_URL = 'ws://127.0.0.1:8090/ws/control'

/**
 * Renderer 只能通过这个桥拿到后端地址，不直接访问 Node。
 * 地址可用 VOB_CONTROL_URL 环境变量覆盖。
 */
const bridge = {
  controlUrl: process.env.VOB_CONTROL_URL ?? DEFAULT_CONTROL_URL,
  transcribeAudio: (audio: Uint8Array, mimeType: string): Promise<{ text: string }> =>
    ipcRenderer.invoke('asr:transcribe', { audio, mimeType }) as Promise<{ text: string }>
}

contextBridge.exposeInMainWorld('vob', bridge)
