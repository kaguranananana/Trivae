// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AssistantTurn from '@/components/chat/AssistantTurn.vue'
import type { AssistantItem } from '@/stores/chat'

const trustedUrl = 'https://github.com/example/repo?tab=readme#overview'

function assistantItem(sources: AssistantItem['sources']): AssistantItem {
  return {
    id: 'assistant-1',
    role: 'assistant',
    answer: `可信链接：${trustedUrl}，错误扩展：${trustedUrl}ABC。`,
    blocks: [],
    status: 'completed',
    degraded: false,
    sources,
    limitations: [],
    traceId: null,
    startedAt: 1_725_000_000_000,
    durationMs: null,
    processProjection: null,
    interrupted: false,
  }
}

describe('AssistantTurn trusted URL wiring', () => {
  afterEach(() => vi.restoreAllMocks())

  it('opens the bound source and returns focus to the paragraph citation', async () => {
    const item = assistantItem([{ index: 2, kind: 'structured', evidence_ids: ['e2'], relations: ['supports'], locator_kind: 'aggregate', locator: 'count', value: 2 }])
    item.answer = '两条消息。'
    item.answerBlocks = [{ block_id: 'b1', text: item.answer, source_indices: [2] }]
    const wrapper = mount(AssistantTurn, { attachTo: document.body, props: { item, conversationId: null } })
    const citation = wrapper.get('[aria-label="查看来源 2"]')
    await citation.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('dialog').attributes('open')).toBeDefined()
    expect(wrapper.get('.source-selected').text()).toContain('[2]')
    await wrapper.get('[aria-label="关闭来源面板，返回正文"]').trigger('click')
    expect(document.activeElement).toBe(citation.element)
    expect(wrapper.get('dialog').attributes('open')).toBeUndefined()
    wrapper.unmount()
  })
  it('derives trusted URLs from source snapshots instead of answer text', () => {
    const wrapper = mount(AssistantTurn, {
      props: {
        item: assistantItem([{
          index: 1,
          kind: 'message',
          evidence_ids: ['evidence-1'],
          relations: ['supports'],
          snapshot: {
            session_display: '可信会话',
            author_display: '可信作者',
            timestamp_ms: 1_725_000_000_000,
            timezone: 'UTC',
            excerpt: 'canonical excerpt',
            excerpt_truncated: false,
            source_message_id: 'message-1',
            urls: [trustedUrl],
          },
        }]),
        conversationId: null,
      },
    })

    const answer = wrapper.find('.md-body')
    expect(answer.find('a').attributes('href')).toBe(trustedUrl)
    expect(answer.html()).not.toContain(`href="${trustedUrl}ABC"`)
  })

  it('does not turn a URL in an answer without Sources into a link', () => {
    const wrapper = mount(AssistantTurn, {
      props: {
        item: assistantItem([]),
        conversationId: null,
      },
    })

    expect(wrapper.find('.md-body a').exists()).toBe(false)
    expect(wrapper.find('.md-body').text()).toContain(trustedUrl)
    expect(wrapper.findComponent({ name: 'SourcesBlock' }).exists()).toBe(false)
  })

  it('copies the original answer and shows clipboard errors', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(writeText)
    const item = assistantItem([])
    const wrapper = mount(AssistantTurn, { props: { item, conversationId: null } })
    await wrapper.get('[aria-label="复制回答"]').trigger('click')
    expect(writeText).toHaveBeenCalledWith(item.answer)
    expect(wrapper.get('[aria-label="已复制回答"]').text()).toContain('已复制')
    writeText.mockRejectedValueOnce(new Error('浏览器拒绝剪贴板权限'))
    await wrapper.get('[aria-label="已复制回答"]').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('浏览器拒绝剪贴板权限')
    wrapper.unmount()
  })

})
