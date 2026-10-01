<template>
  <div class="page-container">
    <h1>Спецификация: {{ uploadDetail?.filename ?? '...' }}</h1>

    <div class="mb-5 flex flex-wrap gap-2">
      <NuxtLink to="/manager/uploads" class="btn-secondary btn-link">
        ← Назад к списку
      </NuxtLink>
      <span :class="['status-badge', uploadDetail?.status]">
        {{ statusLabel(uploadDetail?.status ?? '') }}
      </span>
      <span class="text-muted text-sm">
        Всего строк: {{ uploadDetail?.rows_total ?? '—' }}
      </span>
    </div>

    <!-- Сводка по статусам строк -->
    <div v-if="Object.keys(rowsByStatus).length" class="row-summary">
      <span>
        <span :class="['status-badge', 'matched']">matched</span>
        {{ rowsByStatus.matched ?? 0 }}
      </span>
      <span>
        <span :class="['status-badge', 'unmatched']">unmatched</span>
        {{ rowsByStatus.unmatched ?? 0 }}
      </span>
      <span>
        <span :class="['status-badge', 'confirmed']">confirmed</span>
        {{ rowsByStatus.confirmed ?? 0 }}
      </span>
      <span>
        <span :class="['status-badge', 'excluded']">excluded</span>
        {{ rowsByStatus.excluded ?? 0 }}
      </span>
    </div>

    <!-- SSE-лог -->
    <div v-if="sseMessages.length" class="sse-log">
      <h3>Лог обработки ({{ sseMessages.length }} событий)</h3>
      <ul>
        <li v-for="(msg, i) in sseMessages" :key="i">{{ msg }}</li>
      </ul>
    </div>

    <!-- Таблица строк -->
    <div v-if="rows.length" class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Наименование</th>
            <th>Кол-во</th>
            <th>Ед.</th>
            <th>Тип матча</th>
            <th>Статус</th>
            <th>Позиция каталога</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td class="mono">{{ row.row_number }}</td>
            <td>{{ row.raw_name }}</td>
            <td>{{ row.quantity ?? '—' }}</td>
            <td>{{ row.unit ?? '—' }}</td>
            <td>
              <span v-if="row.match_type" :class="['status-badge', row.match_type]">
                {{ row.match_type }}
              </span>
              <span v-else class="text-muted">—</span>
            </td>
            <td>
              <span :class="['status-badge', row.status]">{{ row.status }}</span>
            </td>
            <td>
              <template v-if="row.matched_item">
                <div class="text-sm">
                  <span class="mono">{{ row.matched_item.sku }}</span> —
                  {{ row.matched_item.name }}
                </div>
              </template>
              <template v-else>
                <span class="text-muted">—</span>
              </template>
            </td>
            <td class="table-actions">
              <!-- Кнопка «Подтвердить» — доступна если есть matched_item или status !== excluded -->
              <button
                v-if="canConfirm(row)"
                class="btn-action btn-sm"
                @click="openConfirmDialog(row)"
              >
                Подтвердить
              </button>
              <!-- Кнопка «Исключить» — доступна если статус не excluded и не confirmed -->
              <button
                v-if="canExclude(row)"
                class="btn-delete btn-sm"
                @click="excludeRow(row)"
              >
                Исключить
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Пагинация -->
      <div class="pager">
        <button
          :disabled="page <= 1"
          class="btn-secondary"
          @click="loadRows(page - 1)"
        >
          ← Назад
        </button>
        <span>Страница {{ page }} из {{ totalPages }}</span>
        <button
          :disabled="page >= totalPages"
          class="btn-secondary"
          @click="loadRows(page + 1)"
        >
          Вперёд →
        </button>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-state">
      Строк спецификации нет
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>
  </div>

  <!-- Диалог подтверждения: выбор из ТОП-N кандидатов -->
  <div v-if="showConfirmDialog" class="modal-backdrop" @click.self="showConfirmDialog = false">
    <div class="modal-card">
      <h3>Подтвердить позицию</h3>
      <p v-if="confirmRow" class="text-sm">
        <strong>Строка:</strong> {{ confirmRow.raw_name }} (строка {{ confirmRow.row_number }})
      </p>

      <!-- Текущая позиция -->
      <div v-if="confirmRow?.matched_item" class="mb-4">
        <h4>Текущая позиция:</h4>
        <div class="text-sm">
          <span class="mono">{{ confirmRow.matched_item.sku }}</span> —
          {{ confirmRow.matched_item.name }}
        </div>
        <button class="btn-action btn-sm mt-2" @click="confirmWithExisting()">
          Подтвердить текущую
        </button>
      </div>

      <!-- Кандидаты из векторного поиска -->
      <div v-if="candidates.length" class="mb-4">
        <h4>Кандидаты (ТОП-{{ candidates.length }}):</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Наименование</th>
              <th>Схожесть</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in candidates" :key="c.id">
              <td class="mono">{{ c.sku }}</td>
              <td>{{ c.name }}</td>
              <td>{{ (c.similarity * 100).toFixed(1) }}%</td>
              <td>
                <button class="btn-candidate btn-sm" @click="confirmWithCandidate(c)">
                  Выбрать
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="form-actions mt-4">
        <button class="btn-secondary" @click="showConfirmDialog = false">
          Отмена
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSpecStream } from '~/composables/useSpecStream'
import { useFingerprint } from '~/composables/useFingerprint'

