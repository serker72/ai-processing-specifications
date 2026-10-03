"""Сервис чтения Excel-файлов для превью прайс-листов.

Реальные прайс-листы редко начинаются со строки-шапки: перед таблицей идут
преамбула (название, дата, контакты) и многоуровневая шапка (строка групп
«Базовая цена» / «РОЦ» / «РРЦ» над строкой подзаголовков «с НДС» / «без НДС»).
Поэтому строка-шапка определяется эвристикой, а не берётся как первая, и строки
данных читаются уже после неё.
"""

import re
from typing import Any

from openpyxl import load_workbook


class ExcelPreviewService:
    """Чтение строк Excel-файла с автоопределением строки-шапки.

    Принимает seekable file-like объект (SpooledTemporaryFile из UploadFile
    или BytesIO) — read_only-режим openpyxl читает строки лениво, без загрузки
    всего файла в память.
    """

    MAX_PREVIEW_ROWS = 50

    # Сколько первых строк просматривать в поиске строки-шапки.
    HEADER_SEARCH_LIMIT = 30

    @staticmethod
    def _row_values(row: Any) -> list[object]:
        """Значения ячеек строки openpyxl в список."""
        return [cell.value for cell in row]

    @staticmethod
    def _is_number(value: object) -> bool:
        """Число ли значение (bool — не число, хотя в Python является int)."""
        return isinstance(value, int | float) and not isinstance(value, bool)

    @staticmethod
    def _is_filled(value: object) -> bool:
        """Заполнена ли ячейка (не None и не пустая строка)."""
        return value is not None and str(value).strip() != ""

    @classmethod
    def _detect_header_row(cls, rows: list[list[object]]) -> int:
        """Индекс строки-шапки среди первых строк листа.

        Шапка — строка с наибольшим числом непустых ячеек, в которой нет чисел
        (в строке данных есть числовые цены/количества). При равенстве берётся
        самая ранняя строка. Если подходящих строк нет — 0 (первая строка).
        """
        best_index = 0
        best_score = -1
        for index, values in enumerate(rows):
            filled = [value for value in values if cls._is_filled(value)]
            if len(filled) < 2:
                continue
            if any(cls._is_number(value) for value in filled):
                continue
            score = len(filled)
            if score > best_score:
                best_score = score
                best_index = index
        return best_index

    @classmethod
    def _group_row(cls, rows: list[list[object]], header_index: int) -> list[object] | None:
        """Строка-группа над шапкой (например, «Базовая цена», «РОЦ», «РРЦ»).

        Нужна, чтобы развести одинаковые подзаголовки по группам. Групповой
        считается строка прямо над шапкой, если она текстово-разреженная
        (несколько непустых текстовых ячеек, меньше, чем в шапке) и без чисел.
        """
        if header_index == 0:
            return None
        previous = rows[header_index - 1]
        filled = [value for value in previous if cls._is_filled(value)]
        header_filled = sum(1 for value in rows[header_index] if cls._is_filled(value))
        if len(filled) < 2 or any(cls._is_number(value) for value in filled):
            return None
        if len(filled) >= header_filled:
            return None
        return previous

    @classmethod
    def _build_headers(
        cls, header_values: list[object], group_values: list[object] | None
    ) -> list[str]:
        """Имена колонок: нормализация пробелов и разведение дубликатов.

        Дубликаты подзаголовков (например, «с НДС», повторяющийся в группах
        «Базовая цена»/«РОЦ»/«РРЦ») получают префикс группы; оставшиеся
        совпадения нумеруются суффиксом. Имена должны совпадать у превью и
        подтверждения маппинга — обе стороны используют этот метод.
        """
        base: list[str] = []
        for index, value in enumerate(header_values):
            text = re.sub(r"\s+", " ", str(value)).strip() if cls._is_filled(value) else ""
            base.append(text or f"col_{index}")

        if len(set(base)) == len(base):
            return base

        # Дубликаты разводим префиксом группы (forward-fill по строке групп):
        # непустая ячейка группы «открывает» группу для последующих колонок.
        names = list(base)
        if group_values is not None:
            current_group: str | None = None
            for index in range(len(names)):
                group_value = group_values[index] if index < len(group_values) else None
                if cls._is_filled(group_value):
                    current_group = re.sub(r"\s+", " ", str(group_value)).strip()
                if current_group and base.count(base[index]) > 1:
                    names[index] = f"{current_group} {base[index]}"

        # Финальная нумерация: дубликаты, не разведённые группой (её нет или
        # имена совпали внутри одной группы), получают суффикс « (2)», « (3)».
        seen: dict[str, int] = {}
        result: list[str] = []
        for name in names:
            count = seen.get(name, 0) + 1
            seen[name] = count
            result.append(name if count == 1 else f"{name} ({count})")
        return result

    @classmethod
    def _buffer_rows(cls, rows_iter: Any, limit: int) -> list[list[object]]:
        """Прочитать не более limit первых строк генератора openpyxl."""
        buffered: list[list[object]] = []
        for _ in range(limit):
            try:
                buffered.append(cls._row_values(next(rows_iter)))
            except StopIteration:
                break
        return buffered

    @classmethod
    def _headers_from_buffer(cls, buffered: list[list[object]]) -> tuple[list[str], int]:
        """Собрать имена колонок и индекс шапки из буфера первых строк."""
        if not buffered:
            return [], 0
        header_index = cls._detect_header_row(buffered)
        group_values = cls._group_row(buffered, header_index)
        headers = cls._build_headers(buffered[header_index], group_values)
        return headers, header_index

    @classmethod
    def read_preview(cls, fileobj: Any, max_rows: int | None = None) -> dict[str, object]:
        """Прочитать строки Excel после строки-шапки.

        Возвращает:
        {
            "sheets": ["Лист1", ...],
            "headers": ["Артикул", "Наименование", ...],
            "rows": [[val1, val2], ...],   # только строки данных
            "total_rows": 150,             # число прочитанных строк данных
        }
        """
        fileobj.seek(0)
        wb = load_workbook(filename=fileobj, read_only=True, data_only=True)
        try:
            sheets = list(wb.sheetnames)
            rows_iter = wb.active.iter_rows()

            buffered = cls._buffer_rows(rows_iter, cls.HEADER_SEARCH_LIMIT)
            headers, header_index = cls._headers_from_buffer(buffered)

            data_rows = buffered[header_index + 1 :]
            if max_rows is None or len(data_rows) < max_rows:
                for row in rows_iter:
                    data_rows.append(cls._row_values(row))
                    if max_rows is not None and len(data_rows) >= max_rows:
                        break
            if max_rows is not None:
                data_rows = data_rows[:max_rows]

            return {
                "sheets": sheets,
                "headers": headers,
                "rows": data_rows,
                "total_rows": len(data_rows),
            }
        finally:
            wb.close()

    @classmethod
    def read_headers(cls, fileobj: Any) -> list[str]:
        """Заголовки первого листа (строка-шапка) без чтения строк данных.

        Нужен проверке маппинга при подтверждении: имена колонок сверяются с
        файлом, а содержимое прайс-листа для этого не читаем. Должен возвращать
        ровно те же имена, что и read_preview, — иначе подтверждение маппинга
        не найдёт колонку.
        """
        fileobj.seek(0)
        wb = load_workbook(filename=fileobj, read_only=True, data_only=True)
        try:
            buffered = cls._buffer_rows(wb.active.iter_rows(), cls.HEADER_SEARCH_LIMIT)
            headers, _ = cls._headers_from_buffer(buffered)
            return headers
        finally:
            wb.close()
