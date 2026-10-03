/**
 * Всплывающие уведомления (тосты) — единая замена текстовым error-блокам.
 *
 * Очередь тостов лежит в useState, поэтому доступна из любого компонента и
 * переживает навигацию. Хост для отрисовки один — CommonToastHost в layout'ах.
 *
 * fromError(err, fallback) извлекает detail из ответа $api (ofetch) и показывает
 * его; если detail не строка — fallback. Это самый частый сценарий: обработчик
 * ловит ошибку и хочет показать причину с backend.
 */

import { useState } from '#imports'

export type ToastType = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  type: ToastType
  message: string
}

/** Время жизни тоста по типу, мс. Ошибки висят дольше — их важно прочитать. */
const TOAST_TIMEOUT_MS: Record<ToastType, number> = {
  success: 4000,
  info: 5000,
  error: 8000,
}

// Сквозной счётчик id: уникален даже для тостов из разных компонентов.
let toastCounter = 0

export function useToast() {
  const toasts = useState<Toast[]>('app-toasts', () => [])

  function dismiss(id: number) {
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  function show(message: string, type: ToastType = 'info') {
    const id = ++toastCounter
    toasts.value = [...toasts.value, { id, type, message }]
    // Таймер только на клиенте: на SSR setTimeout не нужен и удерживал бы процесс
    if (import.meta.client) {
      setTimeout(() => dismiss(id), TOAST_TIMEOUT_MS[type])
    }
    return id
  }

  /** Показать сообщение об ошибке из ответа $api (err.data.detail) или fallback. */
  function fromError(err: unknown, fallback: string) {
    const detail = (err as { data?: { detail?: unknown } } | null)?.data?.detail
    show(typeof detail === 'string' && detail ? detail : fallback, 'error')
  }

  return {
    toasts,
    show,
    dismiss,
    success: (message: string) => show(message, 'success'),
    error: (message: string) => show(message, 'error'),
    info: (message: string) => show(message, 'info'),
    fromError,
  }
}
