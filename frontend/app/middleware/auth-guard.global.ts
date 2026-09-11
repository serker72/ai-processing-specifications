/**
 * Global route middleware: проверка аутентификации и доступа к разделам по роли.
 *
 * Суффикс `.global` в имени файла обязателен: иначе Nuxt не подключает
 * middleware к переходам, и страницы /admin/*, /manager/* остаются открытыми.
 *
 * Правила:
 *  - неавторизованный попадает на /login (с указанием, куда вернуться);
 *  - авторизованный не заходит на /login и на чужой раздел:
 *    /admin/** — только admin, /manager/** — только manager;
 *  - '/' и '/login' для авторизованного открывают домашнюю страницу его роли.
 *
 * Работает только на клиенте: access/refresh-куки ставит backend на своём
 * origin (см. plugins/api.ts), поэтому SSR-запрос в Nuxt их не получает и
 * проверить сессию на сервере нельзя. Это не средство защиты, а удобство —
 * настоящий контроль ролей остаётся на backend (require_role).
 */

import type { UserRole } from '~/composables/useAuth'

/** Раздел сайта и требуемая для него роль по префиксу пути. */
const SECTION_ROLE: Record<string, UserRole> = {
  admin: 'admin',
  manager: 'manager',
}

/** Раздел по пути ('/admin/users' → 'admin'); для остальных маршрутов — null. */
function sectionOf(path: string): UserRole | null {
  const section = path.split('/')[1]
  return SECTION_ROLE[section] ?? null
}

export default defineNuxtRouteMiddleware(async (to) => {
  if (import.meta.server) {
    return
  }

  const { user, isFetched, ensureAuth, homePath } = useAuth()

  // Пользователя ещё не запрашивали в этой сессии — поднимаем сессию
  // (me → при 401 refresh → me повторно). Повторных запросов на каждый
  // переход не делаем: состояние лежит в useState и видно всем страницам.
  if (!user.value && !isFetched.value) {
    await ensureAuth()
  }

  // Корень — не самостоятельная страница: гостя ведём на вход,
  // авторизованного — на домашний маршрут его роли.
  if (to.path === '/') {
    return user.value ? navigateTo(homePath.value) : navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }

  // Гостевые страницы: авторизованному здесь делать нечего
  if (to.path === '/login') {
    return user.value ? navigateTo(homePath.value) : undefined
  }

  if (!user.value) {
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }

  const required = sectionOf(to.path)
  if (required && user.value.role !== required) {
    // Чужой раздел — на домашнюю страницу своей роли
    return navigateTo(homePath.value)
  }

  return undefined
})
