<template>
  <!-- Цвета только из токенов темы (@theme inline в assets/css/main.css):
       утилиты bg-app-*/text-app-* подставляют var(--app-*), поэтому переключение
       темы меняет всё сразу — dark:-варианты здесь не нужны. -->
  <div class="min-h-screen bg-app-bg text-app-text">
    <nav class="border-b border-app-border bg-app-surface shadow-sm">
      <div class="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <span class="text-xl font-bold">Auth System</span>

        <div class="flex items-center gap-4">
          <CommonThemeToggle />

          <!-- На /login пользователя нет: показывать пустой email и «Выход» гостю
               бессмысленно. -->
          <template v-if="user">
            <span class="hidden text-sm text-app-muted sm:inline">{{ user.email }}</span>

            <button
              type="button"
              class="rounded bg-app-danger px-4 py-2 text-sm text-white transition-colors hover:bg-app-danger-strong"
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
 * Layout со страницами в один столбец (вход, рабочее место менеджера): шапка с
 * переключателем темы, email пользователя и выходом. Для /admin/** есть
 * отдельный layout admin с панелью навигации. Авторизация и роли — на страницах
 * и в auth-guard, здесь только отображение уже загруженного пользователя.
 */
const { user, logout } = useAuth()

async function handleLogout() {
  await logout()
  // replace, чтобы «Назад» не возвращал в уже закрытую сессию
  await navigateTo('/login', { replace: true })
}
</script>
