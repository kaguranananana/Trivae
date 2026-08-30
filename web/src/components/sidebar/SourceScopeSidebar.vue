<script setup lang="ts">
/**
 * Source Scope 一级导航：数据只来自 GET /api/source-sessions。
 * 「全部范围」+ 每个真实 Source Session；高亮当前 navigation selection。
 * Source Session 决定 Retrieval 范围（ExecutionScope），与 AI Conversation 是不同概念。
 */
import { storeToRefs } from 'pinia'
import { useScopeStore } from '@/stores/scope'
import { navigationSelectionsEqual, type SelectedSourceScope } from '@/utils/scope'

const emit = defineEmits<{
  select: [selection: SelectedSourceScope]
}>()

const scopeStore = useScopeStore()
const { sessions, selectedSourceScope, catalogLoading, catalogError } = storeToRefs(scopeStore)

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
  <aside class="flex w-52 flex-col border-r border-default bg-elevated/30" data-testid="source-scope-sidebar">
    <div class="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-dimmed">
      聊天范围
    </div>
    <nav class="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
      <button
        class="w-full rounded-lg px-2 py-1.5 text-left text-sm text-default hover:bg-elevated"
        :class="{ 'bg-primary/10 font-medium text-primary': isCurrent({ kind: 'all' }) }"
        data-testid="scope-all"
        @click="selectAll"
      >
        全部范围
      </button>
      <button
        v-for="session in sessions"
        :key="session.session_id"
        class="w-full truncate rounded-lg px-2 py-1.5 text-left text-sm text-default hover:bg-elevated"
        :class="{
          'bg-primary/10 font-medium text-primary': isCurrent({ kind: 'session', sessionId: session.session_id }),
        }"
        :title="session.name"
        :data-testid="`scope-session-${session.session_id}`"
        @click="selectSession(session.session_id)"
      >
        {{ session.name }}
      </button>

      <div v-if="catalogLoading" class="px-2 py-1.5 text-xs text-dimmed" data-testid="scope-loading">
        正在加载聊天范围…
      </div>
      <div
        v-else-if="catalogError"
        class="px-2 py-1.5 text-xs text-error"
        data-testid="scope-error"
      >
        聊天范围加载失败：{{ catalogError }}
      </div>
    </nav>

    <div class="border-t border-default p-3 text-[11px] text-dimmed">
      <div>Source Session ≠ AI Conversation</div>
      <div>范围决定检索边界；先选范围，再查看对话。</div>
    </div>
  </aside>
</template>
