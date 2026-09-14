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
      <table v-if="uploads.length" class="data-table">
        <thead>
          <tr>
            <th>Файл</th>
            <th>Дата загрузки</th>
            <th>Статус</th>
            <th>ID загрузки</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="upload in uploads" :key="upload.id">
            <td>{{ upload.filename }}</td>
            <td>{{ formatDateTime(upload.created_at) }}</td>
            <td>
              <span :class="['status-badge', upload.status]">{{ statusLabel(upload.status) }}</span>
            </td>
            <td class="mono">{{ upload.id }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!isLoading" class="empty-state">
        Спецификации ещё не загружались
      </div>
      <div v-else class="empty-state">Загрузка списка…</div>
    </div>

    <p v-if="loadError" class="text-danger">{{ loadError }}</p>
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
  mapping_predicted: 'Маппинг предсказан',
  processing: 'Обработка',
  completed: 'Завершено',
  failed: 'Ошибка',
}

const uploads = ref<SpecificationUploadItem[]>([])
const isLoading = ref(false)
const loadError = ref('')

// $api — API-клиент из plugins/api.ts: credentials и повтор запроса после 401
const { $api } = useNuxtApp() as any

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

async function loadUploads() {
  isLoading.value = true
  loadError.value = ''

  try {
    const response = await $api('/manager/specifications')
    uploads.value = response.uploads
  } catch (err: any) {
    loadError.value = err?.data?.detail || 'Не удалось загрузить список спецификаций'
  } finally {
    isLoading.value = false
  }
}

onMounted(loadUploads)
</script>
