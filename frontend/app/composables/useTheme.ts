/**
 * Composable темы оформления (светлая/тёмная).
 *
 * Выбор пользователя хранится в localStorage (ключ `app_theme`) и применяется
 * классом `.dark` на <html>. Тот же класс ставит блокирующий скрипт из
 * nuxt.config.ts ещё до гидратации, поэтому при перезагрузке нет мигания
 * светлой версией страницы (FOUC).
 *
 * Цвета берёт CSS: токены в `~/assets/css/main.css` переопределены для
 * `html.dark`, а вариант `dark:` в утилитах Tailwind настроен на класс.
 */

/** Ключ localStorage с выбором темы. */
export const THEME_STORAGE_KEY = 'app_theme'

export type Theme = 'light' | 'dark'

/** Значение темы по умолчанию, когда пользователь ещё ничего не выбирал. */
function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Сохранённая тема; при отсутствии/некорректном значении — системная. */
function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : systemTheme()
  } catch {
    // localStorage недоступен (например, приватный режим)
    return 'light'
  }
}

/** Покрасить документ: класс темы + colorScheme для нативных элементов и скроллбаров. */
function applyTheme(theme: Theme): void {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

/**
 * Возвращает reactive состояние темы и переключатель.
 * Значение живёт в общем useState, поэтому все компоненты видят смену темы сразу.
 */
export function useTheme() {
  const theme = useState<Theme>('app:theme', () => 'light')

  /** Применить и запомнить тему (только в браузере). */
  function setTheme(next: Theme): void {
    theme.value = next
    if (import.meta.server) {
      return
    }
    applyTheme(next)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Не удаось сохранить — тема действует до перезагрузки страницы
    }
  }

  function toggleTheme(): void {
    setTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  /**
   * Синхронизировать состояние с DOM/localStorage. Вызывается из клиентского
   * плагина: на сервере localStorage недоступен, иначе состояние разошлось бы
   * с классом, который уже проставил inline-скрипт.
   */
  function initTheme(): void {
    if (import.meta.server) {
      return
    }
    const current: Theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light'
    theme.value = current
    applyTheme(current)
  }

  return {
    theme: computed(() => theme.value),
    isDark: computed(() => theme.value === 'dark'),
    setTheme,
    toggleTheme,
    initTheme,
  }
}
