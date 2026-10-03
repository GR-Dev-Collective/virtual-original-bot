export class AudioRecorder {
  private recorder: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    this.chunks = []
    this.recorder = new MediaRecorder(this.stream)
    this.recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) this.chunks.push(event.data)
    })
    this.recorder.start()
  }

  stop(): Promise<Blob> {
    const recorder = this.recorder
    if (!recorder) return Promise.reject(new Error('录音尚未开始'))

    return new Promise((resolve, reject) => {
      recorder.addEventListener('stop', () => {
        this.stream?.getTracks().forEach((track) => track.stop())
        this.stream = null
        this.recorder = null
        resolve(new Blob(this.chunks, { type: recorder.mimeType || 'audio/webm' }))
      }, { once: true })
      recorder.addEventListener('error', () => reject(new Error('录音失败')), { once: true })
      recorder.stop()
    })
  }

  get isRecording(): boolean {
    return this.recorder?.state === 'recording'
  }
}
