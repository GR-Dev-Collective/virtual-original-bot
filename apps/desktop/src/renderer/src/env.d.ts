interface VobBridge {
  controlUrl: string
  transcribeAudio(audio: Uint8Array, mimeType: string): Promise<{ text: string }>
}

interface Window {
  vob?: VobBridge
}
