<template>
  <div class="page-container">
    <h1>Управление шаблонами КП</h1>
    
    <!-- Форма загрузки шаблона -->
    <div class="upload-section">
      <h3>Загрузить новый шаблон</h3>
      <div class="upload-form sm:grid-cols-2">
        <div class="form-group">
          <label for="template-name">Название шаблона</label>
          <input
            id="template-name"
            v-model="form.name"
            type="text"
            placeholder="Например: Стандартный шаблон Q4"
            required
          />
        </div>
        <div class="form-group">
          <label for="template-file">HTML-шаблон</label>
          <input
            id="template-file"
            ref="fileInput"
            type="file"
            accept=".html"
            @change="handleFileSelect"
          />
        </div>
        <div class="form-group">
          <label for="start-date">Дата начала действия</label>
          <input
            id="start-date"
            v-model="form.start_date"
            type="date"
            :min="minDate"
            @input="validateDate"
            required
          />
        </div>
        <div v-if="dateWarning" class="date-warning col-span-full">
          ⚠️ {{ dateWarning }}
        </div>
        <div class="form-actions col-span-full">
          <button
            class="btn-upload"
            :disabled="!isFormValid || isUploading"
            @click="handleUpload"
          >
            {{ isUploading ? 'Загрузка...' : 'Загрузить шаблон' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Список шаблонов -->
    <div class="table-wrapper">
      <h3>Список шаблонов</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>Название</th>
            <th>Дата начала</th>
            <th>Статус</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="template in templates" :key="template.id">
            <td>{{ template.name }}</td>
            <td>{{ formatDate(template.start_date) }}</td>
            <td>
              <span v-if="template.id === currentTemplateId" class="status-badge current">
                Текущий
              </span>
              <span v-else class="status-badge upcoming">
                Предстоящий
              </span>
            </td>
            <td>
              <button class="btn-icon" @click="editTemplate(template)">✏️</button>
              <button class="btn-icon danger" @click="deleteTemplate(template.id)">🗑️</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!templates.length" class="empty-state">
        Нет загруженных шаблонов
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

definePageMeta({ layout: 'admin' })

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const templates = ref<any[]>([])
const currentTemplateId = ref<string | null>(null)

const form = ref({
  name: '',
  start_date: '',
})

// Минимальная дата — завтра
const today = new Date()
today.setDate(today.getDate() + 1)
const minDate = today.toISOString().split('T')[0]

// Предупреждение о дате
const dateWarning = computed(() => {
  if (!form.value.start_date) return ''
  
  const selectedDate = new Date(form.value.start_date)
  const maxExistingDate = getMaxExistingDate()
  
  if (selectedDate <= new Date()) {
    return 'Дата начала должна быть в будущем'
  }
  
  if (maxExistingDate && selectedDate <= maxExistingDate) {
    return `Дата должна быть позже ${formatDate(maxExistingDate)}`
  }
  
  return ''
})

const isFormValid = computed(() => {
  return (
    form.value.name &&
    form.value.start_date &&
    selectedFile.value &&
    !dateWarning.value
  )
})

function getMaxExistingDate() {
  if (!templates.value.length) return null
  const dates = templates.value.map(t => new Date(t.start_date))
  return new Date(Math.max(...dates))
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('ru-RU')
}

function validateDate() {
  // Валидация происходит автоматически через computed property
}

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
}

async function handleUpload() {
  if (!isFormValid.value || !selectedFile.value) return
  
  isUploading.value = true
  
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('name', form.value.name)
    formData.append('start_date', form.value.start_date)

    const response = await $fetch('/admin/proposal-templates', {
      baseURL: useRuntimeConfig().public.apiBase,
      method: 'POST',
      body: formData,
      credentials: 'include',
    })

    // Добавляем новый шаблон в список
    templates.value.unshift(response)
    
    // Очищаем форму
    form.value.name = ''
    form.value.start_date = ''
    selectedFile.value = null
    
    // Определяем текущий шаблон
    updateCurrentTemplate()
  } catch (err: any) {
    console.error('Upload failed:', err)
    alert(err?.data?.detail || 'Ошибка загрузки шаблона')
  } finally {
    isUploading.value = false
  }
}

async function loadTemplates() {
  try {
    const response = await $fetch('/admin/proposal-templates', {
      baseURL: useRuntimeConfig().public.apiBase,
      credentials: 'include',
    })
    templates.value = response.templates
    updateCurrentTemplate()
  } catch (err) {
    console.error('Failed to load templates:', err)
  }
}

function updateCurrentTemplate() {
  // Текущий шаблон — ближайшая дата >= today
  const todayDate = new Date()
  todayDate.setHours(0, 0, 0, 0)
  
  const current = templates.value
    .filter(t => new Date(t.start_date) >= todayDate)
    .sort((a, b) => new Date(a.start_date).getTime() - new Date(b.start_date).getTime())[0]
  
  currentTemplateId.value = current?.id || null
}

function editTemplate(template: any) {
  console.log('Edit template:', template.id)
  // TODO: Реализовать редактирование
}

async function deleteTemplate(templateId: string) {
  if (!confirm('Удалить шаблон?')) return
  
  try {
    await $fetch(`/admin/proposal-templates/${templateId}`, {
      baseURL: useRuntimeConfig().public.apiBase,
      method: 'DELETE',
      credentials: 'include',
    })
    
    // Удаляем из списка
    templates.value = templates.value.filter(t => t.id !== templateId)
    updateCurrentTemplate()
  } catch (err: any) {
    console.error('Delete failed:', err)
    alert(err?.data?.detail || 'Ошибка удаления шаблона')
  }
}

onMounted(() => {
  loadTemplates()
})
</script>
