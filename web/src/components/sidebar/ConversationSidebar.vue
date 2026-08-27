<script setup lang="ts">
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useScopeStore } from '@/stores/scope'

const chat = useChatStore()
const conversationsStore = useConversationsStore()
const scopeStore = useScopeStore()
const { currentKey } = storeToRefs(chat)
const { groups } = storeToRefs(conversationsStore)

const renaming = ref<string | null>(null)
const renameTitle = ref('')

function open(conversationId: string): void {
  void chat.openConversation(conversationId)
}

function newChat(): void {
  chat.newChat(scopeStore.scope())
}

async function confirmRename(conversationId: string): Promise<void> {
  const title = renameTitle.value.trim()
  if (title) {
    try {
      await conversationsStore.rename(conversationId, title)
    } catch {
      // rename 失败保持在编辑态，用户可重试
    }
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
      <div v-for="group in groups" :key="group.label" class="mb-4">
        <div class="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-dimmed">
          {{ group.label }}
        </div>
        <div
          v-for="conversation in group.conversations"
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
