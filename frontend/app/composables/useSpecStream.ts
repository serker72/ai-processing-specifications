/**
 * Устойчивая подписка на SSE-поток обработки спецификации (задача P1.5).
 *
 * Голый EventSource не проходит через интерцептор 401→refresh плагина $api,
 * поэтому при обрыве потока (в т.ч. из-за истёкшего access-токена) перед
 * переподключением вызывается $authRefresh из plugins/api.ts.
 *
 * Backend отдаёт события с монотонным полем seq и воспроизводит буфер Redis
 * при подписке, поэтому повторное подключение ничего не теряет; дедупликацию
 * по seq выполняет сам composable — при реконнекте буфер переигрывается,
 * и без этого в логе появлялись бы дубликаты.
 */

import { onBeforeUnmount, ref } from 'vue'
import { useNuxtApp, useRuntimeConfig } from '#imports'

export interface SpecStreamEvent {
  upload_id?: string
  seq?: number | null
  status?: string
  message?: string
  row_number?: number
  raw_name?: string
  [key: string]: unknown
}

interface UseSpecStreamOptions {
  /** Вызывается на каждое событие потока. */
  onEvent: (data: SpecStreamEvent) => void
  /** Вызывается один раз при терминальном событии (completed/error) — поток закрывается. */
  onDone?: (data: SpecStreamEvent) => void
}

/** Максимальная задержка переподключения, мс. */
const MAX_RECONNECT_DELAY_MS = 15000

export function useSpecStream({ onEvent, onDone }: UseSpecStreamOptions) {
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
      let data: SpecStreamEvent
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

  /** Подписаться на поток загрузки uploadId (повторный вызов перезапускает подписку). */
  function open(uploadId: string) {
    stop()
    stopped = false
    attempt = 0
    lastSeq = 0
    streamPath = `/manager/specifications/${uploadId}/stream`
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
