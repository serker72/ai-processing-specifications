/**
 * Composable аутентификации: логин, рефреш, выход, данные текущего пользователя.
 *
 * Общие состояния (`auth:user`, `auth:fetched`) хранятся в useState Nuxt, а не в
 * ref внутри useAuth(): их видят layout, middleware и все страницы сразу, на
 * сервере такие состояния изолированы по запросам (данные одного посетителя не
 * «протекают» в рендер другого), а на клиенте переживают переходы между
 * страницами и повторные вызовы useAuth().
 *
 * Роль пользователя берётся из ответа backend (GET /auth/me), а не из
 * localStorage: клиентские флаги не являются основанием для показа админ-разделов,
 * проверка ролей остаётся на сервере.
 */

import { computed, ref } from 'vue'

import { ROLE_NAV } from '~/composables/useNavMenu'

export type UserRole = 'admin' | 'manager'

/** Ответ GET /auth/me (backend/app/schemas/user.py). */
export interface AuthUser {
  id: string
  email: string
  role: UserRole
}

/**
 * Домашняя страница роли: единственное место, куда ведут вход и корень сайта.
 * Берётся из первого пункта меню раздела (useNavMenu.ROLE_NAV), чтобы после
 * входа открывался раздел, который пользователь видит в панели активным.
 */
export const ROLE_HOME: Record<UserRole, string> = {
  admin: ROLE_NAV.admin.items[0].to,
  manager: ROLE_NAV.manager.items[0].to,
}

/**
 * Выполняет логин пользователя.
 *
 * @param email — email пользователя
 * @param password — пароль
 * @param fingerprint — fingerprint устройства (обязательно)
 */
export function useAuth() {
  const { $api } = useNuxtApp() as any

  const user = useState<AuthUser | null>('auth:user', () => null)
  const fetched = useState<boolean>('auth:fetched', () => false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function login(email: string, password: string, fingerprint: string) {
    isLoading.value = true
    error.value = null

    try {
      await $api('/auth/login', {
        method: 'POST',
        body: { email, password, fingerprint },
      })

      // Login отдаёт 204 и только HttpOnly-куки: роль берём из /auth/me,
      // иначе страница после входа не знает, на какой маршрут её редиректить.
      const profile = await fetchMe({ force: true })
      if (!profile) {
        error.value = 'Не удалось определить роль пользователя'
        return { success: false, error: error.value }
      }

      return { success: true, user: profile, home: ROLE_HOME[profile.role] }
    } catch (err: any) {
      error.value = err?.data?.detail || err?.message || 'Ошибка авторизации'
      user.value = null
      return { success: false, error: error.value }
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Выполняет рефреш access-токена (явный вызов: ensureAuth после 401).
   * В фоновом режиме 401 обрабатывает интерцептор plugins/api.ts — он обновляет
   * токен своим запросом и повторяет исходный, не заходя в этот метод.
   */
  async function refresh() {
    // Backend требует fingerprint и в теле /auth/refresh (app/schemas/auth.py).
    const fingerprint = await resolveFingerprint()

    if (!fingerprint) {
      user.value = null
      return { success: false, error: 'Fingerprint не определён' }
    }

    try {
      await $api('/auth/refresh', { method: 'POST', body: { fingerprint } })
      return { success: true }
    } catch {
      // Рефреш провалился — пользователь считается не авторизованным
      user.value = null
      return { success: false, error: 'Сессия истекла' }
    }
  }

  /**
   * Возвращает данные текущего пользователя, при необходимости загрузив их.
   *
   * @param options.force — запросить /auth/me даже если данные уже есть
   * (например, сразу после входа или при подозрении на смену роли).
   */
  async function fetchMe(options: { force?: boolean } = {}): Promise<AuthUser | null> {
    if (user.value && !options.force) {
      return user.value
    }

    try {
      const profile = (await $api('/auth/me')) as AuthUser
      user.value = profile
      return profile
    } catch {
      // 401/403 — доступа нет; состояние очищаем, редирект решает middleware
      user.value = null
      return null
    } finally {
      fetched.value = true
    }
  }

  /**
   * Гарантированно возвращает пользователя или null: уже загруженные данные →
   * /auth/me → рефреш токена → /auth/me повторно. Использует auth-guard.
   */
  async function ensureAuth(): Promise<AuthUser | null> {
    if (user.value) {
      return user.value
    }
    if (await fetchMe()) {
      return user.value
    }
    const refreshed = await refresh()
    if (refreshed.success) {
      await fetchMe({ force: true })
    }
    return user.value
  }

  /**
   * Выполняет выход из системы.
   */
  async function logout() {
    try {
      await $api('/auth/logout', { method: 'POST' })
    } catch {
      // Игнорируем ошибки при выходе
    } finally {
      user.value = null
    }
  }

  /** Fingerprint из client-only плагина ThumbmarkJS (пустая строка, если недоступен). */
  async function resolveFingerprint(): Promise<string> {
    try {
      const thumbmark = (useNuxtApp() as any).$thumbmark
      return thumbmark ? await thumbmark.ensure() : ''
    } catch {
      return ''
    }
  }

  return {
    user: computed(() => user.value),
    isAuthenticated: computed(() => user.value !== null),
    isAdmin: computed(() => user.value?.role === 'admin'),
    isManager: computed(() => user.value?.role === 'manager'),
    homePath: computed(() => (user.value ? ROLE_HOME[user.value.role] : '/login')),
    isFetched: computed(() => fetched.value),
    isLoading: computed(() => isLoading.value),
    error: computed(() => error.value),
    login,
    refresh,
    fetchMe,
    ensureAuth,
    logout,
  }
}
