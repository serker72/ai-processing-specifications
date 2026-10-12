"""
Юнит-тесты для `ExcelPreviewService`: нормализация заголовков и автоопределение строки-шапки.

Запуск:
    cd backend && uv run pytest tests/unit/test_excel_preview_service.py -v
"""

import io

from openpyxl import Workbook

from app.services.excel_preview_service import ExcelPreviewService

# ── normalize_title ──────────────────────────────────────────────────────────


class TestNormalizeTitle:
    """Нормализация имени колонки: пробелы → один, trim, без учёта регистра."""

    def test_strips_and_collapses(self):
        assert ExcelPreviewService.normalize_title("  Ед.   изм.  ") == "ед. изм."

    def test_case_insensitive(self):
        assert ExcelPreviewService.normalize_title("НАИМЕНОВАНИЕ") == ExcelPreviewService.normalize_title("наименование")

    def test_empty(self):
        assert ExcelPreviewService.normalize_title("") == ""

    def test_none_string(self):
        assert ExcelPreviewService.normalize_title(None) == "none"


# ── resolve_column_indexes ───────────────────────────────────────────────────


class TestResolveColumnIndexes:
    """Сопоставление имён колонок из column_mapping с заголовками листа."""

    def test_exact_match(self):
        headers = ["Артикул", "Наименование", "Количество", "Ед. изм."]
        mapping = {
            "name_column": "Наименование",
            "quantity_column": "Количество",
            "unit_column": "Ед. изм.",
        }
        result = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit", "quantity_column": "quantity"}, mapping
        )
        assert result["name"] == 1
        assert result["quantity"] == 2
        assert result["unit"] == 3

    def test_dirty_whitespace(self):
        """Заголовок «Ед.  изм.» (два пробела) должен совпасть с «Ед. изм.»."""
        headers = ["Наименование", "Ед.  изм."]
        mapping = {"name_column": "Наименование", "unit_column": "Ед. изм."}
        result = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit"}, mapping
        )
        assert result["unit"] == 1

    def test_case_insensitive(self):
        """«НАИМЕНОВАНИЕ» (верхний регистр) должен совпасть с «Наименование»."""
        headers = ["НАИМЕНОВАНИЕ", "ЕД. ИЗМ."]
        mapping = {"name_column": "Наименование", "unit_column": "Ед. изм."}
        result = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit"}, mapping
        )
        assert result["name"] == 0
        assert result["unit"] == 1

    def test_missing_mapping(self):
        """Если column_mapping не содержит колонки, она не должна попасть в результат."""
        headers = ["Наименование", "Ед. изм."]
        mapping = {"name_column": "Наименование"}
        result = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit"}, mapping
        )
        assert "name" in result
        assert "unit" not in result

    def test_no_match(self):
        """Если колонка не найдена, она отсутствует в результате."""
        headers = ["Наименование", "Ед. изм."]
        mapping = {"name_column": "Название", "unit_column": "Единица"}
        result = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit"}, mapping
        )
        assert "name" not in result
        assert "unit" not in result

    def test_leading_trailing_spaces(self):
        """Заголовок с пробелами по краям должен найтись."""
        headers = ["  Наименование  ", " Ед. изм. "]
        mapping = {"name_column": "Наименование", "unit_column": "Ед. изм."}
        result = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit"}, mapping
        )
        assert result["name"] == 0
        assert result["unit"] == 1


# ── sheet_headers_and_rows ───────────────────────────────────────────────────


