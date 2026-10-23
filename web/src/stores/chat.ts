/**
 * AI Chat 运行时 store（ChatLab aiChat buffer 模式）。
 *
 * 每个 conversation 拥有独立 buffer；stream 事件按 request_id 写回 owner buffer，
 * 与"当前显示哪个 conversation"完全解耦——切换 conversation 不会串线，
 * 后台运行中的 stream 持续写回自己的 buffer。
 */

import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { api } from '@/api/client'
import { scopeKey, selectableScopesEqual } from '@/utils/scope'
import type {
  ProcessProjection,
  ScopeRequest,
  SourceItem,
  StreamEnvelope,
  StreamEvent,
  ToolResultProjection,
  AnswerBlockDTO,
} from '@/types/contracts'

export const DRAFT_PREFIX = '__draft__:'

/** scope-keyed draft key：不同 Source Scope 的草稿互不覆写（如 __draft__:all、__draft__:session:<id>）。 */
export function draftBufferKey(scope: ScopeRequest): string {
  return `${DRAFT_PREFIX}${scopeKey(scope)}`
}

export interface PlanStep {
  goal?: string
  suggested_tools?: string[]
  evidence_needed?: string[]
}

export type ProcessBlock =
  | {
      kind: 'route'
      route?: string | null
      reason?: string | null
      confidence?: number | null
      source?: string | null
      degradationCode?: string | null
      durationMs?: number | null
    }
  | {
      kind: 'plan'
      title?: string | null
      intent?: string | null
      steps: PlanStep[]
      successCriteria: string[]
      failed?: boolean
      errorCode?: string | null
      errorMessage?: string | null
      durationMs?: number | null
    }
  | {
      kind: 'thinking'
      text: string
      visibility?: string | null
      running: boolean
      startedAt: number
      durationMs?: number | null
      textTruncated?: boolean
    }
  | {
      kind: 'tool'
      toolCallId: string
      toolName?: string | null
      arguments?: Record<string, unknown> | null
      status: 'running' | 'completed' | 'failed'
      resultSummary?: Record<string, unknown> | null
      resultProjection?: ToolResultProjection | null
      retrieval?: Record<string, unknown> | null
      errorCode?: string | null
      durationMs?: number | null
    }
  | { kind: 'error'; code?: string | null; message?: string | null }
  | { kind: 'narration'; text: string }

export interface UserItem {
  id: string
  role: 'user'
  content: string
  createdAt: number
}

export interface AssistantItem {
  id: string
  role: 'assistant'
  answer: string
  blocks: ProcessBlock[]
  status: 'running' | 'completed' | 'failed' | 'aborted' | 'error'
  degraded: boolean
  sources: SourceItem[]
  limitations: string[]
  traceId: string | null
  startedAt: number
  durationMs?: number | null
  processProjection: ProcessProjection | null
  interrupted: boolean
  // 正式引用绑定随历史和终态投影传入；运行中正文保持原有流式体验。
  answerBlocks?: AnswerBlockDTO[]
  messageOrdinal?: number
}

export type ChatItem = UserItem | AssistantItem

export interface ConversationBuffer {
  key: string
  conversationId: string | null
  title: string
  scope: ScopeRequest | null
  items: ChatItem[]
  loaded: boolean
}

interface StreamContext {
  bufferKey: string
  controller: AbortController
  startedAt: number
}

let idCounter = 0
function nextId(prefix: string): string {
  idCounter += 1
  return `${prefix}-${Date.now()}-${idCounter}`
}

function createBuffer(key: string, scope: ScopeRequest | null, title = '新的对话'): ConversationBuffer {
  return reactive({
    key,
    conversationId: key.startsWith(DRAFT_PREFIX) ? null : key,
    title,
    scope,
    items: [],
    loaded: false,
  })
}

