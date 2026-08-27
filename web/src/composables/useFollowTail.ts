import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * 浏览器真实 scroll state 的 follow-tail：
 * 底部自动跟随；用户上滚立即暂停；点击"回到最新"恢复。
 */
export function useFollowTail(container: Ref<HTMLElement | null>) {
  const following = ref(true)

  function onScroll(): void {
    const element = container.value
    if (!element) return
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
    if (!following.value) return
    const element = container.value
    if (!element) return
    element.scrollTop = element.scrollHeight
  }

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
