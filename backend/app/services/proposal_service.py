"""Сервис формирования и выдачи коммерческих предложений (PDF)."""

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError
from jinja2 import Template

from app.core.messages import ProposalMessages
from app.models.models import Proposal
from app.repositories.app_settings_repository import AppSettingsRepository
from app.repositories.proposal_repository import ProposalRepository
from app.repositories.specification_repository import SpecificationRepository
from app.schemas.proposal import ProposalItem
from app.services.file_naming import StoredFileKey
from app.services.minio_service import MinioService
from app.services.proposal_template_default import DEFAULT_PROPOSAL_TEMPLATE
from app.services.proposal_template_service import ProposalTemplateService


class ProposalSpecificationNotFoundError(LookupError):
    """Спецификация не найдена или принадлежит другому менеджеру."""


class NoRowsToExportError(ValueError):
    """В спецификации нет строк, пригодных для КП."""


class ProposalNotFoundError(LookupError):
    """Коммерческое предложение не найдено."""


class ProposalService:
    """Формирование PDF КП по спецификации, хранение версий и выдача файла."""

    def __init__(
        self,
        proposal_repo: ProposalRepository,
        specification_repo: SpecificationRepository,
        app_settings_repo: AppSettingsRepository,
        template_service: ProposalTemplateService,
        minio: MinioService,
    ) -> None:
        self._proposal_repo = proposal_repo
        self._spec_repo = specification_repo
        self._settings_repo = app_settings_repo
        self._template_service = template_service
        self._minio = minio

    # ---------- публичные операции ----------

    async def get_state(self, upload_id: uuid.UUID, manager_id: uuid.UUID) -> ProposalItem | None:
        """Текущее КП по спецификации без формирования файла (None, если КП ещё нет)."""
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise ProposalSpecificationNotFoundError(ProposalMessages.SPECIFICATION_NOT_FOUND)

        proposal = await self._proposal_repo.get_by_upload(upload.id)
        if proposal is None:
            return None

        rows = await self._spec_repo.list_rows_for_export(upload.id)
        fingerprint = self._fingerprint(self._included_rows(rows))
        return self._build_meta(proposal, fingerprint)

    async def generate(
        self,
        upload_id: uuid.UUID,
        manager_id: uuid.UUID,
        force: bool = False,
    ) -> ProposalItem:
        """Сформировать КП (или вернуть существующее).

        Файл создаётся при первом обращении. При `force=True` формируется новая
        версия под тем же номером; старые версии остаются в истории.
        """
        upload = await self._spec_repo.get_for_manager(upload_id, manager_id)
        if upload is None:
            raise ProposalSpecificationNotFoundError(ProposalMessages.SPECIFICATION_NOT_FOUND)

        rows = await self._spec_repo.list_rows_for_export(upload.id)
        included = self._included_rows(rows)
        if not included:
            raise NoRowsToExportError(ProposalMessages.NO_ROWS_TO_EXPORT)

        fingerprint = self._fingerprint(included)
        proposal = await self._proposal_repo.get_by_upload(upload.id)

        if proposal is not None and not force:
            # Файл уже есть — не пересоздаём, отдаём существующую версию.
            return self._build_meta(proposal, fingerprint)

        if proposal is None:
            number = await self._next_number()
            proposal = await self._proposal_repo.create_proposal(
                number=number,
                user_id=manager_id,
                client_id=upload.client_id,
                upload_id=upload.id,
            )
            proposal = await self._proposal_repo.get_by_id(proposal.id)

        await self._create_document(proposal, included, fingerprint)
        proposal = await self._proposal_repo.get_by_id(proposal.id)
        return self._build_meta(proposal, fingerprint)

    async def list_proposals(self, manager_id: uuid.UUID) -> list[ProposalItem]:
        """История КП менеджера с признаком устаревания."""
        proposals = await self._proposal_repo.list_by_user(manager_id)
        result: list[ProposalItem] = []
        for proposal in proposals:
            rows = await self._spec_repo.list_rows_for_export(proposal.upload_id)
            fingerprint = self._fingerprint(self._included_rows(rows))
            result.append(self._build_meta(proposal, fingerprint))
        return result

    async def download(self, proposal_id: uuid.UUID, manager_id: uuid.UUID) -> tuple[bytes, str]:
        """Вернуть файл последней версии КП (формирует, если файла ещё нет)."""
        proposal = await self._proposal_repo.get_by_id(proposal_id)
        if proposal is None or proposal.user_id != manager_id:
            raise ProposalNotFoundError(ProposalMessages.PROPOSAL_NOT_FOUND)

        if not proposal.documents:
            # Первое обращение: формируем файл.
            await self.generate(proposal.upload_id, manager_id, force=False)
            proposal = await self._proposal_repo.get_by_id(proposal_id)
            if proposal is None or not proposal.documents:
                raise ProposalNotFoundError(ProposalMessages.PROPOSAL_NOT_FOUND)

        latest = self._latest_document(proposal)
        fileobj = await self._minio.download_fileobj(latest.file_key)
        return fileobj.getvalue(), f"{proposal.number}.pdf"

    # ---------- внутреннее ----------

    async def _next_number(self) -> str:
        """Номер КП вида КП-{год}-{5 цифр} (глобальная нумерация, сброс раз в год)."""
        year = datetime.now(UTC).year
        number = await self._proposal_repo.next_number(year)
        return f"КП-{year}-{number:05d}"

    async def _create_document(self, proposal: Proposal, rows: list[Any], fingerprint: str) -> None:
        """Отрисовать PDF, загрузить в MinIO и сохранить версию документа."""
        settings = await self._settings_repo.get_or_create()
        template_html = await self._load_template()
        context = self._build_context(proposal, rows, settings)
        html = Template(template_html).render(**context)
        pdf_bytes = await asyncio.to_thread(self._render_pdf, html)

        file_key = f"proposals/{proposal.id}/{uuid.uuid4().hex}.pdf"
        await self._minio.upload_bytes(file_key, pdf_bytes, content_type="application/pdf")
        await self._proposal_repo.create_document(
            proposal_id=proposal.id,
            file_key=file_key,
            rows_fingerprint=fingerprint,
        )

    async def _load_template(self) -> str:
        """HTML-шаблон: текущий загруженный из MinIO, иначе встроенный."""
        template = await self._template_service.get_current_template()
        if template is None:
            return DEFAULT_PROPOSAL_TEMPLATE
        try:
            fileobj = await self._minio.download_fileobj(template.html_key)
            return fileobj.getvalue().decode("utf-8")
        except (ClientError, UnicodeDecodeError, OSError):
            # Битый/недоступный пользовательский шаблон не должен ломать КП.
            return DEFAULT_PROPOSAL_TEMPLATE

    @staticmethod
    def _render_pdf(html: str) -> bytes:
        """Синхронный рендер HTML → PDF (WeasyPrint), вызывается в отдельном потоке."""
        from weasyprint import HTML

        return HTML(string=html).write_pdf()

    def _build_context(self, proposal: Proposal, rows: list[Any], settings: Any) -> dict:
        """Контекст рендеринга КП (см. app/services/proposal_template_default.py)."""
        items = []
        total = 0.0
        for index, row in enumerate(rows, start=1):
            raw = row.raw_data or {}
            quantity = self._as_number(raw.get("quantity")) or 0.0
            price = float(row.matched_item.price) if row.matched_item.price is not None else 0.0
            row_sum = quantity * price
            total += row_sum
            items.append(
                {
                    "index": index,
                    "name": row.matched_item.name,
                    "sku": row.matched_item.sku,
                    "unit": row.matched_item.unit,
                    "quantity": self._fmt_qty(quantity),
                    "price": self._fmt_amount(price),
                    "sum": self._fmt_amount(row_sum),
                }
            )

        vat_rate = float(settings.vat_rate)
        if settings.vat_included:
            vat = total * vat_rate / (100 + vat_rate) if vat_rate else 0.0
            grand_total = total
        else:
            vat = total * vat_rate / 100 if vat_rate else 0.0
            grand_total = total + vat

        return {
            "seller": settings,
            "client": proposal.client,
            "proposal": {
                "number": proposal.number,
                "date": proposal.created_at.strftime("%d.%m.%Y"),
            },
            "items": items,
            "vat_included": bool(settings.vat_included),
            "vat_rate": self._fmt_rate(vat_rate),
            "totals": {
                "total": self._fmt_amount(total),
                "vat": self._fmt_amount(vat),
                "grand_total": self._fmt_amount(grand_total),
            },
        }

    @staticmethod
    def _included_rows(rows: list[Any]) -> list[Any]:
        """Строки, попадающие в КП: есть позиция каталога и заполнено количество."""
        return [
            row
            for row in rows
            if row.matched_item is not None
            and ProposalService._as_number((row.raw_data or {}).get("quantity")) is not None
        ]

    @staticmethod
    def _fingerprint(rows: list[Any]) -> str:
        """SHA-256 канонического состава строк для контроля изменений после формирования."""
        payload = [
            {
                "id": str(row.id),
                "status": row.status.value if hasattr(row.status, "value") else str(row.status),
                "matched_item_id": str(row.matched_item_id) if row.matched_item_id else None,
                "quantity": ProposalService._as_number((row.raw_data or {}).get("quantity")),
                "price": float(row.matched_item.price) if row.matched_item and row.matched_item.price is not None else None,
            }
            for row in rows
        ]
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _latest_document(proposal: Proposal) -> Any:
        """Последняя сформированная версия файла."""
        return max(proposal.documents, key=lambda doc: (doc.created_at, str(doc.id)))

    def _build_meta(self, proposal: Proposal, current_fingerprint: str) -> ProposalItem:
        """Метаданные КП для API (включая признак устаревания)."""
        documents = sorted(proposal.documents, key=lambda doc: (doc.created_at, str(doc.id)), reverse=True)
        latest = documents[0] if documents else None
        return ProposalItem(
            id=str(proposal.id),
            number=proposal.number,
            created_at=proposal.created_at,
            client_id=str(proposal.client_id),
            client_name=proposal.client.name if proposal.client else None,
            upload_id=str(proposal.upload_id),
            filename=StoredFileKey.original_name(proposal.upload.file_key) if proposal.upload else None,
            documents_count=len(documents),
            latest_document_id=str(latest.id) if latest else None,
            has_document=latest is not None,
            needs_regeneration=latest is not None and latest.rows_fingerprint != current_fingerprint,
        )

    @staticmethod
    def _as_number(raw: object) -> float | None:
        """Числовое значение из raw_data (совместимо с парсингом спецификации)."""
        if raw is None or isinstance(raw, bool):
            return None
        if isinstance(raw, int | float):
            return float(raw)
        text = str(raw).replace("\u00a0", " ").replace(" ", "").replace(",", ".").strip()
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _fmt_amount(value: float) -> str:
        """Сумма в формате «1 234,56»."""
        return f"{value:,.2f}".replace(",", " ").replace(".", ",")

    @staticmethod
    def _fmt_qty(value: float) -> str:
        """Количество без лишних нулей (10, а не 10.00)."""
        if value == int(value):
            return str(int(value))
        return ProposalService._fmt_amount(value)

    @staticmethod
    def _fmt_rate(value: float) -> str:
        """Ставка НДС без лишних нулей (20, а не 20.0)."""
        if value == int(value):
            return str(int(value))
        return f"{value:g}".replace(".", ",")
