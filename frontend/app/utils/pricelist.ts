/**
 * Помощники маппинга колонок прайс-листа (подтверждение админом).
 *
 * Соответствуют backend-схемам: ConfirmMappingRequest
 * (app/schemas/confirm_mapping.py) и column_mapping из
 * PriceListPreviewResponse (app/schemas/price_list.py).
 *
 * Файл в app/utils/ — Nuxt авто-импортирует именованные экспорты.
 */

/** Роль основной колонки прайс-листа. */
export interface MappingRole {
  /** Ключ роли — поле ConfirmMappingRequest. */
  key: 'sku_column' | 'name_column' | 'price_column' | 'unit_column'
  /** Подпись роли для селекта редактора маппинга. */
  label: string
  /** Обязательная роль: без неё векторизация каталога бессмысленна. */
  required: boolean
}

/** Роли основных колонок — по одной колонке файла на роль. */
export const MAPPING_ROLES: MappingRole[] = [
  { key: 'sku_column', label: 'Артикул (SKU)', required: true },
  { key: 'name_column', label: 'Наименование товара', required: true },
  { key: 'price_column', label: 'Цена', required: false },
  { key: 'unit_column', label: 'Единица измерения', required: false },
]

/** Значение селекта для доп. колонки: роль задаётся свободным текстом. */
export const ADDITIONAL_ROLE = 'additional'

/** Назначение колонки в редакторе маппинга. */
export interface ColumnAssignment {
  /** Ключ роли из MAPPING_ROLES, ADDITIONAL_ROLE или '' — «не использовать». */
  role: string
  /** Свободная роль доп. колонки (используется при role === ADDITIONAL_ROLE). */
  additionalRole?: string
}

/** Тело POST /admin/pricelists/{id}/confirm (ConfirmMappingRequest). */
export interface MappingPayload {
  sku_column: string
  name_column: string
  price_column: string | null
  unit_column: string | null
  additional_columns: Record<string, string>
}

/**
 * Инициализировать назначения колонок редактора из сохранённого маппинга.
 *
 * Колонки файла, которых нет в column_mapping (или которых нет в файле),
 * получают роль «не использовать».
 */
export function assignmentsFromMapping(
  columnMapping: Record<string, any> | null | undefined,
  headers: string[],
): Record<string, ColumnAssignment> {
  const assignments: Record<string, ColumnAssignment> = {}
  for (const header of headers) {
    assignments[header] = { role: '' }
  }
  if (!columnMapping) {
    return assignments
  }

  for (const role of MAPPING_ROLES) {
    const column = columnMapping[role.key]
    if (typeof column === 'string' && column && column in assignments) {
      assignments[column] = { role: role.key }
    }
  }

  const additional = columnMapping.additional_columns || {}
  for (const [column, role] of Object.entries(additional)) {
    if (column in assignments) {
      assignments[column] = { role: ADDITIONAL_ROLE, additionalRole: String(role) }
    }
  }
  return assignments
}

/** Собрать тело confirm-запроса из назначений колонок редактора. */
export function buildMappingPayload(
  assignments: Record<string, ColumnAssignment>,
): MappingPayload {
  const payload: MappingPayload = {
    sku_column: '',
    name_column: '',
    price_column: null,
    unit_column: null,
    additional_columns: {},
  }
  for (const [column, assignment] of Object.entries(assignments)) {
    if (assignment.role === ADDITIONAL_ROLE) {
      const role = (assignment.additionalRole || '').trim()
      if (role) {
        payload.additional_columns[column] = role
      }
    } else if (assignment.role) {
      const mappingRole = MAPPING_ROLES.find((item) => item.key === assignment.role)
      if (mappingRole) {
        payload[mappingRole.key] = column
      }
    }
  }
  return payload
}

/** Сколько колонок файла получили роль (для подсказки перед сохранением). */
export function countMappedColumns(assignments: Record<string, ColumnAssignment>): number {
  return Object.values(assignments).filter((assignment) => assignment.role !== '').length
}

/** Готовность к сохранению: обязательные роли (SKU, наименование) назначены. */
export function isMappingComplete(payload: MappingPayload): boolean {
  return Boolean(payload.sku_column) && Boolean(payload.name_column)
}
