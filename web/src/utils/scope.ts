import type { ScopeRequest, SessionDTO } from '@/types/contracts'

export interface ScopeDisplay {
  label: string
  title: string
}

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
