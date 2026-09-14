<template>
  <div class="workspace-layout">
    <aside class="sidebar">
      <!-- Панель зависит от роли и email из /auth/me, которые middleware поднимает
             только на клиенте (SSR не видит куки backend): без ClientOnly серверный
             HTML не совпадал бы с клиентским рендером (hydration mismatch).
             В fallback — статичное название, чтобы панель не была пустой. -->
      <ClientOnly>
        <!-- Логотип ведёт на домашний маршрут роли (useAuth.ROLE_HOME), поэтому
             клик по названию работает как «в начало раздела». -->
        <NuxtLink :to="homePath" class="brand">
          <span class="brand-name">{{ BRAND_NAME }}</span>
          <span class="brand-section">{{ sectionTitle }}</span>
        </NuxtLink>

        <nav>
          <NuxtLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="nav-item"
          >
            {{ item.label }}
          </NuxtLink>
        </nav>

        <div class="logout">
          <span class="user">{{ user?.email }}</span>
          <CommonThemeToggle />
          <button class="btn-delete w-full" @click="handleLogout">Выйти</button>
        </div>

        <template #fallback>
          <div class="brand">
            <span class="brand-name">{{ BRAND_NAME }}</span>
          </div>
        </template>
      </ClientOnly>
    </aside>

    <main class="content">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
/**
 * Общий layout рабочего кабинета: тёмная панель навигации слева + рабочая область.
 * Используется и администратором, и менеджером — наполнение меню берётся из
 * useNavMenu() по роли пользователя, вёрстка и цвета едины.
 * Подключается страницами definePageMeta({ layout: 'workspace' }).
 */
import { useAuth } from '~/composables/useAuth'
import { BRAND_NAME, useNavMenu } from '~/composables/useNavMenu'

const { user, homePath, logout } = useAuth()
const { sectionTitle, navItems } = useNavMenu(() => user.value?.role ?? null)

async function handleLogout() {
  await logout()
  // replace, чтобы «Назад» не возвращал в уже закрытую сессию
  await navigateTo('/login', { replace: true })
}
</script>

<style scoped>
.workspace-layout {
  display: flex;
  height: 100vh;
}

/* Панель всегда тёмная (токены --app-sidebar* в main.css), цвета контента
   через var(--app-*) не берутся — иначе в светлой теме она сливалась бы
   с рабочей областью. */
.sidebar {
  width: 250px;
  background: var(--app-sidebar);
  border-right: 1px solid var(--app-sidebar-border);
  color: var(--app-sidebar-text);
  display: flex;
  flex-direction: column;
  padding: 20px;
}

/* Шапка панели: название продукта + подпись раздела по роли. */
.brand {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 30px;
  text-decoration: none;
  color: var(--app-sidebar-text);
}

.brand-name {
  font-size: 1.5rem;
  font-weight: bold;
}

.brand-section {
  font-size: 12px;
  color: var(--app-sidebar-muted);
}

.nav-item {
  display: block;
  color: var(--app-sidebar-muted);
  text-decoration: none;
  padding: 10px 15px;
  margin-bottom: 5px;
  border-radius: 5px;
  transition: background 0.2s, color 0.2s;
}

.nav-item:hover {
  background: var(--app-sidebar-hover);
  color: var(--app-sidebar-text);
}

/* Активный пункт — сплошная синяя подложка: в тёмной панели accent-текст
   читается хуже, чем инвертированная плашка. Текст — белый в обеих темах
   (--app-sidebar-active-text), потому что и подложка, и панель не меняются. */
.nav-item.router-link-active {
  background: var(--app-sidebar-active);
  color: var(--app-sidebar-active-text);
}

.logout {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Email в панели: длинный адрес не должен расширять сайдбар. */
.user {
  color: var(--app-sidebar-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Переключатель темы стоит в тёмной панели, поэтому его светлые рамки и фон
   из utility-классов перекрашиваем в цвета панели. */
.logout :deep(.theme-toggle) {
  border-color: var(--app-sidebar-border);
  color: var(--app-sidebar-muted);
}

.logout :deep(.theme-toggle:hover) {
  background: var(--app-sidebar-hover);
  color: var(--app-sidebar-text);
}

.content {
  flex: 1;
  padding: 30px;
  background: var(--app-bg);
  overflow-y: auto;
}
</style>
