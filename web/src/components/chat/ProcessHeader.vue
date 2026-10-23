<script setup lang="ts">
import { computed } from 'vue'
import type { ProcessBlock } from '@/stores/chat'
import { formatProcessDuration } from '@/components/chat/processSegments'
import { toolLabel } from '@/utils/presentation'

const props = defineProps<{
  active: boolean
  blocks: ProcessBlock[]
  durationMs: number
}>()

const label = computed(() => {
  if (props.active) {
    const last = props.blocks[props.blocks.length - 1]
    if (last?.kind === 'tool' && last.status === 'running' && last.toolName) return `${toolLabel(last.toolName)}…`
    if (last?.kind === 'thinking' && last.running) return '正在思考…'
    return '执行中…'
  }
  const duration = props.durationMs > 0 ? ` · ${formatProcessDuration(props.durationMs)}` : ''
  return `执行过程${duration}`
})
</script>

<template>
  <span class="font-medium text-default">{{ label }}</span>
</template>
