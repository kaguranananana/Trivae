<script setup lang="ts">
/**
 * Source Scope 一级导航：数据只来自 GET /api/source-sessions。
 * 「全部范围」+ 每个真实 Source Session；高亮当前 navigation selection。
 * Source Session 决定 Retrieval 范围（ExecutionScope），与 AI Conversation 是不同概念。
 */
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useScopeStore } from '@/stores/scope'
import { navigationSelectionsEqual, type SelectedSourceScope } from '@/utils/scope'

const emit = defineEmits<{
  select: [selection: SelectedSourceScope]
}>()

const scopeStore = useScopeStore()
const { sessions, selectedSourceScope, catalogLoading, catalogError } = storeToRefs(scopeStore)

const search = ref('')
/** 搜索仅影响范围列表展示，选中范围与后端检索边界保持原契约。 */
const filteredSessions = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return sessions.value.filter((session) => session.name.toLocaleLowerCase().includes(query))
})

function selectAll(): void {
  emit('select', { kind: 'all' })
}

function selectSession(sessionId: string): void {
  emit('select', { kind: 'session', sessionId })
}

function isCurrent(selection: SelectedSourceScope): boolean {
  return navigationSelectionsEqual(selectedSourceScope.value, selection)
}
</script>

<template>
  <section class="scope-section" data-testid="source-scope-sidebar" aria-label="聊天范围">
    <div class="sidebar-section-heading"><span>聊天范围</span><span>{{ sessions.length }}</span></div>
    <label class="sidebar-search"><span aria-hidden="true">⌕</span><input v-model="search" aria-label="搜索聊天范围" placeholder="搜索群聊" /></label>
    <nav class="scope-list" aria-label="选择聊天范围">
      <button class="scope-option" :class="{ selected: isCurrent({ kind: 'all' }) }" :aria-pressed="isCurrent({ kind: 'all' })" data-testid="scope-all" @click="selectAll">
        <span class="scope-option-icon" aria-hidden="true">◎</span><span>全部范围</span><span v-if="isCurrent({ kind: 'all' })" class="ml-auto" aria-hidden="true">✓</span>
      </button>
      <button v-for="session in filteredSessions" :key="session.session_id" class="scope-option" :class="{ selected: isCurrent({ kind: 'session', sessionId: session.session_id }) }" :aria-pressed="isCurrent({ kind: 'session', sessionId: session.session_id })" :title="session.name" :data-testid="`scope-session-${session.session_id}`" @click="selectSession(session.session_id)">
        <span class="scope-option-icon" aria-hidden="true">#</span><span class="truncate">{{ session.name }}</span>
      </button>
      <div v-if="catalogLoading" class="sidebar-hint" data-testid="scope-loading">正在加载聊天范围…</div>
      <div v-else-if="catalogError" class="sidebar-hint text-error" role="alert" data-testid="scope-error">聊天范围加载失败：{{ catalogError }}</div>
      <div v-else-if="search.trim() && !filteredSessions.length" class="sidebar-hint">没有匹配的群聊</div>
    </nav>
  </section>
</template>
