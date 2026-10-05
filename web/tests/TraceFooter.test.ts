// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TraceFooter from '@/components/chat/TraceFooter.vue'

/** 调试入口收起后仍使用真实 API 契约，复制失败必须可见。 */
describe('TraceFooter details', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('starts collapsed and copies the trace path returned by the server', async () => {
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ path: '/tmp/trace.jsonl' })))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(TraceFooter, { props: { traceId: 'trace-1', durationMs: 1500 } })
    expect(wrapper.get('details').attributes('open')).toBeUndefined()
    expect(wrapper.get('summary').text()).toContain('1.5 秒')
    await wrapper.findAll('button').find((button) => button.text() === '复制文件路径')!.trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/api/traces/trace-1/path', { headers: { 'Content-Type': 'application/json' } })
    expect(writeText).toHaveBeenCalledWith('/tmp/trace.jsonl')
    expect(wrapper.get('[role="status"]').text()).toBe('已复制路径')
  })

  it('shows clipboard rejection without claiming success', async () => {
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('剪贴板不可用'))
    const wrapper = mount(TraceFooter, { props: { traceId: 'trace-1' } })
    await wrapper.findAll('button').find((button) => button.text() === '复制 Trace ID')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('剪贴板不可用')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
