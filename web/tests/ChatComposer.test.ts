// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatComposer from '@/components/composer/ChatComposer.vue'

/** 真实输入事件验证发送门禁和草稿保留，避免只断言按钮样式。 */
describe('ChatComposer interaction', () => {
  it('sends trimmed text with Enter and keeps Shift+Enter as a newline', async () => {
    const wrapper = mount(ChatComposer, { props: { running: false } })
    const input = wrapper.get('textarea')
    await input.setValue('  总结近期讨论  ')
    await input.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(wrapper.emitted('send')).toBeUndefined()
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('send')).toEqual([['总结近期讨论', expect.any(Function)]])
    // 发送接收确认以前保留输入，确认以后才清空。
    expect((input.element as HTMLTextAreaElement).value).toBe('  总结近期讨论  ')
    ;(wrapper.emitted('send')![0]![1] as () => void)()
    await wrapper.vm.$nextTick()
    expect((input.element as HTMLTextAreaElement).value).toBe('')
  })

  it.each([{ running: true, busy: false, disabled: false }, { running: false, busy: true, disabled: false }, { running: false, busy: false, disabled: true }])('does not erase or submit drafts while unavailable: %j', async (props) => {
    const wrapper = mount(ChatComposer, { props })
    await wrapper.get('textarea').setValue('尚未发送的草稿')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('send')).toBeUndefined()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('尚未发送的草稿')
    if (props.running) {
      await wrapper.get('[aria-label="停止生成"]').trigger('click')
      expect(wrapper.emitted('stop')).toHaveLength(1)
    }
  })

  it('does not send while confirming Chinese composition', async () => {
    const wrapper = mount(ChatComposer, { props: { running: false } })
    const input = wrapper.get('textarea')
    await input.setValue('中文问题')
    await input.trigger('compositionstart')
    await input.trigger('keydown', { key: 'Enter' })
    await input.trigger('compositionend')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.emitted('send')).toBeUndefined()
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('send')).toEqual([['中文问题', expect.any(Function)]])
  })

  it('keeps new input typed while the previous question is being accepted', async () => {
    const wrapper = mount(ChatComposer, { props: { running: false, contextKey: 'a' } })
    await wrapper.get('textarea').setValue('旧问题')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    const accepted = wrapper.emitted('send')![0]![1] as () => void
    await wrapper.get('textarea').setValue('等待期间编辑的新问题')
    accepted()
    await wrapper.vm.$nextTick()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('等待期间编辑的新问题')
    wrapper.unmount()
  })

  it('restores each conversation draft when switching contexts', async () => {
    const wrapper = mount(ChatComposer, { props: { running: false, contextKey: 'conversation-a' } })
    await wrapper.get('textarea').setValue('A 的草稿')
    await wrapper.setProps({ contextKey: 'conversation-b' })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
    await wrapper.get('textarea').setValue('B 的草稿')
    await wrapper.setProps({ contextKey: 'conversation-a' })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('A 的草稿')
    await wrapper.setProps({ contextKey: 'conversation-b' })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('B 的草稿')
  })

  it('keeps text written during creation when the same buffer becomes a saved conversation', async () => {
    const buffer = { key: '__draft__:all' }
    const wrapper = mount(ChatComposer, { props: { running: false, busy: true, contextKey: buffer } })
    await wrapper.get('textarea').setValue('等待创建期间写下的问题')
    // 创建对话仅改变 buffer 的标识，输入上下文仍是同一个对话。
    buffer.key = 'saved-conversation'
    await wrapper.setProps({ contextKey: buffer, running: true })
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('等待创建期间写下的问题')
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('send')).toBeUndefined()
  })

})
