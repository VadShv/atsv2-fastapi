"""Порты хранилища файлов и антивируса (Ports & Adapters).

Домен и application-слой зависят от этих интерфейсов.
Реализации: S3FileStorage (prod), InMemoryFileStorage (тесты/stub).
Антивирус: NoOpAntivirus (Wave 0), ClamAV/реальный сканер (E-61).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ats.infra.storage.models import (
    DownloadResult,
    FileCategory,
    FileMetadata,
    ScanResult,
    UploadResult,
)


@runtime_checkable
class FileStorage(Protocol):
    """Порт: хранилище файлов (S3-совместимое).

    SECURE FIRST:
    - Загрузка валидирует MIME-тип и размер (whitelist).
    - Антивирусное сканирование перед сохранением (если включено).
    - Ключи изолированы по tenant_id.
    - Прямой доступ к контенту — только через presigned URL с ограниченным сроком.
    """

    async def upload(
        self,
        tenant_id: object,
        content: bytes,
        filename: str,
        content_type: str,
        category: FileCategory = FileCategory.OTHER,
    ) -> UploadResult:
        """Загрузить файл в хранилище.

        Args:
            tenant_id: идентификатор тенанта (UUID).
            content: байты файла.
            filename: оригинальное имя файла.
            content_type: MIME-тип (должен быть в whitelist).
            category: категория файла.

        Returns:
            UploadResult: метаданные + presigned URL.

        Raises:
            FileValidationError: если MIME-тип или размер недопустимы.
            FileScanError: если антивирус обнаружил угрозу.
            StorageError: если не удалось сохранить в S3.
        """
        ...

    async def download(self, metadata: FileMetadata) -> DownloadResult:
        """Скачать содержимое файла по метаданным.

        Args:
            metadata: метаданные файла (содержит S3-ключ).

        Returns:
            DownloadResult: контент + MIME + размер.

        Raises:
            FileNotFoundError: если файл не найден в хранилище.
            StorageError: если не удалось скачать.
        """
        ...

    async def presigned_url(
        self,
        metadata: FileMetadata,
        expires_in: int | None = None,
    ) -> str:
        """Сгенерировать временный URL для скачивания файла.

        Args:
            metadata: метаданные файла.
            expires_in: срок действия в секундах (None = default из settings).

        Returns:
            Presigned URL (строка), или пустую строку если хранилище не поддерживает.
        """
        ...

    async def delete(self, metadata: FileMetadata) -> None:
        """Удалить файл из хранилища.

        Args:
            metadata: метаданные файла.

        Raises:
            StorageError: если не удалось удалить.
        """
        ...


@runtime_checkable
class AntivirusScanner(Protocol):
    """Порт: антивирусное сканирование файлов (SECURE FIRST).

    Wave 0: заглушка NoOpAntivirus (всегда SKIPPED).
    E-61: реальная реализация (ClamAV / внешний сервис).
    """

    async def scan(self, content: bytes, filename: str) -> ScanResult:
        """Просканировать контент файла на вредоносное содержимое.

        Args:
            content: байты файла.
            filename: имя файла (для контекста/логирования).

        Returns:
            ScanResult: статус (clean/infected/skipped/error) + имя угрозы.
        """
        ...
