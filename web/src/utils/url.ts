import type { SelectedSourceScope } from '@/utils/scope'

/**
 * 轻量导航URL：管理正式会话与范围草稿，不引入额外路由框架。
 *
 * 主动导航使用pushState支持前进后退；首次发送将同一个草稿条目replace为正式会话。
 */

const CONVERSATION_QUERY_PARAM = 'conversation_id'

export function readConversationIdFromUrl(): string | null {
  const value = new URLSearchParams(window.location.search).get(CONVERSATION_QUERY_PARAM)
  return value && value.trim() ? value : null
}

export function writeConversationIdToUrl(conversationId: string | null): void {
  const url = new URL(window.location.href)
  if (conversationId) {
    url.searchParams.set(CONVERSATION_QUERY_PARAM, conversationId)
    url.searchParams.delete('scope')
    url.searchParams.delete('session_id')
  } else {
    url.searchParams.delete(CONVERSATION_QUERY_PARAM)
  }
  window.history.replaceState(null, '', url)
}

/** 范围草稿也可刷新恢复；正式会话仍以其不可变scope为准。 */
export function readScopeFromUrl(): SelectedSourceScope {
  const params = new URLSearchParams(window.location.search)
  if (params.get('scope') === 'all') return { kind: 'all' }
  const sessionId = params.get('session_id')
  return sessionId ? { kind: 'session', sessionId } : null
}

/** 用户主动导航创建历史条目，数据加载和草稿转正使用replace。 */
export function writeNavigationToUrl(conversationId: string | null, selection: SelectedSourceScope): void {
  const url = new URL(window.location.href)
  url.searchParams.delete('conversation_id')
  url.searchParams.delete('scope')
  url.searchParams.delete('session_id')
  if (conversationId) url.searchParams.set('conversation_id', conversationId)
  else if (selection?.kind === 'all') url.searchParams.set('scope', 'all')
  else if (selection?.kind === 'session') url.searchParams.set('session_id', selection.sessionId)
  if (url.href !== window.location.href) window.history.pushState(null, '', url)
}
