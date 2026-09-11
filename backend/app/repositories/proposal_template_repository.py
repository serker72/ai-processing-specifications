"""Репозиторий для работы с шаблонами коммерческих предложений."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ProposalTemplate


class ProposalTemplateRepository:
    """Репозиторий для CRUD-операций с шаблонами КП."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def create(
        self,
        name: str,
        html_key: str,
        start_date: datetime,
    ) -> ProposalTemplate:
        """Создаёт новый шаблон КП."""
        template = ProposalTemplate(
            name=name,
            html_key=html_key,
            start_date=start_date,
        )
        self.db_session.add(template)
        await self.db_session.flush()
        await self.db_session.refresh(template)
        return template

    async def get_by_id(self, template_id: uuid.UUID) -> ProposalTemplate | None:
        """Возвращает шаблон по ID."""
        result = await self.db_session.execute(
            select(ProposalTemplate).where(ProposalTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, order_by: str = "desc") -> list[ProposalTemplate]:
        """Возвращает все шаблоны, отсортированные по start_date."""
        sort_order = ProposalTemplate.start_date.desc() if order_by == "desc" else ProposalTemplate.start_date.asc()
        result = await self.db_session.execute(
            select(ProposalTemplate).order_by(sort_order)
        )
        return list(result.scalars().all())

    async def get_max_start_date(self) -> datetime | None:
        """Возвращает максимальную start_date среди всех существующих шаблонов."""
        from sqlalchemy import func

        result = await self.db_session.execute(
            select(func.max(ProposalTemplate.start_date))
        )
        return result.scalar_one_or_none()

    async def get_current_template(self) -> ProposalTemplate | None:
        """Возвращает текущий шаблон — ближайший start_date >= today."""
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db_session.execute(
            select(ProposalTemplate)
            .where(ProposalTemplate.start_date >= today)
            .order_by(ProposalTemplate.start_date.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        template: ProposalTemplate,
        name: str | None = None,
        start_date: datetime | None = None,
    ) -> ProposalTemplate:
        """Обновляет название и/или дату начала шаблона."""
        if name is not None:
            template.name = name
        if start_date is not None:
            template.start_date = start_date
        template.updated_at = datetime.now(UTC)
        await self.db_session.flush()
        await self.db_session.refresh(template)
        return template

    async def delete(self, template: ProposalTemplate) -> None:
        """Удаляет шаблон из базы данных."""
        await self.db_session.delete(template)
        await self.db_session.flush()
