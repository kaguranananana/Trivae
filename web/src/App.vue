<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'
import { onKeyStroke, useMediaQuery, useStorage, useEventListener } from '@vueuse/core'
import AssistantTurn from '@/components/chat/AssistantTurn.vue'
import ChatComposer from '@/components/composer/ChatComposer.vue'
import ConversationSidebar from '@/components/sidebar/ConversationSidebar.vue'
import SourceScopeSidebar from '@/components/sidebar/SourceScopeSidebar.vue'
import { useFollowTail } from '@/composables/useFollowTail'
import { describeScope, navigationSelectionsEqual, type SelectedSourceScope } from '@/utils/scope'
import { readConversationIdFromUrl, readScopeFromUrl, writeConversationIdToUrl, writeNavigationToUrl } from '@/utils/url'

const chat = useChatStore()
const conversationsStore = useConversationsStore()
const scopeStore = useScopeStore()
const { currentBuffer } = storeToRefs(chat)
const { selectedSourceScope } = storeToRefs(scopeStore)

const scrollContainer = ref<HTMLElement | null>(null)
const { following, scrollToBottom, onContentMutated } = useFollowTail(scrollContainer, currentBuffer)

// 只观察模型写入的数据，用户展开过程或原文不会触发滚到底部。
watch(() => currentBuffer.value?.items, () => onContentMutated(), { deep: true, flush: 'post' })

const readinessText = ref('')
const navigationError = ref('')
const sidebarOpen = ref(false)
const sidebarCollapsed = useStorage('trivae:sidebar-collapsed', false)
let navigationGeneration = 0
const isMobile = useMediaQuery('(max-width: 760px)')
const navigation = ref<HTMLElement | null>(null)
const sidebarClose = ref<HTMLButtonElement | null>(null)
const sidebarToggle = ref<HTMLButtonElement | null>(null)
const composer = ref<InstanceType<typeof ChatComposer> | null>(null)
const suggestions = [
  { title: '总结近期讨论', query: '总结最近一周的主要讨论，按主题整理，并标注消息来源。', icon: '◎' },
  { title: '查找技术方案', query: '最近讨论过哪些技术方案？整理它们的优缺点和适用场景，并提供来源。', icon: '⌕' },
  { title: '梳理不同观点', query: '找出近期讨论中存在分歧的话题，比较不同观点，并引用原始消息。', icon: '◇' },
]

/** 快捷提问只填入草稿，用户仍可编辑并决定何时发送。 */
function fillSuggestion(query: string): void {
  composer.value?.setDraft(query)
}

/** 导航完成后收起手机抽屉，待输入框启用再聚焦。 */
async function focusComposer(): Promise<void> {
  sidebarOpen.value = false
  await nextTick()
  if (!isMobile.value) composer.value?.focus()
}

/** 手机抽屉打开后把键盘焦点交给关闭按钮，避免停留在被遮住的主区。 */
watch(sidebarOpen, async (open) => {
  if (open && isMobile.value) {
    await nextTick()
    sidebarClose.value?.focus()
  }
})
/** 手动关闭导航才恢复开关焦点，选择范围完成后由输入框接管焦点。 */
function collapseSidebar(): void {
  // 手机抽屉关闭不改写桌面折叠偏好。
  if (!isMobile.value) sidebarCollapsed.value = true
  closeSidebar()
}
function closeSidebar(): void {
  sidebarOpen.value = false
  void nextTick(() => sidebarToggle.value?.focus())
}
// 手机抽屉是模态导航，Tab 在抽屉的可操作元素之间循环。
onKeyStroke('Tab', (event) => {
  if (!sidebarOpen.value || !isMobile.value) return
  const controls = Array.from(navigation.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? [])
  const current = controls.indexOf(document.activeElement as HTMLElement)
  const target = event.shiftKey ? current - 1 : current + 1
  if (target < 0 || target >= controls.length) {
    event.preventDefault()
    controls[event.shiftKey ? controls.length - 1 : 0]?.focus()
  }
})

/**
 * Header 只读摘要：读取当前 buffer 的 immutable scope（包括 legacy null 的
 * 「未标记范围」）；无 buffer 时投影 navigation selection。
 */
const currentScopeDisplay = computed(() => {
  if (currentBuffer.value) return describeScope(currentBuffer.value.scope, scopeStore.sessions)
  if (selectedSourceScope.value === null) return { label: '未选择范围', title: '未选择范围' }
  return describeScope(scopeStore.scope, scopeStore.sessions)
})

/** Composer 只在绑定合法 scope 的 buffer 上可用；unselected 与 legacy/未知历史都禁用。 */
const composerEnabled = computed(() => currentBuffer.value?.scope != null)

