"""Тесты модуля resume versions: домен, дедупликация, дебаунс, use case, автофакты.

JUGO-110..114:
- Домен ResumeVersion: создание, статусы, content-hash, debounce
- Дедупликация по content_hash + debounce window
- Use case загрузки резюме к существующему кандидату
- Автообновление фактов из резюме (без перезаписи pinned)
- HTML extraction
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ats.infra.ai.text_extraction import extract_text
from ats.infra.container import build_container
from ats.modules.candidates.application.candidate_crud import CreateCandidateInput
from ats.modules.candidates.application.upload_candidate_resume import (
    UploadCandidateResumeInput,
)
from ats.modules.candidates.domain.facts import FactSource, FactType
from ats.modules.candidates.domain.resume import (
    DEBOUNCE_WINDOW_SECONDS,
    ResumeFileType,
    ResumeSource,
    ResumeSourceKind,
    ResumeVersion,
    ResumeVersionCreated,
    ResumeVersionStatus,
    compute_content_hash,
    detect_file_type,
)
from ats.shared.ids import CandidateId, TenantId
from ats.shared.result import is_error

TENANT = TenantId.from_string("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Domain: compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_same_content_same_hash(self) -> None:
        content = b"resume text content"
        assert compute_content_hash(content) == compute_content_hash(content)

    def test_different_content_different_hash(self) -> None:
        assert compute_content_hash(b"aaa") != compute_content_hash(b"bbb")

    def test_hash_is_sha256_hex(self) -> None:
        h = compute_content_hash(b"test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Domain: detect_file_type
# ---------------------------------------------------------------------------


class TestDetectFileType:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("resume.pdf", ResumeFileType.PDF),
            ("resume.PDF", ResumeFileType.PDF),
            ("cv.docx", ResumeFileType.DOCX),
            ("page.html", ResumeFileType.HTML),
            ("page.htm", ResumeFileType.HTML),
            ("notes.txt", ResumeFileType.TXT),
            ("file.unknown", None),
            ("noext", None),
        ],
    )
    def test_detect(self, filename: str, expected: ResumeFileType | None) -> None:
        assert detect_file_type(filename) == expected


# ---------------------------------------------------------------------------
# Domain: ResumeSource
# ---------------------------------------------------------------------------


class TestResumeSource:
    def test_create_source(self) -> None:
        candidate_id = CandidateId.generate()
        source = ResumeSource.create(
            tenant_id=TENANT,
            candidate_id=candidate_id,
            kind=ResumeSourceKind.UPLOAD,
            label="Загрузка из веб-формы",
        )
        assert source.tenant_id == TENANT
        assert source.candidate_id == candidate_id
        assert source.kind == ResumeSourceKind.UPLOAD
        assert source.label == "Загрузка из веб-формы"
        assert source.external_id is None

    def test_create_source_with_external_id(self) -> None:
        source = ResumeSource.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            kind=ResumeSourceKind.LINKEDIN,
            external_id="linkedin-profile-123",
        )
        assert source.kind == ResumeSourceKind.LINKEDIN
        assert source.external_id == "linkedin-profile-123"


# ---------------------------------------------------------------------------
# Domain: ResumeVersion
# ---------------------------------------------------------------------------


class TestResumeVersion:
    def _make_source(self) -> ResumeSource:
        return ResumeSource.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            kind=ResumeSourceKind.UPLOAD,
        )

    def test_create_publishes_event(self) -> None:
        source = self._make_source()
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc123",
            file_type=ResumeFileType.PDF,
            source=source,
            original_filename="resume.pdf",
        )
        events = version.collect_events()

        assert version.status == ResumeVersionStatus.PENDING
        assert version.version_number == 1
        assert version.content_hash == "abc123"
        assert version.file_type == ResumeFileType.PDF
        assert version.original_filename == "resume.pdf"
        assert version.parsed_data is None
        assert version.provenance_id is None
        assert len(events) == 1
        assert isinstance(events[0], ResumeVersionCreated)
        assert events[0].version_number == 1
        assert events[0].content_hash == "abc123"
        assert events[0].source_kind == "upload"
        assert events[0].file_type == "pdf"

    def test_mark_parsing(self) -> None:
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc",
            file_type=ResumeFileType.TXT,
            source=self._make_source(),
        )
        version.mark_parsing()
        assert version.status == ResumeVersionStatus.PARSING

    def test_mark_parsed(self) -> None:
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc",
            file_type=ResumeFileType.TXT,
            source=self._make_source(),
        )
        provenance_id = uuid4()
        version.mark_parsed(
            parsed_data={"full_name": "Иван"},
            provenance_id=provenance_id,
            parser_version="parse_resume:v1",
        )
        assert version.status == ResumeVersionStatus.PARSED
        assert version.parsed_data == {"full_name": "Иван"}
        assert version.provenance_id == provenance_id
        assert version.parser_version == "parse_resume:v1"
        assert version.parse_error is None

    def test_mark_failed(self) -> None:
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc",
            file_type=ResumeFileType.TXT,
            source=self._make_source(),
        )
        version.mark_failed("Parse error")
        assert version.status == ResumeVersionStatus.FAILED
        assert version.parse_error == "Parse error"

    def test_mark_needs_manual_review(self) -> None:
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc",
            file_type=ResumeFileType.TXT,
            source=self._make_source(),
        )
        version.mark_needs_manual_review()
        assert version.status == ResumeVersionStatus.NEEDS_MANUAL_REVIEW
        assert version.parse_error is not None

    def test_is_within_debounce_window_true(self) -> None:
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc",
            file_type=ResumeFileType.TXT,
            source=self._make_source(),
        )
        assert version.is_within_debounce_window() is True

    def test_is_within_debounce_window_false(self) -> None:
        version = ResumeVersion.create(
            tenant_id=TENANT,
            candidate_id=CandidateId.generate(),
            version_number=1,
            content_hash="abc",
            file_type=ResumeFileType.TXT,
            source=self._make_source(),
        )
        # Имитируем что версия была создана давно
        past = datetime.now(UTC) - timedelta(seconds=DEBOUNCE_WINDOW_SECONDS + 60)
        version.created_at = past
        assert version.is_within_debounce_window() is False

    def test_debounce_window_is_600_seconds(self) -> None:
        assert DEBOUNCE_WINDOW_SECONDS == 600


# ---------------------------------------------------------------------------
# Text extraction: HTML
# ---------------------------------------------------------------------------


class TestHtmlExtraction:
    def test_extract_html_simple(self) -> None:
        html = "<html><body><h1>Иван Иванов</h1><p>Python Developer</p></body></html>".encode()
        text = extract_text(html, "resume.html")
        assert "Иван Иванов" in text
        assert "Python Developer" in text

    def test_extract_html_skips_script_style(self) -> None:
        html = (
            b"<html><head><style>body{color:red}</style></head>"
            b"<body><script>alert(1)</script><p>Visible text</p></body></html>"
        )
        text = extract_text(html, "page.htm")
        assert "Visible text" in text
        assert "alert" not in text
        assert "color:red" not in text

    def test_extract_html_empty_raises(self) -> None:
        with pytest.raises(Exception):
            extract_text(b"<html><body></body></html>", "empty.html")


# ---------------------------------------------------------------------------
# Use case: upload resume to existing candidate
# ---------------------------------------------------------------------------


class TestUploadCandidateResumeUseCase:
    @pytest.fixture
    async def container(self):
        return build_container()

    @pytest.fixture
    async def candidate_id(self, container):
        result = await container.candidate_crud.create(
            TENANT, CreateCandidateInput(full_name="Тестовый Кандидат")
        )
        assert not is_error(result)
        return result.value.id

    async def test_upload_resume_creates_version_and_facts(self, container, candidate_id) -> None:
        resume_text = (
            "Иванов Иван Иванович\n"
            "Middle Python Developer\n"
            "Навыки: Python, FastAPI, PostgreSQL, Docker\n"
            "Опыт: ООО ТехКомпани, Python Developer, 2022-2026\n"
            "Образование: МГТУ, Магистр, 2016-2022\n"
        )
        content = resume_text.encode("utf-8")

        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content=content,
                filename="resume.txt",
            ),
        )

        assert not is_error(result), result.error
        res = result.value
        assert res.version.status == ResumeVersionStatus.PARSED
        assert res.version.version_number == 1
        assert res.facts_created > 0
        assert res.deduplicated is False
        assert res.parsed is not None

    async def test_upload_resume_deduplicates_same_content(self, container, candidate_id) -> None:
        content = b"resume content for dedup test"

        # Первая загрузка
        result1 = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id, content=content, filename="resume.txt"
            ),
        )
        assert not is_error(result1)

        # Вторая загрузка — тот же content_hash, в окне дебаунса
        result2 = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id, content=content, filename="resume.txt"
            ),
        )
        assert not is_error(result2)
        assert result2.value.deduplicated is True

    async def test_upload_resume_creates_facts_with_resume_source(
        self, container, candidate_id
    ) -> None:
        resume_text = (
            "Иванов Иван\n"
            "Python Developer\n"
            "Навыки: Python, Django\n"
            "Опыт: Company A, Developer, 2020-2024\n"
        )
        content = resume_text.encode("utf-8")

        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id, content=content, filename="resume.txt"
            ),
        )
        assert not is_error(result)

        facts = await container.candidate_repository.list_facts(TENANT, candidate_id)
        # Факты от резюме имеют source=resume_version
        resume_facts = [f for f in facts if f.source == FactSource.RESUME_VERSION]
        assert len(resume_facts) > 0
        # Проверяем что есть опыт и навыки
        types = {f.fact_type for f in resume_facts}
        assert FactType.EXPERIENCE in types
        assert FactType.SKILL in types

    async def test_upload_resume_does_not_overwrite_pinned_facts(
        self, container, candidate_id
    ) -> None:
        from ats.modules.candidates.application.candidate_crud import AddFactInput

        # Добавляем закреплённый факт навыка вручную
        await container.candidate_crud.add_fact(
            TENANT,
            candidate_id,
            AddFactInput(
                fact_type=FactType.SKILL,
                source=FactSource.MANUAL,
                content={"skill_name": "Python", "level": "expert"},
                pinned=True,
            ),
        )

        # Загружаем резюме с тем же навыком Python
        resume_text = "Иванов Иван\nНавыки: Python, Django\n"
        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content=resume_text.encode("utf-8"),
                filename="resume.txt",
            ),
        )
        assert not is_error(result)

        facts = await container.candidate_repository.list_facts(TENANT, candidate_id)
        python_facts = [f for f in facts if f.content.get("skill_name") == "Python"]
        # Python не должен продублироваться — закреплённый факт защищён
        assert len(python_facts) == 1
        assert python_facts[0].pinned is True
        assert python_facts[0].source == FactSource.MANUAL

    async def test_upload_resume_creates_language_facts(self, container, candidate_id) -> None:
        # Stub возвращает languages в распарсенном резюме
        resume_text = "Иванов Иван\nPython Developer\nНавыки: Python\n"
        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content=resume_text.encode("utf-8"),
                filename="resume.txt",
            ),
        )
        assert not is_error(result)

        facts = await container.candidate_repository.list_facts(TENANT, candidate_id)
        language_facts = [f for f in facts if f.fact_type == FactType.LANGUAGE]
        # Stub возвращает Русский + Английский
        assert len(language_facts) == 2
        lang_names = {f.content.get("language") for f in language_facts}
        assert "Русский" in lang_names
        assert "Английский" in lang_names

    async def test_upload_resume_nonexistent_candidate_returns_error(self, container) -> None:
        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=CandidateId(uuid4()),
                content=b"some text",
                filename="resume.txt",
            ),
        )
        assert is_error(result)
        assert "not found" in result.error.message.lower()

    async def test_upload_resume_unsupported_format(self, container, candidate_id) -> None:
        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content=b"some data",
                filename="resume.xyz",
            ),
        )
        assert is_error(result)

    async def test_upload_resume_attaches_provenance_to_candidate(
        self, container, candidate_id
    ) -> None:
        result = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content="Иванов Иван Python Developer навыки: Python".encode(),
                filename="resume.txt",
            ),
        )
        assert not is_error(result)

        candidate = await container.candidate_repository.get(TENANT, candidate_id)
        assert candidate is not None
        assert candidate.resume_provenance is not None

    async def test_upload_resume_creates_multiple_versions(self, container, candidate_id) -> None:
        # Первое резюме
        await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content=b"resume version 1 unique content",
                filename="resume.txt",
            ),
        )

        # Второе резюме (другой контент — вне debounce)
        result2 = await container.upload_candidate_resume.execute(
            TENANT,
            UploadCandidateResumeInput(
                candidate_id=candidate_id,
                content=b"resume version 2 different content here",
                filename="resume.txt",
            ),
        )
        assert not is_error(result2)
        assert result2.value.version.version_number == 2

        # Проверяем что в репозитории 2 версии
        versions = await container.resume_repository.list_versions(TENANT, candidate_id)
        assert len(versions) == 2


# ---------------------------------------------------------------------------
# ParsedResume: languages field
# ---------------------------------------------------------------------------


class TestParsedResumeLanguages:
    def test_parsed_resume_has_languages_field(self) -> None:
        from ats.modules.candidates.domain.parsed_resume import ParsedResume

        parsed = ParsedResume(
            full_name="Иван",
            languages=[
                {"language": "Русский", "level": "родной"},
                {"language": "Английский", "level": "C1"},
            ],
        )
        assert len(parsed.languages) == 2
        assert parsed.languages[0].language == "Русский"
        assert parsed.languages[0].level == "родной"
        assert parsed.languages[1].level == "C1"

    def test_parsed_resume_languages_default_empty(self) -> None:
        from ats.modules.candidates.domain.parsed_resume import ParsedResume

        parsed = ParsedResume(full_name="Иван")
        assert parsed.languages == []
