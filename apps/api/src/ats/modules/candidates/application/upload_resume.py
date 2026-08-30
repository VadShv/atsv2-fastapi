"""Use case: загрузка резюме → AI-парсинг → создание кандидата → индексация.

AI NATIVE: загрузил файл → извлекли текст → ИИ распарсил профиль → создали Candidate.
WHITEBOX: кандидат хранит resume_provenance (ссылку на AI-вызов парсинга).
SECURE FIRST: PII не сохраняется в профиле; текст резюме не персистится в открытом виде.
БЫСТРЕЙШИЙ ПОИСК: кандидат сразу индексируется (text + embedding + metadata).
"""

from __future__ import annotations

import logging

from ats.infra.ai.text_extraction import (
    TextExtractionError,
    UnsupportedFormatError,
    extract_text,
)
from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.skills.parse_resume import ParseResume
from ats.modules.candidates.domain.candidate import (
    Candidate,
    CandidateSource,
)
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.search.domain.models import SearchableDocument
from ats.modules.search.ports.search_engine import SearchEngine
from ats.shared.ids import IdempotencyKey, TenantId
from ats.shared.result import ErrorCode, Result, is_error

logger = logging.getLogger(__name__)


class UploadResumeUseCase:
    """Загрузить резюме и создать кандидата на основе AI-парсинга.

    Возвращает созданного кандидата + provenance_id парсинга (whitebox).
    Кандидат сразу индексируется в SearchEngine для быстрейшего поиска.
    """

    def __init__(
        self,
        candidates: CandidateRepository,
        parse_skill: ParseResume,
        search_engine: SearchEngine,
        ai_gateway: AIGateway,
    ) -> None:
        self._candidates = candidates
        self._parse_skill = parse_skill
        self._search_engine = search_engine
        self._ai_gateway = ai_gateway

    async def execute(
        self,
        tenant_id: TenantId,
        content: bytes,
        filename: str,
        idempotency_key: IdempotencyKey,
        source: CandidateSource = CandidateSource.DIRECT,
    ) -> Result[Candidate]:
        # 1. Извлечение текста из файла
        try:
            resume_text = extract_text(content, filename)
        except UnsupportedFormatError as exc:
            return Result.err(ErrorCode.VALIDATION, str(exc))
        except TextExtractionError as exc:
            return Result.err(
                ErrorCode.VALIDATION,
                f"Не удалось извлечь текст: {exc}",
            )

        if not resume_text.strip():
            return Result.err(ErrorCode.VALIDATION, "Резюме не содержит текста")

        # 2. AI-парсинг
        parse_result = await self._parse_skill.execute(tenant_id, resume_text)
        if is_error(parse_result):
            err = parse_result.error
            return Result.err(
                err.code,
                f"Парсинг резюме не удался: {err.message}",
                err.details,
            )

        parsed, provenance_id = parse_result.value

        # 3. Создание кандидата из распарсенных данных
        if not parsed.full_name.strip():
            parsed.full_name = "Кандидат из резюме"

        candidate = Candidate.create(
            tenant_id=tenant_id,
            full_name=parsed.full_name,
            source=source,
            headline=parsed.headline,
            skills=parsed.skills,
        )
        candidate.resume_provenance = provenance_id.value

        # 4. Сохранение
        await self._candidates.save(candidate)

        # 5. Индексация в поисковый движок (БЫСТРЕЙШИЙ ПОИСК)
        await self._index_candidate(tenant_id, candidate, parsed.searchable_text)

        logger.info(
            "Candidate created and indexed: %s (provenance=%s)",
            candidate.full_name,
            provenance_id,
        )

        return Result.ok(candidate)

    async def _index_candidate(
        self,
        tenant_id: TenantId,
        candidate: Candidate,
        searchable_text: str,
    ) -> None:
        """Индексировать кандидата: text + embedding + metadata.

        Graceful degradation: если эмбеддинг недоступен, индексируем только
        текстовый поиск (BM25). Ошибка индексации не блокирует создание кандидата.
        """
        text = searchable_text or " ".join([candidate.headline, *candidate.skills]).strip()
        if not text:
            text = candidate.full_name

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
            logger.warning("Search indexing failed for candidate %s: %s", candidate.id, exc)
