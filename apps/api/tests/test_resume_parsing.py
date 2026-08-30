"""Тесты парсинга резюме: экстракция текста, AI-skill, use case загрузки, HTTP."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from ats.infra.ai.text_extraction import (
    UnsupportedFormatError,
    extract_text,
)
from ats.infra.container_helpers import reset_container
from ats.main import app
from ats.modules.candidates.domain.candidate import CandidateSource
from ats.shared.ids import IdempotencyKey, TenantId

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")
client = TestClient(app)


def setup_function() -> None:
    reset_container()


class TestTextExtraction:
    def test_extract_txt_utf8(self) -> None:
        content = "Иван Иванов\nPython Developer\nОпыт: 5 лет".encode()
        text = extract_text(content, "resume.txt")
        assert "Иван Иванов" in text
        assert "Python" in text

    def test_extract_txt_cp1251(self) -> None:
        content = "Иванов Иван".encode("cp1251")
        text = extract_text(content, "resume.txt")
        assert "Иванов" in text

    def test_extract_pdf(self) -> None:
        # Генерируем простой PDF через pypdf
        pypdf = pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        # pypdf плохо добавляет текст без reportlab; используем pdfplumber-совместимый подход
        # Для теста используем готовый минимальный PDF с текстом через reportlab, если есть
        try:
            from reportlab.pdfgen import canvas

            buf = io.BytesIO()
            c = canvas.Canvas(buf)
            c.drawString(72, 720, "Ivan Ivanov Python Developer")
            c.save()
            pdf_bytes = buf.getvalue()
            text = extract_text(pdf_bytes, "resume.pdf")
            assert "Ivan" in text or "Python" in text
        except ImportError:
            pytest.skip("reportlab не установлен — пропускаем PDF-тест")

    def test_unsupported_format(self) -> None:
        with pytest.raises(UnsupportedFormatError):
            extract_text(b"data", "resume.doc")

    def test_truncates_long_text(self) -> None:
        from ats.infra.ai.text_extraction import MAX_TEXT_LENGTH

        content = ("x" * (MAX_TEXT_LENGTH + 100)).encode()
        text = extract_text(content, "resume.txt")
        assert len(text) == MAX_TEXT_LENGTH


class TestParseResumeSkill:
    @pytest.mark.asyncio
    async def test_parse_returns_structured_profile(self) -> None:
        from ats.infra.container_helpers import get_container
        from ats.modules.ai_core.skills.parse_resume import ParseResume

        container = get_container()
        skill = ParseResume(container.ai_gateway)
        result = await skill.execute(TENANT, "Иванов Иван. Python developer, 5 лет опыта.")

        assert not result.error
        parsed, provenance_id = result.value
        assert parsed.full_name
        assert parsed.searchable_text  # гарантируем заполненным
        assert provenance_id is not None

    @pytest.mark.asyncio
    async def test_parse_rejects_empty_text(self) -> None:
        from ats.infra.container_helpers import get_container
        from ats.modules.ai_core.skills.parse_resume import ParseResume
        from ats.shared.result import is_error

        container = get_container()
        skill = ParseResume(container.ai_gateway)
        result = await skill.execute(TENANT, "   ")
        assert is_error(result)
        assert result.error.code.value == "validation"


class TestUploadResumeUseCase:
    @pytest.mark.asyncio
    async def test_upload_txt_creates_candidate(self) -> None:
        from ats.infra.container_helpers import get_container

        container = get_container()
        content = "Иванов Иван Иванович\nMiddle Python Developer".encode()
        result = await container.upload_resume.execute(
            TENANT, content, "resume.txt", IdempotencyKey("u1")
        )

        assert not result.error
        candidate = result.value
        assert candidate.full_name
        assert candidate.resume_provenance is not None
        assert candidate.source == CandidateSource.DIRECT

    @pytest.mark.asyncio
    async def test_upload_unsupported_format(self) -> None:
        from ats.infra.container_helpers import get_container
        from ats.shared.result import is_error

        container = get_container()
        result = await container.upload_resume.execute(
            TENANT, b"data", "resume.doc", IdempotencyKey("u2")
        )
        assert is_error(result)
        assert result.error.code.value == "validation"


class TestUploadResumeAPI:
    def test_upload_resume_endpoint(self) -> None:
        resume_text = "Иванов Иван\nMiddle Python Developer\nPython, FastAPI, PostgreSQL"
        resp = client.post(
            "/api/v1/candidates/upload-resume",
            files={"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")},
            params={"source": "database"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["full_name"]
        assert data["resume_provenance"] is not None
        assert data["source"] == "database"
        assert "Python" in data["skills"]

    def test_upload_rejects_bad_format(self) -> None:
        resp = client.post(
            "/api/v1/candidates/upload-resume",
            files={"file": ("resume.doc", b"data", "application/msword")},
        )
        assert resp.status_code == 400

    def test_upload_rejects_empty_file(self) -> None:
        resp = client.post(
            "/api/v1/candidates/upload-resume",
            files={"file": ("resume.txt", b"", "text/plain")},
        )
        assert resp.status_code == 400
