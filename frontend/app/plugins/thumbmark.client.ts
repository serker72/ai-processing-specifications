/**
 * Client-only плагин ThumbmarkJS.
 *
 * Библиотека обращается к canvas/webgl/audio, поэтому может работать только в
 * браузере. Суффикс `.client.ts` в каталоге plugins — штатный способ Nuxt 3
 * зарегистрировать плагин с mode: 'client' (в серверный бандл он не попадает).
 *
 * Результат генерации кладётся в общий useState (к нему обращается
 * `useFingerprint()`) и в localStorage — так отпечаток доступен guard'ам и
 * запросу рефреша после перезагрузки страницы.
 */

import { ref } from 'vue'
import { defineNuxtPlugin } from '#app'
import { getFingerprint, getVersion } from '@thumbmarkjs/thumbmarkjs'

import {
  FINGERPRINT_MIN_LENGTH,
  readStoredFingerprint,
  writeStoredFingerprint,
} from '~/composables/useFingerprint'

export default defineNuxtPlugin({
  name: 'thumbmark',
  enforce: 'pre',
  setup() {
    // Стартовое значение берём из localStorage: повторная генерация не нужна,
    // если отпечаток уже определялся в этом браузере.
    const fingerprint = useState<string>('thumbmark:fingerprint', () => readStoredFingerprint())
    const isGenerating = ref(false)
    const error = ref<Error | null>(null)

    // Одна pending-промис на все вызовы: параллельные ensure() не запускают
    // генерацию несколько раз.
    let pending: Promise<string> | null = null

    async function generate(): Promise<string> {
      isGenerating.value = true
      error.value = null
      try {
        const value = await getFingerprint()
        // Пустой/короткий отпечаток бракуем: backend отклонит его с 422.
        if (!value || value.length < FINGERPRINT_MIN_LENGTH) {
          throw new Error(`ThumbmarkJS вернул некорректный fingerprint (длина ${value?.length ?? 0})`)
        }
        fingerprint.value = value
        writeStoredFingerprint(value)
        return value
      } catch (e) {
        error.value = e instanceof Error ? e : new Error(String(e))
        throw error.value
      } finally {
        isGenerating.value = false
      }
    }

    function ensure(): Promise<string> {
      if (fingerprint.value) {
        return Promise.resolve(fingerprint.value)
      }
      if (!pending) {
        pending = generate().finally(() => {
          pending = null
        })
      }
      return pending
    }

    // Прогрев в фоне: canvas-замеры занимают время, а рендер страницы ждать
    // не должен. Страницы, которым нужен отпечаток, вызывают init()/ensure().
    if (!fingerprint.value) {
      ensure().catch(() => {
        // Ошибка уже в ref error — сообщим её в момент обращения к отпечатку.
      })
    }

    return {
      provide: {
        thumbmark: { fingerprint, isGenerating, error, ensure, version: getVersion() },
      },
    }
  },
})
