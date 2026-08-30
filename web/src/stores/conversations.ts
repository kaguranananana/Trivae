/** Conversation 侧栏数据（list/rename/delete）；AI Conversation ≠ Source Session。 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { ConversationSummaryDTO } from '@/types/contracts'
import { useScopeStore } from '@/stores/scope'
import { describeScope, scopeKey } from '@/utils/scope'

export interface ConversationGroup {
  label: string
  conversations: ConversationSummaryDTO[]
}

export interface ScopeConversationGroup {
  key: string
  label: string
  title: string
  dateGroups: ConversationGroup[]
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

export const useConversationsStore = defineStore('conversations', () => {
  const scopeStore = useScopeStore()
  const conversations = ref<ConversationSummaryDTO[]>([])
  const loaded = ref(false)
  const loading = ref(false)

  const groups = computed<ScopeConversationGroup[]>(() => {
    const grouped = new Map<string, ConversationSummaryDTO[]>()
    for (const conversation of conversations.value) {
      const key = scopeKey(conversation.scope)
      const bucket = grouped.get(key) ?? []
      bucket.push(conversation)
      grouped.set(key, bucket)
    }

    const scopeGroups = [...grouped.entries()].map(([key, items]): ScopeConversationGroup => {
      // 同一个 canonical key 中的 scope 等价，首项即可作为展示投影来源。
      const display = describeScope(items[0]?.scope ?? null, scopeStore.sessions)
      const dateBuckets = new Map<string, ConversationSummaryDTO[]>()
      for (const conversation of items) {
        const label = groupLabel(conversation.updated_at)
        const bucket = dateBuckets.get(label) ?? []
        bucket.push(conversation)
        dateBuckets.set(label, bucket)
      }
      const dateGroups = DATE_GROUP_ORDER.flatMap((label) => {
        const conversationsForDate = dateBuckets.get(label)
        return conversationsForDate ? [{ label, conversations: conversationsForDate }] : []
      })
      return { key, label: display.label, title: display.title, dateGroups }
    })

    // all 固定在前、legacy 未标记固定在后；session groups 按可读文案和 key 稳定排序。
    return scopeGroups.sort((left, right) => {
      if (left.key === 'all') return right.key === 'all' ? 0 : -1
      if (right.key === 'all') return 1
      if (left.key === 'unmarked') return right.key === 'unmarked' ? 0 : 1
      if (right.key === 'unmarked') return -1
      return left.label.localeCompare(right.label) || left.key.localeCompare(right.key)
    })
  })

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      conversations.value = await api.conversations(100)
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  async function rename(conversationId: string, title: string): Promise<void> {
    await api.renameConversation(conversationId, title)
    await refresh()
  }

  async function remove(conversationId: string): Promise<void> {
    // 只删除 AI conversation；canonical chat 数据不受影响。
    await api.deleteConversation(conversationId)
    conversations.value = conversations.value.filter((item) => item.conversation_id !== conversationId)
  }

  return { conversations, groups, loaded, loading, refresh, rename, remove }
})
