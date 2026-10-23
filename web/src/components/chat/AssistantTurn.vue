<script setup lang="ts">
/**
 * 一轮 assistant 回答（ChatLab ChatMessage 模式）：
 * 运行中 = timeline 模式，过程块实时出现；完成后收拢为「执行过程」组。
 * Trivae 的 QueryStreamAdapter 只把最终 answer 投影为正文，过程块永远没有 text 块，
 * 因此 Answer 始终渲染在 Process Group 外。
 */
import { computed, ref, watch } from 'vue'
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
import { readableLimitations } from '@/utils/presentation'

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
  // ChatLab 行为：运行中的活动段实时展开；完成后折叠，错误组保持展开。
  return (
    isActiveProcessSegment(segments.value, index, isStreaming.value) ||
    hasProcessSegmentError(segments.value[index], (block) => block.kind === 'error')
  )
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

const trustedUrls = computed(() => {
  // trusted URL 只来自最终 Source snapshot，不从回答正文、excerpt 或相似文本猜测。
  const urls = new Set<string>()
  for (const source of props.item.sources) {
    for (const url of source.snapshot?.urls ?? []) {
      urls.add(url)
    }
  }
  return [...urls]
})

const answerHtml = computed(() => renderMarkdown(props.item.answer, trustedUrls.value))
const showAnswer = computed(() => props.item.answer.length > 0)
const sourcesPanel = ref<InstanceType<typeof SourcesBlock> | null>(null)
const renderedBlocks = computed(() => props.item.answerBlocks?.map((block) => ({ ...block, html: renderMarkdown(block.text, trustedUrls.value) })) ?? [])
const limitations = computed(() => readableLimitations(props.item.limitations))
const copied = ref(false)
const copyError = ref('')
// 回答流式更新后取消旧复制提示，避免声称新内容已被复制。
watch(() => props.item.answer, () => { copied.value = false })
async function copyAnswer(): Promise<void> {
  copyError.value = ''
  copied.value = false
  try {
    // 复制原始 Markdown，保留结构和引用标记供用户粘贴整理。
    await navigator.clipboard.writeText(props.item.answer)
    copied.value = true
  } catch (error) {
    // 浏览器拒绝剪贴板时显式提示，不伪造复制成功。
    copyError.value = `复制失败：${error instanceof Error ? error.message : String(error)}`
  }
}

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
  <article class="assistant-turn" aria-label="Trivae 的回答">
    <div class="assistant-identity"><span class="assistant-avatar" aria-hidden="true">T</span><span>Trivae</span><span v-if="isStreaming" class="assistant-working" role="status">正在整理…</span></div>
    <!-- 执行过程：继续沿用实时展开、完成折叠和错误可见的契约。 -->
    <template v-for="(segment, index) in segments" :key="`seg-${index}`">
      <div v-if="segment.type === 'process'">
        <div
          class="rounded-xl border border-default bg-elevated/40"
          :class="{ 'border-error/50': hasProcessSegmentError(segment, (block) => block.kind === 'error') }"
        >
          <button
            class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
            :aria-expanded="isOpen(index)"
            @click="toggleSegment(index)"
          >
            <span class="font-mono">{{ isOpen(index) ? '▼' : '▶' }}</span>
            <ProcessHeader
              :active="isActiveProcessSegment(segments, index, isStreaming)"
              :blocks="segment.blocks"
              :duration-ms="segmentDuration(index)"
            />
            <span v-if="!isActiveProcessSegment(segments, index, isStreaming)" class="text-dimmed">
              {{ stepCount(index) }} 步
            </span>
          </button>

          <div v-if="isOpen(index)" class="space-y-1 border-t border-default px-3 py-2">
            <template v-for="(block, blockIndex) in segment.blocks" :key="blockIndex">
              <BlockRoute v-if="block.kind === 'route'" :block="block" />
              <BlockPlan v-else-if="block.kind === 'plan'" :block="block" />
              <BlockThinking v-else-if="block.kind === 'thinking'" :block="block" />
              <BlockTool v-else-if="block.kind === 'tool'" :block="block" />
              <div v-else-if="block.kind === 'narration'" class="rounded-md border border-default/50 px-3 py-2 text-xs text-dimmed">
                <span class="mb-1 block text-[10px] uppercase tracking-wide">模型说明（非最终回答）</span>
                <span class="whitespace-pre-wrap">{{ block.text }}</span>
              </div>
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

    <!-- 最终回答始终位于过程分组之外，方便阅读和复制。 -->
    <div v-if="showAnswer && !isStreaming && renderedBlocks.length" class="answer-blocks">
      <section v-for="block in renderedBlocks" :key="block.block_id" class="answer-block">
        <div class="md-body mt-3" v-html="block.html" />
        <div v-if="block.source_indices.length" class="citation-links" aria-label="本段来源">
          <span>来源</span><button v-for="index in block.source_indices" :key="index" :aria-label="`查看来源 ${index}`" @click="sourcesPanel?.openSource(index, $event.currentTarget as HTMLElement)">[{{ index }}]</button>
        </div>
      </section>
    </div>
    <div v-else-if="showAnswer" class="md-body mt-3" v-html="answerHtml" />

    <div v-if="statusLabel" class="mt-2 text-xs text-error">
      {{ statusLabel }}
      <span v-if="item.interrupted">（页面刷新导致执行中断）</span>
    </div>
    <div v-if="limitations.length" class="answer-limitations">
      <span>阅读提示</span><ul><li v-for="limitation in limitations" :key="limitation">{{ limitation }}</li></ul>
    </div>

    <SourcesBlock v-if="item.sources.length > 0" ref="sourcesPanel" :sources="item.sources" :conversation-id="conversationId" :trace-id="item.traceId" :message-ordinal="item.messageOrdinal" />
    <div v-if="showAnswer && !isStreaming" class="answer-actions">
      <button class="copy-answer" :aria-label="copied ? '已复制回答' : '复制回答'" @click="copyAnswer">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M15 8V4H4v11h4" /></svg>{{ copied ? '已复制' : '复制回答' }}
      </button>
      <span v-if="copyError" class="text-xs text-error" role="alert">{{ copyError }}</span>
    </div>
    <TraceFooter v-if="item.traceId" :trace-id="item.traceId" :duration-ms="item.durationMs" :limitations="item.limitations" />
  </article>
</template>
