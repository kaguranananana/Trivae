// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SourcesBlock from '@/components/chat/SourcesBlock.vue'
import type { SourceItem } from '@/types/contracts'

const messageSource: SourceItem = {
  index: 1,
  kind: 'message',
  evidence_ids: ['evidence-1'],
  relations: ['supports'],
  snapshot: {
    session_display: 'GitHub 讨论组',
    author_display: 'Alice',
    timestamp_ms: 1_725_000_000_000,
    timezone: 'UTC',
    excerpt: 'canonical source excerpt',
    excerpt_truncated: false,
    source_message_id: 'message-1',
    urls: ['https://github.com/example/repo'],
  },
}

const structuredSource: SourceItem = {
  index: 2,
  kind: 'structured',
  evidence_ids: ['evidence-2'],
  relations: ['context'],
  locator_kind: 'aggregate',
  locator: 'total_count',
  value: 42,
}

describe('SourcesBlock', () => {
  it('starts collapsed, expands complete details, and collapses again', async () => {
    const wrapper = mount(SourcesBlock, { props: { sources: [messageSource, structuredSource] } })
    const button = wrapper.get('button')

    expect(button.attributes('type')).toBe('button')
    expect(button.attributes('aria-expanded')).toBe('false')
    expect(button.text()).toBe('▶ Sources · 2')
    expect(wrapper.find('ol').exists()).toBe(false)

    await button.trigger('click')
    expect(button.attributes('aria-expanded')).toBe('true')
    expect(button.text()).toBe('▼ Sources · 2')
    expect(wrapper.find('ol').text()).toContain('Alice')
    expect(wrapper.find('ol').text()).toContain('GitHub 讨论组')
    expect(wrapper.find('ol').text()).toContain('canonical source excerpt')
    expect(wrapper.find('ol').text()).toContain('aggregate:total_count')
    expect(wrapper.find('ol').text()).toContain('42')

    await button.trigger('click')
    expect(button.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('ol').exists()).toBe(false)
  })

  it('does not render an empty Sources block', () => {
    const wrapper = mount(SourcesBlock, { props: { sources: [] } })

    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.find('ol').exists()).toBe(false)
  })

  it('shows internal sender, original time, forwarded time and the precise export location', async () => {
    // 同一个 child snapshot 同时保存两种时间，界面必须明确它们分别代表什么。
    const forwarded: SourceItem = {
      ...messageSource,
      snapshot: {
        ...messageSource.snapshot!,
        source_message_id: 'inside-1',
        sender_platform_id: 'u-original',
        sender_uin: '12345',
        forward: {
          root_message_id: 'qq:100:outer',
          parent_message_id: 'qq:100:outer#forward:0.1',
          path: 'content.elements[0].data.messages[1].content.elements[0].data.messages[2]',
          original_timestamp: 1_720_000_000_000,
          root_source_message_id: 'outer',
          source_file: 'raw/group(100).json',
          source_record_index: 6235,
        },
      },
    }
    const wrapper = mount(SourcesBlock, { props: { sources: [forwarded] } })
    await wrapper.get('button').trigger('click')
    const text = wrapper.get('ol').text()

    expect(text).toContain('转发到本群：')
    expect(text).toContain('原始发送：')
    expect(text).toContain(new Date(1_720_000_000_000).toLocaleString('zh-CN', { hour12: false }))
    expect(text).toContain(new Date(messageSource.snapshot!.timestamp_ms).toLocaleString('zh-CN', { hour12: false }))
    expect(text).toContain('内部消息 ID：inside-1')
    expect(text).toContain('发送者 ID：u-original')
    expect(text).toContain('QQ：12345')
    expect(text).toContain('外层消息：qq:100:outer')
    expect(text).toContain('直接父消息：qq:100:outer#forward:0.1')
    expect(text).toContain('来源文件：group(100).json · messages[6235].content.elements[0]')
    expect(text).not.toContain('raw/group(100).json')
  })

  it('states that empty exported nodes are missing without presenting the preview as content', async () => {
    const missing: SourceItem = {
      ...messageSource,
      snapshot: {
        ...messageSource.snapshot!,
        unexpanded_forward_paths: ['content.elements[0].data.messages[2].content.elements[0]'],
      },
    }
    const wrapper = mount(SourcesBlock, { props: { sources: [missing] } })
    await wrapper.get('button').trigger('click')

    expect(wrapper.get('ol').text()).toContain('导出 messages=[]；预览不能代表缺失正文')
    expect(wrapper.get('ol').text()).toContain('content.elements[0].data.messages[2].content.elements[0]')
    expect(wrapper.get('ol').text()).not.toContain('转发到本群：')
  })

  it('keeps expansion state independent across turns and resets on replay mount', async () => {
    const firstTurn = mount(SourcesBlock, { props: { sources: [messageSource] } })
    const secondTurn = mount(SourcesBlock, { props: { sources: [structuredSource] } })

    await firstTurn.get('button').trigger('click')
    expect(firstTurn.find('ol').exists()).toBe(true)
    expect(secondTurn.find('ol').exists()).toBe(false)

    firstTurn.unmount()
    const replayTurn = mount(SourcesBlock, { props: { sources: [messageSource] } })
    expect(replayTurn.get('button').attributes('aria-expanded')).toBe('false')
    expect(replayTurn.find('ol').exists()).toBe(false)
  })
})
