<script setup lang="ts">
/**
 * 一轮 assistant 回答（ChatLab ChatMessage 模式）：
 * 运行中 = timeline 模式，过程块实时出现；完成后收拢为「执行过程」组。
 * Trivae 的 QueryStreamAdapter 只把最终 answer 投影为正文，过程块永远没有 text 块，
 * 因此 Answer 始终渲染在 Process Group 外。
 */
import { computed, ref } from 'vue'
import type { AssistantItem, ProcessBlock } from '@/stores/chat'
import {
  buildProcessSegments,
  getProcessSegmentDurationMs,
  hasProcessSegmentError,
  isActiveProcessSegment,
} from '@/components/chat/processSegments'
import ProcessHeader from '@/components/chat/ProcessHeader.vue'
import BlockRoute from '@/components/chat/BlockRoute.vue'
import BlockPlan from '@/components/chat/BlockPlan.vue'
import BlockThinking from '@/components/chat/BlockThinking.vue'
import BlockTool from '@/components/chat/BlockTool.vue'
import SourcesBlock from '@/components/chat/SourcesBlock.vue'
import TraceFooter from '@/components/chat/TraceFooter.vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  item: AssistantItem
  conversationId: string | null
}>()

const isStreaming = computed(() => props.item.status === 'running')

const segments = computed(() => {
  const isFoldable = (block: ProcessBlock): boolean => block.kind !== 'error'
  const isText = (_block: ProcessBlock): boolean => false
  return buildProcessSegments(props.item.blocks, {
    isFoldable,
    isText,
    mode: isStreaming.value ? 'timeline' : 'completed',
  })
})

const segmentOpen = ref<Record<string, boolean>>({})

function isOpen(index: number): boolean {
  const override = segmentOpen.value[`seg-${index}`]
  if (override !== undefined) return override
  return hasProcessSegmentError(segments.value[index], (block) => block.kind === 'error')
}

function toggleSegment(index: number): void {
  segmentOpen.value = { ...segmentOpen.value, [`seg-${index}`]: !isOpen(index) }
}

function stepCount(index: number): number {
  const segment = segments.value[index]
  return segment?.type === 'process' ? segment.blocks.length : 0
}

function blockDuration(block: ProcessBlock): number | undefined {
  if (block.kind === 'thinking') return block.durationMs ?? undefined
  if (block.kind === 'tool') return block.durationMs ?? undefined
  return undefined
}

function segmentDuration(index: number): number {
  const segment = segments.value[index]
  return segment?.type === 'process' ? getProcessSegmentDurationMs(segment, blockDuration) : 0
}

const answerHtml = computed(() => renderMarkdown(props.item.answer))
const showAnswer = computed(() => props.item.answer.length > 0)

const statusLabel = computed(() => {
  switch (props.item.status) {
    case 'failed':
      return '回答失败'
    case 'aborted':
      return '已停止'
    case 'error':
      return '执行中断'
    default:
      return ''
  }
})
</script>

<template>
  <div class="my-6">
    <!-- Process segments -->
    <template v-for="(segment, index) in segments" :key="`seg-${index}`">
      <div v-if="segment.type === 'process'">
        <div
          class="rounded-xl border border-default bg-elevated/40"
          :class="{ 'border-error/50': hasProcessSegmentError(segment, (block) => block.kind === 'error') }"
        >
          <button
            class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
            @click="toggleSegment(index)"
          >
            <span class="font-mono">{{ isOpen(index) ? '▼' : '▶' }}</span>
            <ProcessHeader
              :active="isActiveProcessSegment(segments, index, isStreaming)"
              :blocks="segment.blocks"
              :duration-ms="segmentDuration(index)"
            />
            <span v-if="!isActiveProcessSegment(segments, index, isStreaming)" class="text-dimmed">
              {{ stepCount(index) }} steps
            </span>
          </button>

          <div v-if="isOpen(index)" class="space-y-1 border-t border-default px-3 py-2">
            <template v-for="(block, blockIndex) in segment.blocks" :key="blockIndex">
              <BlockRoute v-if="block.kind === 'route'" :block="block" />
              <BlockPlan v-else-if="block.kind === 'plan'" :block="block" />
              <BlockThinking v-else-if="block.kind === 'thinking'" :block="block" />
              <BlockTool v-else-if="block.kind === 'tool'" :block="block" />
              <div v-else-if="block.kind === 'error'" class="rounded-md bg-error/10 px-3 py-2 text-xs text-error">
                <span class="font-semibold">执行错误</span>
                <span v-if="block.code" class="ml-1 font-mono">[{{ block.code }}]</span>
                <div v-if="block.message" class="mt-1 text-dimmed">{{ block.message }}</div>
              </div>
            </template>
          </div>
        </div>
      </div>
    </template>

    <!-- Answer：永远在 Process Group 外 -->
    <div v-if="showAnswer" class="md-body mt-3" v-html="answerHtml" />

    <div v-if="statusLabel" class="mt-2 text-xs text-error">
      {{ statusLabel }}
      <span v-if="item.interrupted">（页面刷新导致执行中断）</span>
    </div>
    <div v-if="item.limitations.length > 0" class="mt-1 text-xs text-dimmed">
      限制：{{ item.limitations.join('; ') }}
    </div>

    <SourcesBlock v-if="item.sources.length > 0" :sources="item.sources" />
    <TraceFooter v-if="item.traceId" :trace-id="item.traceId" :duration-ms="item.durationMs" />
  </div>
</template>
