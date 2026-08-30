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
import { useFollowTail } from '@/composables/useFollowTail'
import { describeScope } from '@/utils/scope'

const chat = useChatStore()
const conversationsStore = useConversationsStore()
const scopeStore = useScopeStore()
const { currentBuffer, currentKey } = storeToRefs(chat)

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
const currentScopeDisplay = computed(() => {
  // currentBuffer 存在时必须保留 null；它代表 legacy 未标记范围，而不是 all。
  const actualScope = currentBuffer.value ? currentBuffer.value.scope : scopeStore.scope()
  return describeScope(actualScope, scopeStore.sessions)
})
const unknownSelectedSessionIds = computed(() => {
  const catalogIds = new Set(scopeStore.sessions.map((session) => session.session_id))
  return scopeStore.selectedSessionIds.filter((sessionId) => !catalogIds.has(sessionId))
})
const selectedSessionIdsModel = computed({
  // 多选框通过 computed setter 统一进入 store action，恢复显示与用户导航共享同一规范化逻辑。
  get: (): string[] => scopeStore.selectedSessionIds,
  set: (sessionIds: string[]) => {
    scopeStore.selectSessions(sessionIds)
    navigateToSelectedScope()
  },
})

onMounted(async () => {
  try {
    await Promise.all([conversationsStore.refresh(), scopeStore.load()])
  } catch (error) {
    readinessText.value = error instanceof Error ? error.message : String(error)
  }
  // 刷新恢复：打开最近 conversation；此时如有运行中的请求无法重新 attach，
  // 第一阶段显示 execution interrupted。
  const latest = conversationsStore.conversations[0]
  if (latest) {
    try {
      await chat.openConversation(latest.conversation_id)
      chat.markInterrupted(latest.conversation_id)
      scopeStore.restoreFromScope(chat.currentBuffer?.scope ?? null)
    } catch (error) {
      readinessText.value = error instanceof Error ? error.message : String(error)
      chat.newChat(scopeStore.scope())
    }
  } else {
    chat.newChat(scopeStore.scope())
  }
})

onKeyStroke('Escape', () => {
  if (chat.activeStreamRequestId) void chat.stopCurrent()
})

async function handleSend(query: string): Promise<void> {
  await chat.send(query, scopeStore.scope(), () => {
    void conversationsStore.refresh()
  })
}

/** selector 变化后立即进入对应 draft，避免旧 Conversation 与新范围同时显示。 */
function navigateToSelectedScope(): void {
  chat.newChat(scopeStore.scope())
}

function handleModeChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  scopeStore.selectMode(value === 'sessions' ? 'sessions' : 'all')
  navigateToSelectedScope()
}
</script>

<template>
  <div class="flex h-full">
    <ConversationSidebar />

    <main class="flex min-w-0 flex-1 flex-col">
      <header class="flex items-center justify-between border-b border-default px-6 py-3">
        <div class="flex items-baseline gap-3">
          <h1 class="text-lg font-semibold">Trivae</h1>
          <span class="text-xs text-dimmed">群聊情报分析 · 本地 Web</span>
        </div>
        <div class="flex items-center gap-3 text-xs">
          <div class="flex items-center gap-1.5" data-testid="current-scope">
            <span class="text-dimmed">当前范围:</span>
            <span class="font-medium text-default" :title="currentScopeDisplay.title">
              {{ currentScopeDisplay.label }}
            </span>
          </div>
          <span class="h-4 w-px bg-default" aria-hidden="true"></span>
          <span class="text-dimmed">切换范围:</span>
          <select
            :value="scopeStore.mode"
            class="rounded border border-default bg-default px-2 py-1"
            aria-label="切换范围模式"
            @change="handleModeChange"
          >
            <option value="all">全部群聊</option>
            <option value="sessions">指定群聊</option>
          </select>
          <select
            v-if="scopeStore.mode === 'sessions'"
            v-model="selectedSessionIdsModel"
            multiple
            size="1"
            class="max-w-64 rounded border border-default bg-default px-2 py-1"
            aria-label="选择群聊"
          >
            <option v-for="session in scopeStore.sessions" :key="session.session_id" :value="session.session_id">
              {{ session.name }}
            </option>
            <option v-for="sessionId in unknownSelectedSessionIds" :key="sessionId" :value="sessionId">
              {{ sessionId }}（目录中不存在）
            </option>
          </select>
        </div>
      </header>

      <div ref="scrollContainer" class="relative min-h-0 flex-1 overflow-y-auto">
        <div class="mx-auto max-w-3xl px-4 py-6">
          <div v-if="readinessText" class="mb-4 rounded-md bg-error/10 p-3 text-xs text-error">
            {{ readinessText }}
          </div>

          <div v-if="!currentBuffer || currentBuffer.items.length === 0" class="mt-24 text-center text-dimmed">
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
        :disabled="currentKey === null"
        :running="chat.activeStreamRequestId !== null"
        @send="handleSend"
        @stop="chat.stopCurrent()"
      />
    </main>
  </div>
</template>
