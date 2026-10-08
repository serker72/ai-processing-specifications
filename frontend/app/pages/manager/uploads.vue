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
 * Строки реестра загрузок приходят с backend, сортировка — по времени загрузки
 * (новые первыми); статус — стадия обработки файла Matching Engine.
 */

definePageMeta({ layout: 'workspace' })

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

const POLL_INTERVAL_MS = 5000
let pollTimer: ReturnType<typeof setInterval> | null = null

// $api — API-клиент из plugins/api.ts: credentials и повтор запроса после 401
const { $api } = useNuxtApp() as any
const toast = useToast()

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

/** silent=true — фоновое обновление (polling) без скелетона и тостов об ошибке. */
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

/** Фоновое обновление, пока есть спецификации в обработке (в т.ч. LLM-маппинг). */
function pollProcessing() {
  const inFlight = ['processing', 'mapping_processing', 'pending']
  if (uploads.value.some((upload) => inFlight.includes(upload.status))) {
    loadUploads(true)
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
  pollTimer = setInterval(pollProcessing, POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>
