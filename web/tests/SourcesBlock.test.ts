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
