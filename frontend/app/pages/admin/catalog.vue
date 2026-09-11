<template>
  <div class="page-container">
    <h1>Каталог номенклатуры</h1>
    
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr>
            <th>SKU</th>
            <th>Наименование</th>
            <th>Ед. изм.</th>
            <th>Цена</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in catalog" :key="item.id">
            <td>{{ item.sku }}</td>
            <td>{{ item.name }}</td>
            <td>{{ item.unit }}</td>
            <td>{{ item.price }}</td>
            <td>
              <button class="btn-edit" @click="editItem(item)">Изменить</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: 'admin' })

// Mock data for demonstration
const catalog = ref([
  { id: '1', sku: 'AVT-010', name: 'Автоматический выключатель 16А', unit: 'шт.', price: 320.0 },
  { id: '2', sku: 'KAB-001', name: 'Кабель ВВГнг-LS 3х2.5', unit: 'м', price: 145.5 },
  { id: '3', sku: 'KAB-002', name: 'Кабель ПВС 2х1.5', unit: 'м', price: 89.9 },
])

function editItem(item: any) {
  console.log('Edit item', item.sku)
}
</script>