export const useChatStore = defineStore('chat', () => {
  const buffers = reactive<Record<string, ConversationBuffer>>({})
  const currentKey = ref<string | null>(null)
  const sendingError = ref<string | null>(null)
  const busy = ref(false)
  let navigationGeneration = 0

  /** stream 事件按 request_id 找到 owner buffer；不依赖"当前 conversation"全局变量。 */
  const streamOwners = new Map<string, string>()
  // streams 必须响应式：Send/Stop 按钮与 activeStreamRequestId 依赖它。
  const streams = reactive(new Map<string, StreamContext>())

  const currentBuffer = computed<ConversationBuffer | null>(() => {
    if (currentKey.value === null) return null
    return buffers[currentKey.value] ?? null
  })

  const activeStreamRequestId = computed<string | null>(() => {
    const key = currentKey.value
    if (key === null) return null
    for (const [requestId, context] of streams) {
      if (context.bufferKey === key) return requestId
    }
    return null
  })

  function ensureDraft(scope: ScopeRequest): ConversationBuffer {
    // 草稿按 exact scope key 隔离：A 的 create request await 期间切到 B，
    // B 绑定另一份 draft，A 创建完成后只 rename A 自己的 draft。
    const key = draftBufferKey(scope)
    let buffer = buffers[key]
    if (!buffer) {
      buffer = createBuffer(key, scope)
      buffers[key] = buffer
    } else {
      buffer.scope = scope
    }
    currentKey.value = key
    return buffer
  }

  function newChat(scope: ScopeRequest | null): void {
    navigationGeneration += 1
    // 未选择合法 Source Scope 时不产生 draft；显式失败，不回退到 all。
    if (scope === null) {
      throw new Error('cannot open a draft without a selected source scope')
    }
    // 已有草稿就复用；切换显示不影响后台 stream（它们写自己的 buffer）。
    ensureDraft(scope)
  }

  /** 切换 Source Scope 时只清除主区显示；buffer 与后台 stream context 全部保留。 */
  function clearDisplayed(): void {
    navigationGeneration += 1
    currentKey.value = null
  }

  function renameBufferKey(oldKey: string, newKey: string, conversationId: string): ConversationBuffer {
    const buffer = buffers[oldKey]
    if (!buffer) throw new Error('draft buffer is missing')
    buffer.key = newKey
    buffer.conversationId = conversationId
    buffers[newKey] = buffer
    if (oldKey !== newKey) delete buffers[oldKey]
    if (currentKey.value === oldKey) currentKey.value = newKey
    for (const context of streams.values()) {
      if (context.bufferKey === oldKey) context.bufferKey = newKey
    }
    for (const [requestId, ownerKey] of streamOwners) {
      if (ownerKey === oldKey) streamOwners.set(requestId, newKey)
    }
    return buffer
  }

  async function openConversation(conversationId: string): Promise<boolean> {
    // 详情请求与导航意图绑定，旧请求只缓存数据，不抢回当前页面。
    const generation = ++navigationGeneration
    // 同一 conversation 已在内存：直接切换显示，后台 stream 继续写自己的 buffer。
    if (buffers[conversationId]) {
      currentKey.value = conversationId
      return true
    }
    const detail = await api.conversation(conversationId)
    const buffer = createBuffer(conversationId, detail.scope, conversationTitle(detail))
    for (const message of detail.messages) {
      if (message.role === 'user') {
        buffer.items.push({
          id: message.message_id,
          role: 'user',
          content: message.content,
          createdAt: Date.parse(message.created_at),
        })
      } else {
        buffer.items.push(replayAssistantItem(message))
      }
    }
    buffer.loaded = true
    buffers[conversationId] = buffer
    if (generation !== navigationGeneration) return false
    currentKey.value = conversationId
    return true
  }

  function conversationTitle(detail: { messages: { role: string; content: string }[] }): string {
    const firstUser = detail.messages.find((message) => message.role === 'user')
    return firstUser ? firstUser.content.slice(0, 60) : '新的对话'
  }

  /** 把持久化 message（含 process projection / sources）还原为可渲染的历史 turn。 */
  function replayAssistantItem(message: {
    message_id: string
    content: string
    created_at: string
    trace_id: string | null
    process_projection: ProcessProjection | null
    sources?: SourceItem[]
    limitations?: string[]
    answer_blocks?: AnswerBlockDTO[]
    ordinal?: number
  }): AssistantItem {
    const blocks: ProcessBlock[] = []
    const projection = message.process_projection
    if (projection) {
      const router = projection.router
      if (router) {
        blocks.push({
          kind: 'route',
          route: (router.route as string) ?? null,
          reason: (router.reason as string) ?? null,
          confidence: (router.confidence as number) ?? null,
          source: (router.source as string) ?? null,
          degradationCode: (router.degradation_code as string) ?? null,
          durationMs: (router.duration_ms as number) ?? null,
        })
      }
      const plan = projection.plan
      if (plan && !plan.failed) {
        blocks.push({
          kind: 'plan',
          title: (plan.title as string) ?? null,
          intent: (plan.intent as string) ?? null,
          steps: (plan.steps as PlanStep[]) ?? [],
          successCriteria: (plan.success_criteria as string[]) ?? [],
          durationMs: (plan.duration_ms as number) ?? null,
        })
      } else if (plan?.failed) {
        blocks.push({
          kind: 'plan',
          steps: [],
          successCriteria: [],
          failed: true,
          errorCode: (plan.error_code as string) ?? null,
          errorMessage: (plan.error_message as string) ?? null,
          durationMs: (plan.duration_ms as number) ?? null,
        })
      }
      for (const step of projection.steps ?? []) {
        if (step.kind === 'thinking') {
          blocks.push({
            kind: 'thinking',
            text: step.text ?? '',
            visibility: step.visibility ?? null,
            running: false,
            startedAt: 0,
            textTruncated: step.text_truncated,
          })
        } else if (step.kind === 'tool') {
          blocks.push({
            kind: 'tool',
            toolCallId: step.tool_call_id ?? '',
            toolName: step.tool_name ?? null,
            arguments: step.arguments ?? null,
            status: step.status === 'failed' ? 'failed' : 'completed',
            resultSummary: null,
            retrieval: step.retrieval ?? null,
            errorCode: step.error_code ?? null,
            durationMs: step.duration_ms ?? null,
          })
        }
      }
      if (projection.error) {
        blocks.push({
          kind: 'error',
          code: (projection.error.code as string) ?? null,
          message: (projection.error.message as string) ?? null,
        })
      }
    }
    const status = (projection?.status as AssistantItem['status'] | null) ?? 'completed'
    return {
      id: message.message_id,
      role: 'assistant',
      answer: message.content,
      blocks,
      status: status === 'running' ? 'completed' : status,
      degraded: false,
      sources: message.sources ?? [],
      limitations: message.limitations ?? [],
      traceId: message.trace_id,
      startedAt: Date.parse(message.created_at),
      processProjection: projection,
      interrupted: false,
      answerBlocks: message.answer_blocks,
      messageOrdinal: message.ordinal,
    }
  }

  async function send(
    query: string,
    scope: ScopeRequest | null,
    onFinished?: () => void,
    onCreated?: (conversationId: string) => void,
    onAccepted?: () => void,
  ): Promise<void> {
    const trimmed = query.trim()
    if (!trimmed || busy.value) return
    // Store 级双保险：未选择合法 Source Scope 时显式拒绝，绝不 fallback 到 all。
    if (scope === null) {
      sendingError.value = '请先选择一个聊天范围，再发送问题'
      return
    }
    let buffer = currentBuffer.value
    if (!buffer || !selectableScopesEqual(buffer.scope, scope)) {
      // 已持久化 conversation 的 scope 不可修改；selector 变化时转入绑定新 scope 的草稿。
      buffer = ensureDraft(scope)
    }
    if (!buffer.scope) buffer.scope = scope

    busy.value = true
    sendingError.value = null

    // 草稿第一次发送时创建正式 conversation（ChatLab draft buffer rename 模式）。
    if (buffer.conversationId === null) {
      try {
        const draftScope = buffer.scope
        if (!draftScope) throw new Error('draft buffer is missing its scope')
        const created = await api.createConversation(draftScope)
        renameBufferKey(buffer.key, created.conversation_id, created.conversation_id)
        // Draft 转正即写入 URL：发送第一条消息后 reload 也能恢复当前 conversation。
        onCreated?.(created.conversation_id)
      } catch (error) {
        busy.value = false
        sendingError.value = error instanceof Error ? error.message : String(error)
        return
      }
    }

    const targetBuffer: ConversationBuffer | undefined = buffers[buffer.key]
    if (!targetBuffer) {
      busy.value = false
      return
    }
    const targetScope = targetBuffer.scope
    if (!targetScope) {
      busy.value = false
      throw new Error('conversation buffer is missing its scope')
    }
    targetBuffer.items.push({
      id: nextId('user'),
      role: 'user',
      content: trimmed,
      createdAt: Date.now(),
    })
    const assistant: AssistantItem = {
      id: nextId('assistant'),
      role: 'assistant',
      answer: '',
      blocks: [],
      status: 'running',
      degraded: false,
      sources: [],
      limitations: [],
      traceId: null,
      startedAt: Date.now(),
      processProjection: null,
      interrupted: false,
    }
    targetBuffer.items.push(assistant)
    // 从此问题已在所属会话中可见，通知输入框接收完成。
    onAccepted?.()

    const requestId = nextId('request')
    const controller = new AbortController()
    streamOwners.set(requestId, targetBuffer.key)
    streams.set(requestId, { bufferKey: targetBuffer.key, controller, startedAt: Date.now() })

    try {
      await api.streamQuery(
        {
          query: trimmed,
          scope: targetScope,
          conversation_id: targetBuffer.conversationId,
          request_id: requestId,
        },
        { onEvent: (event) => appendEvent(requestId, event) },
        controller.signal,
      )
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        sendingError.value = error instanceof Error ? error.message : String(error)
        assistant.status = 'error'
        assistant.blocks.push({ kind: 'error', code: null, message: sendingError.value })
      }
    } finally {
      streamOwners.delete(requestId)
      streams.delete(requestId)
      if (assistant.status === 'running') assistant.status = 'error'
      assistant.durationMs = Date.now() - assistant.startedAt
      busy.value = streams.size > 0
      onFinished?.()
    }
  }

  /** 唯一的 stream 写入点：按 request_id 找 owner buffer，绝不写入"当前"buffer。 */
  function appendEvent(requestId: string, event: StreamEvent | StreamEnvelope): void {
    const bufferKey = streamOwners.get(requestId)
    if (!bufferKey) return
    const buffer = buffers[bufferKey]
    if (!buffer) return
    // stream.end 是权威终态；query.failed/query.aborted 可能已经先关闭 running 状态。
    const assistant = event.type === 'stream.end'
      ? lastAssistant(buffer)
      : lastRunningAssistant(buffer)
    if (event.type === 'stream.end') {
      const envelope = event as StreamEnvelope
      if (assistant) {
        assistant.sources = envelope.sources ?? assistant.sources
        assistant.answerBlocks = envelope.answer_blocks
        assistant.limitations = envelope.limitations ?? assistant.limitations
        assistant.traceId = envelope.trace_id ?? assistant.traceId
        assistant.status =
          envelope.status === 'completed'
            ? 'completed'
            : envelope.status === 'aborted'
              ? 'aborted'
              : envelope.status === 'failed'
                ? 'failed'
                : 'error'
        if (envelope.status === 'failed' || envelope.status === 'aborted' || envelope.status === 'error') {
          const terminalError = lastErrorBlock(assistant)
          if (terminalError) {
            // stream.end 的错误字段是权威终态；缺失字段不擦除 live event 已记录的诊断。
            terminalError.code = envelope.error_code ?? terminalError.code
            terminalError.message = envelope.error_message ?? terminalError.message
          } else {
            assistant.blocks.push({
              kind: 'error',
              code: envelope.error_code ?? null,
              message: envelope.error_message ?? null,
            })
          }
        }
      }
      return
    }
    if (!assistant || event.type === 'stream.started' || event.type === 'stream.end') return
    applyStreamEvent(assistant, event as StreamEvent)
  }

  function lastAssistant(buffer: ConversationBuffer): AssistantItem | null {
    for (let index = buffer.items.length - 1; index >= 0; index -= 1) {
      const item: ChatItem | undefined = buffer.items[index]
      if (item && item.role === 'assistant') return item
    }
    return null
  }

  function lastRunningAssistant(buffer: ConversationBuffer): AssistantItem | null {
    const assistant = lastAssistant(buffer)
    return assistant?.status === 'running' ? assistant : null
  }

  function lastErrorBlock(assistant: AssistantItem): Extract<ProcessBlock, { kind: 'error' }> | undefined {
    for (let index = assistant.blocks.length - 1; index >= 0; index -= 1) {
      const block: ProcessBlock | undefined = assistant.blocks[index]
      if (block?.kind === 'error') return block
    }
    return undefined
  }

  /** 将 UI-neutral QueryStreamEvent 应用到 running turn；只投影真实发生的过程。 */
  function applyStreamEvent(assistant: AssistantItem, event: StreamEvent): void {
    if (event.type === 'stream.started' || event.type === 'stream.end') return
    const metadata = event.metadata ?? {}
    switch (event.type) {
      case 'query.started':
        break
      case 'route.completed':
        assistant.blocks.push({
          kind: 'route',
          route: event.route ?? null,
          reason: (metadata['reason'] as string) ?? null,
          confidence: (metadata['confidence'] as number) ?? null,
          source: (metadata['source'] as string) ?? null,
          degradationCode: (metadata['degradation_code'] as string) ?? null,
          durationMs: event.duration_ms ?? null,
        })
        break
      case 'plan.completed': {
        const plan = event.plan ?? {}
        assistant.blocks.push({
          kind: 'plan',
          title: (plan['title'] as string) ?? null,
          intent: (plan['intent'] as string) ?? null,
          steps: (plan['steps'] as PlanStep[]) ?? [],
          successCriteria: (plan['success_criteria'] as string[]) ?? [],
          durationMs: event.duration_ms ?? null,
        })
        break
      }
      case 'plan.failed':
        assistant.blocks.push({
          kind: 'plan',
          steps: [],
          successCriteria: [],
          failed: true,
          errorCode: event.error_code ?? null,
          errorMessage: event.error_message ?? null,
          durationMs: event.duration_ms ?? null,
        })
        break
      case 'thinking.started':
        assistant.blocks.push({
          kind: 'thinking',
          text: '',
          visibility: null,
          running: true,
          startedAt: Date.now(),
        })
        break
      case 'thinking.delta': {
        const block = lastBlock(assistant, 'thinking')
        if (block && block.running) {
          block.text += event.content ?? ''
          if (event.thinking_visibility && !block.visibility) block.visibility = event.thinking_visibility
        }
        break
      }
      case 'thinking.completed': {
        const block = lastBlock(assistant, 'thinking')
        if (block && block.running) {
          block.running = false
          block.durationMs = Date.now() - block.startedAt
        }
        break
      }
      case 'tool.started':
        assistant.blocks.push({
          kind: 'tool',
          toolCallId: event.tool_call_id ?? '',
          toolName: event.tool_name ?? null,
          arguments: event.arguments ?? null,
          status: 'running',
        })
        break
      case 'tool.completed':
      case 'tool.failed': {
        // tool_call_id 精确匹配；同名工具并行调用也能区分。
        const block = findToolBlock(assistant, event.tool_call_id ?? '')
        if (!block) break
        block.status = event.type === 'tool.failed' ? 'failed' : 'completed'
        // runtime 与 normalized 两个事实来源各带一部分投影；只做 additive 合并，不用空值覆盖。
        if (event.result_summary) {
          block.resultSummary = { ...(block.resultSummary ?? {}), ...event.result_summary }
        }
        if (event.result_projection) block.resultProjection = event.result_projection
        if (event.error_code) block.errorCode = event.error_code
        if (event.duration_ms !== null && event.duration_ms !== undefined) block.durationMs = event.duration_ms
        break
      }
      case 'retrieval.completed': {
        // retrieval.parent_operation_id == tool.tool_call_id 才归入 tool；无 parent 独立展示。
        const parentId = event.parent_operation_id
        const block = parentId ? findToolBlock(assistant, parentId) : undefined
        const stats: Record<string, unknown> = { ...(event.result_summary ?? {}) }
        if (event.duration_ms !== undefined) stats['duration_ms'] = event.duration_ms
        if (block) block.retrieval = { ...(block.retrieval ?? {}), ...stats }
        else
          assistant.blocks.push({
            kind: 'tool',
            toolCallId: 'retrieval',
            toolName: 'retrieval',
            status: 'completed',
            retrieval: stats,
          })
        break
      }
      case 'answer.delta':
        assistant.answer += event.content ?? ''
        break
      case 'answer.superseded':
        // Tool 边界确认先前的 provisional 正文只是叙述：降级为过程文本块，answer 等待最终回合。
        if (assistant.answer) {
          assistant.blocks.push({ kind: 'narration', text: assistant.answer })
          assistant.answer = ''
        }
        break
      case 'answer.completed':
        // finalizer 权威文本覆盖流式累积（修正 parser/finalizer 差异）。
        if (event.content) assistant.answer = event.content
        break
      case 'usage.updated':
        break
      case 'query.failed':
      case 'query.aborted':
        assistant.status = event.type === 'query.failed' ? 'failed' : 'aborted'
        assistant.blocks.push({
          kind: 'error',
          code: event.error_code ?? null,
          message: event.error_message ?? null,
        })
        break
      default:
        break
    }
  }

  function lastBlock(assistant: AssistantItem, kind: 'thinking'): Extract<ProcessBlock, { kind: 'thinking' }> | undefined {
    for (let index = assistant.blocks.length - 1; index >= 0; index -= 1) {
      const block: ProcessBlock | undefined = assistant.blocks[index]
      if (block && block.kind === kind) return block
    }
    return undefined
  }

  function findToolBlock(assistant: AssistantItem, toolCallId: string): Extract<ProcessBlock, { kind: 'tool' }> | undefined {
    for (let index = assistant.blocks.length - 1; index >= 0; index -= 1) {
      const block: ProcessBlock | undefined = assistant.blocks[index]
      if (block && block.kind === 'tool' && block.toolCallId === toolCallId) return block
    }
    return undefined
  }

  /** Stop：真正取消 backend query（graceful abort），并继续读取终态事件。 */
  async function stop(requestId: string): Promise<void> {
    await fetch('/api/query/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
    })
  }

  async function stopCurrent(): Promise<void> {
    const requestId = activeStreamRequestId.value
    if (requestId) await stop(requestId)
  }

  function markInterrupted(conversationId: string): void {
    const buffer = buffers[conversationId]
    if (!buffer) return
    const assistant = lastRunningAssistant(buffer)
    if (assistant) {
      assistant.status = 'error'
      assistant.interrupted = true
    }
  }

  function closeBuffer(conversationId: string): void {
    delete buffers[conversationId]
    if (currentKey.value === conversationId) currentKey.value = null
  }

  return {
    buffers,
    currentKey,
    currentBuffer,
    activeStreamRequestId,
    sendingError,
    busy,
    hasRunningStream: () => streams.size > 0,
    ensureDraft,
    newChat,
    clearDisplayed,
    openConversation,
    send,
    stopCurrent,
    appendEvent,
    markInterrupted,
    closeBuffer,
  }
})