/** 刷新和前进/后退共用同一恢复路径，不产生新的历史记录。 */
async function restoreUrl(): Promise<void> {
  const conversationId = readConversationIdFromUrl()
  if (conversationId) {
    await handleOpen(conversationId, true)
    return
  }
  const generation = ++navigationGeneration
  navigationError.value = ''
  try {
    chat.clearDisplayed()
    const selection = readScopeFromUrl()
    scopeStore.select(selection)
    const scope = scopeStore.scope
    if (scope) chat.newChat(scope)
    await conversationsStore.refresh(selection)
  } catch (error) {
    // URL指向不存在的会话时保留错误和地址，便于用户纠正或后退。
    if (generation === navigationGeneration) navigationError.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(async () => {
  await scopeStore.load()
  if (scopeStore.catalogError) readinessText.value = `聊天范围加载失败：${scopeStore.catalogError}`
  await restoreUrl()
})
useEventListener(window, 'popstate', () => { void restoreUrl() })

onKeyStroke('Escape', (event) => {
  // 原生来源对话框自行处理Esc，不能顺带终止后台生成。
  if ((event.target as HTMLElement)?.closest('dialog')) return
  if (sidebarOpen.value) closeSidebar()
  else if (chat.activeStreamRequestId) void chat.stopCurrent()
})

async function handleSend(query: string, accepted: () => void): Promise<void> {
  // 请求处理中及当前回答生成中保留草稿，阻止重复提交。
  if (chat.busy || chat.activeStreamRequestId) return
  await chat.send(
    query,
    scopeStore.scope,
    () => {
      // 回答完成后的列表刷新失败也必须可见，不能留下未处理的 Promise。
      void conversationsStore.refresh(scopeStore.selectedSourceScope).catch((error: unknown) => {
        navigationError.value = error instanceof Error ? error.message : String(error)
      })
    },
    (conversationId) => {
      // 创建期间可能已切换范围，旧请求不能改写当前URL。
      if (chat.currentBuffer?.conversationId === conversationId) writeConversationIdToUrl(conversationId)
    },
    accepted,
  )
}

/** Source Scope 导航切换：先清主区与列表，再加载新范围；不自动打开其最近 conversation。 */
async function handleScopeSelect(selection: SelectedSourceScope): Promise<void> {
  if (navigationSelectionsEqual(selectedSourceScope.value, selection)) {
    await focusComposer()
    return
  }
  const generation = ++navigationGeneration
  navigationError.value = ''
  scopeStore.select(selection)
  chat.clearDisplayed()
  writeNavigationToUrl(null, selection)
  const scope = scopeStore.scope
  if (scope !== null) chat.newChat(scope)
  try {
    await conversationsStore.refresh(selection)
  } catch (error) {
    // 列表失败显式提示；已选择的范围仍可用于创建新对话。
    if (generation === navigationGeneration) navigationError.value = error instanceof Error ? error.message : String(error)
  }
  if (generation === navigationGeneration) await focusComposer()
}

async function openConversation(
  conversationId: string,
  options?: { markInterrupted?: boolean; fromHistory?: boolean },
): Promise<boolean> {
  const generation = ++navigationGeneration
  const previousSelection = selectedSourceScope.value
  const opened = await chat.openConversation(conversationId)
  if (!opened || generation !== navigationGeneration) return false
  if (options?.markInterrupted) chat.markInterrupted(conversationId)
  // 按 immutable scope 恢复合法导航；legacy null / multi / 未知 session 恢复为 null。
  const restored = scopeStore.restoreFromConversationScope(chat.currentBuffer?.scope ?? null)
  if (!options?.fromHistory) writeNavigationToUrl(conversationId, restored)
  if (!navigationSelectionsEqual(previousSelection, restored)) {
    await conversationsStore.refresh(restored)
  }
  return generation === navigationGeneration
}

/** 从侧栏打开失败时显示真实错误，保留当前对话供用户继续操作。 */
async function handleOpen(conversationId: string, fromHistory = false): Promise<void> {
  const generation = navigationGeneration + 1
  navigationError.value = ''
  try {
    if (await openConversation(conversationId, { fromHistory })) {
      sidebarOpen.value = false
      // 历史恢复保持原阅读位置，不主动唤起手机键盘。
      if (!fromHistory) await focusComposer()
    }
  } catch (error) {
    if (generation === navigationGeneration) navigationError.value = error instanceof Error ? error.message : String(error)
  }
}

function handleNewChat(): void {
  navigationGeneration += 1
  const scope = scopeStore.scope
  if (scope === null) return
  chat.newChat(scope)
  writeNavigationToUrl(null, selectedSourceScope.value)
  void focusComposer()
}

function handleDeleted(conversationId: string): void {
  navigationGeneration += 1
  if (chat.currentKey === conversationId) chat.closeBuffer(conversationId)
  writeNavigationToUrl(null, selectedSourceScope.value)
  const scope = scopeStore.scope
  if (scope !== null) chat.newChat(scope)
}
</script>

<template>
  <div class="chat-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed, 'sidebar-open': sidebarOpen }">
    <button v-if="sidebarOpen" class="sidebar-backdrop" tabindex="-1" aria-label="关闭导航" @click="closeSidebar" />
    <aside id="chat-navigation" ref="navigation" class="chat-navigation" aria-label="聊天导航" :role="sidebarOpen && isMobile ? 'dialog' : undefined" :aria-modal="sidebarOpen && isMobile ? true : undefined">
      <div class="sidebar-brand">
        <span class="brand-mark" aria-hidden="true">T</span>
        <span class="font-semibold">Trivae</span>
        <button ref="sidebarClose" class="icon-button ml-auto" aria-label="收起侧栏" title="收起侧栏" @click="collapseSidebar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16m7-11-3 3 3 3" /></svg>
        </button>
      </div>
      <SourceScopeSidebar @select="handleScopeSelect" />
      <ConversationSidebar @open="handleOpen" @new-chat="handleNewChat" @deleted="handleDeleted" />
      <div class="sidebar-footer"><span class="status-dot" />本地工作空间<span class="ml-auto">群聊知识助手</span></div>
    </aside>

    <main class="chat-main" :inert="sidebarOpen && isMobile">
      <header class="chat-header">
        <button ref="sidebarToggle" class="icon-button sidebar-toggle" aria-label="展开侧栏" aria-controls="chat-navigation" :aria-expanded="isMobile ? sidebarOpen : !sidebarCollapsed" @click="sidebarCollapsed = false; sidebarOpen = isMobile ? !sidebarOpen : false">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></svg>
        </button>
        <div class="header-identity"><span class="font-semibold">Trivae</span><span class="header-subtitle">群聊知识助手</span></div>
        <button class="scope-chip" data-testid="current-scope" :title="currentScopeDisplay.title" @click="sidebarCollapsed = false; sidebarOpen = isMobile">
          <span class="status-dot" /><span>{{ currentScopeDisplay.label }}</span><span aria-hidden="true">⌄</span>
        </button>
      </header>

      <div ref="scrollContainer" class="chat-scroll">
        <div class="conversation-content" :class="{ 'is-empty': !currentBuffer?.items.length }">
          <div v-if="readinessText || navigationError || chat.sendingError" class="chat-error" role="alert">
            {{ readinessText || navigationError || chat.sendingError }}
          </div>
          <div v-if="currentBuffer && currentBuffer.scope === null" class="read-only-hint" data-testid="read-only-hint">
            此对话未标记聊天范围；内容可回放，但不能继续发送。
          </div>

          <div v-if="!currentBuffer" class="welcome" data-testid="unselected-state">
            <div class="welcome-mark" aria-hidden="true">T</div>
            <h1>从群聊中，找到答案</h1>
            <p>总结讨论、查找信息、梳理观点。每个回答都有消息来源可查。</p>
            <button class="welcome-start" data-testid="welcome-start" @click="handleScopeSelect({ kind: 'all' })">从全部群聊开始 <span aria-hidden="true">→</span></button>
            <p class="welcome-note">也可以在侧栏选择一个聊天范围</p>
          </div>
          <div v-else-if="currentBuffer.items.length === 0 && currentBuffer.scope !== null" class="welcome" data-testid="draft-state">
            <div class="welcome-mark" aria-hidden="true">T</div>
            <h1>今天想了解什么？</h1>
            <p>基于「{{ currentScopeDisplay.label }}」的聊天记录，为你查找和整理。</p>
            <div class="suggestions">
              <button v-for="suggestion in suggestions" :key="suggestion.title" class="suggestion" @click="fillSuggestion(suggestion.query)">
                <span class="suggestion-icon" aria-hidden="true">{{ suggestion.icon }}</span>
                <span>{{ suggestion.title }}</span><span class="suggestion-arrow" aria-hidden="true">↗</span>
              </button>
            </div>
          </div>

          <template v-for="item in currentBuffer?.items ?? []" :key="item.id">
            <div v-if="item.role === 'user'" class="user-turn">
              <div class="user-bubble">{{ item.content }}</div>
            </div>
            <AssistantTurn v-else :item="item" :conversation-id="currentBuffer?.conversationId ?? null" />
          </template>
        </div>
        <div v-if="!following" class="follow-tail">
          <button class="follow-tail-button" aria-label="回到最新消息" @click="scrollToBottom">↓ 回到最新</button>
        </div>
      </div>

      <ChatComposer ref="composer" :context-key="currentBuffer" :disabled="!composerEnabled" :busy="chat.busy" :running="chat.activeStreamRequestId !== null" @send="handleSend" @stop="chat.stopCurrent()" />
    </main>
  </div>
</template>
