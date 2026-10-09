/**
 * Универсальная подписка на SSE-поток (EventSource) с автопереподключением.
 *
 * Голый EventSource не проходит через интерцептор 401→refresh плагина $api,
 * поэтому при обрыве потока (в т.ч. из-за истёкшего access-токена) перед
 * переподключением вызывается $authRefresh из plugins/api.ts.
 *
 * Backend отдаёт события с монотонным полем seq и воспроизводит буфер Redis
 * при подписке, поэтому повторное подключение ничего не теряет; дедупликацию
 * по seq выполняет сам composable — при реконнекте буфер переигрывается,
 * и без этого в логе появлялись бы дубликаты.
 *
 * Пример: `const { open, stop, connected } = useSseStream({
 *   onEvent: data => { ... },
 *   onDone:   data => { ... },
 * })`
 */

import { onBeforeUnmount, ref } from 'vue'
import { useNuxtApp, useRuntimeConfig } from '#imports'

export interface SseStreamEvent {
  upload_id?: string
  seq?: number | null
  status?: string
  message?: string
  [key: string]: unknown
}

interface UseSseStreamOptions {
  /** Вызывается на каждое событие потока. */
  onEvent: (data: SseStreamEvent) => void
  /** Вызывается один раз при терминальном событии (completed/error) — поток закрывается. */
  onDone?: (data: SseStreamEvent) => void
}

/** Максимальная задержка переподключения, мс. */
const MAX_RECONNECT_DELAY_MS = 15000

/** Зависимости для createSseConnection (инжектируются извне, без useNuxtApp). */
export interface SseConnectionDeps {
  apiBase: string
  authRefresh?: () => Promise<unknown>
}

/** Одна SSE-подписка без Vue-контекста: вызывается из useSseStreams. */
export function createSseConnection(
  deps: SseConnectionDeps,
  { onEvent, onDone }: UseSseStreamOptions,
) {
  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let attempt = 0
  let stopped = true
  let streamPath = ''
  let lastSeq = 0

  function cleanup() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function openStream() {
    if (stopped) return
    eventSource = new EventSource(`${deps.apiBase}${streamPath}`, { withCredentials: true })

    eventSource.onmessage = (event) => {
      let data: SseStreamEvent
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (typeof data.seq === 'number') {
        if (data.seq <= lastSeq) return
        lastSeq = data.seq
      }
      onEvent(data)
      const status = String(data.status ?? '')
      if (status === 'completed' || status === 'error') {
        stopped = true
        cleanup()
        onDone?.(data)
      }
    }

    eventSource.onerror = () => {
      cleanup()
      if (stopped) return
      const delay = Math.min(1000 * 2 ** attempt, MAX_RECONNECT_DELAY_MS)
      attempt += 1
      reconnectTimer = setTimeout(async () => {
        try {
          await deps.authRefresh?.()
        } catch {
          /* рефреш не критичен */
        }
        openStream()
      }, delay)
    }
  }

  function open(path: string) {
    stop()
    stopped = false
    attempt = 0
    lastSeq = 0
    streamPath = path
    openStream()
  }

  function stop() {
    stopped = true
    cleanup()
  }

  return { open, stop }
}

export function useSseStream({ onEvent, onDone }: UseSseStreamOptions) {
  const config = useRuntimeConfig()
  const { $authRefresh } = useNuxtApp() as any

  const connected = ref(false)
  const failed = ref(false)

  let eventSource: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let attempt = 0
  let stopped = true
  let streamPath = ''
  // Последний обработанный seq: отсекает повторы буфера при реконнекте
  let lastSeq = 0

  function cleanup() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    connected.value = false
  }

  function openStream() {
    if (stopped) {
      return
    }
    eventSource = new EventSource(`${config.public.apiBase}${streamPath}`, {
      withCredentials: true,
    })

    eventSource.onopen = () => {
      connected.value = true
      attempt = 0
      failed.value = false
    }

    eventSource.onmessage = (event) => {
      let data: SseStreamEvent
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      // Дедупликация: события с seq <= уже обработанного — повторы буфера
      if (typeof data.seq === 'number') {
        if (data.seq <= lastSeq) {
          return
        }
        lastSeq = data.seq
      }
      onEvent(data)
      const status = String(data.status ?? '')
      if (status === 'completed' || status === 'error') {
        stopped = true
        cleanup()
        onDone?.(data)
      }
    }

    eventSource.onerror = () => {
      // Обрыв (в т.ч. 401: браузер не даёт прочитать код ответа SSE):
      // закрываем поток, обновляем access-токен и переподключаемся с backoff.
      cleanup()
      if (stopped) {
        return
      }
      const delay = Math.min(1000 * 2 ** attempt, MAX_RECONNECT_DELAY_MS)
      attempt += 1
      reconnectTimer = setTimeout(async () => {
        try {
          await $authRefresh?.()
        } catch {
          /* рефреш не критичен: SSE переживёт его провал и попробует снова */
        }
        openStream()
      }, delay)
    }
  }

  /** Подписаться на поток (повторный вызов перезапускает подписку). */
  function open(path: string) {
    stop()
    stopped = false
    attempt = 0
    lastSeq = 0
    streamPath = path
    openStream()
  }

  /** Закрыть поток и отменить переподключения (вызывать при уходе со страницы). */
  function stop() {
    stopped = true
    cleanup()
  }

  onBeforeUnmount(stop)

  return { open, stop, connected, failed }
}
