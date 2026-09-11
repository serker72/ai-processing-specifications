<template>
  <div class="page-container page-container-narrow">
    <h1>Рабочее место менеджера</h1>
    <div class="mb-5 flex flex-wrap gap-2">
      <button class="btn-action" @click="handleUpload" :disabled="isUploading">
        {{ isUploading ? 'Загрузка...' : 'Загрузить спецификацию' }}
      </button>
      <button class="btn-secondary" @click="handleLogout">Выйти</button>
    </div>
    <input
      v-if="!isUploading"
      type="file"
      ref="fileInput"
      accept=".xlsx"
      @change="handleFileSelect"
      style="display: none"
    />
    <div v-if="uploadResult" class="result">
      <h3>Результат загрузки:</h3>
      <pre>{{ JSON.stringify(uploadResult, null, 2) }}</pre>
    </div>
    <div v-if="sseMessages.length > 0" class="sse-log">
      <h3>События обработки:</h3>
      <ul>
        <li v-for="(msg, index) in sseMessages" :key="index">{{ msg }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useFingerprint } from '~/composables/useFingerprint'
import { useAuth } from '~/composables/useAuth'

const { logout } = useAuth()
const { init: initFingerprint } = useFingerprint()
const fileInput = ref<any>(null)
const isUploading = ref(false)
const uploadResult = ref<any>(null)
const sseMessages = ref<string[]>([])

let eventSource: EventSource | null = null

// Проверяем авторизацию
onMounted(async () => {
  // Если отпечаток устройства не определён — перенаправляем на логин
  const fingerprint = await initFingerprint()
  if (!fingerprint) {
    navigateTo('/login')
  }
})

function handleUpload() {
  fileInput.value?.click()
}

async function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  isUploading.value = true
  uploadResult.value = null
  sseMessages.value = []

  try {
    const formData = new FormData()
    formData.append('file', file)

    // Загружаем спецификацию
    const response = await $fetch('/manager/specifications', {
      baseURL: useRuntimeConfig().public.apiBase,
      method: 'POST',
      body: formData,
      credentials: 'include',
    })

    uploadResult.value = response

    // Подписываемся на SSE-поток
    subscribeToSSE(response.upload_id)
  } catch (err: any) {
    console.error('Upload failed:', err)
  } finally {
    isUploading.value = false
  }
}

function subscribeToSSE(uploadId: string) {
  const apiUrl = useRuntimeConfig().public.apiBase
  const streamUrl = `${apiUrl}/manager/specifications/${uploadId}/stream`

  eventSource = new EventSource(streamUrl)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      sseMessages.value.push(
        `[${data.status}] ${data.message || data.raw_name || ''}`
      )
    } catch {
      sseMessages.value.push(event.data)
    }
  }

  eventSource.onerror = (error) => {
    console.error('SSE Error:', error)
    eventSource?.close()
  }
}

onBeforeUnmount(() => {
  eventSource?.close()
})

async function handleLogout() {
  await logout()
  navigateTo('/login')
}
</script>
