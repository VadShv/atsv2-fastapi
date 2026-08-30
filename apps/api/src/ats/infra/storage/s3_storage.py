"""S3-совместимое хранилище файлов (MinIO в dev, Cloud.ru Object Storage в prod).

УСТОЙЧИВОСТЬ: ленивый импорт aioboto3/boto3 — если не установлен, no-op fallback.
SECURE FIRST: валидация MIME + размера + антивирус перед загрузкой в S3.
СКИРОСТЬ: presigned URL отдаются без проксирования контента через API.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.infra.storage.in_memory_storage import (
    FileNotFoundError,
    FileScanError,
    StorageError,
)
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

_HAS_AIOBOTO3 = False
try:
    import aioboto3

    _HAS_AIOBOTO3 = True
except ImportError:
    aioboto3 = None  # type: ignore[assignment]

_HAS_BOTO3 = False
try:
    import boto3
    from botocore.exceptions import ClientError

    _HAS_BOTO3 = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment, misc]


class S3FileStorage:
    """S3-совместимое хранилище файлов.

    Использует aioboto3 для асинхронных операций.
    Presigned URL генерируется через boto3 (синхронный вызов — быстрый).
    """

    def __init__(
        self,
        settings: StorageSettings | None = None,
        antivirus: AntivirusScanner | None = None,
    ) -> None:
        self._settings = settings or StorageSettings()
        from ats.infra.storage.antivirus import NoOpAntivirus

        self._antivirus: AntivirusScanner = antivirus or NoOpAntivirus()
        self._session: object | None = None

    def _get_session(self) -> object:
        """Получить aioboto3-сессию (lazy init)."""
        if not _HAS_AIOBOTO3:
            raise StorageError("aioboto3 не установлен. Установите: pip install aioboto3")
        if self._session is None:
            self._session = aioboto3.Session(  # type: ignore[union-attr]
                aws_access_key_id=self._settings.access_key or None,
                aws_secret_access_key=self._settings.secret_key or None,
                region_name=self._settings.region,
            )
        return self._session

    async def upload(
        self,
        tenant_id: object,
        content: bytes,
        filename: str,
        content_type: str,
        category: FileCategory = FileCategory.OTHER,
    ) -> UploadResult:
        """Загрузить файл в S3 с валидацией и антивирусным сканированием."""
        if not isinstance(tenant_id, UUID):
            raise StorageError("tenant_id должен быть UUID")

        # 1. Валидация расширения → canonical MIME
        canonical_mime = validate_extension(filename, category)

        # 2. Валидация размера
        validate_size(len(content), self._settings.max_file_size_bytes)

        # 3. Антивирус
        scan_result = await self._antivirus.scan(content, filename)
        if scan_result.status == ScanStatus.INFECTED:
            raise FileScanError(
                f"Антивирус обнаружил угрозу: {scan_result.threat_name or 'unknown'}"
            )

        # 4. Метаданные
        metadata = FileMetadata.create(
            tenant_id=tenant_id,
            filename=filename,
            content_type=canonical_mime,
            size_bytes=len(content),
            category=category,
            scan_status=scan_result.status,
        )

        # 5. Загрузка в S3
        if not _HAS_AIOBOTO3:
            raise StorageError("aioboto3 не установлен. Установите: pip install aioboto3")

        session = self._get_session()
        try:
            async with session.client(  # type: ignore[union-attr]
                "s3",
                endpoint_url=self._settings.endpoint_url,
            ) as s3_client:
                await s3_client.put_object(
                    Bucket=self._settings.bucket_name,
                    Key=metadata.key,
                    Body=content,
                    ContentType=canonical_mime,
                    Metadata={
                        "tenant_id": str(tenant_id),
                        "original_filename": filename,
                        "category": category.value,
                        "file_id": str(metadata.id),
                    },
                )
        except ClientError as exc:
            raise StorageError(f"Ошибка загрузки в S3: {exc}") from exc

        logger.info(
            "File uploaded to S3: %s → %s (%d bytes)",
            filename,
            metadata.key,
            len(content),
        )

        # 6. Presigned URL
        url = await self.presigned_url(metadata)

        return UploadResult(metadata=metadata, presigned_url=url)

    async def download(self, metadata: FileMetadata) -> DownloadResult:
        """Скачать содержимое файла из S3."""
        if not _HAS_AIOBOTO3:
            raise StorageError("aioboto3 не установлен. Установите: pip install aioboto3")

        session = self._get_session()
        try:
            async with session.client(  # type: ignore[union-attr]
                "s3",
                endpoint_url=self._settings.endpoint_url,
            ) as s3_client:
                response = await s3_client.get_object(
                    Bucket=self._settings.bucket_name,
                    Key=metadata.key,
                )
                content = await response["Body"].read()
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")  # type: ignore[union-attr]
            if error_code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Файл не найден: {metadata.key}") from exc
            raise StorageError(f"Ошибка скачивания из S3: {exc}") from exc

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
        """Сгенерировать presigned URL для скачивания файла из S3.

        Использует синхронный boto3 (быстрая операция генерации URL).
        """
        if not _HAS_BOTO3:
            logger.warning("boto3 не установлен, presigned URL недоступен")
            return ""

        expiry = expires_in or self._settings.presigned_url_expiry_seconds
        try:
            sync_client = boto3.client(  # type: ignore[union-attr]
                "s3",
                endpoint_url=self._settings.endpoint_url,
                aws_access_key_id=self._settings.access_key or None,
                aws_secret_access_key=self._settings.secret_key or None,
                region_name=self._settings.region,
            )
            url = sync_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._settings.bucket_name,
                    "Key": metadata.key,
                },
                ExpiresIn=expiry,
            )
            return url
        except Exception as exc:
            logger.warning("Не удалось сгенерировать presigned URL: %s", exc)
            return ""

    async def delete(self, metadata: FileMetadata) -> None:
        """Удалить файл из S3."""
        if not _HAS_AIOBOTO3:
            raise StorageError("aioboto3 не установлен. Установите: pip install aioboto3")

        session = self._get_session()
        try:
            async with session.client(  # type: ignore[union-attr]
                "s3",
                endpoint_url=self._settings.endpoint_url,
            ) as s3_client:
                await s3_client.delete_object(
                    Bucket=self._settings.bucket_name,
                    Key=metadata.key,
                )
        except ClientError as exc:
            raise StorageError(f"Ошибка удаления из S3: {exc}") from exc

        logger.info("File deleted from S3: %s", metadata.key)
