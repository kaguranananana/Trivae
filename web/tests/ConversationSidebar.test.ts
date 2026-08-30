// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import ConversationSidebar from '@/components/sidebar/ConversationSidebar.vue'
import { useChatStore, DRAFT_KEY } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'
import type { ConversationSummaryDTO } from '@/types/contracts'

const scopedSummary: ConversationSummaryDTO = {
  conversation_id: 'conv-s1',
  created_at: '2026-08-30T08:00:00+08:00',
  updated_at: '2026-08-30T08:00:00+08:00',
  title: '产品讨论',
  message_count: 0,
  preview: '讨论下一版功能',
  scope: { mode: 'sessions', session_ids: ['s1'], max_results: 5_000 },
}

describe('ConversationSidebar scope lifecycle', () => {
  let currentTitle = scopedSummary.title

  beforeEach(() => {
    currentTitle = scopedSummary.title
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/conversations/conv-s1' && init?.method === 'PATCH') {
        currentTitle = (JSON.parse(String(init.body)) as { title: string }).title
        return new Response(JSON.stringify({ ...scopedSummary, title: currentTitle, messages: [] }))
      }
      if (url === '/api/conversations/conv-s1' && init?.method === 'DELETE') {
        return new Response(JSON.stringify({ status: 'deleted' }))
      }
      if (url === '/api/conversations/conv-s1') {
        return new Response(JSON.stringify({ ...scopedSummary, title: currentTitle, messages: [] }))
      }
      if (url.startsWith('/api/conversations?')) {
        return new Response(JSON.stringify([{ ...scopedSummary, title: currentTitle }]))
      }
      return new Response('{}', { status: 404 })
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('syncs selector on open and preserves scope across new, rename, and delete actions', async () => {
    const pinia = createPinia()
    const scopeStore = useScopeStore(pinia)
    scopeStore.sessions = [{ session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' }]
    const conversationsStore = useConversationsStore(pinia)
    conversationsStore.conversations = [scopedSummary]
    conversationsStore.loaded = true
    const chat = useChatStore(pinia)
    chat.newChat({ mode: 'all' })

    const wrapper = mount(ConversationSidebar, { global: { plugins: [pinia] } })
    const conversationItem = wrapper.find('section .group')
    await conversationItem.trigger('click')
    await flushPromises()

    expect(chat.currentKey).toBe('conv-s1')
    expect(scopeStore.scope()).toEqual({ mode: 'sessions', session_ids: ['s1'] })
    expect(wrapper.get('section > div').classes()).toContain('bg-primary/8')

    await wrapper.findAll('button').find((button) => button.text() === '+ New Chat')?.trigger('click')
    expect(chat.currentKey).toBe(DRAFT_KEY)
    expect(chat.currentBuffer?.scope).toEqual({ mode: 'sessions', session_ids: ['s1'] })

    await wrapper.find('section .group').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '重命名')?.trigger('click')
    const renameInput = wrapper.get('input')
    await renameInput.setValue('新版产品讨论')
    await renameInput.trigger('blur')
    await flushPromises()
    expect(currentTitle).toBe('新版产品讨论')

    await wrapper.findAll('button').find((button) => button.text() === '删除')?.trigger('click')
    await flushPromises()
    expect(conversationsStore.conversations).toEqual([])
    expect(chat.currentKey).toBe(DRAFT_KEY)
    expect(chat.currentBuffer?.scope).toEqual({ mode: 'sessions', session_ids: ['s1'] })
    wrapper.unmount()
  })
})
