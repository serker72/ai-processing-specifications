<template>
  <!-- Цвета только из токенов темы (@theme inline в assets/css/main.css):
       утилиты bg-app-*/text-app-* подставляют var(--app-*), поэтому переключение
       темы меняет всё сразу — dark:-варианты здесь не нужны. -->
  <div class="min-h-screen bg-app-bg text-app-text">
    <nav class="border-b border-app-border bg-app-surface shadow-sm">
      <div class="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <span class="text-xl font-bold">
          {{ BRAND_NAME }}
          <span class="ml-2 hidden text-sm font-normal text-app-muted sm:inline">{{ brandSection }}</span>
        </span>

        <div class="flex items-center gap-4">
          <CommonThemeToggle />

          <!-- На /login пользователя нет: показывать пустой email и «Выход» гостю
               бессмысленно. -->
          <template v-if="user">
            <span class="hidden text-sm text-app-muted sm:inline">{{ user.email }}</span>

            <button
              type="button"
              class="rounded bg-app-danger px-4 py-2 text-sm text-app-on-accent transition-colors hover:bg-app-danger-strong"
              @click="handleLogout"
            >
              Выход
            </button>
          </template>
        </div>
      </div>
    </nav>

    <main class="py-10">
      <NuxtPage />
    </main>
  </div>
</template>

<script setup lang="ts">
/**
 * Layout страницы входа: шапка с названием продукта, переключателем темы, email
 * пользователя и выходом. Кабинеты администратора и менеджера используют общий
 * layout workspace с панелью навигации, поэтому сюда гость попадает только на
 * /login (авторизованного auth-guard ведёт в его кабинет).
 */
import { useAuth } from '~/composables/useAuth'
import { BRAND_NAME } from '~/composables/useNavMenu'

const { user, logout } = useAuth()

async function handleLogout() {
  await logout()
  // replace, чтобы «Назад» не возвращал в уже закрытую сессию
  await navigateTo('/login', { replace: true })
}
</script>
