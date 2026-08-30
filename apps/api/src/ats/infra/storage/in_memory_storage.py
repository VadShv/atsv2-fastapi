"""In-memory хранилище файлов (тесты / stub-режим / dev без S3).

УСТОЙЧИВОСТЬ: если S3 недоступен или не настроен — fallback на in-memory.
Не персистит данные, но полностью реализует FileStorage Protocol.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.infra.storage.antivirus import NoOpAntivirus
from ats.infra.storage.models import (
    DownloadResult,
    FileCategory,
    FileMetadata,
    ScanStatus,
    UploadResult,
)
from ats.infra.storage.protocol import AntivirusScanner
from ats.infra.storage.settings import StorageSettings
from ats.infra.storage.whitelist import validate_extension, validate_size

logger = logging.getLogger(__name__)


class FileNotFoundError(Exception):
    """Файл не найден в хранилище."""


class StorageError(Exception):
    """Ошибка хранилища (upload/download/delete)."""


class FileScanError(Exception):
    """Антивирус обнаружил угрозу в файле."""


class InMemoryFileStorage:
    """In-memory реализация FileStorage.

    Хранит файлы в dict[key → bytes]. Presigned URL — заглушка (in-memory URL).
    Полная валидация: whitelist MIME + размер + антивирус.
    """

    def __init__(
        self,
        settings: StorageSettings | None = None,
        antivirus: AntivirusScanner | None = None,
    ) -> None:
        self._settings = settings or StorageSettings()
        self._antivirus: AntivirusScanner = antivirus or NoOpAntivirus()
        self._files: dict[str, bytes] = {}
        self._metadata: dict[str, FileMetadata] = {}

    async def upload(
        self,
        tenant_id: object,
        content: bytes,
        filename: str,
        content_type: str,
        category: FileCategory = FileCategory.OTHER,
    ) -> UploadResult:
        """Загрузить файл в in-memory хранилище с полной валидацией."""
        if not isinstance(tenant_id, UUID):
            raise StorageError("tenant_id должен быть UUID")

        # 1. Валидация расширения → canonical MIME (SECURE FIRST)
        canonical_mime = validate_extension(filename, category)

        # 2. Валидация размера
        validate_size(len(content), self._settings.max_file_size_bytes)

        # 3. Антивирусное сканирование
        scan_result = await self._antivirus.scan(content, filename)
        if scan_result.status == ScanStatus.INFECTED:
            raise FileScanError(
                f"Антивирус обнаружил угрозу: {scan_result.threat_name or 'unknown'}"
            )

        # 4. Создание метаданных
        metadata = FileMetadata.create(
            tenant_id=tenant_id,
            filename=filename,
            content_type=canonical_mime,
            size_bytes=len(content),
            category=category,
            scan_status=scan_result.status,
        )

        # 5. Сохранение
        self._files[metadata.key] = content
        self._metadata[metadata.key] = metadata

        logger.info(
            "File uploaded (in-memory): %s → %s (%d bytes, %s)",
            filename,
            metadata.key,
            len(content),
            canonical_mime,
        )

        # 6. Presigned URL (заглушка для in-memory)
        url = await self.presigned_url(metadata)

        return UploadResult(metadata=metadata, presigned_url=url)

    async def download(self, metadata: FileMetadata) -> DownloadResult:
        """Скачать содержимое файла из in-memory хранилища."""
        if metadata.key not in self._files:
            raise FileNotFoundError(f"Файл не найден: {metadata.key}")

        content = self._files[metadata.key]
        return DownloadResult(
            content=content,
            content_type=metadata.content_type,
            size_bytes=len(content),
        )

    async def presigned_url(
        self,
        metadata: FileMetadata,
        expires_in: int | None = None,
    ) -> str:
        """Сгенерировать in-memory presigned URL (заглушка).

        В реальном S3 это будет подписанный URL с ограниченным сроком.
        Здесь — mock-URL для совместимости интерфейса.
        """
        expiry = expires_in or self._settings.presigned_url_expiry_seconds
        return f"memory://files/{metadata.key}?expires_in={expiry}"

    async def delete(self, metadata: FileMetadata) -> None:
        """Удалить файл из in-memory хранилища."""
        self._files.pop(metadata.key, None)
        self._metadata.pop(metadata.key, None)
        logger.info("File deleted (in-memory): %s", metadata.key)

    # --- Утилиты для тестов ---

    def get_stored_count(self) -> int:
        """Количество хранящихся файлов (для тестов)."""
        return len(self._files)

    def is_stored(self, key: str) -> bool:
        """Проверить, хранится ли файл по ключу (для тестов)."""
        return key in self._files

    def clear(self) -> None:
        """Очистить хранилище (для тестов)."""
        self._files.clear()
        self._metadata.clear()