definePageMeta({ layout: 'workspace' })

const { $api } = useNuxtApp() as any
const route = useRoute()
const uploadId = String(route.params.uploadId)

// Данные загрузок
interface SpecificationUploadDetail {
  id: string
  filename: string
  status: string
  created_at: string
  column_mapping: Record<string, string> | null
  rows_total: number
  rows_by_status: Record<string, number>
}

interface SpecificationRowItem {
  id: string
  row_number: number
  raw_name: string
  quantity: number | null
  unit: string | null
  price: number | null
  match_type: string | null
  status: string
  matched_item: {
    id: string
    sku: string
    name: string
    unit: string | null
    price: number | null
  } | null
}

interface RowMatchCandidate {
  id: string
  sku: string
  name: string
  unit: string | null
  price: number | null
  similarity: number
}

const uploadDetail = ref<SpecificationUploadDetail | null>(null)
const rows = ref<SpecificationRowItem[]>([])
const rowsByStatus = ref<Record<string, number>>({})
const page = ref(1)
const pageSize = 50
const total = ref(0)
const loading = ref(false)
const error = ref('')
const sseMessages = ref<string[]>([])

// Диалог подтверждения
const showConfirmDialog = ref(false)
const confirmRow = ref<SpecificationRowItem | null>(null)
const candidates = ref<RowMatchCandidate[]>([])

// Подписи статусов
const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  mapping_predicted: 'Маппинг предсказан',
  processing: 'Обработка',
  completed: 'Завершено',
  failed: 'Ошибка',
  matched: 'Matched',
  unmatched: 'Unmatched',
  confirmed: 'Confirmed',
  excluded: 'Excluded',
}

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

// SSE-поток
const { open: openStream, stop: stopStream } = useSpecStream({
  onEvent(data) {
    const status = data.status ?? ''
    const msg = data.message || ''
    sseMessages.value.push(`[${status}] ${msg}`)
    if (status === 'completed' || status === 'error') {
      loadUploadDetail()
    }
  },
  onDone() {
    loadUploadDetail()
  },
})

async function loadUploadDetail() {
  try {
    const detail = await $api(`/manager/specifications/${uploadId}`)
    uploadDetail.value = detail
    rowsByStatus.value = detail.rows_by_status || {}
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить спецификацию'
  }
}

async function loadRows(p: number) {
  loading.value = true
  error.value = ''
  try {
    const response = await $api(`/manager/specifications/${uploadId}/rows`, {
      query: { page: p, page_size: pageSize },
    })
    rows.value = response.rows
    total.value = response.total
    page.value = p
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить строки'
  } finally {
    loading.value = false
  }
}

function canConfirm(row: SpecificationRowItem) {
  return row.status !== 'excluded' && row.status !== 'confirmed' && row.matched_item !== null
}

function canExclude(row: SpecificationRowItem) {
  return row.status !== 'excluded' && row.status !== 'confirmed'
}

async function openConfirmDialog(row: SpecificationRowItem) {
  confirmRow.value = row
  candidates.value = []
  showConfirmDialog.value = true

  // Загрузить кандидатов из векторного поиска
  try {
    const result = await $api(`/manager/specifications/${uploadId}/rows/${row.id}/matches`, {
      query: { limit: 10 },
    })
    candidates.value = result.candidates || []
  } catch {
    // Кандидаты не критичны — можно подтвердить и без них
  }
}

async function confirmWithExisting() {
  if (!confirmRow.value) return
  await updateRowStatus(confirmRow.value.id, 'confirmed', confirmRow.value.matched_item?.id)
}

async function confirmWithCandidate(candidate: RowMatchCandidate) {
  if (!confirmRow.value) return
  await updateRowStatus(confirmRow.value.id, 'confirmed', candidate.id)
}

async function excludeRow(row: SpecificationRowItem) {
  await updateRowStatus(row.id, 'excluded', null)
}

async function updateRowStatus(rowId: string, status: 'confirmed' | 'excluded', catalogItemId: string | null) {
  try {
    await $api(`/manager/specifications/${uploadId}/rows/${rowId}`, {
      method: 'PATCH',
      body: { status, catalog_item_id: catalogItemId },
    })
    showConfirmDialog.value = false
    confirmRow.value = null
    await loadRows(page.value)
    await loadUploadDetail()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось обновить статус строки'
  }
}

onMounted(async () => {
  const fingerprint = await useFingerprint().init()
  if (!fingerprint) {
    navigateTo('/login')
    return
  }
  await loadUploadDetail()
  await loadRows(1)
  openStream(uploadId)
})

onBeforeUnmount(() => {
  stopStream()
})
</script>
