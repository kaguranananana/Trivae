/** Conversation 侧栏数据（list/rename/delete）；AI Conversation ≠ Source Session。 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { ConversationSummaryDTO } from '@/types/contracts'

export interface ConversationGroup {
  label: string
  conversations: ConversationSummaryDTO[]
}

function groupLabel(updatedAtIso: string): string {
  const time = new Date(updatedAtIso).getTime()
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (time >= startOfToday) return '今天'
  if (time >= startOfToday - 86_400_000) return '昨天'
  return '更早'
}

export const useConversationsStore = defineStore('conversations', () => {
  const conversations = ref<ConversationSummaryDTO[]>([])
  const loaded = ref(false)
  const loading = ref(false)

  const groups = computed<ConversationGroup[]>(() => {
    const grouped = new Map<string, ConversationSummaryDTO[]>()
    for (const conversation of conversations.value) {
      const label = groupLabel(conversation.updated_at)
      const bucket = grouped.get(label) ?? []
      bucket.push(conversation)
      grouped.set(label, bucket)
    }
    return [...grouped.entries()].map(([label, items]) => ({ label, conversations: items }))
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
