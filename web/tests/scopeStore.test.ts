import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useScopeStore } from '@/stores/scope'

const catalog = [
  { session_id: 's2', platform: 'wechat', name: '研发群', chat_type: 'group' },
  { session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' },
]

describe('scope store primary navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('starts unselected and loading the catalog does not auto-select', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(catalog))))
    const store = useScopeStore()
    expect(store.selectedSourceScope).toBeNull()
    expect(store.scope).toBeNull()

    await store.load()
    expect(store.sessions).toHaveLength(2)
    expect(store.selectedSourceScope).toBeNull()
    expect(store.scope).toBeNull()
    vi.unstubAllGlobals()
  })

  it('compiles explicit selections into legal ScopeRequests', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(catalog))))
    const store = useScopeStore()
    await store.load()

    store.select({ kind: 'all' })
    expect(store.scope).toEqual({ mode: 'all' })

    store.select({ kind: 'session', sessionId: 's1' })
    expect(store.scope).toEqual({ mode: 'sessions', session_ids: ['s1'] })
    vi.unstubAllGlobals()
  })

  it('restores legal conversation scopes and rejects multi/unknown/null for navigation', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(catalog))))
    const store = useScopeStore()
    await store.load()

    expect(store.restoreFromConversationScope({ mode: 'all' })).toEqual({ kind: 'all' })
    expect(store.selectedSourceScope).toEqual({ kind: 'all' })

    expect(store.restoreFromConversationScope({ mode: 'sessions', session_ids: ['s2', 's2'] }))
      .toEqual({ kind: 'session', sessionId: 's2' })

    // multi-session、未知 session 与 legacy null 都不映射为合法 primary navigation。
    expect(store.restoreFromConversationScope({ mode: 'sessions', session_ids: ['s1', 's2'] })).toBeNull()
    expect(store.restoreFromConversationScope({ mode: 'sessions', session_ids: ['missing'] })).toBeNull()
    expect(store.restoreFromConversationScope(null)).toBeNull()
    expect(store.selectedSourceScope).toBeNull()
    vi.unstubAllGlobals()
  })

  it('surfaces catalog load failures explicitly instead of guessing a scope', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"boom"}', { status: 500 })))
    const store = useScopeStore()
    await store.load()

    expect(store.catalogLoaded).toBe(false)
    expect(store.catalogError).toBe('boom')
    expect(store.selectedSourceScope).toBeNull()
    expect(store.scope).toBeNull()
    vi.unstubAllGlobals()
  })
})
