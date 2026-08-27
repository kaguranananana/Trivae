import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { ScopeRequest, SessionDTO } from '@/types/contracts'

/** Source Session（=ExecutionScope）选择；决定 Retrieval 范围，与 AI Conversation 是不同概念。 */

export const useScopeStore = defineStore('scope', () => {
  const sessions = ref<SessionDTO[]>([])
  const mode = ref<'all' | 'sessions'>('all')
  const selectedSessionIds = ref<string[]>([])

  async function load(): Promise<void> {
    sessions.value = await api.sessions()
    if (selectedSessionIds.value.length === 0 && sessions.value.length > 0) {
      // 默认选第一个真实 session，避免用户误以为"全部"是唯一选项。
      mode.value = 'all'
    }
  }

  function scope(): ScopeRequest {
    if (mode.value === 'sessions' && selectedSessionIds.value.length > 0) {
      return { mode: 'sessions', session_ids: [...selectedSessionIds.value] }
    }
    return { mode: 'all' }
  }

  function describe(): string {
    if (mode.value === 'all') return '全部聊天'
    const names = selectedSessionIds.value
      .map((id) => sessions.value.find((session) => session.session_id === id)?.name ?? id)
      .join(', ')
    return names || '已选会话'
  }

  return { sessions, mode, selectedSessionIds, load, scope, describe }
})
