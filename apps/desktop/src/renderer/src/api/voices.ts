/**
 * 音色 HTTP 接口（GET/POST/DELETE /voices）的前端封装。
 *
 * 后端实现与桌面端并行开发，因此这里的解析对两种常见形态都容错：
 * 直接的数组 `[{...}]` 或包一层的 `{voices: [...], default_voice_id}`。
 * 解析不了时返回空列表而不是抛异常，保证 UI 不崩。
 */

export interface VoiceProfile {
  id: string
  display_name: string
  language: string | null
  builtin: boolean
}

export interface VoiceListResult {
  voices: VoiceProfile[]
  default_voice_id: string | null
}

export class VoiceApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'VoiceApiError'
    this.status = status
  }
}

/** ws://host:port/ws/control?x=y → http://host:port */
export function httpBaseFromControlUrl(controlUrl: string): string {
  try {
    const url = new URL(controlUrl)
    url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:'
    url.pathname = '/'
    url.search = ''
    url.hash = ''
    return url.toString().replace(/\/+$/, '')
  } catch {
    return controlUrl
      .replace(/^ws/, 'http')
      .replace(/\/ws\/control.*$/, '')
      .replace(/\/+$/, '')
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeVoice(value: unknown): VoiceProfile | null {
  if (!isRecord(value)) {
    return null
  }

  const id = typeof value.id === 'string' ? value.id : typeof value.voice_id === 'string' ? value.voice_id : null
  if (!id) {
    return null
  }

  const displayName =
    typeof value.display_name === 'string' && value.display_name.length > 0
      ? value.display_name
      : typeof value.name === 'string' && value.name.length > 0
        ? value.name
        : id

  return {
    id,
    display_name: displayName,
    language: typeof value.language === 'string' ? value.language : null,
    // 后端 /voices 用 is_builtin，旧形态可能是 builtin，两者都兼容。
    builtin: value.is_builtin === true || value.builtin === true
  }
}

function normalizeList(data: unknown): VoiceListResult {
  if (Array.isArray(data)) {
    return { voices: data.map(normalizeVoice).filter((voice): voice is VoiceProfile => voice !== null), default_voice_id: null }
  }

  if (isRecord(data)) {
    const rawList = Array.isArray(data.voices) ? data.voices : Array.isArray(data.items) ? data.items : []
    const defaultId = typeof data.default_voice_id === 'string' ? data.default_voice_id : null
    return {
      voices: rawList.map(normalizeVoice).filter((voice): voice is VoiceProfile => voice !== null),
      default_voice_id: defaultId
    }
  }

  return { voices: [], default_voice_id: null }
}

async function readDetail(response: Response): Promise<string> {
  let text: string
  try {
    text = await response.text()
  } catch {
    return `HTTP ${response.status}`
  }
  if (!text) {
    return '无响应内容'
  }

  try {
    const data: unknown = JSON.parse(text)
    if (isRecord(data) && 'detail' in data) {
      return describeDetail(data.detail)
    }
  } catch {
    // 非 JSON：直接展示原始文本
  }

  return text.slice(0, 400)
}

function describeDetail(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === 'string') {
        return item
      }
      if (isRecord(item)) {
        const location = Array.isArray(item.loc) ? item.loc.join('.') : ''
        const message = typeof item.msg === 'string' ? item.msg : JSON.stringify(item)
        return location ? `${location}: ${message}` : message
      }
      return String(item)
    })
    return parts.join('; ') || '未知错误'
  }
  if (detail === null || detail === undefined) {
    return '未知错误'
  }
  return JSON.stringify(detail)
}

export async function listVoices(baseUrl: string): Promise<VoiceListResult> {
  const response = await fetch(`${baseUrl}/voices`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new VoiceApiError(`HTTP ${response.status}：${await readDetail(response)}`, response.status)
  }

  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    // 空响应或非 JSON：按空列表处理
  }
  return normalizeList(data)
}

export async function cloneVoice(
  baseUrl: string,
  input: { name: string; language: string; audio: File }
): Promise<VoiceProfile | null> {
  const form = new FormData()
  form.append('name', input.name)
  form.append('language', input.language)
  form.append('audio', input.audio, input.audio.name || 'reference.wav')

  const response = await fetch(`${baseUrl}/voices`, { method: 'POST', body: form })
  if (!response.ok) {
    throw new VoiceApiError(`HTTP ${response.status}：${await readDetail(response)}`, response.status)
  }

  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    return null
  }
  if (isRecord(data) && isRecord(data.voice)) {
    return normalizeVoice(data.voice)
  }
  return normalizeVoice(data)
}

export async function deleteVoice(baseUrl: string, voiceId: string): Promise<void> {
  const response = await fetch(`${baseUrl}/voices/${encodeURIComponent(voiceId)}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new VoiceApiError(`HTTP ${response.status}：${await readDetail(response)}`, response.status)
  }
}

export async function renameVoice(
  baseUrl: string,
  voiceId: string,
  displayName: string
): Promise<VoiceProfile | null> {
  const response = await fetch(`${baseUrl}/voices/${encodeURIComponent(voiceId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName })
  })
  if (!response.ok) {
    throw new VoiceApiError(`HTTP ${response.status}：${await readDetail(response)}`, response.status)
  }
  try {
    return normalizeVoice(await response.json())
  } catch {
    return null
  }
}
