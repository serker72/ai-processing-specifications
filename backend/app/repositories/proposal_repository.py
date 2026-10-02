"""Репозиторий коммерческих предложений и их файлов (версий)."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import Proposal, ProposalCounter, ProposalDocument


class ProposalRepository:
    """Доступ к proposals, proposal_documents и счётчику номеров."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_number(self, year: int) -> int:
        """Атомарно получить следующий номер КП в году (счётчик с UPSERT)."""
        statement = (
            pg_insert(ProposalCounter)
            .values(year=year, last_number=1)
            .on_conflict_do_update(
                index_elements=[ProposalCounter.year],
                set_={"last_number": ProposalCounter.__table__.c.last_number + 1},
            )
            .returning(ProposalCounter.last_number)
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def create_proposal(
        self,
        number: str,
        user_id: uuid.UUID,
        client_id: uuid.UUID,
        upload_id: uuid.UUID,
    ) -> Proposal:
        """Создать КП."""
        proposal = Proposal(
            number=number,
            user_id=user_id,
            client_id=client_id,
            upload_id=upload_id,
        )
        self._session.add(proposal)
        await self._session.flush()
        await self._session.refresh(proposal)
        return proposal

    async def create_document(
        self,
        proposal_id: uuid.UUID,
        file_key: str,
        rows_fingerprint: str,
        file_format: str = "pdf",
    ) -> ProposalDocument:
        """Добавить версию файла КП."""
        document = ProposalDocument(
            proposal_id=proposal_id,
            file_key=file_key,
            format=file_format,
            rows_fingerprint=rows_fingerprint,
        )
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def get_by_id(self, proposal_id: uuid.UUID) -> Proposal | None:
        """КП по ID с клиентом и документами (свежие документы первыми)."""
        result = await self._session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.client),
                selectinload(Proposal.documents),
                selectinload(Proposal.upload),
            )
            .where(Proposal.id == proposal_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_by_upload(self, upload_id: uuid.UUID) -> Proposal | None:
        """КП, сформированное по спецификации (одно на спецификацию)."""
        result = await self._session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.client),
                selectinload(Proposal.documents),
                selectinload(Proposal.upload),
            )
            .where(Proposal.upload_id == upload_id)
            .order_by(Proposal.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> list[Proposal]:
        """КП менеджера, свежие — первыми."""
        result = await self._session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.client),
                selectinload(Proposal.documents),
                selectinload(Proposal.upload),
            )
            .where(Proposal.user_id == user_id)
            .order_by(Proposal.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Proposal]:
        """Все КП, свежие — первыми (для администратора)."""
        result = await self._session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.client),
                selectinload(Proposal.documents),
                selectinload(Proposal.upload),
            )
            .order_by(Proposal.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_document(self, document_id: uuid.UUID) -> ProposalDocument | None:
        """Версия файла КП по ID."""
        return await self._session.get(ProposalDocument, document_id)
