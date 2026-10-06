<template>
  <div class="page-container">
    <div class="form-actions mb-4">
      <NuxtLink to="/admin/pricelists" class="btn-link">← История прайс-листов</NuxtLink>
    </div>

    <h1>Маппинг колонок</h1>

    <!-- Ожидание LLM-предсказания: показываем статус и подписываемся на SSE -->
    <div v-if="isMappingProcessing" class="upload-section">
      <div class="form-actions">
        <h3 class="flex-1">{{ preview?.filename || 'Загрузка…' }}</h3>
        <span class="status-badge mapping_processing">Анализирует LLM</span>
      </div>
      <p class="text-muted text-sm mt-2">{{ streamMessage }}</p>
    </div>

    <div v-else-if="isLoading" class="empty-state">Загрузка превью…</div>

    <template v-else-if="preview">
      <div class="upload-section">
        <div class="form-actions">
          <h3 class="flex-1">{{ preview.filename }}</h3>
          <span class="status-badge" :class="preview.status">{{ statusLabel(preview.status) }}</span>
        </div>
        <p class="text-muted text-sm mt-2">
          Лист: {{ preview.sheets[0] || '—' }} · колонок: {{ preview.headers.length }} ·
          строк в превью: {{ preview.total_rows }}
        </p>
        <p v-if="!isEditable" class="date-warning mt-2">
          Маппинг подтверждается только для загрузок в статусах «mapping_predicted» и «failed»;
          текущий маппинг показан только для просмотра.
        </p>
      </div>

      <div class="table-wrapper">
        <h3>Роли колонок</h3>
        <p class="text-muted text-sm mb-4">
          Обязательны «Артикул (SKU)» и «Наименование товара». Каждая основная роль назначается
          одной колонке; доп. колонкам задаётся произвольная роль.
        </p>

        <div class="preview-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Колонка файла</th>
                <th>Примеры значений</th>
                <th>Роль</th>
                <th>Роль доп. колонки</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="header in preview.headers" :key="header">
                <td class="mono">{{ header }}</td>
                <td class="text-muted">{{ sampleValues(header) || '—' }}</td>
                <td>
                  <select
                    :value="assignments[header]?.role ?? ''"
                    :disabled="!isEditable || isSaving"
                    @change="setRole(header, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="">Не использовать</option>
                    <option v-for="role in MAPPING_ROLES" :key="role.key" :value="role.key">
                      {{ role.label }}{{ role.required ? ' *' : '' }}
                    </option>
                    <option :value="ADDITIONAL_ROLE">Доп. колонка</option>
                  </select>
                </td>
                <td>
                  <input
                    v-if="assignments[header]?.role === ADDITIONAL_ROLE"
                    v-model="assignments[header].additionalRole"
                    class="mapping-input"
                    type="text"
                    placeholder="Например: brand"
                    :disabled="!isEditable || isSaving"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="table-wrapper">
        <h3>Превью файла</h3>
        <div v-if="preview.rows.length" class="preview-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th v-for="header in preview.headers" :key="header">
                  {{ header }}
                  <span v-if="roleLabel(header)" class="status-badge processing ml-1">
                    {{ roleLabel(header) }}
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, rowIndex) in preview.rows" :key="rowIndex">
                <td v-for="(_, colIndex) in preview.headers" :key="colIndex">
                  {{ formatCell(row[colIndex]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state">В файле нет строк данных</div>
      </div>

      <div class="form-actions">
        <button
          v-if="isEditable"
          class="btn-submit"
          :disabled="!canSave || isSaving"
          @click="saveMapping"
        >
          {{ isSaving ? 'Сохранение...' : 'Подтвердить маппинг' }}
        </button>
        <span class="text-muted text-sm">
          Назначено колонок: {{ countMappedColumns(assignments) }} из {{ preview.headers.length }}
        </span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * Подтверждение маппинга колонок прайс-листа.
 *
 * GET /admin/pricelists/{id}/preview — превью файла и сохранённый (предсказанный LLM)
 * column_mapping; POST /admin/pricelists/{id}/confirm — подтверждённый маппинг,
 * после которого backend запускает векторизацию каталога.
 *
 * Если загрузка в статусе pending или mapping_processing — страница подписывается
 * на SSE-поток и ждёт терминальное событие (mapping_predicted / error),
 * после чего перезагружает превью.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ColumnAssignment } from '~/utils/pricelist'

definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/price_list.py (PriceListPreviewResponse). */
interface PriceListPreview {
  upload_id: string
  filename: string
  status: string
  sheets: string[]
  headers: string[]
  rows: unknown[][]
  total_rows: number
  column_mapping: Record<string, any> | null
}

/** Статусы, в которых админ может подтвердить маппинг. */
const EDITABLE_STATUSES = ['mapping_predicted', 'failed']

/** Статусы, в которых LLM-предсказание ещё выполняется. */
const PENDING_STATUSES = ['pending', 'mapping_processing']

/** Подписи статусов для отображения. */
const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  mapping_processing: 'Анализирует LLM',
  mapping_predicted: 'Ждёт маппинг',
  processing: 'Обрабатывается',
  completed: 'Готов',
  failed: 'Ошибка',
}

function statusLabel(status: string) {
  return STATUS_LABELS[status] || status
}

/** Сколько непустых значений колонки показывать в подсказке. */
const SAMPLE_SIZE = 3

const { $api } = useNuxtApp() as any
const route = useRoute()
const uploadId = String(route.params.uploadId)
const toast = useToast()

const preview = ref<PriceListPreview | null>(null)
const assignments = ref<Record<string, ColumnAssignment>>({})
const isLoading = ref(false)
const isSaving = ref(false)

const isEditable = computed(() =>
  Boolean(preview.value && EDITABLE_STATUSES.includes(preview.value.status)),
)

/** LLM-предсказание ещё выполняется — показываем индикатор ожидания. */
const isMappingProcessing = computed(() =>
  Boolean(preview.value && PENDING_STATUSES.includes(preview.value.status)),
)

const payload = computed(() => buildMappingPayload(assignments.value))

const canSave = computed(() => isMappingComplete(payload.value))

/** Назначить роль колонке; основная роль снимается с колонки, которой была назначена раньше. */
function setRole(header: string, role: string) {
  const isMainRole = MAPPING_ROLES.some((item) => item.key === role)
  if (isMainRole) {
    for (const [column, assignment] of Object.entries(assignments.value)) {
      if (column !== header && assignment.role === role) {
        assignments.value[column] = { role: '' }
      }
    }
  }
  assignments.value[header] = {
    role,
    additionalRole: role === ADDITIONAL_ROLE ? assignments.value[header]?.additionalRole || '' : undefined,
  }
}

/** Подпись роли колонки для заголовка таблицы превью. */
function roleLabel(header: string): string {
  const assignment = assignments.value[header]
  if (!assignment?.role) {
    return ''
  }
  if (assignment.role === ADDITIONAL_ROLE) {
    return assignment.additionalRole?.trim() || 'доп.'
  }
  return MAPPING_ROLES.find((item) => item.key === assignment.role)?.label || ''
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  return String(value)
}

/** Первые непустые значения колонки — подсказка при выборе роли. */
function sampleValues(header: string): string {
  if (!preview.value) {
    return ''
  }
  const index = preview.value.headers.indexOf(header)
  const values: string[] = []
  for (const row of preview.value.rows) {
    const value = formatCell(row[index]).trim()
    if (value) {
      values.push(value)
    }
    if (values.length >= SAMPLE_SIZE) {
      break
    }
  }
  return values.join(' · ')
}

async function loadPreview() {
  isLoading.value = true
  try {
    const response: PriceListPreview = await $api(`/admin/pricelists/${uploadId}/preview`)
    preview.value = response
    assignments.value = assignmentsFromMapping(response.column_mapping, response.headers)
  } catch (err: any) {
    toast.fromError(err, 'Не удалось загрузить превью прайс-листа')
  } finally {
    isLoading.value = false
  }
}

async function saveMapping() {
  if (!canSave.value) {
    return
  }
  isSaving.value = true
  try {
    await $api(`/admin/pricelists/${uploadId}/confirm`, {
      method: 'POST',
      body: payload.value,
    })
    toast.success('Маппинг подтверждён, запущена обработка прайс-листа')
    await navigateTo('/admin/pricelists')
  } catch (err: any) {
    toast.fromError(err, 'Не удалось подтвердить маппинг')
  } finally {
    isSaving.value = false
  }
}

// --- SSE-подписка на статусы LLM-маппинга ---

const config = useRuntimeConfig()
const { $authRefresh } = useNuxtApp() as any

const streamMessage = ref('LLM определяет роли колонок…')
let eventSource: EventSource | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let streamAttempt = 0
let lastSeq = 0

function cleanupStream() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function openStream() {
  eventSource = new EventSource(`${config.public.apiBase}/admin/pricelists/${uploadId}/stream`, {
    withCredentials: true,
  })

  eventSource.onmessage = (event) => {
    let data: any
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }
    // Дедупликация по seq
    if (typeof data.seq === 'number') {
      if (data.seq <= lastSeq) return
      lastSeq = data.seq
    }

    const status = String(data.status ?? '')
    streamMessage.value = data.message || ''

    // Терминальные события — закрываем поток и обновляем превью
    if (status === 'mapping_predicted' || status === 'error') {
      cleanupStream()
      if (status === 'error') {
        toast.error(data.message || 'Не удалось предсказать маппинг колонок')
      } else {
        toast.success('Маппинг колонок готов')
      }
      loadPreview()
    }
  }

  eventSource.onerror = () => {
    cleanupStream()
    // Переподключение с backoff (только пока LLM-предсказание не завершилось)
    if (preview.value && !PENDING_STATUSES.includes(preview.value.status)) return
    const delay = Math.min(1000 * 2 ** streamAttempt, 15000)
    streamAttempt += 1
    reconnectTimer = setTimeout(async () => {
      try {
        await $authRefresh?.()
      } catch {
        /* не критично */
      }
      openStream()
    }, delay)
  }
}

onMounted(async () => {
  await loadPreview()
  // Если LLM-предсказание ещё выполняется — подписываемся на SSE
  if (preview.value && PENDING_STATUSES.includes(preview.value.status)) {
    openStream()
  }
})

onBeforeUnmount(cleanupStream)
</script>
