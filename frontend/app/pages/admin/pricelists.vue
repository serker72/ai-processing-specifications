<template>
  <div class="page-container">
    <h1>Прайс-листы</h1>
    
    <div class="upload-section">
      <h3>Загрузить новый прайс-лист</h3>
      <div class="upload-form-inline">
        <input type="file" ref="fileInput" accept=".xlsx" @change="handleFileSelect" style="display: none" />
        <button class="btn-upload" @click="fileInput?.click()">Выбрать файл</button>
        <span v-if="selectedFile" class="file-name flex-1">{{ selectedFile.name }}</span>
        <button 
          class="btn-submit" 
          :disabled="!selectedFile || isUploading"
          @click="handleUpload"
        >
          {{ isUploading ? 'Загрузка...' : 'Загрузить' }}
        </button>
      </div>
      <div v-if="uploadResult" class="result">
        <p>Upload ID: <code>{{ uploadResult.upload_id }}</code></p>
      </div>
    </div>

    <div class="table-wrapper">
      <h3>История загрузок</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Файл</th>
            <th>Загрузил</th>
            <th>Дата</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pl in pricelists" :key="pl.id">
            <td>{{ pl.id }}</td>
            <td>{{ pl.filename }}</td>
            <td>{{ pl.manager }}</td>
            <td>{{ new Date(pl.created_at).toLocaleDateString() }}</td>
            <td>
              <span :class="['status-badge', pl.status === 'completed' ? 'completed' : 'processing']">
                {{ pl.status }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const uploadResult = ref<any>(null)

// Mock data for demonstration
const pricelists = ref([
  { id: 'pl-1', filename: 'price_2023_09.xlsx', manager: 'Admin', created_at: '2023-09-01T10:00:00Z', status: 'completed' },
  { id: 'pl-2', filename: 'price_2023_08.xlsx', manager: 'Admin', created_at: '2023-08-15T14:30:00Z', status: 'completed' },
])

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement
  selectedFile.value = target.files?.[0] || null
}

async function handleUpload() {
  if (!selectedFile.value) return
  isUploading.value = true
  try {
    // TODO: Implement API call to upload pricelist
    console.log('Upload file:', selectedFile.value.name)
    uploadResult.value = { upload_id: 'new-upload-id' }
  } catch (err) {
    console.error('Upload failed', err)
  } finally {
    isUploading.value = false
  }
}
</script>
