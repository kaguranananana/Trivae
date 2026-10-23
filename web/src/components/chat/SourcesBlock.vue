<script setup lang="ts">
import { computed, nextTick, ref, reactive } from 'vue'
import type { SourceItem } from '@/types/contracts'
import { api } from '@/api/client'

const props = defineProps<{ sources: SourceItem[]; conversationId?: string | null; traceId?: string | null; messageOrdinal?: number }>()
// 展开状态属于当前 SourcesBlock 实例，避免不同回答或历史 replay 共享 UI 状态。
const expanded = ref(false)
const panel = ref<HTMLDialogElement | null>(null)
const search = ref('')
const selectedIndex = ref<number | null>(null)
let returnTarget: HTMLElement | null = null
const cards = new Map<number, HTMLElement>()
const filteredSources = computed(() => {
  const term = search.value.trim().toLocaleLowerCase()
  return props.sources.filter((item) => `${item.index} ${item.snapshot?.author_display ?? ''} ${item.snapshot?.session_display ?? ''} ${item.snapshot?.excerpt ?? ''} ${item.locator ?? ''}`.toLocaleLowerCase().includes(term))
})

/** 使用原生模态对话框管理焦点和背景隔离，面板滚动独立于答案。 */
async function openSource(index: number | null = null, trigger?: HTMLElement): Promise<void> {
  returnTarget = trigger ?? document.activeElement as HTMLElement
  selectedIndex.value = index
  search.value = ''
  expanded.value = true
  await nextTick()
  panel.value?.showModal()
  if (index !== null) {
    const card = cards.get(index)
    card?.scrollIntoView({ block: 'nearest' })
    card?.focus({ preventScroll: true })
  }
}
function closePanel(): void {
  panel.value?.close()
  expanded.value = false
  // preventScroll避免返回正文时改变原阅读位置。
  returnTarget?.focus({ preventScroll: true })
}
defineExpose({ openSource })

let ordinal = props.messageOrdinal
let ordinalRequest: Promise<number> | null = null
/** 同一轮只定位一次持久化ordinal，不为每条来源重复下载整份对话。 */
async function resolveOrdinal(): Promise<number> {
  if (ordinal !== undefined) return ordinal
  if (!ordinalRequest) ordinalRequest = (async () => {
    const conversation = await api.conversation(props.conversationId!)
    const message = conversation.messages.find((message) => message.role === 'assistant' && message.trace_id === props.traceId)
    if (!message) throw new Error('这一轮回答尚未保存，无法定位原消息。')
    ordinal = message.ordinal
    return ordinal
  })()
  try { return await ordinalRequest } finally { ordinalRequest = null }
}
// 原文按来源独立展开；只在用户点击时读取本地Canonical消息，不触发模型推理。
const originals = ref<Record<number, { open: boolean; loading: boolean; error: string | null; content: string | null }>>({})

async function toggleOriginal(index: number): Promise<void> {
  const prior = originals.value[index]
  if (prior) {
    prior.open = !prior.open
    return
  }
  await readOriginal(index)
}

/** 重读只由明确用户动作触发，错误继续显示，不做后台自动重试。 */
async function readOriginal(index: number): Promise<void> {
  if (!props.conversationId || !props.traceId) return
  const state = reactive({ open: true, loading: true, error: null as string | null, content: null as string | null })
  originals.value[index] = state
  try {
    const messageOrdinal = await resolveOrdinal()
    const result = await api.sourceContext(props.conversationId, messageOrdinal, index, 0, 0)
    const target = result.messages.find((message) => message.is_target)
    if (!target) throw new Error('来源读取结果中没有对应的原消息。')
    // 完整原文保留换行，不用摘录覆盖或伪造缺失正文。
    state.content = target.content
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.loading = false
  }
}

function relationLabel(relation: string): string {
  return ({ supports: '支持', contradicts: '相反观点', context: '背景' } as Record<string, string>)[relation] ?? relation
}

function formatTimestamp(timestampMs?: number | null): string {
  if (timestampMs === null || timestampMs === undefined) return '未知'
  return new Date(timestampMs).toLocaleString('zh-CN', { hour12: false })
}

function sourceFilename(path: string): string {
  // 文件名与 record index 足以定位导出记录，不把本地目录占据来源面板。
  return path.split(/[\\/]/).pop() ?? path
}

const label = computed(() => `来源 · ${props.sources.length}`)

function toggleExpanded(): void {
  if (expanded.value) closePanel()
  else void openSource()
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

      <dialog ref="panel" class="source-dialog" aria-label="回答的消息来源" @cancel.prevent="closePanel">
        <template v-if="expanded">
        <header class="source-panel-header"><div><h2>消息来源 <span>{{ sources.length }}</span></h2><p>核对原文后，可返回刚才的阅读位置。</p></div><button class="source-close" aria-label="关闭来源面板，返回正文" @click="closePanel">返回正文 ×</button></header>
        <label class="source-search">搜索来源<input v-model="search" placeholder="按编号、作者、群聊或摘录搜索…" autocomplete="off" /></label>
        <div class="source-panel-scroll">
        <ol class="space-y-2">
          <li v-for="item in filteredSources" :key="item.index" :ref="(element) => { if (element) cards.set(item.index, element as HTMLElement); else cards.delete(item.index) }" class="source-card" :class="{ 'source-selected': selectedIndex === item.index }" tabindex="-1">
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
                {{ relationLabel(relation) }}
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
            <blockquote v-if="item.snapshot" class="source-excerpt">
              “{{ item.snapshot.excerpt }}”
            </blockquote>
            <p v-if="item.snapshot?.excerpt_truncated" class="mt-1 text-dimmed">以上为原消息摘录。</p>
            <p v-if="item.snapshot?.excerpt_offset" class="mt-1 text-dimmed">
              摘录从原文第 {{ item.snapshot.excerpt_offset + 1 }} 个字符开始。
            </p>
            <template v-if="item.kind === 'message' && conversationId && traceId">
              <button
                type="button"
                class="mt-1 min-h-11 rounded px-2 text-primary underline focus-visible:outline focus-visible:outline-2"
                :aria-expanded="originals[item.index]?.open ?? false"
                :aria-busy="originals[item.index]?.loading ?? false"
                :disabled="originals[item.index]?.loading"
                @click="toggleOriginal(item.index)"
              >
                {{ originals[item.index]?.loading ? '正在读取原消息…' : originals[item.index]?.open ? '收起原消息' : '查看完整原消息' }}
              </button>
              <div v-if="originals[item.index]?.open" class="mt-1">
                <div v-if="originals[item.index]?.error" class="source-error"><p class="text-error" role="alert">{{ originals[item.index]?.error }}</p><button class="source-reread" @click="readOriginal(item.index)">重新读取</button></div>
                <p v-else-if="originals[item.index]?.content !== null" data-source-content class="whitespace-pre-wrap break-words text-default">{{ originals[item.index]?.content }}</p>
              </div>
            </template>
            <div v-else-if="item.kind === 'structured'" class="mt-1 font-mono break-all text-dimmed">
              {{ JSON.stringify(item.value) }}
            </div>
          </li>
        </ol>
        <p v-if="!filteredSources.length" class="sidebar-hint" role="status">没有匹配的来源</p>
        </div>
        </template>
      </dialog>
    </div>
  </template>
</template>
