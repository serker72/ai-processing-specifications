/**
 * Composable для работы с fingerprint устройства.
 *
 * Отпечаток формирует библиотека ThumbmarkJS (canvas/webgl/audio/math замеры),
 * результат — стабильный hex-хэш. Генерация возможна только в браузере, поэтому
 * библиотека подключается в client-only плагине `~/plugins/thumbmark.client.ts`,
 * а здесь — только доступ к значению и ожидание готовности.
 *
 * Fingerprint отправляется в теле запросов /auth/login и /auth/refresh:
 * backend привязывает токены к отпечатку (app/schemas/auth.py, min_length=8).
 */

import { computed, ref, type Ref } from 'vue'

/** Ключ localStorage: по нему auth-guard проверяет, что устройство опознано. */
export const FINGERPRINT_STORAGE_KEY = 'device_fingerprint'

/** Минимальная длина отпечатка, которую принимает backend (Field(min_length=8)). */
export const FINGERPRINT_MIN_LENGTH = 8

/** Публичный API client-only плагина `$thumbmark`. */
export interface ThumbmarkClient {
  fingerprint: Ref<string>
  isGenerating: Ref<boolean>
  error: Ref<Error | null>
  ensure: () => Promise<string>
  version: string
}

/**
 * Читает fingerprint из localStorage.
 * Пустая строка — отпечаток ещё не генерировался в этом браузере.
 */
export function readStoredFingerprint(): string {
  try {
    return localStorage.getItem(FINGERPRINT_STORAGE_KEY) ?? ''
  } catch {
    // localStorage недоступен (например, приватный режим)
    return ''
  }
}

/**
 * Сохраняет fingerprint в localStorage, чтобы он пережил перезагрузку страницы.
 */
export function writeStoredFingerprint(value: string): void {
  try {
    localStorage.setItem(FINGERPRINT_STORAGE_KEY, value)
  } catch {
    // localStorage недоступен
  }
}

/**
 * Composable для работы с fingerprint устройства.
 * Возвращает reactive refs и init() для ожидания значения перед запросом.
 */
export function useFingerprint() {
  // Общее состояние: плагин пишет в этот же useState, поэтому значение
  // синхронно обновляется во всех компонентах по завершении генерации.
  const fingerprint = useState<string>('thumbmark:fingerprint', () => '')
  const client = import.meta.client ? ((useNuxtApp() as any).$thumbmark as ThumbmarkClient | undefined) : undefined

  // На сервере плагина нет: генерация не запускается, значение остаётся пустым.
  const localError = ref<Error | null>(null)
  const isGenerating = client ? client.isGenerating : ref(false)
  const pluginError = client ? client.error : localError

  /**
   * Возвращает fingerprint, при необходимости дождавшись генерации.
   * Вызывать перед /auth/login и /auth/refresh — иначе на сервер уйдёт пустое
   * значение и backend ответит 422 string_too_short.
   */
  async function init(): Promise<string> {
    if (!client) {
      localError.value = new Error('Fingerprint недоступен: генерация возможна только в браузере')
      return ''
    }
    try {
      return await client.ensure()
    } catch (e) {
      localError.value = e instanceof Error ? e : new Error(String(e))
      return ''
    }
  }

  return {
    fingerprint: computed(() => fingerprint.value),
    isLoading: computed(() => isGenerating.value),
    error: computed(() => pluginError.value ?? localError.value),
    version: client?.version ?? '',
    init,
  }
}
