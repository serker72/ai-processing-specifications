<template>
  <div class="processing-panel">
    <!-- Индикатор SSE-потока -->
    <div class="panel-header">
      <div class="sse-indicator">
        <span :class="['sse-dot', { active: sseActive, error: sseError }]"></span>
        <span class="sse-label">
          SSE-поток:
          <span :class="['sse-status', { active: sseActive, error: sseError }]">
            {{ sseError ? 'Ошибка' : sseActive ? 'Активен' : 'Подключение…' }}
          </span>
        </span>
      </div>
      <!-- Пункт 3: кнопка перехода к результатам -->
      <template v-if="phase !== 'error'">
        <button
          v-if="phase === 'complete'"
          class="btn-action btn-results"
          @click="goToResults"
        >
          К результатам матчинга →
        </button>
        <span v-else class="btn-results-hint" title="Строки будут готовы после завершения обработки">
          К результатам матчинга →
        </span>
      </template>
    </div>

    <!-- Имя файла -->
    <h2 class="file-title">Обработка файла: {{ fileName }}</h2>

    <!-- Заголовок с процентом и подзаголовком -->
    <div class="progress-heading">
      <div class="progress-percent">{{ percent }}%</div>
      <div class="progress-subtitle">
        <template v-if="phase === 'error'">
          Ошибка обработки: {{ errorMessage }}
        </template>
        <template v-else-if="phase === 'complete'">
          Обработка завершена — Обработано {{ processed }} из {{ total }} строк
        </template>
        <template v-else>
          Обработано {{ processed }} из {{ total }} строк
        </template>
      </div>
    </div>

    <!-- Многокомпонентный прогресс-бар -->
    <div class="stacked-bar" role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100">
      <div
        class="bar-segment seg-auto"
        :style="{ width: segWidth(tierAuto) }"
        :title="`Совпадения: ${tierAuto}`"
      ></div>
      <div
        class="bar-segment seg-topn"
        :style="{ width: segWidth(tierTopN) }"
        :title="`Кандидаты: ${tierTopN}`"
      ></div>
      <div
        class="bar-segment seg-unmatched"
        :style="{ width: segWidth(tierUnmatched) }"
        :title="`Не распознано: ${tierUnmatched}`"
      ></div>
      <div class="bar-segment seg-pending" :style="{ width: segWidth(pendingCount) }"></div>
    </div>

    <!-- Карточки метрик по Tier -->
    <div class="metric-cards">
      <div class="metric-card card-auto">
        <div class="metric-name">Совпадения</div>
        <div class="metric-value">{{ tierAuto }}</div>
        <div class="metric-desc">Высокая схожесть, строка сопоставлена автоматически</div>
      </div>
      <div class="metric-card card-topn">
        <div class="metric-name">Найдены кандидаты</div>
        <div class="metric-value">{{ tierTopN }}</div>
        <div class="metric-desc">Несколько вариантов — нужен выбор менеджера</div>
      </div>
      <div class="metric-card card-unmatched">
        <div class="metric-name">Не распознано</div>
        <div class="metric-value">{{ tierUnmatched }}</div>
        <div class="metric-desc">Позиция каталога не найдена</div>
      </div>
    </div>

    <!-- Бегущий лог последних строк -->
    <div v-if="logRows.length" class="live-log">
      <div v-for="entry in logRows" :key="entry.key" class="log-row">
        <span :class="['log-marker', tierClass(entry.tier)]"></span>
        <span class="log-time">{{ entry.time }}</span>
        <span class="log-text">
          Строка {{ entry.rowNumber }}: {{ entry.rawName }}
          <span :class="['log-tier', tierClass(entry.tier)]">{{ tierLabel(entry.tier) }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Панель визуализации обработки спецификации в реальном времени (проблема 2).
 *
 * Потребляет события SSE-потока spec_{upload_id}:
 * - RowMatchEvent — строка обработана, tier (auto / top_n / unmatched)
 *   определяет цветовую маркировку счётчиков, бара и лога;
 * - ProgressEvent — processed/total и терминальный статус (completed/error).
 *
 * Обновления UI троттлятся (THROTTLE_TIMEOUT): при быстрых батчах матчинга рендер
 * не дёргается на каждое событие.
 */

import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'

export interface RowMatchEntry {
  row_number: number
  raw_name: string
  match_type: string | null
  status: string
  timestamp?: string
}

export interface SpecStreamState {
  /** Обработано строк (из ProgressEvent). */
  processed: number
  /** Всего строк (из ProgressEvent). */
  total: number
  /** Терминальная фаза: running / complete / error. */
  phase: 'running' | 'complete' | 'error'
  /** Сообщение терминальной ошибки. */
  errorMessage: string
  /** Счётчики по Tier из RowMatchEvent. */
  tierAuto: number
  tierTopN: number
  tierUnmatched: number
  /** Бегущий лог последних строк (новые вверху). */
  log: RowMatchEntry[]
}

const props = defineProps<{
  fileName: string
  uploadId: string
  /** Индикатор подключения EventSource (из useSseStream). */
  sseActive: boolean
  /** Поток завершился ошибкой соединения. */
  sseError: boolean
  state: SpecStreamState
}>()

const router = useRouter()

/** Максимум строк в бегущем логе. */
const LOG_LIMIT = 5

/** Пауза между обновлениями UI при троттлинге, мс. */
const THROTTLE_TIMEOUT = 80

/** Копия state для троттлинга: reactive-прокси нельзя присвоить в ref — Vue не
 *  заметит изменения, поэтому делаем поверхностный снимок. */
function snapshot(s: SpecStreamState): SpecStreamState {
  return { ...s, log: [...s.log] }
}

const throttled = ref<SpecStreamState>(snapshot(props.state))
let throttleTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.state,
  (next) => {
    // Первый тик — без задержки: первое событие пакета обновляет UI сразу
    if (!throttleTimer) {
      throttled.value = snapshot(next)
      throttleTimer = setTimeout(() => {
        throttleTimer = null
        // Догнать последнее состояние, если за время паузы пришли новые события
        throttled.value = snapshot(props.state)
      }, THROTTLE_TIMEOUT)
    }
  },
  { deep: true },
)

