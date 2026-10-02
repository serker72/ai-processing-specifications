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
    <div v-if="uploadResult" class="result">
      <h3>Результат загрузки:</h3>
      <pre>{{ JSON.stringify(uploadResult, null, 2) }}</pre>
    </div>
    <p v-if="error" class="text-danger">{{ error }}</p>
    <div v-if="sseMessages.length > 0" class="sse-log">
      <h3>События обработки:</h3>
      <ul>
        <li v-for="(msg, index) in sseMessages" :key="index">{{ msg }}</li>
      </ul>
    </div>

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
        <p v-if="clientError" class="text-danger">{{ clientError }}</p>
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
import { computed, ref, onMounted } from 'vue'
import { useSpecStream } from '~/composables/useSpecStream'
import { useFingerprint } from '~/composables/useFingerprint'

definePageMeta({ layout: 'workspace' })

interface Client {
  id: string
  name: string
  inn: string
}

const { init: initFingerprint } = useFingerprint()
// $api — API-клиент из plugins/api.ts: credentials и повтор запроса после 401
const { $api } = useNuxtApp() as any
const fileInput = ref<any>(null)
const isUploading = ref(false)
const uploadResult = ref<any>(null)
const error = ref('')
const sseMessages = ref<string[]>([])

const clients = ref<Client[]>([])
const selectedClientId = ref('')

// Создание клиента в модальном окне
const isClientModalOpen = ref(false)
const isCreatingClient = ref(false)
const clientError = ref('')
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

// Устойчивый SSE: реконнект с backoff и refresh токена перед повторным подключением
const { open: openStream } = useSpecStream({
  onEvent(data) {
    sseMessages.value.push(
      `[${data.status}] ${data.message || data.raw_name || ''}`
    )
  },
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

async function loadClients() {
  try {
    const response = await $api('/manager/clients')
    clients.value = response.clients
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить список клиентов'
  }
}

function openClientModal() {
  clientError.value = ''
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
  clientError.value = ''
  try {
    const created = await $api('/manager/clients', { method: 'POST', body: clientForm.value })
    clients.value.push({ id: created.id, name: created.name, inn: created.inn })
    selectedClientId.value = created.id
    isClientModalOpen.value = false
  } catch (err: any) {
    clientError.value = err?.data?.detail || 'Не удалось создать клиента'
  } finally {
    isCreatingClient.value = false
  }
}

function handleUpload() {
  if (!selectedClientId.value) {
    error.value = 'Сначала выберите клиента'
    return
  }
  fileInput.value?.click()
}

async function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  isUploading.value = true
  uploadResult.value = null
  sseMessages.value = []
  error.value = ''

  try {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('client_id', selectedClientId.value)

    // Загружаем спецификацию: FormData, заголовок Content-Type ставит ofetch
    const response = await $api('/manager/specifications', {
      method: 'POST',
      body: formData,
    })

    uploadResult.value = response

    // Подписываемся на SSE-поток обработки загрузки
    openStream(response.upload_id)
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить спецификацию'
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
</style>
