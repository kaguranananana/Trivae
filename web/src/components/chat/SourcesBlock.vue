<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SourceItem } from '@/types/contracts'

const props = defineProps<{ sources: SourceItem[] }>()
// 展开状态属于当前 SourcesBlock 实例，避免不同回答或历史 replay 共享 UI 状态。
const expanded = ref(false)

function formatTimestamp(timestampMs?: number | null): string {
  if (timestampMs === null || timestampMs === undefined) return '未知'
  return new Date(timestampMs).toLocaleString('zh-CN', { hour12: false })
}

function sourceFilename(path: string): string {
  // 文件名与 record index 足以定位导出记录，不把本地目录占据来源面板。
  return path.split(/[\\/]/).pop() ?? path
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
                <span class="text-dimmed">{{ item.snapshot.forward ? '转发到本群：' : '' }}{{ formatTimestamp(item.snapshot.timestamp_ms) }}</span>
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
            <div v-if="item.snapshot?.forward" class="mt-1 space-y-1 break-all text-dimmed">
              <p>原始发送：{{ formatTimestamp(item.snapshot.forward.original_timestamp) }}</p>
              <p>内部消息 ID：{{ item.snapshot.source_message_id ?? '未知' }} · 发送者 ID：{{ item.snapshot.sender_platform_id ?? '未知' }}<template v-if="item.snapshot.sender_uin"> · QQ：{{ item.snapshot.sender_uin }}</template></p>
              <p>外层消息：{{ item.snapshot.forward.root_message_id }}<template v-if="item.snapshot.forward.root_source_message_id">（原始 ID：{{ item.snapshot.forward.root_source_message_id }}）</template></p>
              <p>直接父消息：{{ item.snapshot.forward.parent_message_id }}</p>
              <p>嵌套位置：{{ item.snapshot.forward.path }}</p>
              <p v-if="item.snapshot.forward.source_file">来源文件：{{ sourceFilename(item.snapshot.forward.source_file) }} · messages[{{ item.snapshot.forward.source_record_index ?? '?' }}].{{ item.snapshot.forward.path }}</p>
            </div>
            <div v-if="item.snapshot?.unexpanded_forward_paths?.length" class="mt-1 text-warning">
              <p>部分转发节点未展开，导出 messages=[]；预览不能代表缺失正文。</p>
              <p v-for="path in item.snapshot.unexpanded_forward_paths" :key="path" class="break-all">{{ path }}</p>
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
