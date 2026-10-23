// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import App from '@/App.vue'
import { useChatStore, draftBufferKey } from '@/stores/chat'
import { useScopeStore } from '@/stores/scope'
import type { ConversationSummaryDTO } from '@/types/contracts'

const catalog = [
  { session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' },
  { session_id: 's2', platform: 'wechat', name: '研发群', chat_type: 'group' },
]

function summary(
  conversationId: string,
  scope: ConversationSummaryDTO['scope'],
): ConversationSummaryDTO {
  return {
    conversation_id: conversationId,
    created_at: '2026-08-30T08:00:00+08:00',
    updated_at: '2026-08-30T08:00:00+08:00',
    title: conversationId,
    message_count: 0,
    preview: null,
    scope,
  }
}

const allSummary = summary('conv-all', { mode: 'all', max_results: 5_000 })
const scopedSummary = summary('conv-s1', { mode: 'sessions', session_ids: ['s1'], max_results: 5_000 })

function detail(summaryDto: ConversationSummaryDTO) {
  return JSON.stringify({ ...summaryDto, messages: [] })
}

// 输入框现在提供聚焦接口，集成测试使用真实组件验证导航后的启用与聚焦。
describe('App source scope navigation', () => {
  beforeEach(() => {
    // 导航现在真实写入历史，测试间隔离URL，刷新恢复测试自行设置目标。
    window.history.replaceState(null, '', '/')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/source-sessions') return new Response(JSON.stringify(catalog))
      if (url === '/api/conversations?scope_mode=all&limit=100') {
        return new Response(JSON.stringify([allSummary]))
      }
      if (url === '/api/conversations?scope_mode=sessions&session_id=s1&limit=100') {
        return new Response(JSON.stringify([scopedSummary]))
      }
      if (url === '/api/conversations/conv-s1') return new Response(detail(scopedSummary))
      if (url === '/api/conversations/conv-all') return new Response(detail(allSummary))
      return new Response('{}', { status: 404 })
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('restores scope drafts on browser history navigation without pushing another entry', async () => {
    const pinia = createPinia()
    const wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.get('[data-testid="welcome-start"]').trigger('click')
    await flushPromises()
    await wrapper.get('.conversation-link').trigger('click')
    await flushPromises()
    expect(useChatStore(pinia).currentKey).toBe('conv-all')
    const length = window.history.length
    // 模拟浏览器popstate携带的目标URL；处理程序不得额外pushState。
    window.history.replaceState(null, '', '/?scope=all')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await flushPromises()
    expect(useChatStore(pinia).currentKey).toBe(draftBufferKey({ mode: 'all' }))
    expect(window.history.length).toBe(length)
    wrapper.unmount()
  })

  it('keeps the first question when conversation creation fails', async () => {
    // 走真实 App→Composer→Store，故障只注入正式创建接口。
    const originalFetch = fetch
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/conversations' && init?.method === 'POST') {
        return Promise.resolve(new Response(JSON.stringify({ detail: '创建失败，请稍后再试' }), { status: 500 }))
      }
      return originalFetch(input, init)
    }))
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })
    await flushPromises()
    await wrapper.get('[data-testid="welcome-start"]').trigger('click')
    await flushPromises()
    await wrapper.get('textarea').setValue('不能丢失的长问题')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('创建失败')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('不能丢失的长问题')
    wrapper.unmount()
  })

  it('starts unselected: no conversation list request, empty state, and disabled composer', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/source-sessions') return new Response(JSON.stringify(catalog))
      return new Response('{}', { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    const scopeStore = useScopeStore(pinia)
    const chat = useChatStore(pinia)
    expect(scopeStore.selectedSourceScope).toBeNull()
    // 未选择范围时绝不请求 conversation 列表，也不自动打开最近项。
    expect(fetchMock.mock.calls.map((call) => String(call[0])).filter((url) => url.startsWith('/api/conversations')))
      .toEqual([])
    expect(chat.currentKey).toBeNull()
    expect(wrapper.find('[data-testid="unselected-state"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('loads only the all-scope list when the user selects 全部范围', async () => {
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="scope-all"]').trigger('click')
    await flushPromises()

    const chat = useChatStore(pinia)
    const scopeStore = useScopeStore(pinia)
    expect(scopeStore.selectedSourceScope).toEqual({ kind: 'all' })
    expect(chat.currentKey).toBe(draftBufferKey({ mode: 'all' }))
    expect(chat.currentBuffer?.scope).toEqual({ mode: 'all' })
    expect(wrapper.get('[data-testid="current-scope"]').text()).toContain('全部群聊')
    wrapper.unmount()
  })

  it('loads only the session list when the user selects a single session', async () => {
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="scope-session-s1"]').trigger('click')
    await flushPromises()

    const chat = useChatStore(pinia)
    const scopeStore = useScopeStore(pinia)
    expect(scopeStore.selectedSourceScope).toEqual({ kind: 'session', sessionId: 's1' })
    expect(chat.currentKey).toBe(draftBufferKey({ mode: 'sessions', session_ids: ['s1'] }))
    expect(wrapper.get('[data-testid="current-scope"]').text()).toContain('产品群')
    wrapper.unmount()
  })

  it('clears the main area when switching scopes and never opens the other scope history', async () => {
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="scope-session-s1"]').trigger('click')
    await flushPromises()
    const chat = useChatStore(pinia)

    // 直接打开 session A 的历史 conversation 后切到 all：主区必须立即离开旧 buffer。
    await chat.openConversation('conv-s1')
    await flushPromises()

    await wrapper.get('[data-testid="scope-all"]').trigger('click')
    await flushPromises()

    expect(chat.currentKey).toBe(draftBufferKey({ mode: 'all' }))
    expect(chat.currentBuffer?.scope).toEqual({ mode: 'all' })
    // 旧 buffer 保留（后台 stream owner 不被破坏），但不再显示。
    expect(chat.buffers['conv-s1']).toBeDefined()
    wrapper.unmount()
  })

  it('restores the legal navigation scope and scoped list from the conversation URL', async () => {
    window.history.replaceState(null, '', '/?conversation_id=conv-s1')
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    const chat = useChatStore(pinia)
    const scopeStore = useScopeStore(pinia)
    expect(chat.currentKey).toBe('conv-s1')
    expect(scopeStore.selectedSourceScope).toEqual({ kind: 'session', sessionId: 's1' })
    // detail-first：URL conversation 打开后才请求该 scope 的列表。
    const requestedUrls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0]))
    const listIndex = requestedUrls.indexOf('/api/conversations?scope_mode=sessions&session_id=s1&limit=100')
    const detailIndex = requestedUrls.indexOf('/api/conversations/conv-s1')
    expect(listIndex).toBeGreaterThan(detailIndex)
    expect(listIndex).toBeGreaterThan(-1)
    wrapper.unmount()
    window.history.replaceState(null, '', '/')
  })

  it('keeps legacy null-scope history read-only without mapping it to navigation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/source-sessions') return new Response(JSON.stringify(catalog))
      if (url === '/api/conversations/conv-legacy') {
        return new Response(detail(summary('conv-legacy', null)))
      }
      return new Response('{}', { status: 404 })
    }))
    window.history.replaceState(null, '', '/?conversation_id=conv-legacy')
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    const chat = useChatStore(pinia)
    const scopeStore = useScopeStore(pinia)
    expect(chat.currentKey).toBe('conv-legacy')
    expect(scopeStore.selectedSourceScope).toBeNull()
    expect(wrapper.get('[data-testid="current-scope"]').text()).toContain('未标记范围')
    expect(wrapper.find('[data-testid="read-only-hint"]').exists()).toBe(true)
    wrapper.unmount()
    window.history.replaceState(null, '', '/')
  })

  it('starts from the welcome action and fills suggestions without sending', async () => {
    const wrapper = mount(App, { attachTo: document.body, global: { plugins: [createPinia()], stubs: { AssistantTurn: true } } })
    await flushPromises()
    await wrapper.get('[data-testid="welcome-start"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="draft-state"]').exists()).toBe(true)
    expect(document.activeElement).toBe(wrapper.get('textarea').element)
    await wrapper.findAll('.suggestion')[0]!.trigger('click')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toContain('最近一周')
    expect(wrapper.get('textarea').attributes('disabled')).toBeUndefined()
    const urls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.startsWith('/api/query'))).toBe(false)
    await wrapper.get('[aria-label="搜索聊天范围"]').setValue('研发')
    expect(wrapper.find('[data-testid="scope-session-s1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="scope-session-s2"]').exists()).toBe(true)
    wrapper.unmount()
  })

})
