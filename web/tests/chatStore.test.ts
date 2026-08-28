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
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
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

  it('streams provisional deltas and demotes narration on superseded', async () => {
    const chat = useChatStore()
    chat.newChat({ mode: 'all' })
    const streamLines: object[] = [
      { type: 'stream.started', request_id: 'request-1', conversation_id: 'conv-1' },
      { type: 'answer.delta', sequence: 1, content: '我需要先查数据', provisional: true },
      { type: 'answer.superseded', sequence: 2, content: '我需要先查数据' },
      { type: 'answer.delta', sequence: 3, content: '最终', provisional: true },
      { type: 'answer.delta', sequence: 4, content: '答案', provisional: true },
      { type: 'answer.completed', sequence: 5, content: '权威最终答案' },
      {
        type: 'stream.end',
        request_id: 'request-1',
        status: 'completed',
        conversation_id: 'conv-1',
        trace_id: 'trace-1',
        sources: [],
      },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/conversations')) {
        return new Response(JSON.stringify(createdConversation), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        return ndjsonResponse(streamLines)
      }
      return new Response('{}', { status: 404 })
    }))
    await chat.send('问题', { mode: 'all' })

    const assistant = chat.buffers['conv-1']?.items[1]
    const blocks = assistant && assistant.role === 'assistant' ? assistant.blocks : []
    const narration = blocks.find((block) => block.kind === 'narration')
    expect(narration && narration.kind === 'narration' ? narration.text : null).toBe('我需要先查数据')
    expect(assistant && assistant.role === 'assistant' ? assistant.answer : null).toBe('权威最终答案')
    expect(assistant && assistant.role === 'assistant' ? assistant.traceId : null).toBe('trace-1')
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

  it('creates a scoped conversation when the selector differs from the opened conversation', async () => {
    const chat = useChatStore()
    const selectedScope = { mode: 'sessions' as const, session_ids: ['qq:831907794'] }
    const requestBodies: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/conversations/conv-all')) {
        return new Response(JSON.stringify({ ...createdConversation, conversation_id: 'conv-all' }))
      }
      if (url.endsWith('/api/conversations') && init?.method === 'POST') {
        requestBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>)
        return new Response(JSON.stringify({
          ...createdConversation,
          conversation_id: 'conv-scoped',
          scope: selectedScope,
        }), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        requestBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        return ndjsonResponse([{
          type: 'stream.end',
          request_id: 'request-scoped',
          status: 'completed',
          conversation_id: 'conv-scoped',
          trace_id: 'trace-scoped',
        }])
      }
      return new Response('{}', { status: 404 })
    }))

    await chat.openConversation('conv-all')
    await chat.send('最近两天大家都在聊什么', selectedScope)

    // selector scope 与旧会话不一致时，创建和查询必须共同使用新 scope 快照。
    expect(requestBodies).toEqual([
      { scope: selectedScope },
      expect.objectContaining({
        query: '最近两天大家都在聊什么',
        scope: selectedScope,
        conversation_id: 'conv-scoped',
      }),
    ])
    expect(chat.buffers['conv-all']?.items).toHaveLength(0)
    expect(chat.buffers['conv-scoped']?.scope).toEqual(selectedScope)
  })

  it('reuses the opened conversation for a same-scope follow-up', async () => {
    const chat = useChatStore()
    const selectedScope = {
      mode: 'sessions' as const,
      // 顺序差异不应改变 session 集合语义。
      session_ids: ['qq:2', 'qq:1'],
    }
    const persistedScope = {
      ...selectedScope,
      session_ids: ['qq:1', 'qq:2'],
      start_timestamp: null,
      end_timestamp: null,
      max_results: 5_000,
    }
    let createCount = 0
    let queryBody: Record<string, unknown> | null = null
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/conversations/conv-scoped')) {
        return new Response(JSON.stringify({
          ...createdConversation,
          conversation_id: 'conv-scoped',
          // 真实 API 投影的是编译后的 ExecutionScope，包含默认容量和显式 null 时间边界。
          scope: persistedScope,
        }))
      }
      if (url.endsWith('/api/conversations') && init?.method === 'POST') {
        createCount += 1
        return new Response(JSON.stringify(createdConversation), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        queryBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        return ndjsonResponse([{
          type: 'stream.end',
          request_id: 'request-follow-up',
          status: 'completed',
          conversation_id: 'conv-scoped',
          trace_id: 'trace-follow-up',
        }])
      }
      return new Response('{}', { status: 404 })
    }))

    await chat.openConversation('conv-scoped')
    await chat.send('继续说说', selectedScope)

    expect(createCount).toBe(0)
    expect(queryBody).toEqual(expect.objectContaining({
      scope: persistedScope,
      conversation_id: 'conv-scoped',
    }))
  })

  it('attaches stream terminal trace after query.failed closes the assistant', async () => {
    const chat = useChatStore()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/conversations')) {
        return new Response(JSON.stringify(createdConversation), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        return ndjsonResponse([
          {
            type: 'query.failed',
            sequence: 1,
            error_code: 'COVERAGE_MISMATCH',
            error_message: 'recent page coverage moved backwards',
          },
          {
            type: 'stream.end',
            request_id: 'request-failed',
            status: 'failed',
            conversation_id: 'conv-1',
            trace_id: 'trace-failed',
            limitations: ['回答未完成'],
            error_code: 'COVERAGE_MISMATCH',
            error_message: 'recent page coverage moved backwards',
          },
        ])
      }
      return new Response('{}', { status: 404 })
    }))

    chat.newChat({ mode: 'all' })
    await chat.send('问题', { mode: 'all' })

    const assistant = chat.buffers['conv-1']?.items[1]
    expect(assistant?.role).toBe('assistant')
    if (!assistant || assistant.role !== 'assistant') throw new Error('assistant item is missing')
    expect(assistant.status).toBe('failed')
    expect(assistant.traceId).toBe('trace-failed')
    expect(assistant.limitations).toEqual(['回答未完成'])
    const errors = assistant.blocks.filter((block) => block.kind === 'error')
    expect(errors).toHaveLength(1)
    expect(errors[0]).toEqual({
      kind: 'error',
      code: 'COVERAGE_MISMATCH',
      message: 'recent page coverage moved backwards',
    })
  })

  it('applies stream terminal diagnostics after query.aborted closes the assistant', async () => {
    const chat = useChatStore()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/conversations')) {
        return new Response(JSON.stringify(createdConversation), { status: 201 })
      }
      if (url.endsWith('/api/query/stream')) {
        return ndjsonResponse([
          {
            type: 'query.aborted',
            sequence: 1,
          },
          {
            type: 'stream.end',
            request_id: 'request-aborted',
            status: 'aborted',
            conversation_id: 'conv-1',
            trace_id: 'trace-aborted',
            limitations: ['用户已停止回答'],
            error_code: 'RUN_ABORTED',
            error_message: 'query aborted by user',
          },
        ])
      }
      return new Response('{}', { status: 404 })
    }))

    chat.newChat({ mode: 'all' })
    await chat.send('问题', { mode: 'all' })

    const assistant = chat.buffers['conv-1']?.items[1]
    expect(assistant?.role).toBe('assistant')
    if (!assistant || assistant.role !== 'assistant') throw new Error('assistant item is missing')
    expect(assistant.status).toBe('aborted')
    expect(assistant.traceId).toBe('trace-aborted')
    expect(assistant.limitations).toEqual(['用户已停止回答'])
    expect(assistant.blocks.filter((block) => block.kind === 'error')).toEqual([{
      kind: 'error',
      code: 'RUN_ABORTED',
      message: 'query aborted by user',
    }])
  })
})
