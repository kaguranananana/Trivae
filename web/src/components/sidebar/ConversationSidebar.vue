<script setup lang="ts">
/**
 * AI Conversation 侧栏：只展示当前 Source Scope 下的对话（today/yesterday/earlier）。
 * 列表已由后端按 scope 过滤；这里不再做 scope 分组或客户端过滤。
 */
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'

const emit = defineEmits<{
  open: [conversationId: string]
  newChat: []
  deleted: [conversationId: string]
}>()

const chat = useChatStore()
const conversationsStore = useConversationsStore()
const scopeStore = useScopeStore()
const { currentKey } = storeToRefs(chat)
const { dateGroups, conversations, loaded, loading } = storeToRefs(conversationsStore)
const { scope, selectedSourceScope } = storeToRefs(scopeStore)

/** 未选择 Source Scope 时列表区显示引导，而不是空的对话列表。 */
const hasSelection = computed(() => selectedSourceScope.value !== null)
const composerReady = computed(() => scope.value !== null)

const renaming = ref<string | null>(null)
const renameTitle = ref('')

async function confirmRename(conversationId: string): Promise<void> {
  const title = renameTitle.value.trim()
  if (title) {
    // 请求失败时让异常显式交给 Vue error handler，同时保留编辑态供用户重试。
    await conversationsStore.rename(conversationId, title)
  }
  renaming.value = null
}

async function remove(conversationId: string): Promise<void> {
  if (!window.confirm('删除该 AI 对话？不会影响任何群聊记录。')) return
  await conversationsStore.remove(conversationId)
  if (currentKey.value === conversationId) emit('deleted', conversationId)
}

function startRename(conversationId: string, title: string): void {
  renaming.value = conversationId
  renameTitle.value = title
}
</script>

<template>
  <aside class="flex w-64 flex-col border-r border-default bg-elevated/30" data-testid="conversation-sidebar">
    <div class="p-3">
      <button
        class="w-full rounded-lg border border-default px-3 py-2 text-sm font-medium hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!composerReady"
        data-testid="new-chat"
        @click="emit('newChat')"
      >
        + New Chat
      </button>
    </div>

    <nav class="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
      <template v-if="hasSelection">
        <div v-for="dateGroup in dateGroups" :key="dateGroup.label" class="mb-3" data-testid="date-group">
          <div class="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-dimmed">
            {{ dateGroup.label }}
          </div>
          <div
            v-for="conversation in dateGroup.conversations"
            :key="conversation.conversation_id"
            class="group cursor-pointer rounded-lg px-2 py-1.5 hover:bg-elevated"
            :class="{ 'bg-primary/10': currentKey === conversation.conversation_id }"
            :data-testid="`conversation-${conversation.conversation_id}`"
            @click="emit('open', conversation.conversation_id)"
          >
            <template v-if="renaming === conversation.conversation_id">
              <input
                v-model="renameTitle"
                class="w-full rounded border border-default bg-default px-1 py-0.5 text-xs"
                @keyup.enter="confirmRename(conversation.conversation_id)"
                @blur="confirmRename(conversation.conversation_id)"
                @click.stop
              />
            </template>
            <template v-else>
              <div class="truncate text-xs font-medium text-default" :title="conversation.title">
                {{ conversation.title }}
              </div>
              <div class="truncate text-[11px] text-dimmed" :title="conversation.preview ?? ''">
                {{ conversation.preview ?? '（空对话）' }}
              </div>
              <div class="mt-0.5 hidden gap-1 group-hover:flex">
                <button
                  class="rounded px-1 text-[10px] text-dimmed hover:bg-default hover:text-default"
                  @click.stop="startRename(conversation.conversation_id, conversation.title)"
                >
                  重命名
                </button>
                <button
                  class="rounded px-1 text-[10px] text-dimmed hover:bg-error hover:text-default"
                  @click.stop="remove(conversation.conversation_id)"
                >
                  删除
                </button>
              </div>
            </template>
          </div>
        </div>

        <div v-if="loaded && conversations.length === 0" class="px-2 text-xs text-dimmed" data-testid="empty-list">
          该范围下还没有 AI 对话记录。
        </div>
        <div v-else-if="loading" class="px-2 text-xs text-dimmed" data-testid="list-loading">加载中…</div>
      </template>
      <div v-else class="px-2 py-1.5 text-xs text-dimmed" data-testid="unselected-hint">
        选择一个聊天范围以查看 AI 对话。
      </div>
    </nav>

    <div class="border-t border-default p-3 text-[11px] text-dimmed">
      <div>Scope 决定检索范围；对话独立于会话。</div>
    </div>
  </aside>
</template>
