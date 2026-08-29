<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SourceItem } from '@/types/contracts'

const props = defineProps<{ sources: SourceItem[] }>()
// 展开状态属于当前 SourcesBlock 实例，避免不同回答或历史 replay 共享 UI 状态。
const expanded = ref(false)

function formatTimestamp(timestampMs?: number): string {
  if (!timestampMs) return ''
  return new Date(timestampMs).toLocaleString('zh-CN', { hour12: false })
}

const label = computed(() => `Sources · ${props.sources.length}`)

function toggleExpanded(): void {
  // 只切换展示层状态，不修改后端 Sources 数据和 Evidence 顺序。
  expanded.value = !expanded.value
}
</script>

<template>
  <template v-if="sources.length > 0">
    <div class="mt-4 rounded-xl border border-default bg-elevated/30 p-3">
      <button
        type="button"
        class="flex w-full items-center gap-2 text-left text-xs"
        :aria-expanded="expanded"
        @click="toggleExpanded"
      >
        <span class="font-mono">{{ expanded ? '▼ ' : '▶ ' }}</span>
        <span class="font-semibold text-default">{{ label }}</span>
      </button>

      <div v-if="expanded" class="mt-2 border-t border-default pt-2">
        <ol class="space-y-2">
          <li v-for="item in sources" :key="item.index" class="text-xs">
            <div class="flex flex-wrap items-center gap-x-3">
              <span class="font-mono text-dimmed">[{{ item.index }}]</span>
              <template v-if="item.kind === 'message' && item.snapshot">
                <span class="font-semibold text-default">{{ item.snapshot.author_display ?? '未知发送者' }}</span>
                <span class="text-dimmed">{{ item.snapshot.session_display }}</span>
                <span class="text-dimmed">{{ formatTimestamp(item.snapshot.timestamp_ms) }}</span>
              </template>
              <template v-else-if="item.kind === 'structured'">
                <span class="font-mono text-default">{{ item.locator_kind }}:{{ item.locator }}</span>
              </template>
              <template v-else>
                <span class="text-dimmed">来源不可用</span>
              </template>
              <span v-for="relation in item.relations" :key="relation" class="rounded bg-elevated px-1 text-[10px] text-dimmed">
                {{ relation }}
              </span>
            </div>
            <blockquote v-if="item.snapshot" class="mt-1 border-l-2 border-default pl-2 text-dimmed">
              “{{ item.snapshot.excerpt }}”<span v-if="item.snapshot.excerpt_truncated">…</span>
            </blockquote>
            <div v-else-if="item.kind === 'structured'" class="mt-1 font-mono break-all text-dimmed">
              {{ JSON.stringify(item.value) }}
            </div>
          </li>
        </ol>
      </div>
    </div>
  </template>
</template>
