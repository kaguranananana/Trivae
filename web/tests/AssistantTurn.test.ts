// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'
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
})
