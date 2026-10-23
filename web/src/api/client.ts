/** Backend HTTP/NDJSON client；所有数据都来自正式 Web API，不直接触碰 SQLite。 */

import type {
  ConversationDTO,
  ConversationSummaryDTO,
  ContextMessageDTO,
  ReadinessDTO,
  ScopeRequest,
  SessionDTO,
  StreamEnvelope,
  StreamEvent,
} from '@/types/contracts'

export interface StreamHandlers {
  onEvent: (event: StreamEvent | StreamEnvelope) => void
}

/** GET /api/conversations 的 bounded selector；与后端编译契约一一对应。 */
export interface ConversationListSelector {
  scopeMode: 'all' | 'sessions'
  sessionId?: string
}

async function parseError(response: Response): Promise<string> {
  try {
    const detail = (await response.json())?.detail
    if (typeof detail === 'string') return detail
    if (detail?.message) return String(detail.message)
    if (detail?.error_code) return String(detail.error_code)
  } catch {
    // 非 JSON body 时回退到状态文本
  }
  return `${response.status} ${response.statusText}`
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) throw new Error(await parseError(response))
  return (await response.json()) as T
}

export const api = {
  readiness: () => request<ReadinessDTO>('/api/readiness'),

  sessions: () => request<SessionDTO[]>('/api/source-sessions'),

  /** scope 过滤后的 conversation 列表：后端先过滤再排序、limit。 */
  conversations: (selector: ConversationListSelector, limit = 100, query = '', offset = 0) => {
    const params = new URLSearchParams()
    params.set('scope_mode', selector.scopeMode)
    if (selector.sessionId) params.set('session_id', selector.sessionId)
    params.set('limit', String(limit))
    if (query.trim()) params.set('query', query.trim())
    if (offset > 0) params.set('offset', String(offset))
    return request<ConversationSummaryDTO[]>(`/api/conversations?${params.toString()}`)
  },

  createConversation: (scope: ScopeRequest) =>
    request<ConversationDTO>('/api/conversations', { method: 'POST', body: JSON.stringify({ scope }) }),

  conversation: (id: string) => request<ConversationDTO>(`/api/conversations/${id}`),

  renameConversation: (id: string, title: string) =>
    request<ConversationDTO>(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),

  deleteConversation: (id: string) =>
    request<{ status: string }>(`/api/conversations/${id}`, { method: 'DELETE' }),

  sourceContext: (
    conversationId: string,
    ordinal: number,
    sourceIndex: number,
    before = 2,
    after = 2,
  ) =>
    request<{ messages: ContextMessageDTO[] }>(
      `/api/conversations/${conversationId}/messages/${ordinal}/sources/${sourceIndex}/context?before=${before}&after=${after}`,
    ),

  tracePath: (traceId: string) => request<{ path: string }>(`/api/traces/${traceId}/path`),

  revealTrace: (traceId: string) =>
    request<{ status: string; path: string }>(`/api/traces/${traceId}/reveal`, { method: 'POST' }),

  /**
   * 发送流式 Query（POST + NDJSON）。
   * 事件按 request_id 归属，store 负责写回 owner buffer；abort 真正取消 backend query。
   */
  async streamQuery(
    payload: { query: string; scope: ScopeRequest; conversation_id?: string | null; request_id: string },
    handlers: StreamHandlers,
    signal: AbortSignal,
  ): Promise<void> {
    const response = await fetch('/api/query/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
    if (!response.ok) throw new Error(await parseError(response))
    if (!response.body) throw new Error('streaming response has no body')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffered = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffered += decoder.decode(value, { stream: true })
      let newlineIndex = buffered.indexOf('\n')
      while (newlineIndex !== -1) {
        const line = buffered.slice(0, newlineIndex)
        buffered = buffered.slice(newlineIndex + 1)
        if (line.trim()) handlers.onEvent(JSON.parse(line))
        newlineIndex = buffered.indexOf('\n')
      }
    }
    const rest = buffered.trim()
    if (rest) handlers.onEvent(JSON.parse(rest))
  },
}
