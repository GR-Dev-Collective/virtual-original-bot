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

  play(
    ttsId: string,
    url: string,
    handlers: { onStarted(): void; onEnded(): void; onError(): void }
  ): void {
    this.stop()
    const audio = new Audio(url)
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

  private playNext(): void {
    const segment = this.queue.shift()
    const handlers = this.handlers
    if (!segment || !handlers) {
      return
    }

    const audio = new Audio(segment.url)
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
  }
}
