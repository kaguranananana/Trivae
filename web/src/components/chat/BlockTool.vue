<script setup lang="ts">
import { computed, ref } from 'vue'
import { toolLabel } from '@/utils/presentation'
import type { ProcessBlock } from '@/stores/chat'
import type { ToolResultItem, ToolResultProjection } from '@/types/contracts'

const props = defineProps<{ block: Extract<ProcessBlock, { kind: 'tool' }> }>()

const DEFAULT_VISIBLE_ITEMS = 20
const expanded = ref(false)
const showAllItems = ref(false)
const showRawJson = ref(false)

const projection = computed<ToolResultProjection | null>(() => props.block.resultProjection ?? null)
const result = computed(() => projection.value?.result ?? null)

const statusLabel = computed(() => {
  if (props.block.status === 'running') return '执行中…'
  if (props.block.status === 'failed') return '失败'
  const summaryStatus = (props.block.resultSummary?.['status'] as string | undefined) ?? null
  // partial/truncated 必须如实展示，不全部染绿。
  if (props.block.retrieval) {
    const partial = props.block.retrieval['partial'] === true
    const truncated = props.block.retrieval['truncated'] === true
    if (partial || truncated) return '已完成（部分结果）'
  }
  if (summaryStatus === 'partial') return '已完成（部分结果）'
  return props.block.status === 'completed' ? '已完成' : String(props.block.status)
})

const statusTone = computed(() =>
  props.block.status === 'failed' || statusLabel.value.includes('部分')
    ? 'text-warning'
    : props.block.status === 'running'
      ? 'text-primary'
      : 'text-success',
)

const items = computed<ToolResultItem[]>(() => result.value?.items ?? [])
const visibleItems = computed(() =>
  showAllItems.value ? items.value : items.value.slice(0, DEFAULT_VISIBLE_ITEMS),
)

const displayLine = computed(() => {
  if (!result.value) return ''
  const { total_items, transport_truncated, transport_max_items } = result.value
  if (transport_truncated) {
    return `显示 ${Math.min(DEFAULT_VISIBLE_ITEMS, items.value.length)} / ${items.value.length} 条（传输上限 ${transport_max_items} / 总数 ${total_items}；完整数据见 Trace）`
  }
  const shown = showAllItems.value ? items.value.length : Math.min(DEFAULT_VISIBLE_ITEMS, items.value.length)
  return `显示 ${shown} / ${total_items} 条`
})

const retrievalRows = computed(() => {
  if (!props.block.retrieval) return []
  const labels: Record<string, string> = {
    query: '查询',
    candidate_count: '候选数',
    total_hits: '命中数',
    returned_messages: '返回消息',
    expanded_count: '上下文消息',
    coverage: '覆盖情况',
    partial: '部分结果',
    truncated: '截断',
    latency_ms: '耗时',
    duration_ms: '耗时',
  }
  return Object.entries(props.block.retrieval)
    .filter(([key]) => labels[key] !== undefined)
    .map(([key, value]) => ({ label: labels[key], key, value: String(value) }))
})

