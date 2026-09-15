"""Сервис чтения Excel-файлов для превью прайс-листов."""

from typing import Any

from openpyxl import load_workbook


class ExcelPreviewService:
    """Чтение первых 50 строк из Excel-файла (без векторизации, только превью).

    Принимает seekable file-like объект (SpooledTemporaryFile из UploadFile
    или BytesIO) — read_only-режим openpyxl читает строки лениво, без загрузки
    всего файла в память.
    """

    MAX_PREVIEW_ROWS = 50

    @staticmethod
    def read_preview(fileobj: Any, max_rows: int | None = None) -> dict[str, object]:
        """Прочитать первые строки Excel и вернуть dict с заголовками и данными.

        Возвращает:
        {
            "sheets": ["Лист1", ...],
            "headers": ["Колонка1", "Колонка2", ...],
            "rows": [[val1, val2], ...],
            "total_rows": 150,
        }
        """
        fileobj.seek(0)
        wb = load_workbook(filename=fileobj, read_only=True, data_only=True)
        ws = wb.active
        sheets = list(wb.sheetnames)
        rows_iter = ws.iter_rows()

        headers: list[str] = []
        preview_rows: list[list[object]] = []
        total_rows = 0

        for i, row in enumerate(rows_iter):
            values = [cell.value for cell in row]
            if i == 0:
                headers = [str(v) if v is not None else f"col_{j}" for j, v in enumerate(values)]
            else:
                preview_rows.append(values)
                total_rows += 1
                if max_rows and len(preview_rows) >= max_rows:
                    break

        wb.close()
        return {
            "sheets": sheets,
            "headers": headers,
            "rows": preview_rows,
            "total_rows": total_rows,
        }

    @staticmethod
    def read_headers(fileobj: Any) -> list[str]:
        """Заголовки первого листа (первая строка) без чтения строк данных.

        Нужен проверке маппинга при подтверждении: имена колонок сверяются с
        файлом, а содержимое прайс-листа для этого не читаем.
        """
        fileobj.seek(0)
        wb = load_workbook(filename=fileobj, read_only=True, data_only=True)
        try:
            for row in wb.active.iter_rows(max_row=1):
                return [str(cell.value) if cell.value is not None else f"col_{j}" for j, cell in enumerate(row)]
            return []
        finally:
            wb.close()
