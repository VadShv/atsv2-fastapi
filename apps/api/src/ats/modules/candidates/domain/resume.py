"""Домен резюме: источники и версии.

Резюме — артефакт кандидата. Может быть несколько версий (из разных источников
или обновлённых). Каждая версия имеет content-hash для дедупликации (дебаунс),
статус парсинга и parser_version (whitebox AI).

УСТОЙЧИВОСТЬ: контент-хэш + дебаунс 10 мин предотвращают дубликаты.
WHITEBOX AI: parser_version и provenance_id хранят, как было распарсено резюме.
SECURE FIRST: сырой текст резюме не хранится в домене — только хэш и метаданные.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import CandidateId, TenantId

# Дебаунс: если резюме загружено повторно с тем же content-hash в течение
# этого окна, новая версия не создаётся (дубликат игнорируется).
DEBOUNCE_WINDOW_SECONDS = 600  # 10 минут


class ResumeSourceKind(StrEnum):
    """Тип источника резюме (как в Huntflow)."""

    UPLOAD = "upload"
    EMAIL = "email"
    JOB_BOARD = "job_board"
    REFERRAL = "referral"
    AGENCY = "agency"
    LINKEDIN = "linkedin"
    MANUAL = "manual"
    OTHER = "other"


class ResumeVersionStatus(StrEnum):
    """Статус обработки версии резюме."""

    PENDING = "pending"  # загружено, ожидает парсинга
    PARSING = "parsing"  # парсинг в процессе
    PARSED = "parsed"  # успешно распарсено
    FAILED = "failed"  # парсинг не удался
    NEEDS_MANUAL_REVIEW = "needs_manual_review"  # нечитаемый файл → ручной разбор


class ResumeFileType(StrEnum):
    """Допустимые форматы файлов резюме."""

    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    TXT = "txt"


ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt"}


@dataclass(frozen=True)
class ResumeVersionCreated(DomainEvent):
    """Событие: создана новая версия резюме кандидата."""

    version_id: UUID = field(default_factory=uuid4)
    candidate_id: UUID = field(default_factory=uuid4)
    version_number: int = 0
    content_hash: str = ""
    source_kind: str = ""
    file_type: str = ""


@dataclass(frozen=True)
class ResumeSource:
    """Источник резюме (канал привлечения).

    Один кандидат может иметь резюме из разных источников.
    Источник привязывается к конкретной версии резюме.
    """

    id: UUID
    tenant_id: TenantId
    candidate_id: CandidateId
    kind: ResumeSourceKind
    label: str = ""  # Человекочитаемое название источника
    external_id: str | None = None  # ID во внешней системе (job_board, linkedin)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        kind: ResumeSourceKind,
        label: str = "",
        external_id: str | None = None,
    ) -> ResumeSource:
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            kind=kind,
            label=label,
            external_id=external_id,
        )


def compute_content_hash(content: bytes) -> str:
    """Вычислить SHA-256 хэш содержимого файла для дедупликации."""
    return hashlib.sha256(content).hexdigest()


@dataclass
class ResumeVersion(AggregateRoot):
    """Версия резюме кандидата.

    Инварианты:
    - candidate_id обязателен (версия принадлежит кандидату).
    - content_hash — SHA-256 сырого файла (для дедупликации).
    - version_number монотонно возрастает (1, 2, 3...).
    - parsed_data хранится только после успешного парсинга (JSONB).
    - provenance_id — ссылка на AI-вызов парсинга (whitebox).
    """

    id: UUID
    tenant_id: TenantId
    candidate_id: CandidateId
    version_number: int
    content_hash: str
    file_type: ResumeFileType
    source: ResumeSource
    # default поля
    file_storage_key: str = ""
    original_filename: str = ""
    status: ResumeVersionStatus = ResumeVersionStatus.PENDING
    parser_version: str = ""
    provenance_id: UUID | None = None
    parsed_data: dict | None = None
    parse_error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        version_number: int,
        content_hash: str,
        file_type: ResumeFileType,
        source: ResumeSource,
        file_storage_key: str = "",
        original_filename: str = "",
    ) -> ResumeVersion:
        """Создать новую версию резюме (статус = PENDING)."""
        version = cls(
            id=uuid4(),
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            version_number=version_number,
            content_hash=content_hash,
            file_type=file_type,
            source=source,
            file_storage_key=file_storage_key,
            original_filename=original_filename,
        )
        version._record(
            ResumeVersionCreated(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                version_id=version.id,
                payload={
                    "candidate_id": str(candidate_id.value),
                    "version_number": version_number,
                    "content_hash": content_hash,
                },
                candidate_id=candidate_id.value,
                version_number=version_number,
                content_hash=content_hash,
                source_kind=source.kind.value,
                file_type=file_type.value,
            )
        )
        return version

    def mark_parsing(self) -> None:
        """Перевести в статус PARSING."""
        self.status = ResumeVersionStatus.PARSING

    def mark_parsed(
        self,
        parsed_data: dict,
        provenance_id: UUID,
        parser_version: str,
    ) -> None:
        """Отметить успешный парсинг."""
        self.status = ResumeVersionStatus.PARSED
        self.parsed_data = parsed_data
        self.provenance_id = provenance_id
        self.parser_version = parser_version
        self.parse_error = None

    def mark_failed(self, error: str) -> None:
        """Отметить неудачный парсинг."""
        self.status = ResumeVersionStatus.FAILED
        self.parse_error = error

    def mark_needs_manual_review(self, reason: str = "") -> None:
        """Перевести в статус NEEDS_MANUAL_REVIEW (нечитаемый файл)."""
        self.status = ResumeVersionStatus.NEEDS_MANUAL_REVIEW
        self.parse_error = reason or "Файл не поддаётся автоматическому парсингу"

    def is_within_debounce_window(self, now: datetime | None = None) -> bool:
        """Проверить, находится ли версия в окне дебаунса (10 мин)."""
        check_at = now or datetime.now(UTC)
        delta = (check_at - self.created_at).total_seconds()
        return delta < DEBOUNCE_WINDOW_SECONDS


def detect_file_type(filename: str) -> ResumeFileType | None:
    """Определить тип файла резюме по расширению."""
    from pathlib import Path

    ext = Path(filename).suffix.lower()
    mapping = {
        ".pdf": ResumeFileType.PDF,
        ".docx": ResumeFileType.DOCX,
        ".html": ResumeFileType.HTML,
        ".htm": ResumeFileType.HTML,
        ".txt": ResumeFileType.TXT,
    }
    return mapping.get(ext)
