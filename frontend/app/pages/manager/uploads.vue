<template>
  <div class="page-container">
    <h1>Список спецификаций</h1>

    <div class="mb-5 flex flex-wrap gap-2">
      <NuxtLink to="/manager/specifications" class="btn-action btn-link">
        Загрузить спецификацию
      </NuxtLink>
      <button class="btn-secondary" :disabled="isLoading" @click="loadUploads">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <h3>Ранее загруженные спецификации</h3>
      <table v-if="uploads.length || showSkeleton" class="data-table">
        <thead>
          <tr>
            <th>Файл</th>
            <th>Дата загрузки</th>
            <th>Статус</th>
            <th>Строки</th>
          </tr>
        </thead>
        <tbody>
          <template v-if="showSkeleton">
            <CommonTableSkeleton :columns="4" />
          </template>
          <template v-else>
            <tr v-for="upload in uploads" :key="upload.id">
              <td :title="upload.id">{{ upload.filename }}</td>
              <td>{{ formatDateTime(upload.created_at) }}</td>
              <td>
                <span :class="['status-badge', upload.status]">{{ statusLabel(upload.status) }}</span>
              </td>
              <td class="table-actions">
                <NuxtLink
                  v-if="upload.status === 'completed' || upload.status === 'failed'"
                  :to="`/manager/specifications/${upload.id}`"
                  class="btn-action btn-mapping"
                >
                  Открыть
                </NuxtLink>
                <button
                  v-if="upload.status === 'failed'"
                  class="btn-action"
                  :disabled="retryingId === upload.id"
                  @click="retryUpload(upload.id)"
                >
                  {{ retryingId === upload.id ? 'Запуск…' : 'Повторить' }}
                </button>
                <span v-if="upload.status !== 'completed' && upload.status !== 'failed'" class="text-muted">—</span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-else class="empty-state">
        Спецификации ещё не загружались
      </div>
    </div>

    <p class="text-xs text-muted mt-4">
      Спецификации в статусе «Обработка» обновляются автоматически.
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * Список спецификаций, загруженных текущим менеджером (GET /manager/specifications).
 * Статусы обновляются через SSE-потоки per-upload (problem 4: вместо polling).
 */

definePageMeta({ layout: 'workspace' })

import { useSseStreams } from '~/composables/useSseStreams'

/** Ответ backend: app/schemas/specification.py (SpecificationUploadItem). */
interface SpecificationUploadItem {
  id: string
  filename: string
  status: string
  created_at: string
}

/** Подписи статусов обработки (UploadStatus в app/models/models.py). */
const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает обработки',
  mapping_processing: 'Анализирует LLM',
  mapping_predicted: 'Маппинг предсказан',
  processing: 'Обработка',
  completed: 'Завершено',
  failed: 'Ошибка',
}

const uploads = ref<SpecificationUploadItem[]>([])
const isLoading = ref(false)
const retryingId = ref('')
/** Скелетон вместо пустого состояния — только на первой загрузке страницы. */
const showSkeleton = computed(() => isLoading.value && uploads.value.length === 0)

/** Статусы, по которым держим SSE-подписку на загрузку. */
const ACTIVE_STATUSES = ['pending', 'mapping_processing', 'mapping_predicted', 'processing']

/** Значения status, которые относятся к статусу загрузки: события строк
 * (matched/unmatched) игнорируем — они не меняют статус в списке. */
const STATUS_VALUES = ['pending', 'mapping_processing', 'mapping_predicted', 'processing', 'completed', 'error']

const { track, untrack, trackedIds } = useSseStreams({
  onEvent(id, data) {
    const status = String(data.status ?? '')
    if (!STATUS_VALUES.includes(status)) return
    const row = uploads.value.find((upload) => upload.id === id)
    if (row && row.status !== status) loadUploads(true)
  },
  onDone() {
    loadUploads(true)
  },
})

function syncTracking() {
  const active = new Set(
    uploads.value
      .filter((upload) => ACTIVE_STATUSES.includes(upload.status))
      .map((upload) => upload.id),
  )
  for (const id of active) track(id, `/manager/specifications/${id}/stream`)
  for (const id of trackedIds()) {
    if (!active.has(id)) untrack(id)
  }
}

watch(uploads, syncTracking)

// $api — API-клиент из plugins/api.ts: credentials и повтор запроса после 401
const { $api } = useNuxtApp() as any
const toast = useToast()

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

/** silent=true — фоновое обновление из SSE без скелетона и тостов об ошибке. */
async function loadUploads(silent = false) {
  if (!silent) {
    isLoading.value = true
  }

  try {
    const response = await $api('/manager/specifications')
    uploads.value = response.uploads
  } catch (err: any) {
    if (!silent) {
      toast.fromError(err, 'Не удалось загрузить список спецификаций')
    }
  } finally {
    if (!silent) {
      isLoading.value = false
    }
  }
}

async function retryUpload(id: string) {
  retryingId.value = id
  try {
    await $api(`/manager/specifications/${id}/retry`, { method: 'POST' })
    toast.success('Обработка спецификации перезапущена')
    await loadUploads()
  } catch (err: any) {
    toast.fromError(err, 'Не удалось повторить обработку спецификации')
  } finally {
    retryingId.value = ''
  }
}

onMounted(() => {
  loadUploads()
})
</script>
