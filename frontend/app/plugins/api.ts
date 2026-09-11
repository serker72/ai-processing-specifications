/**
 * Плагин Nuxt для настройки глобального $fetch с credentials.
 * 
 * credentials: 'include' — всегда отправлять куки с запросами.
 */

import { defineNuxtPlugin } from '#app'
import { useRuntimeConfig } from '#imports'

export default defineNuxtPlugin(async (nuxtApp) => {
  const config = useRuntimeConfig()
  const apiBase = config.public.apiBase

  // Создаём базовый $fetch с credentials
  const $api = $fetch.create({
    baseURL: apiBase,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  })

  // Вставляем $api в глобальный контекст Nuxt
  return {
    provide: {
      api: $api,
    },
  }
})
