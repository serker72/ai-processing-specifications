/**
 * Плагин API-клиента $api: общие настройки запросов к backend и обработка 401.
 *
 * credentials: 'include' — обязателен, auth-токены приходят HttpOnly-куками с
 * origin backend.
 *
 * Content-Type по умолчанию НЕ задаётся: ofetch сам ставит application/json для
 * объектов и корректный multipart/form-data для FormData (явный заголовок сломал
 * бы загрузку файлов).
 *
 * 401 → /auth/refresh → повтор исходного запроса (задача 6.1). Рефреш выполняется
 * «чистым» клиентом без интерцептора и однократно на волну 401: параллельные
 * запросы страницы ждут один refresh, а не вызывают его каждый. Если рефреш не
 * помог (refresh-токен истёк или отозван), сессия считается закрытой — состояние
 * очищается и пользователь уходит на /login.
 */

import { defineNuxtPlugin, navigateTo, useState, useRuntimeConfig } from '#imports'
import type { AuthUser } from '~/composables/useAuth'

/** Auth-эндпоинты: 401 на них — штатный ответ, рефреш по нему вызывать нельзя. */
const AUTH_PATHS = ['/auth/login', '/auth/refresh', '/auth/logout']

function isAuthCall(request: unknown): boolean {
  const path = String(request)
  return AUTH_PATHS.some((prefix) => path.includes(prefix))
}

export default defineNuxtPlugin((nuxtApp) => {
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase

  // Клиент без интерцептора: нужен для /auth/refresh, чтобы 401 рефреша
  // не запустил рефреш повторно.
  const rawApi = $fetch.create({
    baseURL: apiBase,
    credentials: 'include',
  })

  let refreshInFlight: Promise<boolean> | null = null

  /** Обновить access-токен; повторные вызовы во время рефреша ждут первый. */
  async function refreshOnce(): Promise<boolean> {
    if (!refreshInFlight) {
      refreshInFlight = (async () => {
        try {
          // Backend требует fingerprint и в теле /auth/refresh (app/schemas/auth.py).
          const thumbmark = (nuxtApp as any).$thumbmark
          const fingerprint: string = thumbmark ? await thumbmark.ensure() : ''
          if (!fingerprint) {
            return false
          }
          await rawApi('/auth/refresh', { method: 'POST', body: { fingerprint } })
          return true
        } catch {
          return false
        }
      })().finally(() => {
        refreshInFlight = null
      })
    }
    return refreshInFlight
  }

  const $api = $fetch.create({
    baseURL: apiBase,
    credentials: 'include',
    retry: 0,

    async onResponseError({ request, response, options }) {
      if (response?.status !== 401 || isAuthCall(request)) {
        return
      }

      if (!(await refreshOnce())) {
        // Сессия закрыта: очищаем состояние пользователя (те же useState, что у
        // useAuth) и уходим на вход, сохранив, куда вернуться после логина.
        useState<AuthUser | null>('auth:user', () => null).value = null
        useState<boolean>('auth:fetched', () => false).value = true
        const redirect = import.meta.client ? window.location.pathname : undefined
        await navigateTo({ path: '/login', query: redirect ? { redirect } : {} })
        return
      }

      // Повтор с исходными параметрами: baseURL передаём явно, retry оставляем 0,
      // чтобы повтор не мог породить цепочку повторов.
      return await $fetch(String(request), { ...options, baseURL: apiBase, retry: 0 })
    },
  })

  return {
    provide: {
      api: $api,
    },
  }
})
