import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'
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

describe('conversations store scope projection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-30T12:00:00+08:00'))
  })

  afterEach(() => vi.useRealTimers())

  it('groups by canonical scope first and date second with stable ordering', () => {
    const scopeStore = useScopeStore()
    scopeStore.sessions = [
      { session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' },
      { session_id: 's2', platform: 'wechat', name: '研发群', chat_type: 'group' },
    ]
    const store = useConversationsStore()
    store.conversations = [
      summary('sessions-today', '2026-08-30T10:00:00+08:00', { mode: 'sessions', session_ids: ['s2', 's1', 's2'] }),
      summary('unmarked', '2026-08-30T09:00:00+08:00', null),
      summary('all-yesterday', '2026-08-29T10:00:00+08:00', { mode: 'all' }),
      summary('sessions-earlier', '2026-08-28T10:00:00+08:00', { mode: 'sessions', session_ids: ['s1', 's2'] }),
    ]

    expect(store.groups.map((group) => [group.key, group.label])).toEqual([
      ['all', '全部群聊'],
      ['sessions:["s1","s2"]', '产品群 + 研发群'],
      ['unmarked', '未标记范围'],
    ])
    expect(store.groups[0]?.dateGroups.map((group) => group.label)).toEqual(['昨天'])
    expect(store.groups[1]?.dateGroups.map((group) => [group.label, group.conversations.map((item) => item.conversation_id)]))
      .toEqual([
        ['今天', ['sessions-today']],
        ['更早', ['sessions-earlier']],
      ])
  })
})
