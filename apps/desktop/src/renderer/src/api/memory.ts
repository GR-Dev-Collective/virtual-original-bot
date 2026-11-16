/** 长期记忆 HTTP 接口。 */

export interface MemoryNote {
  id: string
  text: string
  kind: string
  created_at: number
}

export interface Relationship {
  affinity: number
  stage: string
  interactions: number
  updated_at: number
}

export interface MemoryState {
  user_name: string | null
  notes: MemoryNote[]
  relationship: Relationship
}

async function readDetail(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json()
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      return String((data as { detail: unknown }).detail)
    }
  } catch {
    // ignore
  }
  return `HTTP ${response.status}`
}

export async function getMemory(baseUrl: string): Promise<MemoryState> {
  const response = await fetch(`${baseUrl}/memory`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(await readDetail(response))
  }
  return (await response.json()) as MemoryState
}

export async function addMemoryNote(baseUrl: string, text: string): Promise<MemoryNote> {
  const response = await fetch(`${baseUrl}/memory/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  })
  if (!response.ok) {
    throw new Error(await readDetail(response))
  }
  return (await response.json()) as MemoryNote
}

export async function deleteMemoryNote(baseUrl: string, noteId: string): Promise<void> {
  const response = await fetch(`${baseUrl}/memory/notes/${encodeURIComponent(noteId)}`, {
    method: 'DELETE'
  })
  if (!response.ok) {
    throw new Error(await readDetail(response))
  }
}
