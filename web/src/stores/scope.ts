import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { ScopeRequest, SessionDTO } from '@/types/contracts'
import {
  compileNavigationScope,
  describeScope,
  restoreNavigationScope,
  type SelectedSourceScope,
} from '@/utils/scope'

/**
 * Source Scope 一级导航状态。
 *
 * `selectedSourceScope` 只是 Web navigation state，初始为 null（未选择）；
 * catalog 加载不会自动选择。合法 ScopeRequest 只能由 navigation selection
 * 编译得到；Source Session（=ExecutionScope）与 AI Conversation 是不同概念。
 */

export const useScopeStore = defineStore('scope', () => {
  const sessions = ref<SessionDTO[]>([])
  const selectedSourceScope = ref<SelectedSourceScope>(null)
  const catalogLoading = ref(false)
  const catalogLoaded = ref(false)
  const catalogError = ref<string | null>(null)

  /** 当前 selection 编译出的合法 ScopeRequest；未选择时为 null，不存在 all fallback。 */
  const scope = computed<ScopeRequest | null>(() => compileNavigationScope(selectedSourceScope.value))

  const scopeDisplay = computed(() => describeScope(scope.value, sessions.value))

  /** 加载 Source Session catalog；失败显式保存在 catalogError，由 Sidebar 呈现。 */
  async function load(): Promise<void> {
    catalogLoading.value = true
    catalogError.value = null
    try {
      sessions.value = await api.sessions()
      catalogLoaded.value = true
    } catch (error) {
      catalogError.value = error instanceof Error ? error.message : String(error)
    } finally {
      catalogLoading.value = false
    }
  }

  function select(selection: SelectedSourceScope): void {
    selectedSourceScope.value = selection
  }

  /**
   * 打开正式 Conversation 后按 immutable scope 恢复合法 navigation selection。
   * 返回恢复结果：legacy null / multi-session / 未知 session 恢复为 null，
   * 历史 buffer 保持只读回放，不猜测合法 scope。
   */
  function restoreFromConversationScope(conversationScope: ScopeRequest | null): SelectedSourceScope {
    const restored = restoreNavigationScope(conversationScope, sessions.value)
    selectedSourceScope.value = restored
    return restored
  }

  return {
    sessions,
    selectedSourceScope,
    catalogLoading,
    catalogLoaded,
    catalogError,
    scope,
    scopeDisplay,
    load,
    select,
    restoreFromConversationScope,
  }
})
