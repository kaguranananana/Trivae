<script setup lang="ts">
/** 输入框：按对话隔离草稿，自动增高，中文组字期间不会发送。 */
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  disabled?: boolean
  busy?: boolean
  running: boolean
  contextKey?: string | object | null
}>()
const emit = defineEmits<{ send: [query: string]; stop: [] }>()
const draft = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const composing = ref(false)
// 草稿只保存在当前页面内存中，按 scope draft / conversation key 隔离。
// App 传入稳定的 buffer 对象；草稿转正式对话只改 key，不会切走正在编辑的输入。
const drafts = new Map<string | object, string>()

watch(() => props.contextKey, (key, previousKey) => {
  // 把离开的对话与草稿绑定，返回时才能恢复原文。
  if (previousKey) drafts.set(previousKey, draft.value)
  // 未选范围使用空输入，避免向其他对话暴露旧草稿。
  draft.value = key ? drafts.get(key) ?? '' : ''
})

/** 先还原高度，再按真实内容高度增长；超过上限后只滚动输入区。 */
function resize(): void {
  const element = textarea.value
  if (!element) return
  // 去除上次固定高度，使删除文本后也能收缩。
  element.style.height = 'auto'
  // 内容最多占 200px，长问题留在输入区内滚动。
  element.style.height = `${Math.min(element.scrollHeight, 200)}px`
}
watch(draft, () => { void nextTick(resize) })

function focus(): void {
  if (!props.disabled) textarea.value?.focus()
}
function setDraft(query: string): void {
  draft.value = query
  focus()
}
defineExpose({ focus, setDraft })

function submit(): void {
  // 门禁必须在清空草稿之前，避免生成中按 Enter 导致文字丢失。
  if (props.disabled || props.running || props.busy || composing.value) return
  // 去除首尾空白，保持问题正文的换行。
  const query = draft.value.trim()
  // 空问题不触发请求。
  if (!query) return
  // 通过门禁后才清空已提交的内容。
  draft.value = ''
  // 向父组件提交问题，后端调用仍由现有 store 负责。
  emit('send', query)
  focus()
}
function onKeydown(event: KeyboardEvent): void {
  // 浏览器原生组字状态与 composition 事件共同保证中文确认键不触发发送。
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || composing.value) return
  event.preventDefault()
  submit()
}
</script>

<template>
  <footer class="composer-footer">
    <div class="composer-box" :class="{ 'composer-disabled': disabled }">
      <textarea ref="textarea" v-model="draft" rows="1" aria-label="输入问题" :placeholder="disabled ? '选择聊天范围后，即可开始提问' : '向 Trivae 提问…'" :disabled="disabled" @input="resize" @compositionstart="composing = true" @compositionend="composing = false" @keydown="onKeydown" />
      <div class="composer-toolbar">
        <span class="composer-context">{{ running ? '正在检索与整理，你可以先写下一条问题' : busy ? '有问题正在处理中，请稍候…' : '基于聊天记录回答' }}</span>
        <button v-if="running" class="send-button stop-button" aria-label="停止生成" title="停止生成（Esc）" @click="emit('stop')"><span class="stop-square" /></button>
        <button v-else class="send-button" aria-label="发送问题" title="发送问题（Enter）" :disabled="disabled || busy || !draft.trim()" @click="submit">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" /></svg>
        </button>
      </div>
    </div>
    <div class="composer-hint"><span>Enter 发送 · Shift+Enter 换行</span><span>回答可通过消息来源核实</span></div>
  </footer>
</template>
