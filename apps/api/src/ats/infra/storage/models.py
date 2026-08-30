"""Доменные модели файлов (хранилище артефактов: резюме, документы).

SECURE FIRST: файлы хранятся в S3, метаданные — в БД.
Контент не возвращается в API напрямую — только presigned URL.
WHITEBOX AI: каждый файл привязан к tenant_id (изоляция) и provenance (traceability).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class FileCategory(StrEnum):
    """Категория файла — для организации ключей и метаданных."""

    RESUME = "resume"
    AVATAR = "avatar"
    DOCUMENT = "document"
    OFFER = "offer"
    OTHER = "other"


class ScanStatus(StrEnum):
    """Результат антивирусного сканирования."""

    CLEAN = "clean"
    INFECTED = "infected"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True)
class FileMetadata:
    """Метаданные загруженного файла.

    Attributes:
        id: уникальный идентификатор файла (UUID).
        tenant_id: тенант-владелец (изоляция).
        key: S3-ключ (путь в бакете), напр. ``tenant_id/category/uuid/filename``.
        filename: оригинальное имя файла (из загрузки).
        content_type: MIME-тип (из whitelist).
        size_bytes: размер в байтах.
        category: категория файла.
        scan_status: результат антивирусного сканирования.
        uploaded_at: момент загрузки.
    """

    id: UUID
    tenant_id: UUID
    key: str
    filename: str
    content_type: str
    size_bytes: int
    category: FileCategory = FileCategory.OTHER
    scan_status: ScanStatus = ScanStatus.SKIPPED
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        category: FileCategory = FileCategory.OTHER,
        scan_status: ScanStatus = ScanStatus.SKIPPED,
    ) -> FileMetadata:
        """Создать метаданные с автогенерацией id и S3-ключа."""
        file_id = uuid4()
        key = _build_s3_key(tenant_id, category, file_id, filename)
        return cls(
            id=file_id,
            tenant_id=tenant_id,
            key=key,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            category=category,
            scan_status=scan_status,
            uploaded_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class UploadResult:
    """Результат загрузки файла: метаданные + presigned URL.

    Attributes:
        metadata: метаданные загруженного файла.
        presigned_url: временная ссылка на скачивание (или пустая строка).
    """

    metadata: FileMetadata
    presigned_url: str = ""


@dataclass(frozen=True)
class ScanResult:
    """Результат антивирусного сканирования.

    Attributes:
        status: статус сканирования (clean/infected/skipped/error).
        threat_name: имя найденной угрозы (если infected), иначе пусто.
        scanned_at: момент сканирования.
    """

    status: ScanStatus
    threat_name: str = ""
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class DownloadResult:
    """Результат скачивания файла: контент + метаданные.

    Attributes:
        content: байты файла.
        content_type: MIME-тип.
        size_bytes: размер.
    """

    content: bytes
    content_type: str
    size_bytes: int


def _build_s3_key(
    tenant_id: UUID,
    category: FileCategory,
    file_id: UUID,
    filename: str,
) -> str:
    """Построить S3-ключ: ``tenant_id/category/file_id/filename``.

    SECURE FIRST: tenant_id в пути обеспечивает изоляцию на уровне ключей.
    """
    # Санитизация имени файла: только безопасные символы
    safe_name = filename.replace("/", "_").replace("\\", "_").strip()
    if not safe_name:
        safe_name = "file"
    return f"{tenant_id}/{category.value}/{file_id}/{safe_name}"
