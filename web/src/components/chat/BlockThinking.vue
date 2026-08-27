<script setup lang="ts">
import { computed } from 'vue'
import type { ProcessBlock } from '@/stores/chat'
import { formatProcessDuration } from '@/components/chat/processSegments'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ block: Extract<ProcessBlock, { kind: 'thinking' }> }>()

const html = computed(() => renderMarkdown(props.block.text))
const label = computed(() => {
  if (props.block.running) return 'Thinking…'
  const duration = props.block.durationMs ? ` · ${formatProcessDuration(props.block.durationMs)}` : ''
  const tag = props.block.visibility === 'provider_reasoning' ? 'Reasoning' : 'Thinking'
  return `${tag}${duration}`
})
</script>

<template>
  <div class="rounded-lg border border-default/60 px-3 py-2 text-xs">
    <div class="flex items-center gap-2">
      <span v-if="block.running" class="inline-block h-2 w-2 animate-pulse rounded-full bg-primary" />
      <span class="font-medium" :class="block.running ? 'text-primary' : 'text-default'">{{ label }}</span>
    </div>
    <!-- 内容多时内部滚动，不粗暴截断 -->
    <div class="md-body mt-1 max-h-64 overflow-y-auto whitespace-pre-wrap text-dimmed" v-html="html" />
    <div v-if="block.textTruncated" class="mt-1 text-warning">内容已截断（完整数据见 Trace）</div>
  </div>
</template>
