// @vitest-environment happy-dom

import { defineComponent, h, nextTick, ref, shallowRef } from 'vue'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { useFollowTail } from '@/composables/useFollowTail'

describe('conversation reading position', () => {
  it('follows data appends, pauses on upward reading and restores each view', async () => {
    const a = {}, b = {}
    const view = shallowRef<object | null>(a)
    let tail!: ReturnType<typeof useFollowTail>
    const wrapper = mount(defineComponent({ setup() {
      const container = ref<HTMLElement | null>(null)
      tail = useFollowTail(container, view)
      return () => h('div', { ref: container })
    } }))
    const element = wrapper.element as HTMLElement
    let height = 1200
    Object.defineProperties(element, { scrollHeight: { get: () => height }, clientHeight: { value: 400 } })
    tail.scrollToBottom()
    height = 1500
    tail.onContentMutated()
    await nextTick()
    expect(element.scrollTop).toBe(1500)

    // 用户上滚后，新数据不能抢走正在阅读的位置。
    element.dispatchEvent(new WheelEvent('wheel', { deltaY: -100 }))
    element.scrollTop = 240
    element.dispatchEvent(new Event('scroll'))
    tail.onContentMutated()
    await nextTick()
    expect(element.scrollTop).toBe(240)

    view.value = b
    await nextTick(); await nextTick()
    expect(element.scrollTop).toBe(1500)
    view.value = a
    await nextTick(); await nextTick()
    expect(element.scrollTop).toBe(240)
    expect(tail.following.value).toBe(false)
    wrapper.unmount()
  })
})
