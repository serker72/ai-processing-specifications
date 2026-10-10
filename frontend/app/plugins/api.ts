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
 * «чистым» клиентом без обёртки и однократно на волну 401: параллельные запросы
 * страницы ждут один refresh, а не вызывают его каждый. Если рефреш не помог
 * (refresh-токен истёк или отозван), сессия считается закрытой — состояние
 * очищается и пользователь уходит на /login.
 *
 * Повтор при 401 сделан функцией-обёрткой $api, а не интерцептором ofetch
 * onResponseError: ofetch 1.5.1 игнорирует возвращаемое значение onResponseError
 * и всегда бросает исходную ошибку, поэтому результат повторного запроса из
 * интерцептора вызывающему коду не вернуть.
 */

import { defineNuxtPlugin, navigateTo, useState, useRuntimeConfig } from '#imports'
import type { AuthUser } from '~/composables/useAuth'

/** Auth-эндпоинты: 401 на них — штатный ответ, рефреш по нему вызывать нельзя. */
const AUTH_PATHS = ['/auth/login', '/auth/refresh', '/auth/logout']

function isAuthCall(request: unknown): boolean {
  const path = String(request)
  return AUTH_PATHS.some((prefix) => path.includes(prefix))
}

/**
 * Опции запроса $api. Тело можно передать функцией () => FormData: ofetch
 * навешивает на переданный объект FormData проверочный флаг, поэтому повтор с
 * тем же объектом мог бы уйти без корректного multipart boundary.
 */
export interface ApiRequestOptions {
  method?: string
  headers?: Record<string, any>
  query?: Record<string, any>
  body?: any | (() => FormData)
  responseType?: 'json' | 'text' | 'blob' | 'arrayBuffer' | 'stream'
  timeout?: number
  signal?: AbortSignal
  [key: string]: any
}

export type ApiCall = <T = any>(request: string, options?: ApiRequestOptions) => Promise<T>

export default defineNuxtPlugin((nuxtApp) => {
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase

  // Клиент без обёртки 401→refresh: нужен для /auth/refresh, чтобы 401 рефреша
  // не запустил рефреш повторно.
  const rawApi = $fetch.create({
    baseURL: apiBase,
    credentials: 'include',
    retry: 0,
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

  /**
   * Закрыть сессию: очистить состояние пользователя (те же useState, что у
   * useAuth) и уйти на вход, сохранив, куда вернуться после логина.
   */
  async function signOutAndRedirect(): Promise<void> {
    useState<AuthUser | null>('auth:user', () => null).value = null
    useState<boolean>('auth:fetched', () => false).value = true
    const redirect = import.meta.client ? window.location.pathname : undefined
    await navigateTo({ path: '/login', query: redirect ? { redirect } : {} })
  }

  /**
   * Клиент API с обработкой 401: рефреш токена и повтор запроса с теми же
   * опциями — результат повтора получает вызывающий код.
   *
   * Повтор ровно один: второй 401 означает «доступа нет», ошибка уходит выше, и
   * страница решает сама (тост, сообщение в форме). Исключение — ответ 2xx без
   * тела (204): он не ошибка, и повторять его нельзя — иначе команда,
   * отдавшая 204, выполнится на сервере дважды.
   */
  const $api: ApiCall = async <T = any>(request: string, options: ApiRequestOptions = {}): Promise<T> => {
    const attempt = (): Promise<T> => {
      const { body, ...rest } = options
      const resolved = typeof body === 'function' ? (body as () => any)() : body
      return rawApi<T>(request, { ...rest, retry: 0, body: resolved })
    }

    try {
      return await attempt()
    } catch (err: any) {
      const status = err?.statusCode ?? err?.response?.status
      if (status !== 401 || isAuthCall(request)) {
        throw err
      }

      if (!(await refreshOnce())) {
        // Сессия закрыта: refresh-токен истёк или отозван — остаётся только
        // войти заново. Исходную ошибку бросаем выше, чтобы catch страницы
        // считал запрос завершённым (редирект на /login уже выполнен).
        await signOutAndRedirect()
        throw err
      }

      return await attempt()
    }
  }

  return {
    provide: {
      api: $api,
      authRefresh: refreshOnce,
    },
  }
})
