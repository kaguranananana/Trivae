<script setup lang="ts">
import type { ProcessBlock } from '@/stores/chat'

const props = defineProps<{ block: Extract<ProcessBlock, { kind: 'route' }> }>()

const routeLabel = props.block.route === 'planned_execution' ? 'PLAN' : props.block.route === 'standard_execution' ? 'STANDARD' : (props.block.route ?? '')
const tone = props.block.route === 'planned_execution' ? 'bg-primary/15 text-primary' : 'bg-success/15 text-success'
</script>

<template>
  <div class="rounded-lg border border-default px-3 py-2 text-xs">
    <div class="flex items-center gap-2">
      <span class="text-dimmed">Router</span>
      <span class="rounded px-1.5 py-0.5 font-mono font-semibold" :class="tone">{{ routeLabel }}</span>
      <span v-if="block.degradationCode" class="rounded bg-warning/15 px-1.5 py-0.5 text-warning">
        degraded · {{ block.degradationCode }}
      </span>
      <span v-if="block.durationMs !== null && block.durationMs !== undefined" class="ml-auto text-dimmed">
        {{ Math.round(block.durationMs) }}ms
      </span>
    </div>
    <div v-if="block.reason" class="mt-1 text-dimmed">
      <span class="text-default">Reason:</span> {{ block.reason }}
    </div>
    <div v-if="block.confidence !== null && block.confidence !== undefined" class="mt-0.5 text-dimmed">
      <span class="text-default">Confidence:</span> {{ block.confidence.toFixed(2) }}
      <span v-if="block.source" class="ml-2">source: {{ block.source }}</span>
    </div>
  </div>
</template>
