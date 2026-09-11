<template>
  <button
    type="button"
    class="theme-toggle rounded border border-app-border px-2 py-1 text-sm text-app-muted transition-colors hover:bg-app-surface-muted hover:text-app-text"
    aria-label="Переключить тему"
    @click="toggleTheme"
  >
    <!-- Оба набора иконок присутствуют в DOM всегда, видимость решает CSS:
         разметка одинакова на сервере и клиенте, hydration mismatch не возникает. -->
    <span class="inline-flex items-center gap-1">
      <svg
        class="inline-block size-4 dark:hidden"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
      </svg>
      <svg
        class="hidden size-4 dark:inline-block"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
      </svg>
      <span class="dark:hidden">Тёмная</span>
      <span class="hidden dark:inline">Светлая</span>
    </span>
  </button>
</template>

<script setup lang="ts">
/**
 * Переключатель светлой/тёмной темы.
 *
 * Кнопка рендерится и на сервере, но toggle безвреден до гидрации: класс `dark`
 * навешивает inline-скрипт из nuxt.config (до первой отрисовки), а сам компонент
 * меняет только его состояние через useTheme().
 */
const { toggleTheme } = useTheme()
</script>
