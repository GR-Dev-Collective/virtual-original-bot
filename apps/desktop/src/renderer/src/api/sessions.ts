/** 会话列表 HTTP 接口。 */

export interface SessionSummary {
  session_id: string
  title: string
  created_at: number
  updated_at: number
  message_count: number
  voice_id: string
}

export async function listSessions(baseUrl: string): Promise<SessionSummary[]> {
  const response = await fetch(`${baseUrl}/sessions`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  const data: unknown = await response.json()
  if (!Array.isArray(data)) {
    return []
  }
  return data.filter((item): item is SessionSummary => {
    if (typeof item !== 'object' || item === null) return false
    const value = item as Record<string, unknown>
    return typeof value.session_id === 'string' && typeof value.title === 'string'
  })
}