class TestSheetHeadersAndRows:
    """Определение строки-шапки и извлечение данных."""

    @staticmethod
    def _make_rows(cells: list[list]) -> iter:
        """Создать строки в формате, ожидаемом iter_rows(): каждый элемент — объект с атрибутом .value."""

        class _Cell:
            def __init__(self, value):
                self.value = value

        return iter([[_Cell(v) for v in row] for row in cells])

    def test_simple_case(self):
        """Стандартный файл: строка 1 — шапка, строки 2+ — данные."""
        cells = [
            ["Артикул", "Наименование", "Ед. изм.", "Цена"],
            ["SKU001", "Товар 1", "шт", 100],
            ["SKU002", "Товар 2", "шт", 200],
        ]
        headers, rows = ExcelPreviewService.sheet_headers_and_rows(TestSheetHeadersAndRows._make_rows(cells))
        assert headers == ["Артикул", "Наименование", "Ед. изм.", "Цена"]
        assert len(rows) == 2
        # rows — list[list[object]], где каждый элемент — значение ячейки
        assert rows[0] == ["SKU001", "Товар 1", "шт", 100]
        assert rows[1] == ["SKU002", "Товар 2", "шт", 200]

    def test_skips_empty_rows(self):
        """Пустые строки в конце файла не попадают в результат."""
        cells = [
            ["Наименование", "Ед. изм."],
            ["Товар 1", "шт"],
            [None, None],
            ["", ""],
        ]
        _, rows = ExcelPreviewService.sheet_headers_and_rows(TestSheetHeadersAndRows._make_rows(cells))
        assert len(rows) == 1
        assert rows[0] == ["Товар 1", "шт"]

    def test_header_detection_with_preamble(self):
        """Первая строка — преамбула, вторая — шапка, дальше — данные."""
        cells = [
            ["ООО «Ромашка»", "", "", ""],  # преамбула — мало текстовых ячеек
            ["Артикул", "Наименование", "Ед. изм.", "Цена"],  # шапка — 4 текстовых
            ["SKU001", "Товар 1", "шт", 100],
        ]
        headers, rows = ExcelPreviewService.sheet_headers_and_rows(TestSheetHeadersAndRows._make_rows(cells))
        assert headers == ["Артикул", "Наименование", "Ед. изм.", "Цена"]
        assert len(rows) == 1
        assert rows[0] == ["SKU001", "Товар 1", "шт", 100]

    def test_header_detection_skips_numeric_rows(self):
        """Строка с числами не может быть шапкой."""
        cells = [
            ["Артикул", "Наименование", "Ед. изм."],  # шапка — 3 текстовых
            ["SKU001", "Товар 1", "шт"],
            ["100", "500", "200"],  # числа — не шапка
        ]
        headers, rows = ExcelPreviewService.sheet_headers_and_rows(TestSheetHeadersAndRows._make_rows(cells))
        assert headers == ["Артикул", "Наименование", "Ед. изм."]
        assert len(rows) == 2
        assert rows[0] == ["SKU001", "Товар 1", "шт"]
        assert rows[1] == ["100", "500", "200"]

    def test_no_matching_headers(self):
        """Если заголовки не совпадают с column_mapping, кол-во и единица — None."""
        cells = [
            ["Наименование", "Количество"],
            ["Товар 1", 10],
        ]
        mapping = {
            "name_column": "Наименование",
            "unit_column": "Ед. изм.",  # такой колонки нет
        }
        headers, _ = ExcelPreviewService.sheet_headers_and_rows(TestSheetHeadersAndRows._make_rows(cells))
        col_idx = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit", "quantity_column": "quantity"}, mapping
        )
        assert "name" in col_idx
        assert "unit" not in col_idx
        assert "quantity" not in col_idx

    def test_mixed_whitespace_in_headers(self):
        """Заголовки с разными пробелами должны нормально обрабатываться."""
        cells = [
            ["  Артикул ", "Наименование ", "  Ед.  изм.  ", "Цена "],
            ["SKU1", "Товар", "шт", 10],
        ]
        mapping = {
            "name_column": "Наименование",
            "unit_column": "Ед. изм.",
        }
        headers, _ = ExcelPreviewService.sheet_headers_and_rows(TestSheetHeadersAndRows._make_rows(cells))
        col_idx = ExcelPreviewService.resolve_column_indexes(
            headers, {"name_column": "name", "unit_column": "unit"}, mapping
        )
        assert col_idx["name"] == 1
        assert col_idx["unit"] == 2


# ── read_preview ─────────────────────────────────────────────────────────────


class TestReadPreview:
    """Интеграционный тест: чтение превью из in-memory xlsx."""

    @staticmethod
    def _make_xlsx(cells: list[list]) -> io.BytesIO:
        """Создать xlsx-файл из списка строк ячеек."""
        wb = Workbook()
        ws = wb.active
        for row in cells:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def test_basic_preview(self):
        buf = self._make_xlsx([
            ["Артикул", "Наименование", "Ед. изм.", "Цена"],
            ["SKU001", "Товар 1", "шт", 100],
            ["SKU002", "Товар 2", "шт", 200],
        ])
        result = ExcelPreviewService.read_preview(buf)
        assert result["headers"] == ["Артикул", "Наименование", "Ед. изм.", "Цена"]
        assert len(result["rows"]) == 2
        assert result["rows"][0] == ["SKU001", "Товар 1", "шт", 100]

    def test_preview_with_preamble(self):
        buf = self._make_xlsx([
            ["ООО «Ромашка»", "", "", ""],
            ["Артикул", "Наименование", "Ед. изм.", "Цена"],
            ["SKU001", "Товар 1", "шт", 100],
            ["SKU002", "Товар 2", "шт", 200],
        ])
        result = ExcelPreviewService.read_preview(buf)
        assert result["headers"] == ["Артикул", "Наименование", "Ед. изм.", "Цена"]
        assert len(result["rows"]) == 2
        # Строка с "ООО" не входит в rows — она была в преамбуле

    def test_preview_no_headers_match(self):
        """Заголовки, не совпадающие с column_mapping, не должны вызывать ошибок."""
        buf = self._make_xlsx([
            ["A", "B"],
            ["1", "2"],
        ])
        result = ExcelPreviewService.read_preview(buf)
        assert result["headers"] == ["A", "B"]
        assert len(result["rows"]) == 1
        assert result["rows"][0] == ["1", "2"]
