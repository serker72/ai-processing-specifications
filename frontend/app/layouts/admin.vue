<template>
  <div class="admin-layout">
    <aside class="sidebar">
      <div class="logo">AI Specs Admin</div>
      <nav>
        <NuxtLink to="/admin/users" class="nav-item">Пользователи</NuxtLink>
        <NuxtLink to="/admin/devices" class="nav-item">Устройства</NuxtLink>
        <NuxtLink to="/admin/sessions" class="nav-item">Сессии</NuxtLink>
        <NuxtLink to="/admin/pricelists" class="nav-item">Прайс-листы</NuxtLink>
        <NuxtLink to="/admin/catalog" class="nav-item">Каталог</NuxtLink>
        <NuxtLink to="/admin/proposal-templates" class="nav-item">Шаблоны КП</NuxtLink>
      </nav>
      <div class="logout">
        <span class="user">{{ user?.email }}</span>
        <CommonThemeToggle />
        <button class="btn-delete w-full" @click="handleLogout">Выйти</button>
      </div>
    </aside>
    <main class="content">
      <NuxtPage />
    </main>
  </div>
</template>

<script setup lang="ts">
/**
 * Layout админки: постоянная тёмная панель навигации + рабочая область справа.
 * Подключается страницами /admin/** через definePageMeta({ layout: 'admin' }).
 */
import { useAuth } from '~/composables/useAuth'

const { user, logout } = useAuth()

async function handleLogout() {
  await logout()
  // replace, чтобы «Назад» не возвращал в уже закрытую сессию
  await navigateTo('/login', { replace: true })
}
</script>

<style scoped>
.admin-layout {
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

.logo {
  font-size: 1.5rem;
  font-weight: bold;
  margin-bottom: 30px;
  color: var(--app-sidebar-text);
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
   читается хуже, чем инвертированная плашка. */
.nav-item.router-link-active {
  background: var(--app-sidebar-active);
  color: #fff;
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
