import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown trusted URL contract', () => {
  it('renders only an exact trusted URL and keeps link attributes', () => {
    const trustedUrl = 'https://github.com/example/repo?tab=readme#overview'
    const html = renderMarkdown(
      `可信 ${trustedUrl}，扩展 ${trustedUrl}ABC，其他 https://github.com/example/repo-wrong。`,
      [trustedUrl],
    )

    expect((html.match(/<a\b/g) ?? []).length).toBe(1)
    expect(html).toContain(`href="${trustedUrl}"`)
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain(`${trustedUrl}ABC`)
    expect(html).not.toContain(`href="${trustedUrl}ABC"`)
    expect(html).not.toContain('href="https://github.com/example/repo-wrong"')
  })

  it('checks explicit Markdown links and autolinks against the same exact set', () => {
    const trustedUrl = 'https://example.com/docs/%E4%B8%AD%E6%96%87?x=a%20b#readme'
    const html = renderMarkdown(
      `[可信](${trustedUrl}) [错误](https://example.com/docs/wrong) <${trustedUrl}>`,
      [trustedUrl],
    )

    expect((html.match(/<a\b/g) ?? []).length).toBe(2)
    expect(html).toContain(`href="${trustedUrl}"`)
    expect(html).not.toContain('href="https://example.com/docs/wrong"')
    expect(html).toContain('可信')
    expect(html).toContain('错误')
  })

  it('does not make a URL clickable without a canonical source', () => {
    const html = renderMarkdown(
      '请查看 https://example.com/not-a-source，也不要打开[错误链接](https://example.com/wrong)。',
      [],
    )

    expect(html).not.toMatch(/<a\b/)
    expect(html).toContain('https://example.com/not-a-source')
    expect(html).toContain('错误链接')
  })

  it('treats Chinese punctuation as a boundary while rejecting URL continuations', () => {
    const trustedUrl = 'https://example.com/resource'
    const html = renderMarkdown(
      `（${trustedUrl}），${trustedUrl}?next=1，以及 ${trustedUrl}ABC。`,
      [trustedUrl],
    )

    expect((html.match(/<a\b/g) ?? []).length).toBe(1)
    expect(html).toContain(`href="${trustedUrl}"`)
    expect(html).toContain(`${trustedUrl}?next=1`)
    expect(html).toContain(`${trustedUrl}ABC`)
  })

  it('preserves Markdown formatting and code text without creating links', () => {
    const trustedUrl = 'https://example.com/code'
    const html = renderMarkdown(
      `**说明** ${trustedUrl}\n\n\`${trustedUrl}\`\n\n\`\`\`text\n${trustedUrl}\n\`\`\``,
      [trustedUrl],
    )

    expect(html).toContain('<strong>说明</strong>')
    expect((html.match(/<a\b/g) ?? []).length).toBe(1)
    expect(html).toContain(`<code>${trustedUrl}</code>`)
    expect(html).toContain(`<pre><code class="language-text">${trustedUrl}\n</code></pre>`)
  })

  it('keeps HTML disabled and includes trusted URLs in the cache key', () => {
    const trustedUrl = 'https://example.com/cache-key'
    const text = `<b>raw</b> ${trustedUrl}`
    const trustedHtml = renderMarkdown(text, [trustedUrl])
    const untrustedHtml = renderMarkdown(text, [])

    expect(trustedHtml).toContain('&lt;b&gt;raw&lt;/b&gt;')
    expect(trustedHtml).toMatch(/<a\b/)
    expect(untrustedHtml).not.toMatch(/<a\b/)
  })
})
