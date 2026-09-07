"""Сервис обработки спецификаций: загрузка, превью, предсказание маппинга колонок.

Файл передаётся как поток (SpooledTemporaryFile), не читается в память целиком.
"""

import uuid
from typing import Any

from app.core.messages import CommonMessages
from app.repositories.specification_repository import SpecificationRepository
from app.schemas.specification import SpecificationMappingPrediction
from app.services.excel_preview_service import ExcelPreviewService
from app.services.llm_service import LlmService
from app.services.minio_service import MinioService

# Максимальный размер загружаемой спецификации (50 МБ)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


class FileTooLargeError(Exception):
    """Загруженный файл превышает допустимый размер."""


class SpecificationService:
    """Оркестратор: загрузка спецификации в MinIO, превью, LLM-предсказание маппинга."""

    XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(
        self,
        minio: MinioService,
        excel_preview: ExcelPreviewService,
        llm: LlmService,
        specification_repo: SpecificationRepository,
    ) -> None:
        self._minio = minio
        self._excel_preview = excel_preview
        self._llm = llm
        self._spec_repo = specification_repo

    async def upload_and_predict(
        self,
        fileobj: Any,
        original_filename: str,
        manager_id: object,
    ) -> dict:
        """Загрузить спецификацию в MinIO, прочитать превью, предсказать маппинг.

        Файл передаётся как поток (UploadFile.file):
        - в MinIO уходит потоково (multipart),
        - превью читается лениво (openpyxl read_only).
        """
        # 0. Проверить размер
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(0)
        if size > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(CommonMessages.FILE_TOO_LARGE)

        # 1. Сохранить файл в MinIO
        file_key = f"specifications/{uuid.uuid4().hex}-{original_filename}"
        await self._minio.create_bucket_if_not_exists()
        file_url = await self._minio.upload_fileobj(
            file_key, fileobj, content_type=self.XLSX_CONTENT_TYPE
        )

        # 2. Прочитать превью
        preview = self._excel_preview.read_preview(fileobj, max_rows=50)

        # 3. Предсказать маппинг через LLM
        predicted_mapping = await self._predict_column_mapping(preview["headers"])

        # 4. Сохранить запись в БД
        upload = await self._spec_repo.create(
            manager_id=manager_id,
            file_key=file_key,
        )
        await self._spec_repo.update_mapping(
            upload.id, predicted_mapping.model_dump()
        )

        return {
            "upload_id": str(upload.id),
            "file_key": file_key,
            "file_url": file_url,
            "preview": preview,
            "predicted_mapping": predicted_mapping.model_dump(),
        }

    async def _predict_column_mapping(
        self, headers: list[str]
    ) -> SpecificationMappingPrediction:
        """Запросить у LLM предсказание ролей колонок спецификации."""
        headers_str = ", ".join(f'"{h}"' for h in headers)
        prompt = (
            "Определи роли колонок спецификации клиента по их названиям.\n"
            f"Колонки таблицы: [{headers_str}].\n\n"
            "Верни JSON строго по схеме:\n"
            '{"name_column": "<колонка с наименованием товара>", '
            '"quantity_column": "<колонка с количеством или null>", '
            '"unit_column": "<колонка с единицей измерения или null>", '
            '"price_column": "<колонка с ценой или null>", '
            '"additional_columns": {"<имя колонки>": "<роль>"}\n'
            "}\n\n"
            "Значения — точные названия колонок из списка выше."
        )
        schema = {
            "type": "object",
            "properties": {
                "name_column": {"type": "string"},
                "quantity_column": {"type": ["string", "null"]},
                "unit_column": {"type": ["string", "null"]},
                "price_column": {"type": ["string", "null"]},
                "additional_columns": {"type": "object"},
            },
            "required": [
                "name_column",
                "quantity_column",
                "unit_column",
                "price_column",
                "additional_columns",
            ],
        }
        result = await self._llm.complete_json(
            "Ты определяешь роли колонок спецификации. Отвечай только JSON без пояснений.",
            prompt,
            schema,
        )
        return SpecificationMappingPrediction.from_llm_response(result)