function formatTimestamp(timestamp?: number): string {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="rounded-lg border border-default px-3 py-2 text-xs">
    <button class="flex w-full items-center gap-2 text-left" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="font-mono text-dimmed">{{ expanded ? '▼' : '▶' }}</span>
      <span class="font-mono font-semibold text-default">{{ toolLabel(block.toolName ?? '工具') }}</span>
      <span :class="statusTone">{{ statusLabel }}</span>
      <span v-if="block.errorCode" class="font-mono text-error">[{{ block.errorCode }}]</span>
      <span v-if="block.durationMs !== null && block.durationMs !== undefined" class="ml-auto text-dimmed">
        {{ (block.durationMs / 1000).toFixed(1) }}s
      </span>
    </button>

    <div v-if="expanded" class="mt-2 space-y-2">
      <!-- Arguments -->
      <div v-if="block.arguments">
        <div class="mb-1 text-dimmed">工具参数 · {{ block.toolName }}</div>
        <pre class="max-h-48 overflow-auto rounded bg-elevated p-2 font-mono">{{ JSON.stringify(block.arguments, null, 2) }}</pre>
      </div>

      <!-- Retrieval stats -->
      <div v-if="retrievalRows.length > 0" class="rounded border border-default/60 p-2">
        <div class="mb-1 text-dimmed">检索详情</div>
        <div class="grid grid-cols-2 gap-x-4 gap-y-0.5">
          <div v-for="row in retrievalRows" :key="row.key" class="flex justify-between gap-2">
            <span class="text-dimmed">{{ row.label }}</span>
            <span class="font-mono">{{ row.value }}</span>
          </div>
        </div>
      </div>

      <!-- 结构化 Result -->
      <div v-if="result && result.item_kind !== 'none'">
        <div class="mb-1 flex items-center justify-between">
          <span class="text-dimmed">结果</span>
          <span v-if="items.length > 0" class="text-dimmed">{{ displayLine }}</span>
        </div>

        <ol class="space-y-2">
          <li
            v-for="(item, index) in visibleItems"
            :key="item.source_handle + String(index)"
            class="rounded border border-default/50 p-2"
            :class="item.kind === 'message' && item.hit === false ? 'opacity-70' : ''"
          >
            <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5">
              <span class="font-mono text-dimmed">{{ index + 1 }}.</span>
              <template v-if="item.kind === 'message'">
                <span class="font-semibold text-default">{{ item.sender }}</span>
                <span v-if="item.timestamp" class="text-dimmed">{{ formatTimestamp(item.timestamp) }}</span>
                <span class="text-dimmed">{{ item.session }}</span>
                <span v-if="item.hit === false" class="rounded bg-elevated px-1 text-[10px]">context</span>
              </template>
              <template v-else>
                <span class="font-mono">{{ item.locator_kind }}:{{ item.locator }}</span>
                <span class="font-mono text-dimmed">{{ item.source_handle }}</span>
              </template>
            </div>
            <div v-if="item.kind === 'message'" class="mt-1 whitespace-pre-wrap">{{ item.content }}</div>
            <div v-else class="mt-1 font-mono break-all text-dimmed">{{ JSON.stringify(item.value) }}</div>
            <div v-if="item.urls?.length" class="mt-1 flex flex-wrap gap-2">
              <a
                v-for="url in item.urls"
                :key="url"
                :href="url"
                target="_blank"
                rel="noopener noreferrer"
                class="text-primary underline underline-offset-2"
              >{{ url }}</a>
            </div>
          </li>
        </ol>

        <button
          v-if="!showAllItems && items.length > DEFAULT_VISIBLE_ITEMS"
          class="mt-2 rounded border border-default px-2 py-1 hover:bg-elevated"
          @click="showAllItems = true"
        >
          查看完整结果（{{ items.length }} 条）
        </button>
        <button
          v-if="showAllItems && items.length > DEFAULT_VISIBLE_ITEMS"
          class="mt-2 rounded border border-default px-2 py-1 hover:bg-elevated"
          @click="showAllItems = false"
        >
          收起
        </button>

        <div v-if="result.transport_truncated" class="mt-1 text-warning">
          传输已截断：完整数据在 Trace / canonical record 中
        </div>
        <div v-if="result.limitations.length" class="mt-1 text-dimmed">
          限制：{{ result.limitations.join('; ') }}
        </div>
      </div>

      <div v-else-if="result" class="text-dimmed">结果无可展示条目（0 条）</div>
      <div v-else-if="block.status === 'running'" class="text-dimmed">等待结果…</div>
      <div v-else-if="block.status === 'failed'" class="text-error">工具执行失败，无结果返回</div>

      <!-- Raw JSON：secondary developer view -->
      <button class="text-dimmed underline underline-offset-2" @click="showRawJson = !showRawJson">
        {{ showRawJson ? '隐藏' : '查看' }} Raw JSON
      </button>
      <pre v-if="showRawJson" class="max-h-64 overflow-auto rounded bg-elevated p-2 font-mono">{{
        JSON.stringify({ resultSummary: block.resultSummary, resultProjection: block.resultProjection }, null, 2)
      }}</pre>
    </div>
  </div>
</template>
