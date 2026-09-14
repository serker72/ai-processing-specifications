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
            <td>
              <!-- Режим правки: название и дата начала меняются PATCH-запросом -->
              <input v-if="editingId === template.id" v-model="editForm.name" class="form-control" />
              <span v-else>{{ template.name }}</span>
            </td>
            <td>
              <input
                v-if="editingId === template.id"
                v-model="editForm.start_date"
                class="form-control"
                type="date"
              />
              <span v-else>{{ formatDate(template.start_date) }}</span>
            </td>
            <td>
              <span v-if="template.id === currentTemplateId" class="status-badge current">
                Текущий
              </span>
              <span v-else class="status-badge upcoming">
                Предстоящий
              </span>
            </td>
            <td>
              <template v-if="editingId === template.id">
                <button class="btn-icon" :disabled="isSaving" @click="saveTemplate(template)">
                  💾
                </button>
                <button class="btn-icon" :disabled="isSaving" @click="editingId = null">✖️</button>
              </template>
              <template v-else>
                <button class="btn-icon" @click="startEdit(template)">✏️</button>
                <button class="btn-icon danger" @click="deleteTemplate(template.id)">🗑️</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!templates.length" class="empty-state">
        {{ isLoading ? 'Загрузка списка…' : 'Нет загруженных шаблонов' }}
      </div>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

definePageMeta({ layout: 'workspace' })

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const isLoading = ref(false)
const templates = ref<any[]>([])
const currentTemplateId = ref<string | null>(null)
const error = ref('')

// Правка шаблона в таблице: id редактируемой строки и её новые значения
const editingId = ref<string | null>(null)
const isSaving = ref(false)
const editForm = ref({ name: '', start_date: '' })

// $api — API-клиент из plugins/api.ts: credentials и повтор запроса после 401
const { $api } = useNuxtApp() as any

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

    await $api('/admin/proposal-templates', {
      method: 'POST',
      body: formData,
    })

    // Очищаем форму
    form.value.name = ''
    form.value.start_date = ''
    selectedFile.value = null

    // Список перечитываем: backend возвращает только созданный объект,
    // а порядок и «текущий» шаблон считает loadTemplates()
    await loadTemplates()

  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить шаблон'
  } finally {
    isUploading.value = false
  }
}

async function loadTemplates() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/admin/proposal-templates')
    templates.value = response.templates
    updateCurrentTemplate()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить список шаблонов'
  } finally {
    isLoading.value = false
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

function startEdit(template: any) {
  editingId.value = template.id
  // input[type=date] принимает только дату (YYYY-MM-DD), backend отдаёт datetime
  editForm.value = {
    name: template.name,
    start_date: new Date(template.start_date).toISOString().split('T')[0],
  }
}

async function saveTemplate(template: any) {
  if (!editForm.value.name || !editForm.value.start_date) {
    error.value = 'Укажите название и дату начала'
    return
  }

  isSaving.value = true
  error.value = ''
  try {
    const updated = await $api(`/admin/proposal-templates/${template.id}`, {
      method: 'PATCH',
      body: { name: editForm.value.name, start_date: editForm.value.start_date },
    })
    template.name = updated.name
    template.start_date = updated.start_date
    editingId.value = null
    updateCurrentTemplate()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось обновить шаблон'
  } finally {
    isSaving.value = false
  }
}

async function deleteTemplate(templateId: string) {
  if (!confirm('Удалить шаблон?')) return
  
  try {
    await $api(`/admin/proposal-templates/${templateId}`, { method: 'DELETE' })
    
    // Удаляем из списка
    templates.value = templates.value.filter(t => t.id !== templateId)
    updateCurrentTemplate()
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось удалить шаблон'
  }
}

onMounted(() => {
  loadTemplates()
})
</script>
