<script setup lang="ts">
/**
 * AI Conversation 侧栏：只展示当前 Source Scope 下的对话（today/yesterday/earlier）。
 * 列表已由后端按 scope 过滤；这里不再做 scope 分组或客户端过滤。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { watchDebounced } from '@vueuse/core'
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
const { dateGroups, conversations, loaded, loading, query, error, hasMore } = storeToRefs(conversationsStore)
const { scope, selectedSourceScope } = storeToRefs(scopeStore)

/** 未选择 Source Scope 时列表区显示引导，而不是空的对话列表。 */
const hasSelection = computed(() => selectedSourceScope.value !== null)
const composerReady = computed(() => scope.value !== null)

const renaming = ref<string | null>(null)
const renameTitle = ref('')
const renameInput = ref<HTMLInputElement[] | null>(null)
const renameSaving = ref(false)
const search = ref('')
const actionError = ref('')
// 输入停顿后请求正式全文搜索，范围/刷新后的查询条件也同步回输入框。
watch(query, (value) => { search.value = value })
watchDebounced(search, (value) => {
  if (value.trim() !== query.value) void conversationsStore.search(value)
}, { debounce: 250 })
const filteredGroups = dateGroups

async function confirmRename(conversationId: string): Promise<void> {
  // Enter 成功后再触发 blur 时不重复请求。
  if (renaming.value !== conversationId || renameSaving.value) return
  const title = renameTitle.value.trim()
  if (!title) {
    actionError.value = '对话名称不能为空'
    return
  }
  actionError.value = ''
  renameSaving.value = true
  try {
    await conversationsStore.rename(conversationId, title)
    renaming.value = null
  } catch (error) {
    // 请求失败保留编辑状态，并把具体错误展示给用户。
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    renameSaving.value = false
  }
}

async function remove(conversationId: string): Promise<void> {
  if (!window.confirm('删除该 AI 对话？不会影响任何群聊记录。')) return
  actionError.value = ''
  try {
    await conversationsStore.remove(conversationId)
    if (currentKey.value === conversationId) emit('deleted', conversationId)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

function startRename(conversationId: string, title: string): void {
  actionError.value = ''
  renaming.value = conversationId
  renameTitle.value = title
  // 列表内 ref 是数组，编辑框渲染后聚焦并选中名称。
  void nextTick(() => {
    renameInput.value?.[0]?.focus()
    renameInput.value?.[0]?.select()
  })
}
</script>

<template>
  <section class="history-section" data-testid="conversation-sidebar" aria-label="AI 对话">
    <div class="new-chat-wrap"><button class="new-chat-button" :disabled="!composerReady" data-testid="new-chat" @click="emit('newChat')"><span aria-hidden="true">＋</span> 新建对话<span class="ml-auto" aria-hidden="true">↗</span></button></div>
    <div class="sidebar-section-heading">你的对话</div>
    <label v-if="hasSelection" class="sidebar-search"><span aria-hidden="true">⌕</span><input v-model="search" aria-label="搜索当前范围内的对话" placeholder="搜索全部历史标题和正文…" autocomplete="off" /></label>
    <div v-if="actionError || error" class="sidebar-hint text-error" role="alert">{{ actionError || error }}<button v-if="error" class="retry-list" @click="conversationsStore.search(search)">重新加载</button></div>
    <nav class="history-list" aria-label="历史对话">
      <template v-if="hasSelection">
        <div v-for="dateGroup in filteredGroups" :key="dateGroup.label" class="date-group" data-testid="date-group">
          <div class="date-label">{{ dateGroup.label }}</div>
          <div v-for="conversation in dateGroup.conversations" :key="conversation.conversation_id" class="conversation-row" :class="{ selected: currentKey === conversation.conversation_id }" :data-testid="`conversation-${conversation.conversation_id}`" @click="emit('open', conversation.conversation_id)">
            <input v-if="renaming === conversation.conversation_id" ref="renameInput" v-model="renameTitle" class="rename-input" aria-label="对话名称" @keyup.enter="confirmRename(conversation.conversation_id)" @keyup.esc="renaming = null" @blur="confirmRename(conversation.conversation_id)" @click.stop />
            <template v-else>
              <button class="conversation-link" :aria-current="currentKey === conversation.conversation_id ? 'true' : undefined" :title="conversation.title" @click.stop="emit('open', conversation.conversation_id)">
                <span class="truncate">{{ conversation.title }}</span><span class="conversation-preview truncate">{{ conversation.preview ?? '（空对话）' }}</span>
              </button>
              <div class="conversation-actions">
                <button aria-label="重命名" title="重命名" @click.stop="startRename(conversation.conversation_id, conversation.title)">重命名</button>
                <button aria-label="删除" title="删除" @click.stop="remove(conversation.conversation_id)">删除</button>
              </div>
            </template>
          </div>
        </div>
        <div v-if="loaded && conversations.length === 0 && !query" class="sidebar-hint" data-testid="empty-list">该范围下还没有 AI 对话记录。</div>
        <div v-else-if="loading" class="sidebar-hint" data-testid="list-loading">加载中…</div>
        <div v-else-if="query && !filteredGroups.length && !loading && !error" class="sidebar-hint">没有匹配的对话</div>
        <button v-if="hasMore" class="load-more" :disabled="loading" @click="conversationsStore.loadMore()">{{ loading ? '加载中…' : '加载更多对话' }}</button>
      </template>
      <div v-else class="sidebar-hint" data-testid="unselected-hint">选择一个聊天范围以查看 AI 对话。</div>
    </nav>
  </section>
</template>
