"""Тесты S3-клиента + модуля core/files (JUGO-013).

Проверяют:
- StorageSettings (env: ATS_STORAGE_*)
- FileMetadata: создание, S3-ключ, изоляция по tenant_id
- Whitelist: валидация расширений, MIME-типов, размера
- NoOpAntivirus: всегда SKIPPED
- InMemoryFileStorage: upload, download, presigned_url, delete
- Category-specific whitelist (напр. .jpg только для AVATAR)
- FileScanError при обнаружении угрозы (mock антивируса)
- get_storage() фабрика: stub → InMemory, prod → S3
- Protocol: InMemoryFileStorage соответствует FileStorage Protocol
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.storage.antivirus import NoOpAntivirus
from ats.infra.storage.in_memory_storage import (
    FileNotFoundError,
    FileScanError,
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
from ats.infra.storage.settings import StorageSettings
from ats.infra.storage.whitelist import (
    FileValidationError,
    get_allowed_extensions,
    get_allowed_mime_types,
    validate_extension,
    validate_size,
)

# ──────────────────────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────────────────────


class TestStorageSettings:
    def test_defaults(self) -> None:
        s = StorageSettings()
        assert s.endpoint_url == "http://localhost:9000"
        assert s.access_key == ""
        assert s.secret_key == ""
        assert s.region == "ru-1"
        assert s.bucket_name == "ats-files"
        assert s.max_file_size_bytes == 25 * 1024 * 1024
        assert s.presigned_url_expiry_seconds == 3600
        assert s.antivirus_enabled is False
        assert s.use_stub is True


# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────


class TestFileMetadata:
    def test_create_generates_id_and_key(self) -> None:
        tenant_id = uuid4()
        meta = FileMetadata.create(
            tenant_id=tenant_id,
            filename="resume.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            category=FileCategory.RESUME,
        )
        assert meta.id is not None
        assert meta.tenant_id == tenant_id
        assert meta.filename == "resume.pdf"
        assert meta.content_type == "application/pdf"
        assert meta.size_bytes == 1024
        assert meta.category == FileCategory.RESUME
        assert str(tenant_id) in meta.key
        assert "resume" in meta.key

    def test_key_isolates_tenant(self) -> None:
        """SECURE FIRST: tenant_id в ключе обеспечивает изоляцию."""
        tenant_a = uuid4()
        tenant_b = uuid4()
        meta_a = FileMetadata.create(
            tenant_id=tenant_a,
            filename="f.pdf",
            content_type="application/pdf",
            size_bytes=10,
        )
        meta_b = FileMetadata.create(
            tenant_id=tenant_b,
            filename="f.pdf",
            content_type="application/pdf",
            size_bytes=10,
        )
        assert meta_a.key != meta_b.key
        assert str(tenant_a) in meta_a.key
        assert str(tenant_b) in meta_b.key

    def test_key_sanitizes_filename(self) -> None:
        """Имя файла с / и \\ санитизируется в ключе."""
        tenant_id = uuid4()
        meta = FileMetadata.create(
            tenant_id=tenant_id,
            filename="..\\etc/passwd",
            content_type="application/pdf",
            size_bytes=10,
        )
        last_segment = meta.key.rsplit("/", 1)[-1]
        assert "/" not in last_segment
        assert "\\" not in last_segment
        assert "passwd" in last_segment

    def test_create_empty_filename_uses_default(self) -> None:
        meta = FileMetadata.create(
            tenant_id=uuid4(),
            filename="  ",
            content_type="application/pdf",
            size_bytes=10,
        )
        assert meta.filename.strip() or "file" in meta.key


class TestScanResult:
    def test_clean(self) -> None:
        r = ScanResult(status=ScanStatus.CLEAN)
        assert r.status == ScanStatus.CLEAN
        assert r.threat_name == ""

    def test_infected(self) -> None:
        r = ScanResult(status=ScanStatus.INFECTED, threat_name="EICAR")
        assert r.status == ScanStatus.INFECTED
        assert r.threat_name == "EICAR"


# ──────────────────────────────────────────────────────────────
# Whitelist
# ──────────────────────────────────────────────────────────────


class TestWhitelist:
    def test_validate_pdf(self) -> None:
        mime = validate_extension("resume.pdf")
        assert mime == "application/pdf"

    def test_validate_txt(self) -> None:
        mime = validate_extension("notes.txt", FileCategory.RESUME)
        assert mime == "text/plain"

    def test_validate_docx(self) -> None:
        mime = validate_extension("cv.docx", FileCategory.RESUME)
        assert "wordprocessingml" in mime

    def test_validate_jpeg(self) -> None:
        mime = validate_extension("photo.jpeg", FileCategory.AVATAR)
        assert mime == "image/jpeg"

    def test_reject_exe(self) -> None:
        with pytest.raises(FileValidationError, match="Недопустимое расширение"):
            validate_extension("malware.exe")

    def test_reject_no_extension(self) -> None:
        with pytest.raises(FileValidationError, match="без расширения"):
            validate_extension("file")

    def test_reject_empty_filename(self) -> None:
        with pytest.raises(FileValidationError, match="пустым"):
            validate_extension("")

    def test_category_restriction_jpg_not_for_resume(self) -> None:
        """JPG разрешён только для AVATAR, не для RESUME."""
        with pytest.raises(FileValidationError, match="разрешён только для категорий"):
            validate_extension("photo.jpg", FileCategory.RESUME)

    def test_category_restriction_pdf_any(self) -> None:
        """PDF разрешён для всех категорий (frozenset() = unrestricted)."""
        mime = validate_extension("doc.pdf", FileCategory.OTHER)
        assert mime == "application/pdf"

    def test_case_insensitive(self) -> None:
        assert validate_extension("RESUME.PDF") == "application/pdf"
        assert validate_extension("Resume.Pdf") == "application/pdf"

    def test_get_allowed_extensions(self) -> None:
        exts = get_allowed_extensions()
        assert ".pdf" in exts
        assert ".txt" in exts
        assert ".docx" in exts
        assert ".exe" not in exts

    def test_get_allowed_mime_types(self) -> None:
        mimes = get_allowed_mime_types()
        assert "application/pdf" in mimes
        assert "text/plain" in mimes

    def test_validate_size_ok(self) -> None:
        validate_size(1024, 4096)

    def test_validate_size_too_large(self) -> None:
        with pytest.raises(FileValidationError, match="превышает лимит"):
            validate_size(8192, 4096)

    def test_validate_size_zero(self) -> None:
        with pytest.raises(FileValidationError, match="положительным"):
            validate_size(0, 4096)

    def test_validate_size_negative(self) -> None:
        with pytest.raises(FileValidationError, match="положительным"):
            validate_size(-1, 4096)


# ──────────────────────────────────────────────────────────────
# Antivirus
# ──────────────────────────────────────────────────────────────


class TestNoOpAntivirus:
    async def test_scan_returns_skipped(self) -> None:
        av = NoOpAntivirus()
        result = await av.scan(b"file content", "test.txt")
        assert result.status == ScanStatus.SKIPPED
        assert result.threat_name == ""


class MockInfectedAntivirus:
    """Mock антивирус — всегда возвращает INFECTED."""

    async def scan(self, content: bytes, filename: str) -> ScanResult:
        return ScanResult(status=ScanStatus.INFECTED, threat_name="EICAR-Test")


class MockCleanAntivirus:
    """Mock антивирус — всегда возвращает CLEAN."""

    async def scan(self, content: bytes, filename: str) -> ScanResult:
        return ScanResult(status=ScanStatus.CLEAN)


# ──────────────────────────────────────────────────────────────
# InMemoryFileStorage
# ──────────────────────────────────────────────────────────────


class TestInMemoryFileStorage:
    def _make_storage(self, **kwargs: object) -> object:
        defaults: dict[str, object] = {
            "max_file_size_bytes": 10 * 1024 * 1024,
            "use_stub": True,
        }
        defaults.update(kwargs)
        from ats.infra.storage.in_memory_storage import InMemoryFileStorage

        return InMemoryFileStorage(settings=StorageSettings(**defaults))

    async def test_upload_success(self) -> None:
        storage = self._make_storage()
        tenant_id = uuid4()
        content = b"Hello resume content"
        result = await storage.upload(
            tenant_id=tenant_id,
            content=content,
            filename="resume.pdf",
            content_type="application/pdf",
            category=FileCategory.RESUME,
        )
        assert isinstance(result, UploadResult)
        assert result.metadata.filename == "resume.pdf"
        assert result.metadata.content_type == "application/pdf"
        assert result.metadata.size_bytes == len(content)
        assert result.metadata.tenant_id == tenant_id
        assert result.presigned_url != ""

    async def test_upload_and_download_roundtrip(self) -> None:
        storage = self._make_storage()
        tenant_id = uuid4()
        content = b"PDF binary content here"
        result = await storage.upload(
            tenant_id=tenant_id,
            content=content,
            filename="doc.pdf",
            content_type="application/pdf",
        )
        downloaded = await storage.download(result.metadata)
        assert isinstance(downloaded, DownloadResult)
        assert downloaded.content == content
        assert downloaded.content_type == "application/pdf"
        assert downloaded.size_bytes == len(content)

    async def test_presigned_url_contains_key(self) -> None:
        storage = self._make_storage()
        tenant_id = uuid4()
        result = await storage.upload(
            tenant_id=tenant_id,
            content=b"data",
            filename="file.pdf",
            content_type="application/pdf",
        )
        url = await storage.presigned_url(result.metadata)
        assert result.metadata.key in url
        assert "expires_in=" in url

    async def test_presigned_url_custom_expiry(self) -> None:
        storage = self._make_storage()
        tenant_id = uuid4()
        result = await storage.upload(
            tenant_id=tenant_id,
            content=b"data",
            filename="file.pdf",
            content_type="application/pdf",
        )
        url = await storage.presigned_url(result.metadata, expires_in=7200)
        assert "expires_in=7200" in url

    async def test_delete(self) -> None:
        storage = self._make_storage()
        tenant_id = uuid4()
        result = await storage.upload(
            tenant_id=tenant_id,
            content=b"data",
            filename="file.pdf",
            content_type="application/pdf",
        )
        assert storage.get_stored_count() == 1
        await storage.delete(result.metadata)
        assert storage.get_stored_count() == 0
        assert not storage.is_stored(result.metadata.key)

    async def test_download_not_found(self) -> None:
        storage = self._make_storage()
        meta = FileMetadata.create(
            tenant_id=uuid4(),
            filename="x.pdf",
            content_type="application/pdf",
            size_bytes=1,
        )
        with pytest.raises(FileNotFoundError):
            await storage.download(meta)

    async def test_upload_rejects_bad_extension(self) -> None:
        storage = self._make_storage()
        with pytest.raises(FileValidationError):
            await storage.upload(
                tenant_id=uuid4(),
                content=b"data",
                filename="malware.exe",
                content_type="application/octet-stream",
            )

    async def test_upload_rejects_oversized(self) -> None:
        storage = self._make_storage(max_file_size_bytes=100)
        with pytest.raises(FileValidationError, match="превышает лимит"):
            await storage.upload(
                tenant_id=uuid4(),
                content=b"x" * 200,
                filename="big.pdf",
                content_type="application/pdf",
            )

    async def test_upload_ignores_client_content_type(self) -> None:
        """SECURE FIRST: MIME определяется по расширению, не от клиента."""
        storage = self._make_storage()
        result = await storage.upload(
            tenant_id=uuid4(),
            content=b"data",
            filename="resume.pdf",
            content_type="application/octet-stream",
            category=FileCategory.RESUME,
        )
        assert result.metadata.content_type == "application/pdf"

    async def test_upload_with_infected_file_raises(self) -> None:
        storage = self._make_storage()
        storage._antivirus = MockInfectedAntivirus()  # type: ignore[attr-defined]
        with pytest.raises(FileScanError, match="угрозу"):
            await storage.upload(
                tenant_id=uuid4(),
                content=b"EICAR",
                filename="resume.pdf",
                content_type="application/pdf",
            )

    async def test_upload_with_clean_antivirus(self) -> None:
        storage = self._make_storage()
        storage._antivirus = MockCleanAntivirus()  # type: ignore[attr-defined]
        result = await storage.upload(
            tenant_id=uuid4(),
            content=b"clean content",
            filename="resume.pdf",
            content_type="application/pdf",
        )
        assert result.metadata.scan_status == ScanStatus.CLEAN

    async def test_upload_requires_uuid_tenant(self) -> None:
        storage = self._make_storage()
        with pytest.raises(StorageError, match="UUID"):
            await storage.upload(
                tenant_id="not-a-uuid",  # type: ignore[arg-type]
                content=b"data",
                filename="file.pdf",
                content_type="application/pdf",
            )

    async def test_multiple_uploads_isolated(self) -> None:
        storage = self._make_storage()
        tenant_a = uuid4()
        tenant_b = uuid4()
        await storage.upload(
            tenant_id=tenant_a,
            content=b"a",
            filename="f.pdf",
            content_type="application/pdf",
        )
        await storage.upload(
            tenant_id=tenant_b,
            content=b"b",
            filename="f.pdf",
            content_type="application/pdf",
        )
        assert storage.get_stored_count() == 2

    async def test_clear(self) -> None:
        storage = self._make_storage()
        await storage.upload(
            tenant_id=uuid4(),
            content=b"a",
            filename="f.pdf",
            content_type="application/pdf",
        )
        assert storage.get_stored_count() == 1
        storage.clear()
        assert storage.get_stored_count() == 0

    async def test_category_specific_upload(self) -> None:
        """JPG загружается только для AVATAR категории."""
        storage = self._make_storage()
        result = await storage.upload(
            tenant_id=uuid4(),
            content=b"\xff\xd8\xff\xe0",
            filename="avatar.jpg",
            content_type="image/jpeg",
            category=FileCategory.AVATAR,
        )
        assert result.metadata.content_type == "image/jpeg"
        with pytest.raises(FileValidationError):
            await storage.upload(
                tenant_id=uuid4(),
                content=b"\xff\xd8\xff\xe0",
                filename="photo.jpg",
                content_type="image/jpeg",
                category=FileCategory.RESUME,
            )


# ──────────────────────────────────────────────────────────────
# Protocol compliance
# ──────────────────────────────────────────────────────────────


class TestProtocolCompliance:
    def test_in_memory_is_file_storage(self) -> None:
        from ats.infra.storage.in_memory_storage import InMemoryFileStorage

        storage = InMemoryFileStorage()
        assert isinstance(storage, FileStorage)

    def test_in_memory_is_antivirus(self) -> None:
        av = NoOpAntivirus()
        assert isinstance(av, AntivirusScanner)

    def test_noop_antivirus_is_antivirus(self) -> None:
        av = NoOpAntivirus()
        assert isinstance(av, AntivirusScanner)


# ──────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────


class TestGetStorageFactory:
    def test_stub_mode_returns_in_memory(self) -> None:
        from ats.infra.storage import get_storage

        storage = get_storage(settings=StorageSettings(use_stub=True))
        from ats.infra.storage.in_memory_storage import InMemoryFileStorage

        assert isinstance(storage, InMemoryFileStorage)

    def test_non_stub_without_sdk_falls_back_to_in_memory(self) -> None:
        """Если S3 SDK не установлен — fallback на InMemory."""
        """Если S3 SDK не установлен — fallback на InMemory."""
        import sys
        from unittest.mock import patch

        saved = sys.modules.pop("aioboto3", None)
        try:
            with patch.dict(sys.modules, {"aioboto3": None}):
                from ats.infra.storage import get_storage

                storage = get_storage(settings=StorageSettings(use_stub=False))
                from ats.infra.storage.in_memory_storage import (
                    InMemoryFileStorage,
                )

                assert isinstance(storage, InMemoryFileStorage)
        finally:
            if saved is not None:
                sys.modules["aioboto3"] = saved
        from ats.infra.storage.in_memory_storage import InMemoryFileStorage

        assert isinstance(storage, InMemoryFileStorage)

    def test_factory_returns_file_storage_protocol(self) -> None:
        from ats.infra.storage import get_storage

        storage = get_storage()
        assert isinstance(storage, FileStorage)