onBeforeUnmount(() => {
  if (throttleTimer) clearTimeout(throttleTimer)
})

const state = computed(() => throttled.value)

const processed = computed(() => state.value.processed)
const total = computed(() => state.value.total)
const phase = computed(() => state.value.phase)
const errorMessage = computed(() => state.value.errorMessage)
const tierAuto = computed(() => state.value.tierAuto)
const tierTopN = computed(() => state.value.tierTopN)
const tierUnmatched = computed(() => state.value.tierUnmatched)

const percent = computed(() => {
  if (!total.value) return 0
  return Math.min(100, Math.round((processed.value / total.value) * 100))
})

const pendingCount = computed(() => Math.max(0, total.value - processed.value))

/** Ширина сегмента бара в % от total (min 2%, чтобы ненулевые были видны). */
function segWidth(count: number) {
  if (!total.value || count <= 0) return '0%'
  const percentValue = (count / total.value) * 100
  return `${Math.max(2, percentValue)}%`
}

const logRows = computed(() =>
  state.value.log.slice(0, LOG_LIMIT).map((entry, index) => ({
    key: `${entry.row_number}-${index}`,
    rowNumber: entry.row_number,
    rawName: entry.raw_name,
    tier: entry.match_type ?? 'unmatched',
    time: formatTime(entry.timestamp),
  })),
)

function formatTime(timestampValue?: string) {
  if (!timestampValue) return ''
  const date = new Date(timestampValue)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('ru-RU')
}

function tierClass(tier: string) {
  if (tier === 'auto') return 'tier-auto'
  if (tier === 'top_n') return 'tier-topn'
  return 'tier-unmatched'
}

function tierLabel(tier: string) {
  if (tier === 'auto') return 'совпадение'
  if (tier === 'top_n') return 'кандидаты'
  return 'не распознано'
}

/** Пункт 3: переход к результатам матчинга. */
function goToResults() {
  router.push(`/manager/specifications/${props.uploadId}`)
}
</script>

<style scoped>
.processing-panel {
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 24px;
  margin-top: 20px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* Индикатор SSE */
.sse-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.875rem;
}

.sse-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--app-border);
  flex-shrink: 0;
}

.sse-dot.active {
  background: var(--app-success);
  animation: sse-blink 1.2s ease-in-out infinite;
}

.sse-dot.error {
  background: var(--app-danger);
}

@keyframes sse-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.sse-status {
  font-weight: 600;
  color: var(--app-text);
}

.sse-status.active {
  color: var(--app-success);
}

.sse-status.error {
  color: var(--app-danger);
}

/* Пункт 3: кнопка результатов */
.btn-results-hint {
  display: inline-block;
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px dashed var(--app-border);
  color: var(--app-text);
  opacity: 0.5;
  font-size: 0.875rem;
  cursor: not-allowed;
}

.file-title {
  margin: 16px 0 8px;
  font-size: 1.125rem;
  overflow-wrap: anywhere;
}

/* Заголовок прогресса */
.progress-heading {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.progress-percent {
  font-size: 2rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--app-text);
}

.progress-subtitle {
  color: var(--app-text);
  opacity: 0.75;
  font-variant-numeric: tabular-nums;
}

/* Stacked-бар */
.stacked-bar {
  display: flex;
  width: 100%;
  height: 18px;
  border-radius: 9px;
  overflow: hidden;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
}

.bar-segment {
  height: 100%;
  transition: width 0.3s ease;
}

.seg-auto { background: var(--app-success); }
.seg-topn { background: #f59e0b; }
.seg-unmatched { background: var(--app-danger); }
.seg-pending { background: var(--app-surface-muted); }

/* Карточки метрик */
.metric-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.metric-card {
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 14px;
  border-top-width: 4px;
}

.card-auto { border-top-color: var(--app-success); }
.card-topn { border-top-color: #f59e0b; }
.card-unmatched { border-top-color: var(--app-danger); }

.metric-name {
  font-size: 0.8125rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  opacity: 0.75;
}

.metric-value {
  font-size: 1.75rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  margin: 4px 0;
}

.metric-desc {
  font-size: 0.75rem;
  opacity: 0.65;
}

/* Бегущий лог */
.live-log {
  margin-top: 16px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 8px 12px;
}

.log-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  font-size: 0.8125rem;
}

.log-marker {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.log-time {
  font-variant-numeric: tabular-nums;
  opacity: 0.6;
  flex-shrink: 0;
}

.log-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-tier {
  margin-left: 6px;
  font-weight: 600;
  font-size: 0.75rem;
}

.tier-auto { color: var(--app-success); }
.tier-topn { color: #b45309; }
.tier-unmatched { color: var(--app-danger); }

.log-marker.tier-auto { background: var(--app-success); }
.log-marker.tier-topn { background: #f59e0b; }
.log-marker.tier-unmatched { background: var(--app-danger); }
</style>
