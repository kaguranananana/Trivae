/**
 * Conversation 侧栏数据（list/rename/delete）。
 *
 * 列表请求是 selector-scoped：后端在 scope 过滤后再排序、limit；
 * 前端不再对全局最近列表做客户端过滤。generation guard 保证 A→B 切换时
 * 延迟到达的 A response 不能覆盖 B 的列表。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { ConversationSummaryDTO, ScopeRequest } from '@/types/contracts'
import { compileNavigationScope, normalizeSessionIds, type SelectedSourceScope } from '@/utils/scope'

export interface ConversationGroup {
  label: string
  conversations: ConversationSummaryDTO[]
}

const DATE_GROUP_ORDER = ['今天', '昨天', '更早'] as const

function groupLabel(updatedAtIso: string): string {
  const time = new Date(updatedAtIso).getTime()
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (time >= startOfToday) return '今天'
  if (time >= startOfToday - 86_400_000) return '昨天'
  return '更早'
}

/** 把合法 ScopeRequest 编译为 bounded list selector；primary navigation 只产生 all 或单 session。 */
function toListSelector(scope: ScopeRequest): { scopeMode: 'all' | 'sessions'; sessionId?: string } {
  if (scope.mode === 'all') return { scopeMode: 'all' }
  const sessionIds = normalizeSessionIds(scope.session_ids)
  if (sessionIds.length !== 1) {
    throw new Error(`conversation list selector requires exactly one session, got ${sessionIds.length}`)
  }
  return { scopeMode: 'sessions', sessionId: sessionIds[0] }
}

export const useConversationsStore = defineStore('conversations', () => {
  const conversations = ref<ConversationSummaryDTO[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  /** 最近一次 refresh 的 navigation selection；rename 后 scoped refresh 复用。 */
  const activeSelection = ref<SelectedSourceScope>(null)
  let generation = 0

  const dateGroups = computed<ConversationGroup[]>(() => {
    const dateBuckets = new Map<string, ConversationSummaryDTO[]>()
    for (const conversation of conversations.value) {
      const label = groupLabel(conversation.updated_at)
      const bucket = dateBuckets.get(label) ?? []
      bucket.push(conversation)
      dateBuckets.set(label, bucket)
    }
    return DATE_GROUP_ORDER.flatMap((label) => {
      const conversationsForDate = dateBuckets.get(label)
      return conversationsForDate ? [{ label, conversations: conversationsForDate }] : []
    })
  })

  /**
   * 按当前 navigation selection 请求 scope 过滤后的列表。
   * selection=null 时不发请求：列表立即清空，显示未选择状态。
   */
  async function refresh(selection: SelectedSourceScope): Promise<void> {
    generation += 1
    const requestGeneration = generation
    activeSelection.value = selection
    // 立即清空：A→B 切换时 B 立即看到空列表，而不是 A 的旧数据。
    conversations.value = []
    loaded.value = false
    const scopeRequest = compileNavigationScope(selection)
    if (scopeRequest === null) {
      loading.value = false
      return
    }
    loading.value = true
    try {
      const results = await api.conversations(toListSelector(scopeRequest), 100)
      // race guard：只有仍是最新请求时才提交 response。
      if (requestGeneration !== generation) return
      conversations.value = results
      loaded.value = true
    } finally {
      if (requestGeneration === generation) {
        loading.value = false
      }
    }
  }

  async function rename(conversationId: string, title: string): Promise<void> {
    await api.renameConversation(conversationId, title)
    await refresh(activeSelection.value)
  }

  async function remove(conversationId: string): Promise<void> {
    // 只删除 AI conversation；canonical chat 数据不受影响。
    await api.deleteConversation(conversationId)
    conversations.value = conversations.value.filter((item) => item.conversation_id !== conversationId)
  }

  return { conversations, dateGroups, loaded, loading, activeSelection, refresh, rename, remove }
})
