import type { VoiceProfile } from '../api/voices'

export interface CloneInput {
  name: string
  language: string
  file: File
}

export type HintTone = 'info' | 'error'

export interface VoiceView {
  onSelect(handler: (voiceId: string) => void): void
  onCloneSubmit(handler: (input: CloneInput) => void): void
  onCloneCancel(handler: () => void): void
  setVoices(voices: VoiceProfile[], selectedId: string | null): void
  setSelected(voiceId: string | null): void
  setHint(text: string, tone?: HintTone): void
  openClonePanel(): void
  closeClonePanel(): void
  setCloneBusy(busy: boolean): void
  setCloneError(text: string | null): void
  resetCloneForm(): void
}

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id)
  if (!element) {
    throw new Error(`页面缺少元素 #${id}`)
  }
  return element as T
}

/** 顶栏音色选择 + 克隆面板。 */
export function createVoiceView(): VoiceView {
  const select = requireElement<HTMLSelectElement>('voice-select')
  const cloneOpen = requireElement<HTMLButtonElement>('voice-clone-open')
  const hint = requireElement<HTMLElement>('voice-hint')
  const panel = requireElement<HTMLElement>('clone-panel')
  const form = requireElement<HTMLFormElement>('clone-form')
  const nameInput = requireElement<HTMLInputElement>('clone-name')
  const languageSelect = requireElement<HTMLSelectElement>('clone-language')
  const audioInput = requireElement<HTMLInputElement>('clone-audio')
  const errorBox = requireElement<HTMLElement>('clone-error')
  const submit = requireElement<HTMLButtonElement>('clone-submit')
  const cancel = requireElement<HTMLButtonElement>('clone-cancel')

  let selectHandler: (voiceId: string) => void = () => {}
  let submitHandler: (input: CloneInput) => void = () => {}
  let cancelHandler: () => void = () => {}
  let busy = false

  function setHint(text: string, tone: HintTone = 'info'): void {
    hint.textContent = text
    hint.dataset.tone = tone
    hint.hidden = text.length === 0
  }

  function setCloneError(text: string | null): void {
    errorBox.textContent = text ?? ''
    errorBox.hidden = !text
  }

  function resetCloneForm(): void {
    nameInput.value = ''
    languageSelect.value = 'ZH'
    audioInput.value = ''
  }

  function setCloneBusy(next: boolean): void {
    busy = next
    submit.disabled = next
    submit.textContent = next ? '提交中…' : '提交克隆'
    cancel.disabled = next
    nameInput.disabled = next
    languageSelect.disabled = next
    audioInput.disabled = next
  }

  function openClonePanel(): void {
    setCloneError(null)
    panel.hidden = false
    nameInput.focus()
  }

  function closeClonePanel(): void {
    panel.hidden = true
    setCloneError(null)
    resetCloneForm()
  }

  function setSelected(voiceId: string | null): void {
    if (!voiceId) {
      return
    }
    const exists = Array.from(select.options).some((option) => option.value === voiceId)
    if (exists) {
      select.value = voiceId
    }
  }

  function setVoices(voices: VoiceProfile[], selectedId: string | null): void {
    select.replaceChildren()

    if (voices.length === 0) {
      const option = document.createElement('option')
      option.value = ''
      option.textContent = '（暂无音色）'
      select.append(option)
      select.value = ''
      select.disabled = true
      return
    }

    select.disabled = false
    for (const voice of voices) {
      const option = document.createElement('option')
      option.value = voice.id
      option.textContent = voice.builtin ? `${voice.display_name}（内置）` : voice.display_name
      select.append(option)
    }

    const fallback = voices[0] ? voices[0].id : ''
    const target = selectedId && voices.some((voice) => voice.id === selectedId) ? selectedId : fallback
    select.value = target
  }

  select.addEventListener('change', () => {
    if (select.value) {
      selectHandler(select.value)
    }
  })

  cloneOpen.addEventListener('click', () => {
    openClonePanel()
  })

  cancel.addEventListener('click', () => {
    closeClonePanel()
    cancelHandler()
  })

  form.addEventListener('submit', (event) => {
    event.preventDefault()
    if (busy) {
      return
    }

    const name = nameInput.value.trim()
    if (name.length === 0) {
      setCloneError('请填写音色名称')
      return
    }

    const file = audioInput.files && audioInput.files.length > 0 ? audioInput.files[0] : null
    if (!file) {
      setCloneError('请选择参考音频文件')
      return
    }

    setCloneError(null)
    submitHandler({ name, language: languageSelect.value, file })
  })

  return {
    onSelect(handler) {
      selectHandler = handler
    },
    onCloneSubmit(handler) {
      submitHandler = handler
    },
    onCloneCancel(handler) {
      cancelHandler = handler
    },
    setVoices,
    setSelected,
    setHint,
    openClonePanel,
    closeClonePanel,
    setCloneBusy,
    setCloneError,
    resetCloneForm
  }
}
