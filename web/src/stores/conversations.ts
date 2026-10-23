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
import { compileNavigationScope, normalizeSessionIds, type SelectedSourceScope, navigationSelectionsEqual } from '@/utils/scope'

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
  const query = ref('')
  const error = ref('')
  const hasMore = ref(false)
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
  async function refresh(selection: SelectedSourceScope, search?: string): Promise<void> {
    // 范围切换清空旧搜索，同范围刷新保留搜索条件。
    query.value = search ?? (navigationSelectionsEqual(selection, activeSelection.value) ? query.value : '')
    error.value = ''
    hasMore.value = false
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
      const results = await api.conversations(toListSelector(scopeRequest), 100, query.value)
      // race guard：只有仍是最新请求时才提交 response。
      if (requestGeneration !== generation) return
      conversations.value = results
      loaded.value = true
      hasMore.value = results.length === 100
    } catch (cause) {
      if (requestGeneration !== generation) return
      error.value = cause instanceof Error ? cause.message : String(cause)
      throw cause
    } finally {
      if (requestGeneration === generation) {
        loading.value = false
      }
    }
  }

  /** 继续读取同一范围和搜索条件，失败保留已读结果及明确错误。 */
  async function loadMore(): Promise<void> {
    const scopeRequest = compileNavigationScope(activeSelection.value)
    if (!scopeRequest || loading.value || !hasMore.value) return
    const requestGeneration = generation
    loading.value = true
    error.value = ''
    try {
      const results = await api.conversations(toListSelector(scopeRequest), 100, query.value, conversations.value.length)
      if (requestGeneration !== generation) return
      conversations.value.push(...results)
      hasMore.value = results.length === 100
    } catch (cause) {
      if (requestGeneration === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  /** 搜索覆盖当前范围所有已保存标题和消息正文，由服务器过滤后分页。 */
  async function search(text: string): Promise<void> {
    // refresh已保存具体错误，界面消费状态，不创建无人处理的Promise异常。
    try { await refresh(activeSelection.value, text.trim()) } catch { /* 错误由error原样展示。 */ }
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

  return { conversations, dateGroups, loaded, loading, activeSelection, query, error, hasMore, refresh, loadMore, search, rename, remove }
})
