import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { ScopeRequest, SessionDTO } from '@/types/contracts'
import { describeScope, normalizeSessionIds } from '@/utils/scope'

/** Source Session（=ExecutionScope）选择；决定 Retrieval 范围，与 AI Conversation 是不同概念。 */

export const useScopeStore = defineStore('scope', () => {
  const sessions = ref<SessionDTO[]>([])
  const mode = ref<'all' | 'sessions'>('all')
  const selectedSessionIds = ref<string[]>([])

  const selectorDisplay = computed(() => describeScope(scope(), sessions.value))

  async function load(): Promise<void> {
    sessions.value = await api.sessions()
    legalizeSelector()
  }

  function scope(): ScopeRequest {
    const sessionIds = normalizeSessionIds(selectedSessionIds.value)
    if (mode.value === 'sessions' && sessionIds.length > 0) {
      return { mode: 'sessions', session_ids: sessionIds }
    }
    return { mode: 'all' }
  }

  /** 保证 selector 不会停在 sessions + 空集合这种不可表达状态。 */
  function legalizeSelector(): void {
    selectedSessionIds.value = normalizeSessionIds(selectedSessionIds.value)
    if (mode.value !== 'sessions' || selectedSessionIds.value.length > 0) return

    const firstSession = sessions.value[0]
    if (firstSession) {
      selectedSessionIds.value = [firstSession.session_id]
      return
    }
    mode.value = 'all'
  }

  /** mode 切换是显式导航动作；进入 sessions 时选择第一个真实 Source Session。 */
  function selectMode(nextMode: 'all' | 'sessions'): void {
    mode.value = nextMode
    if (nextMode === 'all') selectedSessionIds.value = []
    legalizeSelector()
  }

  /** 多选清空时回到 all，不保留误导性的空 sessions 模式。 */
  function selectSessions(sessionIds: readonly string[]): void {
    selectedSessionIds.value = normalizeSessionIds(sessionIds)
    mode.value = selectedSessionIds.value.length > 0 ? 'sessions' : 'all'
  }

  /**
   * 打开正式 Conversation 后只恢复 selector 可表达字段。
   * legacy null 没有合法 selector 表达，因此明确保持用户最近一次合法选择。
   */
  function restoreFromScope(conversationScope: ScopeRequest | null): void {
    if (conversationScope === null) return
    if (conversationScope.mode === 'all') {
      selectMode('all')
      return
    }
    selectSessions(conversationScope.session_ids ?? [])
  }

  function describe(): string {
    return selectorDisplay.value.label
  }

  return {
    sessions,
    mode,
    selectedSessionIds,
    selectorDisplay,
    load,
    scope,
    legalizeSelector,
    selectMode,
    selectSessions,
    restoreFromScope,
    describe,
  }
})
