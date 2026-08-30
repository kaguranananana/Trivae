<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'
import { onKeyStroke } from '@vueuse/core'
import AssistantTurn from '@/components/chat/AssistantTurn.vue'
import ChatComposer from '@/components/composer/ChatComposer.vue'
import ConversationSidebar from '@/components/sidebar/ConversationSidebar.vue'
import SourceScopeSidebar from '@/components/sidebar/SourceScopeSidebar.vue'
import { useFollowTail } from '@/composables/useFollowTail'
import { describeScope, navigationSelectionsEqual, type SelectedSourceScope } from '@/utils/scope'
import { readConversationIdFromUrl, writeConversationIdToUrl } from '@/utils/url'

const chat = useChatStore()
const conversationsStore = useConversationsStore()
const scopeStore = useScopeStore()
const { currentBuffer, currentKey } = storeToRefs(chat)
const { selectedSourceScope } = storeToRefs(scopeStore)

const scrollContainer = ref<HTMLElement | null>(null)
const { following, scrollToBottom, onContentMutated } = useFollowTail(scrollContainer)

const itemsEnd = computed(() => currentBuffer.value?.items.length ?? 0)
watch(itemsEnd, () => onContentMutated())

watch(
  () =>
    currentBuffer.value?.items
      .map((item) => (item.role === 'assistant' ? `${item.status}|${item.answer.length}|${item.blocks.length}` : ''))
      .join('#'),
  () => onContentMutated(),
)

const readinessText = ref('')

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
const composerEnabled = computed(() => currentKey.value !== null && currentBuffer.value?.scope != null)

onMounted(async () => {
  await scopeStore.load()
  if (scopeStore.catalogError) {
    readinessText.value = `聊天范围加载失败：${scopeStore.catalogError}`
  }
  // 刷新恢复：先读 URL conversation detail、恢复合法 navigation scope，
  // 再请求对应 scope 的列表；无 conversation id 时保持未选择，不自动打开最近项。
  const conversationId = readConversationIdFromUrl()
  if (conversationId) {
    try {
      await openConversation(conversationId, { markInterrupted: true })
      return
    } catch (error) {
      readinessText.value = error instanceof Error ? error.message : String(error)
      writeConversationIdToUrl(null)
    }
  }
  await conversationsStore.refresh(scopeStore.selectedSourceScope)
})

onKeyStroke('Escape', () => {
  if (chat.activeStreamRequestId) void chat.stopCurrent()
})

async function handleSend(query: string): Promise<void> {
  await chat.send(
    query,
    scopeStore.scope,
    () => {
      void conversationsStore.refresh(scopeStore.selectedSourceScope)
    },
    (conversationId) => writeConversationIdToUrl(conversationId),
  )
}

/** Source Scope 导航切换：先清主区与列表，再加载新范围；不自动打开其最近 conversation。 */
async function handleScopeSelect(selection: SelectedSourceScope): Promise<void> {
  if (navigationSelectionsEqual(selectedSourceScope.value, selection)) return
  scopeStore.select(selection)
  chat.clearDisplayed()
  writeConversationIdToUrl(null)
  await conversationsStore.refresh(selection)
  // 进入新范围的 draft 空状态；A 的后台 stream 继续写 A buffer。
  const scope = scopeStore.scope
  if (scope !== null) chat.newChat(scope)
}

async function openConversation(
  conversationId: string,
  options?: { markInterrupted?: boolean },
): Promise<void> {
  const previousSelection = selectedSourceScope.value
  await chat.openConversation(conversationId)
  if (options?.markInterrupted) chat.markInterrupted(conversationId)
  // 按 immutable scope 恢复合法导航；legacy null / multi / 未知 session 恢复为 null。
  const restored = scopeStore.restoreFromConversationScope(chat.currentBuffer?.scope ?? null)
  writeConversationIdToUrl(conversationId)
  if (!navigationSelectionsEqual(previousSelection, restored)) {
    await conversationsStore.refresh(restored)
  }
}

function handleNewChat(): void {
  const scope = scopeStore.scope
  if (scope === null) return
  chat.newChat(scope)
  writeConversationIdToUrl(null)
}

function handleDeleted(conversationId: string): void {
  if (chat.currentKey === conversationId) chat.closeBuffer(conversationId)
  writeConversationIdToUrl(null)
  const scope = scopeStore.scope
  if (scope !== null) chat.newChat(scope)
}
</script>

<template>
  <div class="flex h-full">
    <SourceScopeSidebar @select="handleScopeSelect" />
    <ConversationSidebar @open="openConversation" @new-chat="handleNewChat" @deleted="handleDeleted" />

    <main class="flex min-w-0 flex-1 flex-col">
      <header class="flex items-center justify-between border-b border-default px-6 py-3">
        <div class="flex items-baseline gap-3">
          <h1 class="text-lg font-semibold">Trivae</h1>
          <span class="text-xs text-dimmed">群聊情报分析 · 本地 Web</span>
        </div>
        <div class="flex items-center gap-3 text-xs" data-testid="current-scope">
          <span class="text-dimmed">当前范围:</span>
          <span class="font-medium text-default" :title="currentScopeDisplay.title">
            {{ currentScopeDisplay.label }}
          </span>
        </div>
      </header>

      <div ref="scrollContainer" class="relative min-h-0 flex-1 overflow-y-auto">
        <div class="mx-auto max-w-3xl px-4 py-6">
          <div v-if="readinessText" class="mb-4 rounded-md bg-error/10 p-3 text-xs text-error">
            {{ readinessText }}
          </div>

          <div
            v-if="currentBuffer && currentBuffer.scope === null"
            class="mb-4 rounded-md bg-default p-3 text-xs text-dimmed"
            data-testid="read-only-hint"
          >
            此对话未标记聊天范围；内容可回放，但不能继续发送。
          </div>

          <div v-if="!currentBuffer" class="mt-24 text-center text-dimmed" data-testid="unselected-state">
            <p class="text-2xl font-semibold text-default">选择一个聊天范围</p>
            <p class="mt-2 text-sm">选择一个聊天范围以查看 AI 对话；范围决定检索边界。</p>
          </div>
          <div v-else-if="currentBuffer.items.length === 0" class="mt-24 text-center text-dimmed">
            <p class="text-2xl font-semibold text-default">向 Trivae 提问</p>
            <p class="mt-2 text-sm">基于已导入的聊天记录检索、分析与回答，过程透明可追溯。</p>
          </div>

          <template v-for="item in currentBuffer?.items ?? []" :key="item.id">
            <div v-if="item.role === 'user'" class="my-6 flex justify-end">
              <div class="max-w-[80%] rounded-2xl rounded-br-sm bg-primary/10 px-4 py-2.5 text-sm whitespace-pre-wrap">
                {{ item.content }}
              </div>
            </div>
            <AssistantTurn v-else :item="item" :conversation-id="currentBuffer?.conversationId ?? null" />
          </template>
        </div>

        <div
          v-if="!following"
          class="pointer-events-auto sticky bottom-4 flex justify-center"
        >
          <button
            class="rounded-full border border-default bg-default px-3 py-1 text-xs shadow hover:bg-elevated"
            @click="scrollToBottom"
          >
            ↓ 回到最新
          </button>
        </div>
      </div>

      <ChatComposer
        :disabled="!composerEnabled"
        :running="chat.activeStreamRequestId !== null"
        @send="handleSend"
        @stop="chat.stopCurrent()"
      />
    </main>
  </div>
</template>
