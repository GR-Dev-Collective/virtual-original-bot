export interface QueuedSegment {
  ttsId: string
  index: number
  url: string
  final: boolean
}

export interface SegmentHandlers {
  onStarted(): void
  onAllEnded(): void
  onError(): void
}

/**
 * 音频播放器：支持单条播放（历史重播）与按 segment_index 排序的分段队列。
 * 分段队列在最后一段播放结束后触发 onAllEnded，由调用方回报 tts.finished。
 */
export class AudioPlayer {
  private audio: HTMLAudioElement | null = null
  private activeTtsId: string | null = null
  private queue: QueuedSegment[] = []
  private handlers: SegmentHandlers | null = null
  private finalPlayed = false
  private context: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private sourceNode: MediaElementAudioSourceNode | null = null
  private waveform: Uint8Array<ArrayBuffer> | null = null

  play(
    ttsId: string,
    url: string,
    handlers: { onStarted(): void; onEnded(): void; onError(): void }
  ): void {
    this.stop()
    const audio = this.createAudio(url)
    this.audio = audio
    this.activeTtsId = ttsId
    audio.addEventListener('playing', handlers.onStarted, { once: true })
    audio.addEventListener('ended', () => {
      if (this.audio === audio) {
        this.audio = null
        this.activeTtsId = null
        handlers.onEnded()
      }
    })
    audio.addEventListener('error', () => {
      if (this.audio === audio) {
        this.audio = null
        this.activeTtsId = null
        handlers.onError()
      }
    })
    void audio.play().catch(() => {
      if (this.audio === audio) {
        this.audio = null
        this.activeTtsId = null
        handlers.onError()
      }
    })
  }

  enqueue(segment: QueuedSegment, handlers: SegmentHandlers): void {
    if (this.activeTtsId && this.activeTtsId !== segment.ttsId) {
      this.stop()
    }
    this.handlers = handlers
    this.queue.push(segment)
    this.queue.sort((left, right) => left.index - right.index)
    if (!this.audio) {
      this.playNext()
    }
  }

  stop(): string | null {
    const ttsId = this.activeTtsId
    this.clearCurrent()
    this.queue = []
    this.handlers = null
    this.finalPlayed = false
    this.activeTtsId = null
    return ttsId
  }

  get isPlaying(): boolean {
    return this.audio !== null
  }

  /** 0..1 的实时振幅，用于 Live2D 口型；没有音频或分析器时返回 0。 */
  getMouthLevel(): number {
    const analyser = this.analyser
    if (!analyser || !this.audio) {
      return 0
    }
    if (!this.waveform || this.waveform.length !== analyser.fftSize) {
      this.waveform = new Uint8Array(new ArrayBuffer(analyser.fftSize))
    }
    analyser.getByteTimeDomainData(this.waveform)
    let sum = 0
    for (const value of this.waveform) {
      const centered = (value - 128) / 128
      sum += centered * centered
    }
    return Math.min(1, Math.sqrt(sum / this.waveform.length) * 6)
  }

  private playNext(): void {
    const segment = this.queue.shift()
    const handlers = this.handlers
    if (!segment || !handlers) {
      return
    }

    const audio = this.createAudio(segment.url)
    this.audio = audio
    this.activeTtsId = segment.ttsId
    audio.addEventListener('playing', handlers.onStarted, { once: true })
    audio.addEventListener('ended', () => {
      if (this.audio !== audio) {
        return
      }
      this.audio = null
      this.finalPlayed = this.finalPlayed || segment.final
      if (this.queue.length > 0) {
        this.playNext()
        return
      }
      if (!this.finalPlayed) {
        // 下一段还没合成完：保留 handlers，等 enqueue 继续；不要提前回报播放结束。
        return
      }
      this.finalPlayed = false
      this.activeTtsId = null
      this.handlers = null
      handlers.onAllEnded()
    })
    audio.addEventListener('error', () => {
      if (this.audio !== audio) {
        return
      }
      this.clearCurrent()
      this.queue = []
      this.handlers = null
      this.activeTtsId = null
      handlers.onError()
    })
    void audio.play().catch(() => {
      if (this.audio === audio) {
        this.clearCurrent()
        this.queue = []
        this.handlers = null
        this.activeTtsId = null
        handlers.onError()
      }
    })
  }

  private clearCurrent(): void {
    this.audio?.pause()
    this.audio?.removeAttribute('src')
    this.audio?.load()
    this.audio = null
    this.sourceNode?.disconnect()
    this.sourceNode = null
  }

  private createAudio(url: string): HTMLAudioElement {
    const audio = new Audio()
    // 音频来自后端（跨源）；加 anonymous 才能接 Web Audio 分析器。
    audio.crossOrigin = 'anonymous'
    audio.src = url
    this.attachAnalyser(audio)
    return audio
  }

  private attachAnalyser(audio: HTMLAudioElement): void {
    try {
      this.context = this.context ?? new AudioContext()
      void this.context.resume()
      if (!this.analyser) {
        this.analyser = this.context.createAnalyser()
        this.analyser.fftSize = 512
        this.analyser.connect(this.context.destination)
      }
      this.sourceNode?.disconnect()
      this.sourceNode = this.context.createMediaElementSource(audio)
      this.sourceNode.connect(this.analyser)
    } catch {
      // 浏览器不支持/被策略拒绝时退化为无声谱口型，不影响播放。
      this.analyser = null
    }
  }
}
