<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'
import { scopeKey } from '@/utils/scope'

const chat = useChatStore()
const conversationsStore = useConversationsStore()
const scopeStore = useScopeStore()
const { currentBuffer, currentKey } = storeToRefs(chat)
const { groups } = storeToRefs(conversationsStore)
const currentScopeKey = computed(() => currentBuffer.value ? scopeKey(currentBuffer.value.scope) : null)

const renaming = ref<string | null>(null)
const renameTitle = ref('')

async function open(conversationId: string): Promise<void> {
  await chat.openConversation(conversationId)
  // 正式 Conversation 的 immutable scope 打开后，显式恢复 selector；不使用双向 watch。
  scopeStore.restoreFromScope(chat.currentBuffer?.scope ?? null)
}

function newChat(): void {
  chat.newChat(scopeStore.scope())
}

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
  if (currentKey.value === conversationId) {
    chat.closeBuffer(conversationId)
    chat.newChat(scopeStore.scope())
  }
}

function startRename(conversationId: string, title: string): void {
  renaming.value = conversationId
  renameTitle.value = title
}
</script>

<template>
  <aside class="flex w-64 flex-col border-r border-default bg-elevated/30">
    <div class="p-3">
      <button
        class="w-full rounded-lg border border-default px-3 py-2 text-sm font-medium hover:bg-elevated"
        @click="newChat"
      >
        + New Chat
      </button>
    </div>

    <nav class="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
      <section v-for="group in groups" :key="group.key" class="mb-4" :data-scope-key="group.key">
        <div
          class="rounded-md px-2 py-1.5 text-xs font-semibold text-default"
          :class="{ 'bg-primary/8 text-primary': currentScopeKey === group.key }"
          :title="group.title"
        >
          {{ group.label }}
        </div>
        <div v-for="dateGroup in group.dateGroups" :key="dateGroup.label" class="mt-1">
          <div class="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-dimmed">
            {{ dateGroup.label }}
          </div>
          <div
            v-for="conversation in dateGroup.conversations"
            :key="conversation.conversation_id"
            class="group cursor-pointer rounded-lg px-2 py-1.5 hover:bg-elevated"
            :class="{ 'bg-primary/10': currentKey === conversation.conversation_id }"
            @click="open(conversation.conversation_id)"
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
      </section>

      <div v-if="conversationsStore.loaded && conversationsStore.conversations.length === 0" class="px-2 text-xs text-dimmed">
        还没有 AI 对话记录。
      </div>
    </nav>

    <div class="border-t border-default p-3 text-[11px] text-dimmed">
      <div>Source Session ≠ AI Conversation</div>
      <div>Scope 决定检索范围；对话独立于会话。</div>
    </div>
  </aside>
</template>
