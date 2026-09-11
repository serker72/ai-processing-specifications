<template>
  <!-- Страница не показывается: auth-guard перехватывает '/' раньше и ведёт
       гостя на /login, а авторизованного — на домашний маршрут его роли. -->
  <div class="flex min-h-screen items-center justify-center text-app-muted">
    Перенаправляем…
  </div>
</template>

<script setup lang="ts">
/**
 * Корневой маршрут — редирект по роли.
 *
 * Основная логика в middleware/auth-guard.global.ts; здесь — страховка на случай,
 * если страница всё же отрендерилась (например, guard отключат): на клиенте
 * всё равно уходим на домашний маршрут роли или на вход.
 */
definePageMeta({ layout: false })

const { user, homePath } = useAuth()

if (import.meta.client) {
  await navigateTo(user.value ? homePath.value : '/login', { replace: true })
}
</script>
