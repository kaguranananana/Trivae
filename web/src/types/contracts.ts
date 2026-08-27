/** 与 backend contract 一一对应的 TS 类型（NDJSON / JSON payloads）。 */

export type ScopeMode = 'all' | 'sessions'

export interface ScopeRequest {
  mode: ScopeMode
  session_ids?: string[] | null
  start_timestamp?: number | null
  end_timestamp?: number | null
  max_results?: number | null
}

export interface SessionDTO {
  session_id: string
  platform: string
  name: string
  chat_type: string
}

export interface ReadinessDTO {
  database: { status: string; session_count: number | null; message_count: number | null; message?: string | null }
  semantic: { status: string } | null
  provider: { status: string; provider?: string | null; model?: string | null }
}

export interface SourceSnapshot {
  session_display: string
  author_display: string | null
  timestamp_ms: number
  timezone: string
  excerpt: string
  excerpt_truncated: boolean
  source_message_id: string | null
  urls: string[]
}

export interface SourceItem {
  index: number
  kind: 'message' | 'structured' | 'unavailable'
  evidence_ids: string[]
  relations: string[]
  session_id?: string
  internal_message_id?: string
  snapshot?: SourceSnapshot
  locator_kind?: string
  locator?: string
  value?: unknown
  limitations?: string[]
}

export interface ContextMessageDTO {
  internal_message_id: string
  session_id: string
  session_display: string
  sender: string | null
  timestamp: number
  content: string
  is_target: boolean
}

export interface ToolResultItem {
  kind: 'message' | 'structured'
  source_handle: string
  sender?: string
  timestamp?: number
  session?: string
  content?: string
  content_truncated?: boolean
  hit?: boolean
  urls?: string[]
  locator_kind?: string
  locator?: string
  value?: unknown
}

export interface ToolResultProjection {
  tool_call_id: string
  tool_name: string
  tool_result_id: string
  status: string
  result: {
    items: ToolResultItem[]
    item_kind: 'messages' | 'structured' | 'none'
    total_items: number
    message_items: number
    structured_items: number
    hit_items: number
    limitations: string[]
    transport_truncated: boolean
    transport_max_items: number
  }
}

export interface ProcessStep {
  kind: 'thinking' | 'tool'
  text?: string
  text_truncated?: boolean
  visibility?: string
  tool_call_id?: string
  tool_name?: string
  arguments?: Record<string, unknown> | null
  status?: string
  error_code?: string | null
  duration_ms?: number | null
  result_status?: string | null
  total_items?: number | null
  item_kind?: string | null
  limitations?: string[] | null
  retrieval?: Record<string, unknown> | null
}

export interface ProcessProjection {
  schema_version: number
  router?: Record<string, unknown> | null
  plan?: Record<string, unknown> | null
  steps: ProcessStep[]
  usage?: Record<string, number> | null
  error?: Record<string, unknown> | null
  status?: string | null
}

export interface ConversationSummaryDTO {
  conversation_id: string
  created_at: string
  updated_at: string
  title: string
  message_count: number
  preview: string | null
  scope: ScopeRequest | null
}

export interface MessageDTO {
  message_id: string
  ordinal: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  trace_id: string | null
  process_projection: ProcessProjection | null
  sources?: SourceItem[]
  limitations?: string[]
}

export interface ConversationDTO {
  conversation_id: string
  created_at: string
  updated_at: string
  scope: ScopeRequest | null
  messages: MessageDTO[]
}

/** stream.started / stream.end 信封事件。 */
export interface StreamEnvelope {
  type: 'stream.started' | 'stream.end'
  request_id: string
  conversation_id?: string | null
  status?: 'completed' | 'failed' | 'aborted' | 'error'
  trace_id?: string | null
  sources?: SourceItem[]
  limitations?: string[]
  error_code?: string | null
  error_message?: string | null
}

export interface StreamEvent {
  type: string
  sequence: number
  request_id?: string
  trace_id?: string | null
  content?: string | null
  thinking_visibility?: 'public_summary' | 'provider_reasoning' | null
  route?: string | null
  plan?: Record<string, unknown> | null
  tool_name?: string | null
  tool_call_id?: string | null
  arguments?: Record<string, unknown> | null
  result_summary?: Record<string, unknown> | null
  result_detail?: string | null
  result_projection?: ToolResultProjection | null
  error_code?: string | null
  error_message?: string | null
  duration_ms?: number | null
  usage?: Record<string, number> | null
  source_operation?: string | null
  source_sequence?: number | null
  parent_operation_id?: string | null
  metadata?: Record<string, unknown>
}
