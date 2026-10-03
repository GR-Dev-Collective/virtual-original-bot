export class AudioPlayer {
  private audio: HTMLAudioElement | null = null
  private activeTtsId: string | null = null

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
      if (this.activeTtsId === ttsId) {
        this.audio = null
        this.activeTtsId = null
        handlers.onEnded()
      }
    })
    audio.addEventListener('error', () => {
      if (this.activeTtsId === ttsId) {
        this.audio = null
        this.activeTtsId = null
        handlers.onError()
      }
    })
    void audio.play().catch(() => {
      if (this.activeTtsId === ttsId) {
        this.audio = null
        this.activeTtsId = null
        handlers.onError()
      }
    })
  }

  stop(): string | null {
    const ttsId = this.activeTtsId
    this.audio?.pause()
    this.audio?.removeAttribute('src')
    this.audio?.load()
    this.audio = null
    this.activeTtsId = null
    return ttsId
  }

  get isPlaying(): boolean {
    return this.audio !== null
  }
}
