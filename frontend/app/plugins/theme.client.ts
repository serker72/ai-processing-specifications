/**
 * Client-only плагин темы.
 *
 * Синхронизирует общий useState темы с классом `.dark`, который до гидратации
 * проставил блокирующий скрипт из nuxt.config.ts. Без этого состояния кнопки
 * переключателя расходились бы с фактической темой страницы.
 */

import { defineNuxtPlugin } from '#app'

import { useTheme } from '~/composables/useTheme'

export default defineNuxtPlugin({
  name: 'theme',
  enforce: 'post',
  setup() {
    useTheme().initTheme()
  },
})
