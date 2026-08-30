"""Use case: загрузка резюме к существующему кандидату.

JUGO-113: POST /candidates/{id}/resumes → привязка источника + автосоздание версии.
JUGO-114: Автообновление фактов из резюме (source_kind=resume_version, без перезаписи закреплённых).

AI NATIVE: текст резюме → ИИ извлекает структуру → факты профиля.
WHITEBOX AI: версия хранит parser_version + provenance_id (ссылку на AI-вызов).
SECURE FIRST: сырой текст резюме не персистится — только content_hash + parsed_data.
УСТОЙЧИВОСТЬ: content-hash дедупликация + debounce 10 мин предотвращают дубликаты.
БЫСТРЕЙШИЙ ПОИСК: кандидат переиндексируется после обновления профиля.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from ats.infra.ai.text_extraction import (
    TextExtractionError,
    UnsupportedFormatError,
    extract_text,
)
from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.skills.parse_resume import ParseResume
from ats.modules.candidates.domain.candidate import Candidate
from ats.modules.candidates.domain.facts import (
    CandidateFact,
    FactId,
    FactSource,
    FactType,
    build_experience_fact,
    build_skill_fact,
)
from ats.modules.candidates.domain.parsed_resume import ParsedResume
from ats.modules.candidates.domain.resume import (
    ResumeSource,
    ResumeSourceKind,
    ResumeVersion,
    compute_content_hash,
    detect_file_type,
)
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.candidates.ports.resume_repository import ResumeRepository
from ats.modules.search.domain.models import SearchableDocument, build_search_text
from ats.modules.search.ports.search_engine import SearchEngine
from ats.shared.ids import CandidateId, TenantId
from ats.shared.result import ErrorCode, Result, is_error

logger = logging.getLogger(__name__)


@dataclass
class UploadCandidateResumeInput:
    """DTO загрузки резюме к существующему кандидату."""

    candidate_id: CandidateId
    content: bytes
    filename: str
    source_kind: ResumeSourceKind = ResumeSourceKind.UPLOAD
    source_label: str = ""
    external_id: str | None = None


@dataclass
class UploadCandidateResumeResult:
    """Результат загрузки резюме к кандидату."""

    version: ResumeVersion
    candidate: Candidate
    parsed: ParsedResume | None = None
    facts_created: int = 0
    deduplicated: bool = False  # True если версия уже существовала (debounce/dedup)


class UploadCandidateResumeUseCase:
    """Загрузить резюме к существующему кандидату: дедупликация → версия →
    извлечение текста → AI-парсинг → автофакты → переиндексация.

    Возвращает ResumeVersion + обновлённого кандидата + кол-во созданных фактов.
    """

    def __init__(
        self,
        candidates: CandidateRepository,
        resume_repo: ResumeRepository,
        parse_skill: ParseResume,
        search_engine: SearchEngine,
        ai_gateway: AIGateway,
    ) -> None:
        self._candidates = candidates
        self._resume_repo = resume_repo
        self._parse_skill = parse_skill
        self._search_engine = search_engine
        self._ai_gateway = ai_gateway

    async def execute(
        self,
        tenant_id: TenantId,
        dto: UploadCandidateResumeInput,
    ) -> Result[UploadCandidateResumeResult]:
        # 1. Проверить существование кандидата
        candidate = await self._candidates.get(tenant_id, dto.candidate_id)
        if candidate is None:
            return Result.err(ErrorCode.NOT_FOUND, "Candidate not found")

        # 2. Определить тип файла
        file_type = detect_file_type(dto.filename)
        if file_type is None:
            return Result.err(
                ErrorCode.VALIDATION,
                f"Неподдерживаемый формат файла: {dto.filename}",
            )

        # 3. Вычислить content-hash и проверить дедупликацию (debounce)
        content_hash = compute_content_hash(dto.content)
        existing = await self._resume_repo.find_by_content_hash(
            tenant_id, dto.candidate_id, content_hash
        )
        if existing is not None and existing.is_within_debounce_window():
            logger.info(
                "Resume version deduplicated (debounce): candidate=%s hash=%s",
                dto.candidate_id,
                content_hash[:12],
            )
            return Result.ok(
                UploadCandidateResumeResult(
                    version=existing,
                    candidate=candidate,
                    parsed=None,
                    facts_created=0,
                    deduplicated=True,
                )
            )

        # 4. Создать источник резюме
        source = ResumeSource.create(
            tenant_id=tenant_id,
            candidate_id=dto.candidate_id,
            kind=dto.source_kind,
            label=dto.source_label or dto.source_kind.value,
            external_id=dto.external_id,
        )
        await self._resume_repo.save_source(source)

        # 5. Создать версию резюме (статус PENDING)
        version_number = await self._resume_repo.get_next_version_number(
            tenant_id, dto.candidate_id
        )
        version = ResumeVersion.create(
            tenant_id=tenant_id,
            candidate_id=dto.candidate_id,
            version_number=version_number,
            content_hash=content_hash,
            file_type=file_type,
            source=source,
            original_filename=dto.filename,
        )
        await self._resume_repo.save_version(version)

        # 6. Извлечь текст
        try:
            resume_text = extract_text(dto.content, dto.filename)
        except UnsupportedFormatError as exc:
            version.mark_failed(str(exc))
            await self._resume_repo.save_version(version)
            return Result.err(ErrorCode.VALIDATION, str(exc))
        except TextExtractionError as exc:
            version.mark_needs_manual_review(str(exc))
            await self._resume_repo.save_version(version)
            return Result.ok(
                UploadCandidateResumeResult(
                    version=version,
                    candidate=candidate,
                    parsed=None,
                    facts_created=0,
                )
            )

        if not resume_text.strip():
            version.mark_needs_manual_review("Резюме не содержит извлекаемого текста")
            await self._resume_repo.save_version(version)
            return Result.ok(
                UploadCandidateResumeResult(
                    version=version,
                    candidate=candidate,
                    parsed=None,
                    facts_created=0,
                )
            )

        # 7. AI-парсинг
        version.mark_parsing()
        await self._resume_repo.save_version(version)

        parse_result = await self._parse_skill.execute(tenant_id, resume_text)
        if is_error(parse_result):
            err = parse_result.error
            version.mark_failed(f"AI parse error: {err.message}")
            await self._resume_repo.save_version(version)
            return Result.err(
                err.code,
                f"Парсинг резюме не удался: {err.message}",
                err.details,
            )

        parsed, provenance_id = parse_result.value

        # 8. Отметить версию как распарсенную (whitebox: parser_version + provenance)
        version.mark_parsed(
            parsed_data=parsed.model_dump(mode="json"),
            provenance_id=provenance_id.value,
            parser_version="parse_resume:v1",
        )
        await self._resume_repo.save_version(version)

        # 9. Привязать resume_provenance к кандидату
        candidate.attach_resume(provenance_id.value)

        # Обновить профиль кандидата из распарсенных данных
        if parsed.headline and not candidate.headline:
            candidate.update_profile(headline=parsed.headline)
        if parsed.skills and not candidate.skills:
            candidate.update_profile(skills=parsed.skills)
        if parsed.full_name and candidate.full_name == "Кандидат из резюме":
            candidate.update_profile(full_name=parsed.full_name)

        await self._candidates.save(candidate)

        # 10. Автообновление фактов (JUGO-114)
        facts_created = await self._sync_facts_from_resume(
            tenant_id, dto.candidate_id, parsed, str(version.id)
        )

        # 11. Переиндексация кандидата (БЫСТРЕЙШИЙ ПОИСК)
        await self._reindex_candidate(tenant_id, candidate, parsed)

        logger.info(
            "Resume uploaded to candidate %s: version=%d facts=%d",
            dto.candidate_id,
            version_number,
            facts_created,
        )

        return Result.ok(
            UploadCandidateResumeResult(
                version=version,
                candidate=candidate,
                parsed=parsed,
                facts_created=facts_created,
            )
        )

    async def _sync_facts_from_resume(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        parsed: ParsedResume,
        source_ref: str,
    ) -> int:
        """Автообновление фактов из распарсенного резюме (JUGO-114).

        - EXPERIENCE: из experience[]
        - SKILL: из skills[]
        - EDUCATION: из education[]
        - LANGUAGE: из languages[]
        Не перезаписывает pinned/manual факты (через can_be_overwritten_by).
        """
        existing_facts = await self._candidates.list_facts(tenant_id, candidate_id)
        created = 0

        # Опыт работы
        for exp in parsed.experience:
            if not exp.company and not exp.position:
                continue
            start_dt = _try_parse_date(exp.start_date)
            end_dt = _try_parse_date(exp.end_date)
            fact = build_experience_fact(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                company=exp.company,
                position=exp.position,
                start_date=start_dt,
                end_date=end_dt,
                description=exp.description,
                source=FactSource.RESUME_VERSION,
                source_ref=source_ref,
            )
            if _should_create_fact(fact, existing_facts):
                await self._candidates.add_fact(fact)
                existing_facts.append(fact)
                created += 1

        # Навыки
        for skill_name in parsed.skills:
            if not skill_name.strip():
                continue
            fact = build_skill_fact(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                skill_name=skill_name.strip(),
                source=FactSource.RESUME_VERSION,
                source_ref=source_ref,
            )
            if _should_create_fact(fact, existing_facts):
                await self._candidates.add_fact(fact)
                existing_facts.append(fact)
                created += 1

        # Образование
        for edu in parsed.education:
            if not edu.institution and not edu.degree:
                continue
            fact = CandidateFact(
                id=FactId(uuid4()),
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                fact_type=FactType.EDUCATION,
                source=FactSource.RESUME_VERSION,
                content={
                    "institution": edu.institution,
                    "degree": edu.degree,
                    "start_date": edu.start_date,
                    "end_date": edu.end_date,
                },
                source_ref=source_ref,
            )
            if _should_create_fact(fact, existing_facts):
                await self._candidates.add_fact(fact)
                existing_facts.append(fact)
                created += 1

        # Языки
        for lang in parsed.languages:
            if not lang.language.strip():
                continue
            fact = CandidateFact(
                id=FactId(uuid4()),
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                fact_type=FactType.LANGUAGE,
                source=FactSource.RESUME_VERSION,
                content={
                    "language": lang.language.strip(),
                    "level": lang.level,
                },
                source_ref=source_ref,
            )
            if _should_create_fact(fact, existing_facts):
                await self._candidates.add_fact(fact)
                existing_facts.append(fact)
                created += 1

        logger.info("Synced %d facts from resume for candidate %s", created, candidate_id)
        return created

    async def _reindex_candidate(
        self,
        tenant_id: TenantId,
        candidate: Candidate,
        parsed: ParsedResume,
    ) -> None:
        """Переиндексировать кандидата: text + embedding + metadata.

        Graceful degradation: ошибка индексации не блокирует загрузку резюме.
        """
        companies = [exp.company for exp in parsed.experience if exp.company]
        text = build_search_text(
            full_name=candidate.full_name,
            headline=candidate.headline,
            skills=candidate.skills,
            companies=companies,
            resume_text=parsed.searchable_text,
        )

        embedding: list[float] | None = None
        try:
            embedding = await self._ai_gateway.embed(tenant_id, text)
        except Exception as exc:
            logger.warning(
                "Embedding failed for candidate %s, indexing text-only: %s",
                candidate.id,
                exc,
            )

        document = SearchableDocument(
            id=candidate.id.value,
            tenant_id=tenant_id.value,
            text=text,
            embedding=embedding,
            metadata={
                "headline": candidate.headline,
                "skills": candidate.skills,
                "source": candidate.source.value,
                "full_name": candidate.full_name,
            },
        )
        try:
            await self._search_engine.index(document)
        except Exception as exc:
            logger.warning("Search re-indexing failed for candidate %s: %s", candidate.id, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_parse_date(value: str) -> date | None:
    """Попытаться распарсить строку даты (YYYY, YYYY-MM, YYYY-MM-DD)."""
    if not value or not value.strip():
        return None
    value = value.strip()
    for _fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            continue
    # Простой fallback: если 4 цифры → год
    if len(value) == 4 and value.isdigit():
        try:
            return date(int(value), 1, 1)
        except ValueError:
            pass
    return None


def _should_create_fact(
    new_fact: CandidateFact,
    existing_facts: list[CandidateFact],
) -> bool:
    """Проверить, нужно ли создавать факт.

    Не создаём дубликат: если есть существующий факт того же типа с тем же
    естественным ключом — пропускаем.
    """
    for existing in existing_facts:
        if existing.fact_type == new_fact.fact_type and _same_natural_key(existing, new_fact):
            return False
    return True


def _same_natural_key(a: CandidateFact, b: CandidateFact) -> bool:
    """Сравнить факты по естественному ключу (без учёта уровня/confidence).

    SKILL: по skill_name
    EXPERIENCE: по company + position
    EDUCATION: по institution + degree
    LANGUAGE: по language
    """
    if a.fact_type != b.fact_type:
        return False
    if a.fact_type == FactType.SKILL:
        return a.content.get("skill_name") == b.content.get("skill_name")
    if a.fact_type == FactType.EXPERIENCE:
        return a.content.get("company") == b.content.get("company") and a.content.get(
            "position"
        ) == b.content.get("position")
    if a.fact_type == FactType.EDUCATION:
        return a.content.get("institution") == b.content.get("institution") and a.content.get(
            "degree"
        ) == b.content.get("degree")
    if a.fact_type == FactType.LANGUAGE:
        return a.content.get("language") == b.content.get("language")
    # Fallback: полное сравнение content
    return a.content == b.content
