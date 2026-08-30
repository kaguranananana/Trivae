import type { ScopeRequest, SessionDTO } from '@/types/contracts'

export interface ScopeDisplay {
  label: string
  title: string
}

/**
 * Source Scope 一级导航的选中状态。
 * null 表示未选择：不请求列表、不创建 draft、Composer 禁用。
 * 它只是 Web navigation state，不进入后端 ExecutionScope contract。
 */
export type SelectedSourceScope = null | { kind: 'all' } | { kind: 'session'; sessionId: string }

/**
 * 把 Session ID 规范化为稳定集合。
 * 去重保证重复选择不会制造新范围，排序保证选择顺序不影响 identity。
 */
export function normalizeSessionIds(sessionIds: readonly string[] | null | undefined): string[] {
  return [...new Set(sessionIds ?? [])].sort()
}

/** 为 Sidebar 生成不会把 legacy null 误报为 all 的稳定范围 key。 */
export function scopeKey(scope: ScopeRequest | null): string {
  if (scope === null) return 'unmarked'
  if (scope.mode === 'all') return 'all'
  return `sessions:${JSON.stringify(normalizeSessionIds(scope.session_ids))}`
}

/**
 * 比较 selector 当前能表达的字段。
 * 后端完整 scope 中的时间与容量快照不参与比较，follow-up 仍沿用 buffer 原快照。
 */
export function selectableScopesEqual(left: ScopeRequest | null, right: ScopeRequest | null): boolean {
  if (left === null || right === null) return left === right
  return scopeKey(left) === scopeKey(right)
}

/** 比较两个 navigation selection 是否指向同一 Source Scope。 */
export function navigationSelectionsEqual(
  left: SelectedSourceScope,
  right: SelectedSourceScope,
): boolean {
  if (left === null || right === null) return left === right
  if (left.kind !== right.kind) return false
  if (left.kind === 'session' && right.kind === 'session') return left.sessionId === right.sessionId
  return true
}

/**
 * 把 navigation selection 编译为 ScopeRequest。
 * 未选择时返回 null——调用方必须先得到非 null 结果才能 New Chat / Send；
 * 这里不存在回退到 all 的 fallback。
 */
export function compileNavigationScope(selection: SelectedSourceScope): ScopeRequest | null {
  if (selection === null) return null
  if (selection.kind === 'all') return { mode: 'all' }
  return { mode: 'sessions', session_ids: [selection.sessionId] }
}

/**
 * 按 immutable conversation scope 恢复合法 navigation selection。
 * multi-session、未知 session 与 legacy null 返回 null：历史可只读回放，
 * 但不映射为合法 primary navigation scope。
 */
export function restoreNavigationScope(
  scope: ScopeRequest | null,
  sessions: readonly SessionDTO[],
): SelectedSourceScope {
  if (scope === null) return null
  if (scope.mode === 'all') return { kind: 'all' }
  const normalized = normalizeSessionIds(scope.session_ids)
  if (normalized.length !== 1) return null
  const sessionId = normalized[0]
  if (!sessionId) return null
  const known = sessions.some((session) => session.session_id === sessionId)
  return known ? { kind: 'session', sessionId } : null
}

/** 使用 Source Session catalog 生成紧凑文案和完整 tooltip。 */
export function describeScope(scope: ScopeRequest | null, sessions: readonly SessionDTO[]): ScopeDisplay {
  if (scope === null) return { label: '未标记范围', title: '未标记范围' }
  if (scope.mode === 'all') return { label: '全部群聊', title: '全部群聊' }

  const sessionNames = new Map(sessions.map((session) => [session.session_id, session.name]))
  const names = normalizeSessionIds(scope.session_ids).map((sessionId) => sessionNames.get(sessionId) ?? sessionId)
  const title = names.join(' + ')

  if (names.length === 1) return { label: names[0] ?? '', title }
  if (names.length === 2) return { label: names.join(' + '), title }
  return { label: `${names.length} 个群聊`, title }
}
