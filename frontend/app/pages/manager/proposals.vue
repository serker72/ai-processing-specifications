<template>
  <div class="page-container">
    <h1>Коммерческие предложения</h1>

    <div class="mb-5 flex flex-wrap gap-2">
      <NuxtLink to="/manager/specifications" class="btn-action btn-link">
        Загрузить спецификацию
      </NuxtLink>
      <button class="btn-secondary" :disabled="isLoading" @click="loadProposals">
        {{ isLoading ? 'Обновление...' : 'Обновить' }}
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="proposals.length" class="data-table">
        <thead>
          <tr>
            <th>Номер</th>
            <th>Клиент</th>
            <th>Спецификация</th>
            <th>Создано</th>
            <th>Версий</th>
            <th>Статус</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in proposals" :key="item.id">
            <td class="mono">{{ item.number }}</td>
            <td>{{ item.client_name ?? '—' }}</td>
            <td :title="item.upload_id">{{ item.filename ?? '—' }}</td>
            <td>{{ formatDateTime(item.created_at) }}</td>
            <td>{{ item.documents_count }}</td>
            <td>
              <span v-if="item.needs_regeneration" class="status-badge failed">
                Данные изменились
              </span>
              <span v-else class="status-badge completed">Актуально</span>
            </td>
            <td class="table-actions">
              <button
                class="btn-action btn-sm"
                :disabled="downloadingId === item.id"
                @click="download(item)"
              >
                {{ downloadingId === item.id ? 'Скачивание…' : 'Скачать PDF' }}
              </button>
              <NuxtLink
                :to="`/manager/specifications/${item.upload_id}`"
                class="btn-secondary btn-sm btn-link"
              >
                Открыть
              </NuxtLink>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!isLoading" class="empty-state">
        Коммерческие предложения ещё не формировались
      </div>
      <div v-else class="empty-state">Загрузка списка…</div>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
/**
 * История сформированных КП текущего менеджера (GET /manager/proposals).
 * «Данные изменились» — строки спецификации правились после последнего
 * формирования файла (rows_fingerprint на backend не совпал).
 */
definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/proposal.py (ProposalItem). */
interface ProposalItem {
  id: string
  number: string
  created_at: string
  client_id: string
  client_name: string | null
  upload_id: string
  filename: string | null
  documents_count: number
  latest_document_id: string | null
  has_document: boolean
  needs_regeneration: boolean
}

const { $api } = useNuxtApp() as any

const proposals = ref<ProposalItem[]>([])
const isLoading = ref(false)
const downloadingId = ref('')
const error = ref('')

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('ru-RU')
}

async function loadProposals() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/manager/proposals')
    proposals.value = response.proposals
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить список КП'
  } finally {
    isLoading.value = false
  }
}

async function download(item: ProposalItem) {
  downloadingId.value = item.id
  error.value = ''
  try {
    const blob = await $api(`/manager/proposals/${item.id}/download`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${item.number}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось скачать КП'
  } finally {
    downloadingId.value = ''
  }
}

onMounted(loadProposals)
</script>
