/**
 * Подписка на SSE-поток обработки спецификации (задача P1.5).
 *
 * Тонкая обёртка над общим стрим-хелпером `useSseStream`: фиксирует путь
 * канала `/manager/specifications/{uploadId}/stream`, вся устойчивость
 * (реконнект с backoff, refresh токена, дедупликация по seq) — в нём.
 */

import { useSseStream, type SseStreamEvent } from './useSseStream'

interface UseSpecStreamOptions {
  /** Вызывается на каждое событие потока. */
  onEvent: (data: SseStreamEvent) => void
  /** Вызывается один раз при терминальном событии (completed/error) — поток закрывается. */
  onDone?: (data: SseStreamEvent) => void
}

export function useSpecStream({ onEvent, onDone }: UseSpecStreamOptions) {
  const stream = useSseStream({ onEvent, onDone })

  /** Подписаться на поток загрузки uploadId (повторный вызов перезапускает подписку). */
  function open(uploadId: string) {
    stream.open(`/manager/specifications/${uploadId}/stream`)
  }

  return { open, stop: stream.stop, connected: stream.connected, failed: stream.failed }
}
