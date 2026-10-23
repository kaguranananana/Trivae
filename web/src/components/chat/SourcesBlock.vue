<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SourceItem } from '@/types/contracts'
import { api } from '@/api/client'

const props = defineProps<{ sources: SourceItem[]; conversationId?: string | null; traceId?: string | null }>()
// 展开状态属于当前 SourcesBlock 实例，避免不同回答或历史 replay 共享 UI 状态。
const expanded = ref(false)
// 原文按来源独立展开；只在用户点击时读取本地Canonical消息，不触发模型推理。
const originals = ref<Record<number, { open: boolean; loading: boolean; error: string | null; content: string | null }>>({})

async function toggleOriginal(index: number): Promise<void> {
  const prior = originals.value[index]
  if (prior) {
    prior.open = !prior.open
    return
  }
  if (!props.conversationId || !props.traceId) return
  const state = { open: true, loading: true, error: null as string | null, content: null as string | null }
  originals.value[index] = state
  try {
    // 用服务器持久化ordinal定位这一轮，不能把前端列表索引或临时消息ID当成ordinal。
    const conversation = await api.conversation(props.conversationId)
    const message = conversation.messages.find((message) => message.role === 'assistant' && message.trace_id === props.traceId)
    if (!message) throw new Error('这一轮回答尚未保存，无法定位原消息。')
    const result = await api.sourceContext(props.conversationId, message.ordinal, index, 0, 0)
    const target = result.messages.find((message) => message.is_target)
    if (!target) throw new Error('来源读取结果中没有对应的原消息。')
    // 保存完整正文，不能再次用引用摘录覆盖长消息尾部。
    state.content = target.content
  } catch (error) {
    // 原文读取失败显式展示；现有引用摘录保留，不能假装它就是完整原文。
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.loading = false
    originals.value[index] = { ...state }
  }
}

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
                <p v-if="originals[item.index]?.error" class="text-error" role="alert">{{ originals[item.index]?.error }}</p>
                <p v-else-if="originals[item.index]?.content !== null" data-source-content class="whitespace-pre-wrap break-words text-default">{{ originals[item.index]?.content }}</p>
              </div>
            </template>
            <div v-else-if="item.kind === 'structured'" class="mt-1 font-mono break-all text-dimmed">
              {{ JSON.stringify(item.value) }}
            </div>
          </li>
        </ol>
      </div>
    </div>
  </template>
</template>
