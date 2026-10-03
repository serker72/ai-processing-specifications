<template>
  <!-- Скелетон-строки таблицы на время загрузки: columns задаёт число ячеек,
       rows — число строк (по умолчанию 5). Рендерится прямо в <tbody>. -->
  <tr v-for="row in rows" :key="row" class="skeleton-row">
    <td v-for="col in columns" :key="col">
      <span class="skeleton-line" />
    </td>
  </tr>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ columns: number; rows?: number }>(), { rows: 5 })
</script>
