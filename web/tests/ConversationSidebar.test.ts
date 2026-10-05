// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import ConversationSidebar from '@/components/sidebar/ConversationSidebar.vue'
import { useChatStore } from '@/stores/chat'
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

const earlierSummary: ConversationSummaryDTO = {
  conversation_id: 'conv-old',
  created_at: '2026-08-20T08:00:00+08:00',
  updated_at: '2026-08-20T08:00:00+08:00',
  title: '更早的讨论',
  message_count: 2,
  preview: '历史内容',
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
      if (url === '/api/conversations?scope_mode=sessions&session_id=s1&limit=100') {
        return new Response(JSON.stringify([{ ...scopedSummary, title: currentTitle }]))
      }
      return new Response('{}', { status: 404 })
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('emits open with the immutable scope restore and keeps highlight/date groups/rename/delete', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-30T12:00:00+08:00'))
    const pinia = createPinia()
    const scopeStore = useScopeStore(pinia)
    scopeStore.sessions = [{ session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' }]
    scopeStore.select({ kind: 'session', sessionId: 's1' })
    const conversationsStore = useConversationsStore(pinia)
    conversationsStore.conversations = [scopedSummary, earlierSummary]
    conversationsStore.loaded = true
    // rename 内部会 refresh 当前 selection；fixture 与真实导航流程保持一致。
    conversationsStore.activeSelection = { kind: 'session', sessionId: 's1' }
    const chat = useChatStore(pinia)
    chat.newChat({ mode: 'sessions', session_ids: ['s1'] })

    const wrapper = mount(ConversationSidebar, { global: { plugins: [pinia] } })

    // today/earlier 日期分组保留。
    const dateGroups = wrapper.findAll('[data-testid="date-group"]')
    expect(dateGroups.map((group) => group.find('div').text())).toEqual(['今天', '更早'])

    await wrapper.get('[data-testid="conversation-conv-s1"]').trigger('click')
    expect(wrapper.emitted('open')).toEqual([['conv-s1']])

    // 模拟父级已打开该 conversation：rename 与 delete-current 都发生在打开状态下。
    await chat.openConversation('conv-s1')
    await flushPromises()
    expect(chat.currentKey).toBe('conv-s1')

    await wrapper.findAll('button').find((button) => button.text() === '重命名')?.trigger('click')
    // 新增搜索框后，用可访问名称定位重命名输入，继续验证真实 PATCH 请求。
    const renameInput = wrapper.get('input[aria-label="对话名称"]')
    await renameInput.setValue('新版产品讨论')
    await renameInput.trigger('blur')
    await flushPromises()
    expect(currentTitle).toBe('新版产品讨论')

    await wrapper.findAll('button').find((button) => button.text() === '删除')?.trigger('click')
    await flushPromises()
    expect(conversationsStore.conversations).toEqual([])
    // 当前项被删除时通知父级清理 buffer 与 URL。
    expect(wrapper.emitted('deleted')).toEqual([['conv-s1']])

    // New Chat 继承当前 navigation selection 的 scope。
    await wrapper.get('[data-testid="new-chat"]').trigger('click')
    expect(wrapper.emitted('newChat')).toHaveLength(1)
    vi.useRealTimers()
    wrapper.unmount()
  })

  it('disables New Chat while no source scope is selected and shows the unselected hint', () => {
    const pinia = createPinia()
    const scopeStore = useScopeStore(pinia)
    scopeStore.sessions = [{ session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' }]
    const conversationsStore = useConversationsStore(pinia)
    conversationsStore.conversations = [scopedSummary]

    const wrapper = mount(ConversationSidebar, { global: { plugins: [pinia] } })
    expect(wrapper.get('[data-testid="new-chat"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="unselected-hint"]').text()).toContain('选择一个聊天范围')
    // 未选择时不渲染列表分组。
    expect(wrapper.findAll('[data-testid="date-group"]')).toHaveLength(0)
    wrapper.unmount()
  })

  it('shows an empty state once the selected scope has no conversations', () => {
    const pinia = createPinia()
    const scopeStore = useScopeStore(pinia)
    scopeStore.select({ kind: 'all' })
    const conversationsStore = useConversationsStore(pinia)
    conversationsStore.conversations = []
    conversationsStore.loaded = true

    const wrapper = mount(ConversationSidebar, { global: { plugins: [pinia] } })
    expect(wrapper.get('[data-testid="new-chat"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="empty-list"]').text()).toContain('该范围下还没有 AI 对话记录')
    wrapper.unmount()
  })

  it('searches loaded conversations inside the selected scope', async () => {
    const pinia = createPinia()
    useScopeStore(pinia).select({ kind: 'all' })
    const store = useConversationsStore(pinia)
    store.conversations = [scopedSummary, earlierSummary]
    store.loaded = true
    const wrapper = mount(ConversationSidebar, { global: { plugins: [pinia] } })
    await wrapper.get('[aria-label="搜索当前范围内的对话"]').setValue('历史内容')
    expect(wrapper.find('[data-testid="conversation-conv-s1"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="conversation-conv-old"]').exists()).toBe(true)
    // 搜索不扩大请求范围，也不发起任何新的网络查询。
    expect(fetch).not.toHaveBeenCalled()
    wrapper.unmount()
  })

})
