<template>
  <div class="page-container">
    <h1>Прайс-листы</h1>

    <div class="upload-section">
      <h3>Загрузить новый прайс-лист</h3>
      <div class="upload-form-inline">
        <input
          ref="fileInput"
          type="file"
          accept=".xlsx"
          style="display: none"
          @change="handleFileSelect"
        />
        <button class="btn-upload" :disabled="isUploading" @click="fileInput?.click()">
          Выбрать файл
        </button>
        <span v-if="selectedFile" class="file-name flex-1">{{ selectedFile.name }}</span>
        <button class="btn-submit" :disabled="!selectedFile || isUploading" @click="handleUpload">
          {{ isUploading ? 'Загрузка...' : 'Загрузить' }}
        </button>
      </div>

      <div v-if="uploadResult" class="result">
        <p>Upload ID: <code>{{ uploadResult.upload_id }}</code></p>
        <p>Файл в хранилище: <code>{{ uploadResult.file_key }}</code></p>
      </div>
      <p class="text-muted text-sm mt-2">
        После загрузки backend строит превью листа и предсказывает маппинг колонок;
        подтверждение маппинга выполняется отдельно, статус виден в истории ниже.
      </p>
    </div>

    <div class="table-wrapper">
      <h3>История загрузок</h3>

      <div class="status-filters">
        <button
          class="filter-chip"
          :class="{ active: !statusFilter }"
          :disabled="isLoading"
          @click="applyFilter('')"
        >
          Все · {{ totalCount }}
        </button>
        <button
          v-for="(count, status) in counts"
          :key="status"
          class="filter-chip"
          :class="{ active: statusFilter === status }"
          :disabled="isLoading"
          @click="applyFilter(String(status))"
        >
          {{ statusLabel(String(status)) }} · {{ count }}
        </button>
      </div>

      <table v-if="uploads.length" class="data-table">
        <thead>
          <tr>
            <th>Файл</th>
            <th>Загрузил</th>
            <th>Дата</th>
            <th>Статус</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="upload in uploads" :key="upload.id">
            <td :title="upload.id">{{ upload.filename }}</td>
            <td>{{ upload.admin_email || '—' }}</td>
            <td>{{ formatDateTime(upload.created_at) }}</td>
            <td>
              <span class="status-badge" :class="upload.status">{{ upload.status }}</span>
            </td>
            <td class="table-actions">
              <NuxtLink
                v-if="upload.status === 'mapping_predicted' || upload.status === 'failed'"
                :to="`/admin/pricelists/${upload.id}`"
                class="btn-action btn-mapping"
              >
                Маппинг
              </NuxtLink>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">
        {{ isLoading ? 'Загрузка списка…' : 'Прайс-листы ещё не загружались' }}
      </div>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>

    <div class="form-actions">
      <button class="btn-secondary" :disabled="isLoading" @click="loadUploads">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Прайс-листы: загрузка Excel (POST /admin/pricelists) и история загрузок
 * (GET /admin/pricelists). Статусы обработки приходят из backend —
 * pending / processing / mapping_predicted / completed / failed.
 */
import { computed, onMounted, ref } from 'vue'

definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/price_list.py (PriceListUploadItem). */
interface PriceListUpload {
  id: string
  filename: string
  admin_email: string
  status: string
  created_at: string
}

const { $api } = useNuxtApp() as any

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const isLoading = ref(false)
const uploadResult = ref<any>(null)
const uploads = ref<PriceListUpload[]>([])
const counts = ref<Record<string, number>>({})
const statusFilter = ref('')
const error = ref('')

/** Подписи статусов UploadStatus для чипов фильтра. */
const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  mapping_predicted: 'Ждёт маппинг',
  processing: 'Обрабатывается',
  completed: 'Готов',
  failed: 'Ошибка',
}

function statusLabel(status: string) {
  return STATUS_LABELS[status] || status
}

/** Всего загрузок по всем статусам (для чипа «Все»). */
const totalCount = computed(() =>
  Object.values(counts.value).reduce((sum, count) => sum + count, 0),
)

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

async function loadUploads() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/admin/pricelists', {
      // Счётчики backend считает по всем загрузкам, фильтр — только по списку.
      query: statusFilter.value ? { status: statusFilter.value } : {},
    })
    uploads.value = response.uploads
    counts.value = response.counts || {}
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить историю прайс-листов'
  } finally {
    isLoading.value = false
  }
}

function applyFilter(status: string) {
  statusFilter.value = status
  loadUploads()
}

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
}

async function handleUpload() {
  if (!selectedFile.value) {
    return
  }

  isUploading.value = true
  error.value = ''
  uploadResult.value = null
  try {
    // FormData, а не JSON: backend читает файл как multipart (UploadFile).
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    uploadResult.value = await $api('/admin/pricelists', { method: 'POST', body: formData })
    selectedFile.value = null
    if (fileInput.value) {
      fileInput.value.value = ''
    }
    await loadUploads()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить прайс-лист'
  } finally {
    isUploading.value = false
  }
}

onMounted(loadUploads)
</script>
