<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'

const props = defineProps<{ traceId: string; durationMs?: number | null }>()

const copied = ref<string | null>(null)
const revealError = ref<string | null>(null)

async function copy(text: string, label: string): Promise<void> {
  revealError.value = null
  copied.value = null
  try {
    // 复制结果必须以浏览器实际成功为准，失败保留具体原因。
    await navigator.clipboard.writeText(text)
    copied.value = label
  } catch (error) {
    revealError.value = error instanceof Error ? error.message : String(error)
  }
}

async function reveal(): Promise<void> {
  revealError.value = null
  try {
    await api.revealTrace(props.traceId)
  } catch (error) {
    revealError.value = error instanceof Error ? error.message : String(error)
  }
}

async function copyPath(): Promise<void> {
  try {
    const payload = await api.tracePath(props.traceId)
    await copy(payload.path, 'path')
  } catch (error) {
    revealError.value = error instanceof Error ? error.message : String(error)
  }
}
</script>

<template>
  <!-- 调试信息收进详情，日常阅读保持简洁，原有 Trace 操作仍可访问。 -->
  <details class="trace-details">
    <summary>运行详情<span v-if="durationMs != null"> · {{ (durationMs / 1000).toFixed(1) }} 秒</span></summary>
    <div class="trace-content">
      <code>{{ traceId }}</code>
      <div class="trace-actions">
        <button @click="copy(traceId, 'id')">复制 Trace ID</button>
        <button @click="copyPath">复制文件路径</button>
        <button @click="reveal">在 Finder 中显示</button>
      </div>
      <span v-if="copied" class="text-success" role="status">已复制{{ copied === 'path' ? '路径' : ' Trace ID' }}</span>
      <span v-if="revealError" class="text-error" role="alert">{{ revealError }}</span>
    </div>
  </details>
</template>
