import MarkdownIt from 'markdown-it'

/** answer/thinking 的 Markdown 渲染：禁 HTML、自动链接、LRU 缓存（同 ChatLab）。 */

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
})

const defaultLinkOpen = md.renderer.rules.link_open
md.renderer.rules.link_open = (tokens, index, options, environment, self) => {
  const token = tokens[index]
  if (token) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
  return defaultLinkOpen ? defaultLinkOpen(tokens, index, options, environment, self) : self.renderToken(tokens, index, options)
}

const MAX_CACHE_ENTRIES = 32
const cache = new Map<string, string>()

export function renderMarkdown(text: string): string {
  if (!text) return ''
  const cached = cache.get(text)
  if (cached !== undefined) {
    cache.delete(text)
    cache.set(text, cached)
    return cached
  }
  const rendered = md.render(text)
  cache.set(text, rendered)
  if (cache.size > MAX_CACHE_ENTRIES) {
    const oldest = cache.keys().next().value ?? null
    if (oldest !== null) cache.delete(oldest)
  }
  return rendered
}
