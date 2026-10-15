<template>
  <div class="page-container page-container-narrow">
    <h1>Загрузка спецификации</h1>

    <div class="form-group">
      <label for="client-select">Клиент (покупатель)</label>
      <div class="client-row">
        <select id="client-select" v-model="selectedClientId" class="form-control">
          <option value="" disabled>Выберите клиента</option>
          <option v-for="client in clients" :key="client.id" :value="client.id">
            {{ client.name }} (ИНН {{ client.inn }})
          </option>
        </select>
        <button class="btn-secondary" type="button" @click="openClientModal">
          Создать нового
        </button>
      </div>
    </div>

    <div class="mb-5 flex flex-wrap gap-2">
      <button
        class="btn-action"
        :disabled="isUploading || !selectedClientId"
        @click="handleUpload"
      >
        {{ isUploading ? 'Загрузка...' : 'Загрузить спецификацию' }}
      </button>
      <NuxtLink to="/manager/uploads" class="btn-secondary btn-link">
        Список спецификаций
      </NuxtLink>
    </div>
    <input
      v-if="!isUploading"
      type="file"
      ref="fileInput"
      accept=".xlsx"
      @change="handleFileSelect"
      style="display: none"
    />

    <!-- Ошибка загрузки: человекочитаемое detail из ответа backend -->
    <div v-if="uploadError" class="upload-error" role="alert">
      {{ uploadError }}
    </div>

    <!-- Панель подтверждения маппинга колонок -->
    <div v-if="showMappingConfirm" class="mapping-confirm-panel">
      <h3>Подтвердите маппинг колонок</h3>
      <p class="text-muted text-sm mb-4">
        LLM предсказал роли колонок. Проверьте и при необходимости отредактируйте перед началом обработки.
      </p>

      <div class="mapping-form">
        <div class="form-group">
          <label>Наименование товара (обязательно)</label>
          <select v-model="mappingForm.name_column" class="form-control">
            <option value="">— Выберите колонку —</option>
            <option v-for="col in mappingHeaders" :key="col" :value="col">{{ col }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>Количество</label>
          <select v-model="mappingForm.quantity_column" class="form-control">
            <option value="">— Нет —</option>
            <option v-for="col in mappingHeaders" :key="col" :value="col">{{ col }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>Единица измерения</label>
          <select v-model="mappingForm.unit_column" class="form-control">
            <option value="">— Нет —</option>
            <option v-for="col in mappingHeaders" :key="col" :value="col">{{ col }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>Цена</label>
          <select v-model="mappingForm.price_column" class="form-control">
            <option value="">— Нет —</option>
            <option v-for="col in mappingHeaders" :key="col" :value="col">{{ col }}</option>
          </select>
        </div>
      </div>

      <div class="form-actions mt-4">
        <button class="btn-action" :disabled="!mappingForm.name_column || confirmingMapping" @click="confirmMapping">
          {{ confirmingMapping ? 'Подтверждение…' : 'Подтвердить и начать обработку' }}
        </button>
      </div>
    </div>

    <!-- Панель обработки: имя файла + SSE-визуализация + кнопка к результатам -->
    <CommonProcessingPanel
      v-if="processing"
      :file-name="processingFileName"
      :upload-id="processingUploadId"
      :sse-active="streamConnected"
      :sse-error="streamFailed"
      :state="streamState"
    />

    <!-- Модальное окно создания клиента: POST /manager/clients, затем автовыбор -->
    <div v-if="isClientModalOpen" class="modal-backdrop" @click.self="closeClientModal">
      <div class="modal-card">
        <h3>Новый клиент</h3>
        <div class="form-group">
          <label for="new-client-name">Наименование *</label>
          <input id="new-client-name" v-model="clientForm.name" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="new-client-inn">ИНН *</label>
          <input id="new-client-inn" v-model="clientForm.inn" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="new-client-address">Адрес *</label>
          <input id="new-client-address" v-model="clientForm.address" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="new-client-contact">Контактное лицо *</label>
          <input id="new-client-contact" v-model="clientForm.contact_person" class="form-control" type="text" />
        </div>
        <div class="form-group">
          <label for="new-client-email">Email *</label>
          <input id="new-client-email" v-model="clientForm.email" class="form-control" type="email" />
        </div>
        <div class="form-group">
          <label for="new-client-phone">Телефон</label>
          <input id="new-client-phone" v-model="clientForm.phone" class="form-control" type="text" />
        </div>
        <div class="form-actions">
          <button
            class="btn-upload"
            :disabled="!isClientFormValid || isCreatingClient"
            @click="createClient"
          >
            {{ isCreatingClient ? 'Сохранение…' : 'Создать' }}
          </button>
          <button class="btn-secondary" type="button" @click="closeClientModal">Отмена</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Загрузка спецификации и панель обработки в реальном времени (проблемы 1–3).
 *
 * Убраны сырой JSON ответа и поток текстовых событий SSE: при успехе сразу
 * открывается CommonProcessingPanel с визуализацией Tier-модели, при ошибке —
 * инлайн-блок с detail из ответа backend.
 */

import { computed, reactive, ref, onMounted, onBeforeUnmount } from 'vue'
import { useSpecStream } from '~/composables/useSpecStream'
import type { SseStreamEvent } from '~/composables/useSseStream'
import { useFingerprint } from '~/composables/useFingerprint'
import type { RowMatchEntry, SpecStreamState } from '~/components/common/ProcessingPanel.vue'

definePageMeta({ layout: 'workspace' })

interface Client {
  id: string
  name: string
  inn: string
}

/** Максимум записей в бегущем логе панели. */
const LOG_LIMIT = 20

const { init: initFingerprint } = useFingerprint()
// $api — API-клиент из plugins/api.ts: credentials и повтор запроса после 401
const { $api } = useNuxtApp() as any
const toast = useToast()
const fileInput = ref<any>(null)
const isUploading = ref(false)

const clients = ref<Client[]>([])
const selectedClientId = ref('')

// Состояние подтверждения маппинга колонок
const showMappingConfirm = ref(false)
/** После подтверждения формы игнорируем повторные события mapping_predicted (переигрывание буфера). */
const mappingConfirmed = ref(false)
const confirmingMapping = ref(false)
const mappingHeaders = ref<string[]>([])
const mappingUploadId = ref('')
const mappingForm = ref({
  name_column: '',
  quantity_column: '',
  unit_column: '',
  price_column: '',
})

// Состояние панели обработки (проблемы 1–3)
// Состояние панели обработки (проблемы 1–3)
const processing = ref(false)
const processingFileName = ref('')
const processingUploadId = ref('')
const uploadError = ref('')

const streamState = reactive<SpecStreamState>({
  processed: 0,
  total: 0,
  phase: 'running',
  errorMessage: '',
  tierAuto: 0,
  tierTopN: 0,
  tierUnmatched: 0,
  log: [],
})

// Создание клиента в модальном окне
const isClientModalOpen = ref(false)
const isCreatingClient = ref(false)
const clientForm = ref({
  name: '',
  inn: '',
  address: '',
  contact_person: '',
  email: '',
  phone: '',
})

const isClientFormValid = computed(
  () =>
    !!clientForm.value.name &&
    !!clientForm.value.inn &&
    !!clientForm.value.address &&
    !!clientForm.value.contact_person &&
    !!clientForm.value.email
)

/** Извлечь человекочитаемое detail из ошибки $api (ofetch). */
function errorDetail(err: any, fallback: string): string {
  const detail = err?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0]
    if (typeof first === 'string') return first
    if (first?.msg) return String(first.msg)
  }
  return fallback
}

/**
 * Обработать событие SSE-потока spec_{upload_id}.
 *
 * Тип события определяется по полям: ProgressEvent несёт processed/total,
 * RowMatchEvent — row_number/match_type. События статуса маппинга
 * (mapping_processing / mapping_predicted) обновляют только фазу.
 */
function handleStreamEvent(data: SseStreamEvent) {
  const status = String(data.status ?? '')

  // Прогресс матчинга: processed/total + терминальные completed/error
  if (typeof data.processed === 'number' && typeof data.total === 'number') {
    streamState.processed = data.processed
    streamState.total = data.total
    if (status === 'completed') streamState.phase = 'complete'
    if (status === 'error') {
      streamState.phase = 'error'
      streamState.errorMessage = String(data.message ?? '')
    }
    return
  }

  // Обработка строки: счётчик Tier + бегущий лог
  if (typeof data.row_number === 'number') {
    const tier = String(data.match_type ?? '')
    if (tier === 'auto') streamState.tierAuto += 1
    else if (tier === 'top_n') streamState.tierTopN += 1
    else streamState.tierUnmatched += 1

    const entry: RowMatchEntry = {
      row_number: data.row_number,
      raw_name: String(data.raw_name ?? ''),
      match_type: tier || null,
      status: String(data.status ?? ''),
      timestamp: data.timestamp ? String(data.timestamp) : undefined,
    }
    streamState.log = [entry, ...streamState.log].slice(0, LOG_LIMIT)
    return
  }

  // Статус LLM-маппинга колонок: показываем экран подтверждения
  if (status === 'mapping_predicted') {
    mappingUploadId.value = String(data.upload_id ?? '')
    loadMappingPreview()
    return
  }
}

// Устойчивый SSE: реконнект с backoff и refresh токена перед повторным подключением
const {
  open: openStream,
  stop: stopStream,
  connected: streamConnected,
  failed: streamFailed,
} = useSpecStream({
  onEvent: handleStreamEvent,
  onDone: handleStreamEvent,
})

// Проверяем авторизацию
onMounted(async () => {
  // Если отпечаток устройства не определён — перенаправляем на логин
  const fingerprint = await initFingerprint()
  if (!fingerprint) {
    navigateTo('/login')
    return
  }
  await loadClients()
})

onBeforeUnmount(stopStream)

async function loadClients() {
  try {
    const response = await $api('/manager/clients')
    clients.value = response.clients
  } catch (err: any) {
    toast.fromError(err, 'Не удалось загрузить список клиентов')
  }
}

function openClientModal() {
  clientForm.value = {
    name: '',
    inn: '',
    address: '',
    contact_person: '',
    email: '',
    phone: '',
  }
  isClientModalOpen.value = true
}

function closeClientModal() {
  isClientModalOpen.value = false
}

async function createClient() {
  isCreatingClient.value = true
  try {
    const created = await $api('/manager/clients', { method: 'POST', body: clientForm.value })
    clients.value.push({ id: created.id, name: created.name, inn: created.inn })
    selectedClientId.value = created.id
    isClientModalOpen.value = false
    toast.success('Клиент создан')
  } catch (err: any) {
    toast.fromError(err, 'Не удалось создать клиента')
  } finally {
    isCreatingClient.value = false
  }
}

function handleUpload() {
  if (!selectedClientId.value) {
    toast.error('Сначала выберите клиента')
    return
  }
  fileInput.value?.click()
}

function resetStreamState() {
  streamState.processed = 0
  streamState.total = 0
  streamState.phase = 'running'
  streamState.errorMessage = ''
  streamState.tierAuto = 0
  streamState.tierTopN = 0
  streamState.tierUnmatched = 0
  streamState.log = []
}

/**
 * Загрузить предпросмотр маппинга: полный список колонок файла + предсказание LLM.
 *
 * Отдельный GET, а не данные из SSE: событие mapping_predicted несёт только статус,
 * а переигрывание буфера при реконнекте не должно повторно показывать форму
 * после подтверждения (флаг mappingConfirmed).
 */
async function loadMappingPreview() {
  if (mappingConfirmed.value) return
  try {
    const preview = await $api(`/manager/specifications/${mappingUploadId.value}/mapping-preview`)
    mappingHeaders.value = preview.headers || []
    const m = preview.mapping || {}
    mappingForm.value = {
      name_column: m.name_column ?? '',
      quantity_column: m.quantity_column ?? '',
      unit_column: m.unit_column ?? '',
      price_column: m.price_column ?? '',
    }
    showMappingConfirm.value = true
    // Матчинг ещё не запущен: панель обработки скрываем, поток до подтверждения не нужен
    processing.value = false
    stopStream()
  } catch (err: any) {
    toast.fromError(err, 'Не удалось загрузить предпросмотр маппинга')
  }
}

/** Подтвердить маппинг и запустить обработку. */
async function confirmMapping() {
  if (!mappingForm.value.name_column) {
    toast.error('Выберите колонку с наименованием товара')
    return
  }
  confirmingMapping.value = true
  try {
    const body = {
      name_column: mappingForm.value.name_column,
      quantity_column: mappingForm.value.quantity_column || null,
      unit_column: mappingForm.value.unit_column || null,
      price_column: mappingForm.value.price_column || null,
      additional_columns: {} as Record<string, string>,
    }
    await $api(`/manager/specifications/${mappingUploadId.value}/confirm-mapping`, {
      method: 'POST',
      body,
    })
    showMappingConfirm.value = false
    mappingConfirmed.value = true
    // Открыть панель обработки и подписаться на SSE
    resetStreamState()
    processing.value = true
    openStream(mappingUploadId.value)
  } catch (err: any) {
    toast.fromError(err, 'Не удалось подтвердить маппинг')
  } finally {
    confirmingMapping.value = false
  }
}

async function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  isUploading.value = true
  uploadError.value = ''

  try {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('client_id', selectedClientId.value)

    // Загружаем спецификацию: FormData, заголовок Content-Type ставит ofetch
    const response = await $api('/manager/specifications', {
      method: 'POST',
      body: formData,
    })

    // Успех: отдельного тоста нет — панель обработки открыта сразу (SSE-индикатор
    // активен на этапе LLM-маппинга), экран подтверждения сменит её по событию
    // mapping_predicted; матчинг начнётся после подтверждения
    resetStreamState()
    mappingConfirmed.value = false
    processingFileName.value = file.name
    processingUploadId.value = response.upload_id
    processing.value = true
    openStream(response.upload_id)
  } catch (err: any) {
    // Ошибка: инлайн-блок с detail из ответа + тост, панель не открывается
    uploadError.value = errorDetail(err, 'Не удалось загрузить спецификацию')
    toast.fromError(err, 'Не удалось загрузить спецификацию')
  } finally {
    isUploading.value = false
    // Сброс input, чтобы повторный выбор того же файла снова сработал
    target.value = ''
  }
}
</script>

<style scoped>
.client-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.client-row .form-control {
  flex: 1;
}

.upload-error {
  margin-top: 16px;
  padding: 12px 16px;
  border-radius: 8px;
  background: var(--app-danger-bg);
  color: var(--app-danger-fg);
  border: 1px solid var(--app-danger);
  font-size: 0.9375rem;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-card {
  background: var(--app-surface, #fff);
  border-radius: 10px;
  padding: 24px;
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  overflow-y: auto;
}
.mapping-confirm-panel {
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 24px;
  margin-top: 20px;
  background: var(--app-surface);
}

.mapping-confirm-panel h3 {
  margin-top: 0;
}

.mapping-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 600px) {
  .mapping-form {
    grid-template-columns: 1fr;
  }
}

</style>
