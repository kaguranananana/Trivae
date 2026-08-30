// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import App from '@/App.vue'
import { useChatStore, DRAFT_KEY } from '@/stores/chat'
import { useScopeStore } from '@/stores/scope'

const catalog = [
  { session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' },
  { session_id: 's2', platform: 'wechat', name: '研发群', chat_type: 'group' },
]

const summary = {
  conversation_id: 'conv-s1',
  created_at: '2026-08-30T08:00:00+08:00',
  updated_at: '2026-08-30T08:00:00+08:00',
  title: '产品讨论',
  message_count: 0,
  preview: null,
  scope: { mode: 'sessions', session_ids: ['s1'], max_results: 5_000 },
}

describe('App scope lifecycle', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/source-sessions') return new Response(JSON.stringify(catalog))
      if (url.startsWith('/api/conversations?')) return new Response(JSON.stringify([summary]))
      if (url === '/api/conversations/conv-s1') {
        return new Response(JSON.stringify({ ...summary, messages: [] }))
      }
      return new Response('{}', { status: 404 })
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('shows the opened buffer scope and enters a draft immediately after selector changes', async () => {
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: {
          AssistantTurn: true,
          ChatComposer: true,
          ConversationSidebar: true,
        },
      },
    })
    await flushPromises()

    const chat = useChatStore(pinia)
    const scopeStore = useScopeStore(pinia)
    expect(chat.currentKey).toBe('conv-s1')
    expect(scopeStore.scope()).toEqual({ mode: 'sessions', session_ids: ['s1'] })
    expect(wrapper.get('[data-testid="current-scope"]').text()).toContain('产品群')

    const sessionSelect = wrapper.get<HTMLSelectElement>('select[aria-label="选择群聊"]')
    const secondSession = [...sessionSelect.element.options].find((option) => option.value === 's2')
    if (!secondSession) throw new Error('second source session option is missing')
    secondSession.selected = true
    await sessionSelect.trigger('change')
    expect(chat.currentKey).toBe(DRAFT_KEY)
    expect(chat.currentBuffer?.scope).toEqual({ mode: 'sessions', session_ids: ['s1', 's2'] })

    await wrapper.get('select[aria-label="切换范围模式"]').setValue('all')

    expect(chat.currentKey).toBe(DRAFT_KEY)
    expect(chat.currentBuffer?.scope).toEqual({ mode: 'all' })
    expect(chat.buffers['conv-s1']?.scope).toEqual(summary.scope)
    expect(wrapper.get('[data-testid="current-scope"]').text()).toContain('全部群聊')
    wrapper.unmount()
  })

  it('shows a legacy null scope as unmarked without changing the legal selector', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/source-sessions') return new Response(JSON.stringify(catalog))
      if (url.startsWith('/api/conversations?')) return new Response(JSON.stringify([{ ...summary, scope: null }]))
      if (url === '/api/conversations/conv-s1') {
        return new Response(JSON.stringify({ ...summary, scope: null, messages: [] }))
      }
      return new Response('{}', { status: 404 })
    }))

    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ChatComposer: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="current-scope"]').text()).toContain('未标记范围')
    expect(useScopeStore(pinia).scope()).toEqual({ mode: 'all' })
    wrapper.unmount()
  })

  it('restores every selected option for a multi-session conversation', async () => {
    const multiSessionSummary = {
      ...summary,
      scope: { mode: 'sessions' as const, session_ids: ['s2', 's1'] },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/source-sessions') return new Response(JSON.stringify(catalog))
      if (url.startsWith('/api/conversations?')) return new Response(JSON.stringify([multiSessionSummary]))
      if (url === '/api/conversations/conv-s1') {
        return new Response(JSON.stringify({ ...multiSessionSummary, messages: [] }))
      }
      return new Response('{}', { status: 404 })
    }))

    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: { AssistantTurn: true, ChatComposer: true, ConversationSidebar: true },
      },
    })
    await flushPromises()

    const sessionSelect = wrapper.get<HTMLSelectElement>('select[aria-label="选择群聊"]')
    expect([...sessionSelect.element.selectedOptions].map((option) => option.value)).toEqual(['s1', 's2'])
    wrapper.unmount()
  })
})
