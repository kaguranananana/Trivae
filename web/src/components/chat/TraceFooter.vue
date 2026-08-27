<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'

const props = defineProps<{ traceId: string; durationMs?: number | null }>()

const copied = ref<string | null>(null)
const revealError = ref<string | null>(null)
const path = ref<string | null>(null)

async function copy(text: string, label: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = label
    setTimeout(() => (copied.value = null), 1500)
  } catch {
    copied.value = null
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
    path.value = payload.path
    await copy(payload.path, 'path')
  } catch (error) {
    revealError.value = error instanceof Error ? error.message : String(error)
  }
}
</script>

<template>
  <div class="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-dimmed">
    <span>Trace</span>
    <button class="font-mono underline underline-offset-2 hover:text-default" @click="copy(traceId, 'id')">
      {{ traceId }}
    </button>
    <span v-if="durationMs" class="text-dimmed">· {{ (durationMs / 1000).toFixed(1) }}s</span>
    <button class="rounded border border-default px-1.5 py-0.5 hover:bg-elevated" @click="copy(traceId, 'id')">
      Copy ID
    </button>
    <button class="rounded border border-default px-1.5 py-0.5 hover:bg-elevated" @click="copyPath">
      Copy Path
    </button>
    <button class="rounded border border-default px-1.5 py-0.5 hover:bg-elevated" @click="reveal">
      Reveal in Finder
    </button>
    <span v-if="copied" class="text-success">已复制 {{ copied === 'path' ? '路径' : 'Trace ID' }}</span>
    <span v-if="revealError" class="text-error">{{ revealError }}</span>
  </div>
</template>
