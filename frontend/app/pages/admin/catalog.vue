<template>
  <div class="page-container">
    <h1>Каталог номенклатуры</h1>

    <div class="upload-form-inline mb-5">
      <input
        v-model="searchQuery"
        class="form-control"
        type="search"
        placeholder="Наименование или артикул"
        @keyup.enter="applySearch"
      />
      <button class="btn-action" :disabled="isLoading" @click="applySearch">Найти</button>
      <button
        v-if="search || searchQuery"
        class="btn-secondary"
        :disabled="isLoading"
        @click="resetSearch"
      >
        Сбросить
      </button>
    </div>

    <div class="table-wrapper">
      <table v-if="items.length" class="data-table">
        <thead>
          <tr>
            <th>Артикул</th>
            <th>Наименование</th>
            <th>Ед. изм.</th>
            <th>Цена</th>
            <th>Добавлена</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td class="mono">{{ item.sku }}</td>
            <td>{{ item.name }}</td>
            <td>{{ item.unit || '—' }}</td>
            <td>{{ formatPrice(item.price) }}</td>
            <td>{{ formatDate(item.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">
        {{ isLoading ? 'Загрузка списка…' : search ? 'Ничего не найдено' : 'Каталог пуст' }}
      </div>
    </div>

    <p v-if="error" class="text-danger">{{ error }}</p>

    <div class="form-actions flex flex-wrap items-center gap-2">
      <button class="btn-secondary" :disabled="isLoading || page <= 1" @click="goToPage(page - 1)">
        Назад
      </button>
      <span class="text-muted text-sm">
        Страница {{ page }} из {{ totalPages }} · всего {{ total }}
      </span>
      <button
        class="btn-secondary"
        :disabled="isLoading || page >= totalPages"
        @click="goToPage(page + 1)"
      >
        Вперёд
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Каталог номенклатуры: страницы позиций из GET /admin/catalog.
 * Позиции наполняются из прайс-листов после подтверждения маппинга колонок,
 * поэтому поиск и пагинация нужны — листы бывают на тысячи строк.
 */
import { computed, onMounted, ref } from 'vue'

definePageMeta({ layout: 'workspace' })

/** Ответ backend: app/schemas/catalog.py (CatalogItemResponse). */
interface CatalogItem {
  id: string
  sku: string
  name: string
  unit: string | null
  price: number | null
  created_at: string
}

const PAGE_SIZE = 50

const { $api } = useNuxtApp() as any

const items = ref<CatalogItem[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const searchQuery = ref('')
const isLoading = ref(false)
const error = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function formatPrice(price: number | null) {
  return price === null ? '—' : `${price.toFixed(2)} ₽`
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('ru-RU')
}

async function loadCatalog() {
  isLoading.value = true
  error.value = ''
  try {
    const response = await $api('/admin/catalog', {
      query: {
        page: page.value,
        page_size: PAGE_SIZE,
        ...(search.value ? { search: search.value } : {}),
      },
    })
    items.value = response.items
    total.value = response.total
  } catch (err: any) {
    error.value = err?.data?.detail || 'Не удалось загрузить каталог'
  } finally {
    isLoading.value = false
  }
}

function applySearch() {
  search.value = searchQuery.value.trim()
  page.value = 1
  loadCatalog()
}

function resetSearch() {
  searchQuery.value = ''
  applySearch()
}

function goToPage(target: number) {
  page.value = Math.min(Math.max(1, target), totalPages.value)
  loadCatalog()
}

onMounted(loadCatalog)
</script>
