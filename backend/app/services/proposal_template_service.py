"""Сервис для работы с шаблонами коммерческих предложений."""

import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException, status

from app.models.models import ProposalTemplate
from app.repositories.proposal_template_repository import ProposalTemplateRepository
from app.services.minio_service import MinioService


class ProposalTemplateService:
    """Сервис для управления шаблонами КП."""

    def __init__(
        self,
        template_repo: ProposalTemplateRepository,
        minio_service: MinioService,
    ):
        self.template_repo = template_repo
        self.minio_service = minio_service

    async def create_template(
        self,
        name: str,
        html_file,
        start_date: date,
    ) -> ProposalTemplate:
        """
        Создаёт новый шаблон КП.
        
        Валидация:
        - start_date > today
        - start_date > max(start_date) из существующих шаблонов
        """
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start_datetime = datetime(
            year=start_date.year,
            month=start_date.month,
            day=start_date.day,
            tzinfo=UTC,
        )

        # Проверка: start_date > today
        if start_datetime <= today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Дата начала должна быть в будущем (позже текущей даты)",
            )

        # Проверка: start_date > max(existing)
        max_date = await self.template_repo.get_max_start_date()
        if max_date and start_datetime <= max_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Дата начала должна быть позже любой существующей даты (максимальная: {max_date.strftime('%d.%m.%Y')})",
            )

        # Загрузка HTML-шаблона в MinIO
        file_key = f"proposal-templates/{uuid.uuid4()}-{html_file.name}"
        await self.minio_service.upload_fileobj(file_key, html_file)

        # Сохранение в БД
        template = await self.template_repo.create(
            name=name,
            html_key=file_key,
            start_date=start_datetime,
        )

        return template

    async def get_template_by_id(self, template_id: uuid.UUID) -> ProposalTemplate:
        """Возвращает шаблон по ID."""
        template = await self.template_repo.get_by_id(template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Шаблон не найден",
            )
        return template

    async def list_templates(self) -> list[ProposalTemplate]:
        """Возвращает все шаблоны."""
        return await self.template_repo.list_all(order_by="desc")

    async def get_current_template(self) -> ProposalTemplate | None:
        """Возвращает текущий шаблон (ближайшая дата >= today)."""
        return await self.template_repo.get_current_template()

    async def update_template(
        self,
        template_id: uuid.UUID,
        name: str | None = None,
        start_date: date | None = None,
    ) -> ProposalTemplate:
        """Обновляет шаблон."""
        template = await self.get_template_by_id(template_id)

        if name is not None:
            template.name = name

        if start_date is not None:
            today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            start_datetime = datetime(
                year=start_date.year,
                month=start_date.month,
                day=start_date.day,
                tzinfo=UTC,
            )

            # Проверка: start_date > today
            if start_datetime <= today:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Дата начала должна быть в будущем",
                )

            # Проверка: start_date > max(existing, excluding current)
            max_date = await self.template_repo.get_max_start_date()
            if max_date and start_datetime <= max_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Дата начала должна быть позже любой существующей даты",
                )

            template.start_date = start_datetime

        template.updated_at = datetime.now(UTC)
        await self.template_repo.db_session.flush()
        await self.template_repo.db_session.refresh(template)

        return template

    async def delete_template(self, template_id: uuid.UUID) -> None:
        """Удаляет шаблон и файл из MinIO."""
        template = await self.get_template_by_id(template_id)

        # Удаление файла из MinIO
        await self.minio_service.delete_file(template.html_key)

        # Удаление из БД
        await self.template_repo.delete(template)
