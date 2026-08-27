<script setup lang="ts">
import type { ProcessBlock } from '@/stores/chat'

defineProps<{ block: Extract<ProcessBlock, { kind: 'plan' }> }>()
</script>

<template>
  <div class="rounded-lg border border-default px-3 py-2 text-xs" :class="{ 'border-error/50': block.failed }">
    <div class="flex items-center gap-2">
      <span class="font-semibold text-default">Planning</span>
      <span v-if="block.failed" class="rounded bg-error/15 px-1.5 py-0.5 text-error">Plan failed</span>
      <span v-if="block.durationMs !== null && block.durationMs !== undefined" class="ml-auto text-dimmed">
        {{ Math.round(block.durationMs) }}ms
      </span>
    </div>
    <div v-if="block.title" class="mt-1 text-dimmed">{{ block.title }}</div>
    <template v-if="!block.failed">
      <ol class="mt-1 list-decimal space-y-0.5 pl-4">
        <li v-for="(step, index) in block.steps" :key="index">
          {{ step.goal }}
          <span v-if="step.suggested_tools?.length" class="text-dimmed">
            [{{ step.suggested_tools.join(', ') }}]
          </span>
        </li>
      </ol>
      <div v-if="block.successCriteria.length" class="mt-1 text-dimmed">
        成功标准：{{ block.successCriteria.join('; ') }}
      </div>
    </template>
    <template v-else>
      <div class="mt-1 text-dimmed">
        {{ block.errorMessage ?? 'planner 未产出可用 plan，已按无 plan 继续执行' }}
        <span v-if="block.errorCode" class="font-mono">[{{ block.errorCode }}]</span>
      </div>
    </template>
  </div>
</template>
