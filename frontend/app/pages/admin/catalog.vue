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
      <table v-if="items.length || showSkeleton" class="data-table">
        <thead>
          <tr>
            <th>Артикул</th>
            <th>Наименование</th>
            <th>Ед. изм.</th>
            <th>Цена</th>
            <th>Добавлена</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <template v-if="showSkeleton">
            <CommonTableSkeleton :columns="6" />
          </template>
          <template v-else>
            <tr v-for="item in items" :key="item.id">
              <td class="mono">{{ item.sku }}</td>
              <td>
                <input v-if="editingId === item.id" v-model="editForm.name" class="form-control" />
                <span v-else>{{ item.name }}</span>
              </td>
              <td>
                <input v-if="editingId === item.id" v-model="editForm.unit" class="form-control" />
                <span v-else>{{ item.unit || '—' }}</span>
              </td>
              <td>
                <input
                  v-if="editingId === item.id"
                  v-model="editForm.price"
                  class="form-control"
                  type="number"
                  min="0"
                  step="0.01"
                />
                <span v-else>{{ formatPrice(item.price) }}</span>
              </td>
              <td>{{ formatDate(item.created_at) }}</td>
              <td>
                <template v-if="editingId === item.id">
                  <button class="btn-icon" :disabled="isSaving" title="Сохранить" @click="saveItem(item)">
                    💾
                  </button>
                  <button
                    class="btn-icon"
                    :disabled="isSaving"
                    title="Отмена"
                    @click="editingId = null"
                  >
                    ✖️
                  </button>
                </template>
                <button v-else class="btn-icon" title="Редактировать" @click="startEdit(item)">
                  ✏️
                </button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <div v-else class="empty-state">
        {{ search ? 'Ничего не найдено' : 'Каталог пуст' }}
      </div>
    </div>

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
 * Каталог номенклатуры: страницы позиций из GET /admin/catalog и инлайн-правка
 * наименования/единицы/цены через PATCH /admin/catalog/{id}.
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
const toast = useToast()

const items = ref<CatalogItem[]>([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const searchQuery = ref('')
const isLoading = ref(false)
/** Скелетон вместо пустого состояния — только на первой загрузке страницы. */
const showSkeleton = computed(() => isLoading.value && items.value.length === 0)

// Правка позиции в таблице: id редактируемой строки и её новые значения
const editingId = ref<string | null>(null)
const isSaving = ref(false)
const editForm = ref({ name: '', unit: '', price: '' })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function formatPrice(price: number | null) {
  return price === null ? '—' : `${price.toFixed(2)} ₽`
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('ru-RU')
}

async function loadCatalog() {
  isLoading.value = true
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
    toast.fromError(err, 'Не удалось загрузить каталог')
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

function startEdit(item: CatalogItem) {
  editingId.value = item.id
  editForm.value = {
    name: item.name,
    unit: item.unit ?? '',
    price: item.price === null ? '' : String(item.price),
  }
}

async function saveItem(item: CatalogItem) {
  const name = editForm.value.name.trim()
  if (!name) {
    toast.error('Наименование не может быть пустым')
    return
  }

  const price = editForm.value.price === '' ? null : Number(editForm.value.price)
  if (price !== null && (!Number.isFinite(price) || price < 0)) {
    toast.error('Цена должна быть неотрицательным числом')
    return
  }

  isSaving.value = true
  try {
    const updated = await $api(`/admin/catalog/${item.id}`, {
      method: 'PATCH',
      body: {
        name,
        unit: editForm.value.unit.trim() || null,
        price,
      },
    })
    item.name = updated.name
    item.unit = updated.unit
    item.price = updated.price
    editingId.value = null
    toast.success('Позиция каталога сохранена')
  } catch (err: any) {
    toast.fromError(err, 'Не удалось сохранить изменения')
  } finally {
    isSaving.value = false
  }
}

onMounted(loadCatalog)
</script>
