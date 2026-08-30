/**
 * 窄的 URL query helper：只管理 conversation_id，不引入 Vue Router。
 *
 * 当前 conversation 写入 URL query 供 reload 恢复；scope switch / New Chat /
 * delete current 时清除。写入使用 history.replaceState，不产生导航历史。
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
  } else {
    url.searchParams.delete(CONVERSATION_QUERY_PARAM)
  }
  window.history.replaceState(null, '', url)
}
