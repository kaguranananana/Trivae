import MarkdownIt from 'markdown-it'
import type StateCore from 'markdown-it/lib/rules_core/state_core.mjs'
import type Token from 'markdown-it/lib/token.mjs'

interface MarkdownRenderEnvironment {
  trustedUrls?: readonly string[]
}

/** answer/thinking 的 Markdown 渲染：禁 HTML，只渲染 canonical trusted URL，保留 LRU 缓存。 */

const md = new MarkdownIt({
  html: false,
  breaks: true,
  // 不启用 MarkdownIt 的全量 linkify，正文 URL 必须经过 trusted snapshot 精确匹配。
  linkify: false,
  typographer: true,
})

const defaultLinkOpen = md.renderer.rules.link_open
md.renderer.rules.link_open = (tokens, index, options, environment, self) => {
  const token = tokens[index]
  if (token) {
    // 只有 token 层已经通过 exact trusted URL 校验的链接才会到达这里。
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
  return defaultLinkOpen ? defaultLinkOpen(tokens, index, options, environment, self) : self.renderToken(tokens, index, options)
}

const MAX_CACHE_ENTRIES = 32
const cache = new Map<string, string>()
const INVALID_PERCENT_ESCAPE = /%(?![0-9A-Fa-f]{2})/
const ASCII_URL_CONTINUATION = /^[A-Za-z0-9/?#%&=:+~_@-]$/
const ASCII_WORD = /^[A-Za-z0-9]$/

function isHttpUrl(value: string): boolean {
  // 前端再次确认协议和 percent escape，避免旧 snapshot 的坏值成为导航目标。
  if (!value || value.trim() !== value || INVALID_PERCENT_ESCAPE.test(value)) return false
  try {
    const parsed = new URL(value)
    // URL 对象只用于验证；href 仍然使用 snapshot 原文，保证 exact canonical contract。
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && md.validateLink(value)
  } catch {
    // malformed snapshot URL 不是可渲染链接，普通回答文本仍然照常渲染。
    return false
  }
}

function normalizedTrustedUrls(input: readonly string[] | undefined): string[] {
  // Set 同时去重，保证同一回答的 cache key 与渲染集合稳定。
  const unique = new Set<string>()
  for (const value of input ?? []) {
    if (isHttpUrl(value)) unique.add(value)
  }
  // 统一排序只用于 cache key；匹配阶段会按长度重新排序以处理 URL 前缀关系。
  return [...unique].sort()
}

function isContinuationAfter(text: string, end: number): boolean {
  const next = text[end]
  if (!next) return false
  // query、fragment、路径和 ASCII 单词字符继续出现时，不能把 trusted URL 的短前缀单独链接。
  if (ASCII_URL_CONTINUATION.test(next)) return true
  // 句末的单独句号是边界，但 `.html` 这类 ASCII 扩展仍属于同一个错误 token。
  return next === '.' && ASCII_WORD.test(text[end + 1] ?? '')
}

function isContinuationBefore(text: string, start: number): boolean {
  const previous = text[start - 1]
  // 不在 ASCII 单词中间插入链接；中文相邻文本可以作为自然边界。
  return previous !== undefined && ASCII_WORD.test(previous)
}

function findTrustedUrlAt(text: string, start: number, trustedUrls: readonly string[]): string | null {
  for (const url of trustedUrls) {
    if (!text.startsWith(url, start)) continue
    // 同时检查前后边界，避免只匹配 canonical URL 的 substring/prefix。
    if (isContinuationBefore(text, start) || isContinuationAfter(text, start + url.length)) continue
    return url
  }
  return null
}

function createTrustedLinkTokens(
  url: string,
  tokenConstructor: StateCore['Token'],
): Token[] {
  // 用 Markdown token 构造链接，让 renderer 继续负责 HTML escaping 和属性输出。
  const linkOpen = new tokenConstructor('link_open', 'a', 1)
  linkOpen.attrSet('href', url)
  const linkText = new tokenConstructor('text', '', 0)
  linkText.content = url
  const linkClose = new tokenConstructor('link_close', 'a', -1)
  return [linkOpen, linkText, linkClose]
}

function linkifyTrustedText(
  text: string,
  trustedUrls: readonly string[],
  tokenConstructor: StateCore['Token'],
): Token[] {
  const tokens: Token[] = []
  let cursor = 0

  while (cursor < text.length) {
    let matchStart = -1
    let matchUrl: string | null = null

    // 从当前游标向后扫描，保证先处理最早出现的 URL；同一位置由 helper 选择最长 URL。
    for (let candidateStart = cursor; candidateStart < text.length; candidateStart += 1) {
      const candidateUrl = findTrustedUrlAt(text, candidateStart, trustedUrls)
      if (candidateUrl !== null) {
        matchStart = candidateStart
        matchUrl = candidateUrl
        break
      }
    }

    if (matchStart < 0 || matchUrl === null) break

    // 普通文本先原样保留，只有 exact trusted URL 片段转换成链接 token。
    if (matchStart > cursor) {
      const textToken = new tokenConstructor('text', '', 0)
      textToken.content = text.slice(cursor, matchStart)
      tokens.push(textToken)
    }
    tokens.push(...createTrustedLinkTokens(matchUrl, tokenConstructor))
    cursor = matchStart + matchUrl.length
  }

  // 把最后未匹配的正文保留为普通 text token。
  if (cursor < text.length) {
    const textToken = new tokenConstructor('text', '', 0)
    textToken.content = text.slice(cursor)
    tokens.push(textToken)
  }
  return tokens
}

function transformInlineTokens(
  children: Token[],
  trustedUrls: readonly string[],
  tokenConstructor: StateCore['Token'],
): Token[] {
  const trustedSet = new Set(trustedUrls)
  const transformed: Token[] = []
  const linkStack: boolean[] = []

  for (const token of children) {
    if (token.type === 'link_open') {
      // 显式 Markdown link 的 href 也必须是 snapshot 中完全相同的 canonical URL。
      const href = token.attrGet('href')
      const trusted = href !== null && trustedSet.has(href)
      linkStack.push(trusted)
      // 不可信链接只移除 wrapper，保留其 label 和其他 Markdown children。
      if (trusted) transformed.push(token)
      continue
    }

    if (token.type === 'link_close') {
      // 与对应 link_open 对称处理，避免留下半个 HTML anchor。
      if (linkStack.pop()) transformed.push(token)
      continue
    }

    if (linkStack.length > 0) {
      // 显式链接内部不再次自动 linkify，避免改变 label 的原始 Markdown 语义。
      transformed.push(token)
      continue
    }

    if (token.type !== 'text' || token.content.length === 0) {
      // code、fence、image 和其他 token 不进入正文 URL 自动匹配。
      transformed.push(token)
      continue
    }

    transformed.push(...linkifyTrustedText(token.content, trustedUrls, tokenConstructor))
  }

  return transformed
}

md.core.ruler.after('inline', 'trusted-links', (state) => {
  // trusted URL 由 AssistantTurn 从 SourceItem.snapshot.urls 传入，renderer 不读取 excerpt 或答案猜测。
  const environment = state.env as MarkdownRenderEnvironment | undefined
  const trustedUrls = normalizedTrustedUrls(environment?.trustedUrls)
  const matchingTrustedUrls = [...trustedUrls].sort(
    (left, right) => right.length - left.length || left.localeCompare(right),
  )
  // 只有 inline token 的 children 是可渲染的 Markdown 正文，代码块等 self-closing token 会被跳过。
  for (const token of state.tokens) {
    if (token.type === 'inline' && token.children) {
      token.children = transformInlineTokens(token.children, matchingTrustedUrls, state.Token)
    }
  }
})

export function renderMarkdown(text: string, trustedUrls: readonly string[] = []): string {
  if (!text) return ''

  // cache key 必须同时包含正文和 trusted set，防止同一正文在不同来源集合间串用 HTML。
  const normalizedUrls = normalizedTrustedUrls(trustedUrls)
  const cacheKey = JSON.stringify([text, normalizedUrls])
  const cached = cache.get(cacheKey)
  if (cached !== undefined) {
    cache.delete(cacheKey)
    cache.set(cacheKey, cached)
    return cached
  }

  const rendered = md.render(text, { trustedUrls: normalizedUrls })
  cache.set(cacheKey, rendered)
  if (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next().value ?? null
    if (oldest !== null) cache.delete(oldest)
  }
  return rendered
}
