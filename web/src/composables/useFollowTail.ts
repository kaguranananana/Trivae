import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/**
 * 浏览器真实 scroll state 的 follow-tail：
 * 底部自动跟随；用户上滚立即暂停；点击"回到最新"恢复。
 */
export function useFollowTail(container: Ref<HTMLElement | null>, view?: Ref<object | null>) {
  // 用稳定buffer对象保存位置，草稿转正式会话改名不会丢失阅读状态。
  const positions = new WeakMap<object, { top: number; following: boolean }>()
  let switching = false
  const following = ref(true)

  function onScroll(): void {
    const element = container.value
    if (!element || switching) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    following.value = distance < 40
  }

  function scrollToBottom(): void {
    const element = container.value
    if (!element) return
    element.scrollTop = element.scrollHeight
    following.value = true
  }

  function onContentMutated(): void {
    if (!following.value || switching) return
    const element = container.value
    if (!element) return
    // 等流式文本渲染进 DOM 后再读取高度，避免最后一段被输入区遮住。
    const owner = view?.value
    void nextTick(() => {
      if (following.value && !switching && view?.value === owner) element.scrollTop = element.scrollHeight
    })
  }

  if (view) watch(view, async (current, previous) => {
    const element = container.value
    if (!element) return
    // DOM更新前读取离开页面的位置，再等待新页面实际渲染。
    if (previous) positions.set(previous, { top: element.scrollTop, following: following.value })
    switching = true
    await nextTick()
    if (view.value !== current) return
    const saved = current ? positions.get(current) : undefined
    following.value = saved?.following ?? true
    element.scrollTop = saved && !saved.following ? saved.top : element.scrollHeight
    switching = false
  })

  function onWheel(event: WheelEvent): void {
    if (event.deltaY < 0) following.value = false
  }

  onMounted(() => {
    container.value?.addEventListener('scroll', onScroll, { passive: true })
    container.value?.addEventListener('wheel', onWheel, { passive: true })
  })

  onBeforeUnmount(() => {
    container.value?.removeEventListener('scroll', onScroll)
    container.value?.removeEventListener('wheel', onWheel)
  })

  return { following, scrollToBottom, onContentMutated }
}
