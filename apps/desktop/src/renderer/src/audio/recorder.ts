function eventError(event: Event): Error {
  const error = (event as Event & { error?: unknown }).error
  return error instanceof Error ? error : new Error('录音失败')
}

export class AudioRecorder {
  private recorder: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []
  private errorHandler: ((error: Error) => void) | null = null
  private dataAvailableHandler: ((event: BlobEvent) => void) | null = null
  private recorderErrorHandler: ((event: Event) => void) | null = null
  private stopping = false

  async start(onError: (error: Error) => void): Promise<void> {
    if (this.recorder || this.stream) {
      throw new Error('录音器已启动')
    }

    this.chunks = []
    this.errorHandler = onError

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      this.recorder = new MediaRecorder(this.stream)
      this.dataAvailableHandler = (event) => {
        if (event.data.size > 0) this.chunks.push(event.data)
      }
      this.recorderErrorHandler = (event) => {
        if (this.stopping) return

        const reportError = this.errorHandler
        const error = eventError(event)
        this.cleanup()
        reportError?.(error)
      }
      this.recorder.addEventListener('dataavailable', this.dataAvailableHandler)
      this.recorder.addEventListener('error', this.recorderErrorHandler)
      this.recorder.start()
    } catch (error) {
      this.cleanup()
      throw error
    }
  }

  stop(): Promise<Blob> {
    const recorder = this.recorder
    if (!recorder) return Promise.reject(new Error('录音尚未开始'))

    this.stopping = true
    return new Promise((resolve, reject) => {
      let settled = false
      const finish = (error?: Error) => {
        if (settled) return
        settled = true

        if (error) {
          this.cleanup()
          reject(error)
          return
        }

        const audio = new Blob(this.chunks, { type: recorder.mimeType || 'audio/webm' })
        this.cleanup()
        resolve(audio)
      }

      recorder.addEventListener('stop', () => finish(), { once: true })
      recorder.addEventListener('error', (event) => finish(eventError(event)), { once: true })

      try {
        recorder.stop()
      } catch (error) {
        finish(error instanceof Error ? error : new Error(String(error)))
      }
    })
  }

  get isRecording(): boolean {
    return this.recorder?.state === 'recording'
  }

  private cleanup(): void {
    const recorder = this.recorder
    if (recorder && this.dataAvailableHandler) {
      recorder.removeEventListener('dataavailable', this.dataAvailableHandler)
    }
    if (recorder && this.recorderErrorHandler) {
      recorder.removeEventListener('error', this.recorderErrorHandler)
    }

    const tracks = this.stream?.getTracks() ?? []
    this.recorder = null
    this.stream = null
    this.chunks = []
    this.errorHandler = null
    this.dataAvailableHandler = null
    this.recorderErrorHandler = null
    this.stopping = false

    for (const track of tracks) {
      try {
        track.stop()
      } catch {
        // Continue releasing the remaining tracks if one track fails to stop.
      }
    }
  }
}
