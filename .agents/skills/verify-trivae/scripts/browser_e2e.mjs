/**
 * Real Chrome -> built Vue UI -> localhost FastAPI -> production Application query
 * -> deterministic SDK model -> SQLite -> citation and canonical source drilldown.
 * All browser traffic must stay on the isolated localhost test server.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve, join } from 'node:path'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../')
const require = createRequire(pathToFileURL(join(root, 'web/package.json')))
const { chromium } = require('playwright-core')

const [baseUrl, evidenceDir, chromePath] = process.argv.slice(2)
assert(baseUrl && evidenceDir && chromePath, 'Usage: browser_e2e.mjs BASE_URL EVIDENCE_DIR CHROME_PATH')
assert.match(baseUrl, /^http:\/\/127\.0\.0\.1:\d+$/, 'Only local fixture server is permitted')
assert(existsSync(chromePath), 'Chrome executable is unavailable')
mkdirSync(evidenceDir, { recursive: true })
const events = []
let browser
let page
try {
  browser = await chromium.launch({ headless: true, executablePath: chromePath, args: ['--no-first-run'] })
  const context = await browser.newContext({ viewport: { width: 1280, height: 850 }, serviceWorkers: 'block' })
  // A local smoke must not fetch fonts, analytics or other external network resources.
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== baseUrl) return route.abort('blockedbyclient')
    return route.continue()
  })
  page = await context.newPage()
  page.on('pageerror', e => events.push({ type: 'pageerror', message: String(e) }))
  page.on('console', m => { if (m.type() === 'error') events.push({ type: 'console-error', message: m.text() }) })
  page.on('response', r => {
    if (r.url().startsWith(baseUrl + '/api/')) events.push({ type: 'response', url: new URL(r.url()).pathname, status: r.status() })
  })
  await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 25000 })
  await page.getByTestId('scope-session-qq:100').click()
  await page.getByTestId('current-scope').getByText('回复实验').waitFor()
  await page.getByRole('textbox', { name: '输入问题' }).fill('这个项目有没有实际使用反馈？')
  await page.getByRole('button', { name: '发送问题' }).click()
  const answer = page.locator('article.assistant-turn')
  await answer.waitFor({ timeout: 25000 })
  // Deliberately assert provenance in the visible browser, not only API status.
  await answer.getByRole('button', { name: /来源 · 1/ }).waitFor({ timeout: 10000 })
  assert.match(await answer.innerText(), /有人实际用过并推荐这个项目/)
  await answer.getByRole('button', { name: /来源 · 1/ }).click()
  const dialog = page.getByRole('dialog', { name: '回答的消息来源' })
  await dialog.waitFor({ timeout: 10000 })
  assert.match(await dialog.innerText(), /实际用过，值得推荐/)
  await dialog.getByRole('button', { name: '查看完整原消息' }).click()
  await dialog.locator('[data-source-content]').getByText('实际用过，值得推荐').waitFor({ timeout: 12000 })
  assert.equal((await dialog.locator('[data-source-content]').innerText()).trim(), '实际用过，值得推荐')
  await page.screenshot({ path: join(evidenceDir, 'source-open.png'), fullPage: true })
  await dialog.getByRole('button', { name: /关闭来源面板/ }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert(!events.some(e => e.type === 'pageerror'), 'Browser raised an unhandled JavaScript error')

  // Verify real backend persistence and Trace; not mocked fetch responses.
  const conversationId = new URL(page.url()).searchParams.get('conversation_id')
  assert(conversationId, 'URL must retain the created conversation')
  const response = await context.request.get(baseUrl + '/api/conversations/' + encodeURIComponent(conversationId))
  assert.equal(response.status(), 200, 'Conversation must be persisted in SQLite')
  const conversation = await response.json()
  const saved = conversation.messages.find(m => m.role === 'assistant')
  assert(saved?.trace_id, 'Saved assistant message must include a persisted Trace ID')
  assert(Array.isArray(saved?.sources) && saved.sources.length === 1, 'Saved assistant message must include its bound source')
  const trace = await context.request.get(baseUrl + '/api/traces/' + encodeURIComponent(saved.trace_id))
  assert.equal(trace.status(), 200, 'Trace must be readable through production API')

  await page.screenshot({ path: join(evidenceDir, 'browser-success.png'), fullPage: true })
  console.log('BROWSER_E2E_PASS: real Chrome / Vue / FastAPI / SQLite / SDK / citations / source drilldown / Trace')
} catch (error) {
  if (page) await page.screenshot({ path: join(evidenceDir, 'browser-failure.png'), fullPage: true }).catch(() => {})
  console.error('BROWSER_E2E_FAIL:', error?.stack ?? error)
  process.exitCode = 1
} finally {
  writeFileSync(join(evidenceDir, 'network-and-errors.json'), JSON.stringify(events, null, 2) + '\n')
  if (browser) await browser.close().catch(() => {})
}
