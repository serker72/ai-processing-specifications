/**
 * Коллекционная подписка на несколько SSE-потоков (страницы-списки).
 *
 * Страницы истории прайс-листов и спецификаций показывают сразу несколько
 * загрузок в обработке. Вместо polling страница подписывается на существующие
 * per-upload SSE-потоки каждой активной загрузки: буфер событий на backend
 * переигрывается при подписке, поэтому события не теряются.
 *
 * Ядро подписки с реконнектом и refresh-токена — `createSseConnection` из
 * `useSseStream`.
 */

import { onBeforeUnmount } from 'vue'
import { useNuxtApp, useRuntimeConfig } from '#imports'
import { createSseConnection, type SseStreamEvent } from './useSseStream'

export interface UseSseStreamsOptions {
  /** Вызывается на каждое событие потока загрузки id. */
  onEvent: (id: string, data: SseStreamEvent) => void
  /** Вызывается один раз на терминальное событие (completed/error) — поток закрыт. */
  onDone?: (id: string, data: SseStreamEvent) => void
}

export function useSseStreams({ onEvent, onDone }: UseSseStreamsOptions) {
  const config = useRuntimeConfig()
  const { $authRefresh } = useNuxtApp() as any
  const deps = { apiBase: String(config.public.apiBase), authRefresh: $authRefresh }

  const streams = new Map<string, ReturnType<typeof createSseConnection>>()

  /** Подписаться на поток (id, path); повторный вызов для id — no-op. */
  function track(id: string, path: string) {
    if (streams.has(id)) {
      return
    }
    const stream = createSseConnection(deps, {
      onEvent: (data) => onEvent(id, data),
      onDone: (data) => {
        streams.delete(id)
        onDone?.(id, data)
      },
    })
    streams.set(id, stream)
    stream.open(path)
  }

  /** Закрыть поток загрузки id. */
  function untrack(id: string) {
    const stream = streams.get(id)
    if (!stream) {
      return
    }
    stream.stop()
    streams.delete(id)
  }

  /** Идентификаторы активных подписок. */
  function trackedIds(): string[] {
    return [...streams.keys()]
  }

  function stopAll() {
    for (const stream of streams.values()) {
      stream.stop()
    }
    streams.clear()
  }

  onBeforeUnmount(stopAll)

  return { track, untrack, trackedIds, stopAll }
}
