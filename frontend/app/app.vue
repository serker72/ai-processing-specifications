<template>
  <!-- NuxtLayout обязателен: в собственном app.vue без обёртки layout из
       definePageMeta игнорируется, и страницы рендерились «голыми» — не
       выводились ни шапка default, ни панель admin. Страницы с layout: false
       (index.vue) NuxtLayout пропускает. -->
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
