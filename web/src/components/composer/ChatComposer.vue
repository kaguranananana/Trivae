<script setup lang="ts">
/**
 * 输入区：Enter 发送（IME 组字期间不发送）、Shift+Enter 换行；运行中 Send → Stop。
 */
import { ref } from 'vue'

defineProps<{
  disabled?: boolean
  running: boolean
}>()

const emit = defineEmits<{
  send: [query: string]
  stop: []
}>()

const draft = ref('')
const composing = ref(false)

function submit(): void {
  const query = draft.value.trim()
  if (!query) return
  draft.value = ''
  emit('send', query)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !composing.value) {
    event.preventDefault()
    submit()
  }
}
</script>

<template>
  <footer class="border-t border-default px-4 py-3">
    <div class="mx-auto flex max-w-3xl items-end gap-2">
      <textarea
        v-model="draft"
        rows="1"
        placeholder="Ask Trivae…"
        class="max-h-40 min-h-11 flex-1 resize-y rounded-xl border border-default bg-default px-3 py-2 text-sm outline-none focus:border-primary"
        :disabled="disabled"
        @compositionstart="composing = true"
        @compositionend="composing = false"
        @keydown="onKeydown"
      />
      <button
        v-if="running"
        class="h-11 rounded-xl border border-error px-4 text-sm font-medium text-error hover:bg-error/10"
        @click="emit('stop')"
      >
        Stop
      </button>
      <button
        v-else
        class="h-11 rounded-xl bg-primary px-4 text-sm font-medium text-inverted hover:opacity-90 disabled:opacity-40"
        :disabled="disabled || !draft.trim()"
        @click="submit"
      >
        Send
      </button>
    </div>
    <div class="mx-auto mt-1 max-w-3xl text-[11px] text-dimmed">
      Enter 发送 · Shift+Enter 换行 · Esc 停止
    </div>
  </footer>
</template>
