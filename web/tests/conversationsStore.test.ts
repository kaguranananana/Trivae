import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConversationsStore } from '@/stores/conversations'
import type { ConversationSummaryDTO } from '@/types/contracts'

function summary(
  conversationId: string,
  updatedAt: string,
  scope: ConversationSummaryDTO['scope'],
): ConversationSummaryDTO {
  return {
    conversation_id: conversationId,
    created_at: updatedAt,
    updated_at: updatedAt,
    title: conversationId,
    message_count: 1,
    preview: conversationId,
    scope,
  }
}

const allSummary = summary('conv-all', '2026-08-30T10:00:00+08:00', { mode: 'all' })
const scopedSummary = summary('conv-s1', '2026-08-29T10:00:00+08:00', {
  mode: 'sessions',
  session_ids: ['s1'],
  max_results: 5_000,
})

function conversationsResponse(items: ConversationSummaryDTO[]): Response {
  return new Response(JSON.stringify(items))
}

describe('conversations store scoped fetch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-30T12:00:00+08:00'))
  })

  afterEach(() => vi.useRealTimers())

  it('does not request anything while unselected and clears the list', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const store = useConversationsStore()
    store.conversations = [allSummary]

    await store.refresh(null)

    expect(fetchMock).not.toHaveBeenCalled()
    expect(store.conversations).toEqual([])
    expect(store.loaded).toBe(false)
    expect(store.loading).toBe(false)
    vi.unstubAllGlobals()
  })

  it('requests scope_mode=all and keeps only all-scope conversations', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      requests.push(String(input))
      if (String(input).startsWith('/api/conversations?')) {
        return new Response(JSON.stringify([allSummary]))
      }
      return new Response('{}', { status: 404 })
    }))
    const store = useConversationsStore()
    await store.refresh({ kind: 'all' })

    expect(requests[0]).toBe('/api/conversations?scope_mode=all&limit=100')
    expect(store.conversations).toEqual([allSummary])
    expect(store.loaded).toBe(true)
    vi.unstubAllGlobals()
  })

  it('requests the exact single-session selector', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      requests.push(String(input))
      if (String(input).startsWith('/api/conversations?')) {
        return new Response(JSON.stringify([scopedSummary]))
      }
      return new Response('{}', { status: 404 })
    }))
    const store = useConversationsStore()
    await store.refresh({ kind: 'session', sessionId: 's1' })

    expect(requests[0]).toBe('/api/conversations?scope_mode=sessions&session_id=s1&limit=100')
    expect(store.conversations).toEqual([scopedSummary])
    vi.unstubAllGlobals()
  })

  it('drops a late response from A after the user switched to B', async () => {
    type Resolve = (response: Response) => void
    const resolvers: Record<string, Resolve> = {}
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      return new Promise<Response>((resolve) => {
        resolvers[url] = resolve
      })
    }))
    const store = useConversationsStore()
    const refreshA = store.refresh({ kind: 'session', sessionId: 's1' })
    await Promise.resolve()
    const refreshB = store.refresh({ kind: 'session', sessionId: 's2' })
    await Promise.resolve()

    // B 的请求发出后，A 列表立即被清空；A 的延迟 response 到达也不能覆盖 B。
    expect(store.loading).toBe(true)
    resolvers['/api/conversations?scope_mode=sessions&session_id=s1&limit=100']?.(conversationsResponse([scopedSummary]))
    resolvers['/api/conversations?scope_mode=sessions&session_id=s2&limit=100']?.(
      conversationsResponse([summary('conv-s2', '2026-08-30T09:00:00+08:00', { mode: 'sessions', session_ids: ['s2'] })]),
    )
    await Promise.all([refreshA, refreshB])

    expect(store.conversations.map((item) => item.conversation_id)).toEqual(['conv-s2'])
    expect(store.loading).toBe(false)
    vi.unstubAllGlobals()
  })

  it('groups the scoped list by today/yesterday/earlier with stable ordering', () => {
    vi.stubGlobal('fetch', vi.fn())
    const store = useConversationsStore()
    store.conversations = [
      summary('earlier', '2026-08-28T10:00:00+08:00', { mode: 'all' }),
      summary('today-2', '2026-08-30T10:00:00+08:00', { mode: 'all' }),
      summary('yesterday', '2026-08-29T10:00:00+08:00', { mode: 'all' }),
      summary('today-1', '2026-08-30T09:00:00+08:00', { mode: 'all' }),
    ]

    expect(store.dateGroups.map((group) => [group.label, group.conversations.map((item) => item.conversation_id)]))
      .toEqual([
        ['今天', ['today-2', 'today-1']],
        ['昨天', ['yesterday']],
        ['更早', ['earlier']],
      ])
    vi.unstubAllGlobals()
  })

  it('refreshes the active selection after rename and filters locally after delete', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      requests.push(`${init?.method ?? 'GET'} ${url}`)
      if (init?.method === 'PATCH') {
        return new Response(JSON.stringify({ ...allSummary, title: '改名' }))
      }
      if (init?.method === 'DELETE') {
        return new Response(JSON.stringify({ status: 'deleted' }))
      }
      return new Response(JSON.stringify([{ ...allSummary, title: '改名' }]))
    }))
    const store = useConversationsStore()
    await store.refresh({ kind: 'all' })

    await store.rename('conv-all', '改名')
    expect(requests).toContain('PATCH /api/conversations/conv-all')
    expect(requests[requests.length - 1]).toBe('GET /api/conversations?scope_mode=all&limit=100')
    expect(store.conversations[0]?.title).toBe('改名')

    await store.remove('conv-all')
    expect(requests).toContain('DELETE /api/conversations/conv-all')
    expect(store.conversations).toEqual([])
    vi.unstubAllGlobals()
  })
})
