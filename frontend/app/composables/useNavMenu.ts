/**
 * Пункты боковой панели по роли пользователя.
 *
 * Layout `workspace` общий для администратора и менеджера: различается только
 * наполнение меню, поэтому список пунктов живёт в одном месте, а не в разметке
 * каждой страницы. Домашний маршрут роли (useAuth.ROLE_HOME) берётся отсюда,
 * чтобы «переход в начало» и первый пункт меню не могли разъехаться.
 *
 * Роль передаётся аргументом: модуль не зависит от useAuth (только тип), иначе
 * между композаблами получилась бы циклическая зависимость модулей.
 */

import { computed, toValue, type MaybeRefOrGetter } from 'vue'
import type { UserRole } from '~/composables/useAuth'

/** Пункт боковой панели: маршрут подписки NuxtLink и подпись. */
export interface NavItem {
  to: string
  label: string
}

/** Раздел сайта: подпись в шапке панели и её пункты. */
export interface NavSection {
  title: string
  items: NavItem[]
}

/** Название продукта — единственное место, откуда оно берётся в шапках layout'ов. */
export const BRAND_NAME = 'AI Specs'

/** Единственный источник меню: роль → раздел. */
export const ROLE_NAV: Record<UserRole, NavSection> = {
  admin: {
    title: 'Кабинет администратора',
    items: [
      { to: '/admin/users', label: 'Пользователи' },
      { to: '/admin/devices', label: 'Устройства' },
      { to: '/admin/sessions', label: 'Сессии' },
      { to: '/admin/pricelists', label: 'Прайс-листы' },
      { to: '/admin/catalog', label: 'Каталог' },
      { to: '/admin/proposal-templates', label: 'Шаблоны КП' },
    ],
  },
  manager: {
    title: 'Кабинет менеджера',
    items: [
      { to: '/manager/specifications', label: 'Загрузка спецификации' },
      { to: '/manager/uploads', label: 'Список спецификаций' },
    ],
  },
}

/**
 * Меню раздела по роли.
 *
 * @param role — роль текущего пользователя (реф или геттер); до загрузки сессии
 * её нет, поэтому меню пустое (гость в панели навигации не бывает).
 */
export function useNavMenu(role: MaybeRefOrGetter<UserRole | null | undefined>) {
  const section = computed<NavSection | null>(() => {
    const value = toValue(role)
    return value ? ROLE_NAV[value] : null
  })

  return {
    sectionTitle: computed(() => section.value?.title ?? BRAND_NAME),
    navItems: computed<NavItem[]>(() => section.value?.items ?? []),
  }
}
