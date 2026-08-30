import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useScopeStore } from '@/stores/scope'

const catalog = [
  { session_id: 's2', platform: 'wechat', name: '研发群', chat_type: 'group' },
  { session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' },
]

describe('scope store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(catalog))))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('keeps selector scopes canonical and legal', async () => {
    const store = useScopeStore()
    await store.load()

    store.selectMode('sessions')
    expect(store.scope()).toEqual({ mode: 'sessions', session_ids: ['s2'] })

    store.selectSessions(['s2', 's1', 's2'])
    expect(store.scope()).toEqual({ mode: 'sessions', session_ids: ['s1', 's2'] })

    store.selectSessions([])
    expect(store.mode).toBe('all')
    expect(store.scope()).toEqual({ mode: 'all' })
  })

  it('restores a formal conversation scope but preserves the last legal selector for null', () => {
    const store = useScopeStore()
    store.selectSessions(['s2'])
    store.restoreFromScope({ mode: 'sessions', session_ids: ['s1', 's1'] })
    expect(store.scope()).toEqual({ mode: 'sessions', session_ids: ['s1'] })

    store.restoreFromScope(null)
    expect(store.scope()).toEqual({ mode: 'sessions', session_ids: ['s1'] })

    store.restoreFromScope({ mode: 'all', max_results: 5_000 })
    expect(store.scope()).toEqual({ mode: 'all' })
  })

  it('keeps all when sessions mode is selected without a source-session catalog', () => {
    const store = useScopeStore()
    store.selectMode('sessions')
    expect(store.mode).toBe('all')
    expect(store.scope()).toEqual({ mode: 'all' })
  })
})
