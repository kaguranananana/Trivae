import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useChatStore, type ProcessBlock } from '@/stores/chat'
import type { StreamEnvelope, StreamEvent } from '@/types/contracts'

function ndjsonResponse(lines: object[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const line of lines) {
        controller.enqueue(encoder.encode(JSON.stringify(line) + '\n'))
      }
      controller.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } })
}

const createdConversation = {
  conversation_id: 'conv-1',
  created_at: '2026-08-27T00:00:00+00:00',
  updated_at: '2026-08-27T00:00:00+00:00',
  scope: { mode: 'all' },
  messages: [],
}

const streamLines: object[] = [
  { type: 'stream.started', request_id: 'request-1', conversation_id: 'conv-1' },
  {
    type: 'route.completed',
    sequence: 1,
    route: 'planned_execution',
    duration_ms: 12,
    metadata: { reason: '多阶段调查', confidence: 0.95, source: 'rule' },
  },
  { type: 'thinking.started', sequence: 2 },
  { type: 'thinking.delta', sequence: 3, content: '分析问题', thinking_visibility: 'public_summary' },
  { type: 'thinking.completed', sequence: 4 },
  {
    type: 'tool.started',
    sequence: 5,
    tool_name: 'semantic_search',
    tool_call_id: 'run-1/tool-call/1',
    arguments: { query: 'Agent' },
  },
  {
    type: 'tool.completed',
    sequence: 6,
    tool_name: 'semantic_search',
    tool_call_id: 'run-1/tool-call/1',
    result_projection: {
      tool_call_id: 'run-1/tool-call/1',
      tool_name: 'semantic_search',
      tool_result_id: 'r1',
      status: 'ok',
      result: { items: [], item_kind: 'messages', total_items: 5, message_items: 5, structured_items: 0, hit_items: 5, limitations: [], transport_truncated: false, transport_max_items: 200 },
    },
  },
  { type: 'answer.delta', sequence: 7, content: '最终回答' },
  {
    type: 'stream.end',
    request_id: 'request-1',
    status: 'completed',
    conversation_id: 'conv-1',
    trace_id: 'trace-1',
    sources: [],
    limitations: [],
  },
]

describe('chat store stream routing', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/conversations')) {
        return new Response(JSON.stringify(createdConversation), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        return ndjsonResponse(streamLines)
      }
      return new Response('{}', { status: 404 })
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('routes events into owner buffer and renders blocks', async () => {
    const chat = useChatStore()
    chat.newChat({ mode: 'all' })
    await chat.send('问题', { mode: 'all' })

    const buffer = chat.buffers['conv-1']
    expect(buffer).toBeDefined()
    const items = buffer?.items ?? []
    expect(items).toHaveLength(2)
    const assistant = items[1]
    const isAssistant = assistant !== undefined && assistant.role === 'assistant'
    expect(isAssistant && assistant.status).toBe('completed')
    expect(isAssistant && assistant.answer).toBe('最终回答')
    expect(isAssistant && assistant.traceId).toBe('trace-1')
    const blocks: ProcessBlock[] = isAssistant ? assistant.blocks : []
    expect(blocks.map((block) => block.kind)).toEqual(['route', 'thinking', 'tool'])
    const route = blocks[0]
    const routeReason = route?.kind === 'route' ? route.reason : null
    expect(routeReason).toBe('多阶段调查')
    const routeConfidence = route?.kind === 'route' ? route.confidence : null
    expect(routeConfidence).toBe(0.95)
    const tool = blocks[2]
    const toolProjection = tool?.kind === 'tool' ? tool.resultProjection : null
    expect(toolProjection?.result.total_items).toBe(5)
  })

  it('keeps stream writes in owner buffer when the user switches conversations', async () => {
    const chat = useChatStore()
    chat.newChat({ mode: 'all' })
    // 模拟另一个 conversation 已打开：send 时事件流慢速到达
    const pending: Array<(event: StreamEvent) => void> = []
    const existing = vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/conversations')) {
        return new Response(JSON.stringify(createdConversation), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        return new Response(new ReadableStream<Uint8Array>({
          start(controller) {
            const encoder = new TextEncoder()
            pending.push((event: StreamEvent) => {
              if (event.type === 'stream.end') {
                controller.enqueue(encoder.encode(JSON.stringify(event) + '\n'))
                controller.close()
                return
              }
              controller.enqueue(encoder.encode(JSON.stringify(event) + '\n'))
            })
          },
        }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } })
      }
      return new Response('{}', { status: 404 })
    }))
    const sendPromise = chat.send('问题', { mode: 'all' })
    await vi.waitFor(() => expect(chat.buffers['conv-1']).toBeDefined())
    // 切到别的 buffer（模拟切换 conversation）
    chat.buffers['conv-other'] = {
      key: 'conv-other',
      conversationId: 'conv-other',
      title: '其他',
      scope: { mode: 'all' },
      items: [],
      loaded: true,
    }
    chat.currentKey = 'conv-other'
    // stream 事件持续写回 owner（conv-1），而不是当前显示的 conv-other
    const push = (event: StreamEvent | StreamEnvelope) => pending[0]?.(event as StreamEvent)
    push({ type: 'route.completed', sequence: 1, route: 'standard_execution', metadata: { reason: '简单查询' } })
    // 读循环是异步的；等事件真正写回 owner buffer。
    await vi.waitFor(() => {
      const ownerBuffer = chat.buffers['conv-1']
      const ownerAssistant = ownerBuffer?.items[1]
      const ownerBlocks: ProcessBlock[] =
        ownerAssistant && ownerAssistant.role === 'assistant' ? ownerAssistant.blocks : []
      expect(ownerBlocks.map((block) => block.kind)).toEqual(['route'])
      expect(chat.buffers['conv-other']?.items).toHaveLength(0)
    })
    push({ type: 'stream.end', request_id: 'x', status: 'completed' })
    await sendPromise
    void existing
  })
})
