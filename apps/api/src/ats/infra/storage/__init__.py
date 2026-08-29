"""Модууль хранения файлов (S3-совместимое хранилище).

JUGO-013: S3-клиент + модуль core/files.

Архитектура:
    settings.py          — StorageSettings (env: ATS_STORAGE_*)
    models.py            — FileMetadata, UploadResult, ScanResult, DownloadResult
    protocol.py          — FileStorage Protocol + AntivirusScanner Protocol
    whitelist.py         — MIME whitelist + валидация размера
    antivirus.py         — NoOpAntivirus (заглушка, реализация в E-61)
    in_memory_storage.py — InMemoryFileStorage (тесты/stub/dev)
    s3_storage.py        — S3FileStorage (lazy aioboto3 + boto3 fallback)

Принципы:
    SECURE FIRST — whitelist MIME, лимит размера, антивирус, изоляция по tenant_id.
    УСТОЙЧИВОСТЬ — ленивый импорт S3 SDK, no-op/in-memory fallback если не установлен.
    СКОРОСТЬ    — presigned URL без проксирования контента.
"""

from __future__ import annotations

from ats.infra.storage.antivirus import NoOpAntivirus
from ats.infra.storage.in_memory_storage import (
    FileScanError,
    FileNotFoundError,
    StorageError,
)
from ats.infra.storage.models import (
    DownloadResult,
    FileCategory,
    FileMetadata,
    ScanResult,
    ScanStatus,
    UploadResult,
)
from ats.infra.storage.protocol import AntivirusScanner, FileStorage
from ats.infra.storage.settings import StorageSettings, settings as storage_settings
from ats.infra.storage.whitelist import (
    FileValidationError,
    get_allowed_extensions,
    get_allowed_mime_types,
    validate_extension,
    validate_size,
)

__all__ = [
    # Settings
    "StorageSettings",
    "storage_settings",
    # Models
    "FileCategory",
    "FileMetadata",
    "UploadResult",
    "DownloadResult",
    "ScanResult",
    "ScanStatus",
    # Protocols
    "FileStorage",
    "AntivirusScanner",
    # Implementations
    "NoOpAntivirus",
    "InMemoryFileStorage",
    "S3FileStorage",
    # Errors
    "FileValidationError",
    "FileScanError",
    "FileNotFoundError",
    "StorageError",
    # Whitelist utils
    "get_allowed_extensions",
    "get_allowed_mime_types",
    "validate_extension",
    "validate_size",
    # Factory
    "get_storage",
]


def get_storage(
    settings: StorageSettings | None = None,
    antivirus: AntivirusScanner | None = None,
) -> FileStorage:
    """Фабрика хранилища: InMemory (stub/dev) или S3 (prod).

    УСТОЙЧИВОСТЬ: если S3 SDK не установлен, fallback на InMemory.
    """
    from ats.infra.storage.in_memory_storage import InMemoryFileStorage
    from ats.infra.storage.s3_storage import S3FileStorage

    cfg = settings or storage_settings

    if cfg.use_stub:
        return InMemoryFileStorage(settings=cfg, antivirus=antivirus)

    # S3 mode — но если SDK не установлен, fallback на in-memory
    try:
        import aioboto3  # noqa: F401

        return S3FileStorage(settings=cfg, antivirus=antivirus)
    except ImportError:
        import logging

        logging.getLogger(__name__).warning(
            "aioboto3 не установлен, fallback на InMemoryFileStorage"
        )
        return InMemoryFileStorage(settings=cfg, antivirus=antivirus)


# Lazy import for InMemoryFileStorage / S3FileStorage (避免 circular import)
from ats.infra.storage.in_memory_storage import InMemoryFileStorage  # noqa: E402
from ats.infra.storage.s3_storage import S3FileStorage  # noqa: E402
