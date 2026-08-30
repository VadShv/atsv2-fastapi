"""Use cases дедупликации кандидатов (JUGO-150..155).

JUGO-150: Точные проверки (HMAC контактов) → find_exact_duplicates
JUGO-151: Нечёткий скоринг → find_fuzzy_duplicates
JUGO-152: Мердж → merge_candidates (перенос откликов/фактов/резюме/контактов)
JUGO-153: Откат мерджа → rollback_merge (30 дней)
JUGO-155: Автомердж → auto_merge_exact (фича-флаг)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ats.modules.candidates.application.fuzzy_scoring import (
    find_fuzzy_duplicates,
    score_pair,
)
from ats.modules.candidates.domain.candidate import Candidate
from ats.modules.candidates.domain.dedup import (
    ContactHash,
    ContactKind,
    DuplicateConfidence,
    DuplicateMatch,
    MergeLog,
    hash_contact,
)
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.candidates.ports.dedup_repository import DedupRepository
from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.shared.ids import CandidateId, TenantId, UserId
from ats.shared.result import ErrorCode, Result


@dataclass
class MergeResult:
    """Результат мерджа."""

    merge_log: MergeLog
    transferred_applications: int
    transferred_facts: int
    transferred_contact_hashes: int
    transferred_tags: int


class DedupUseCase:
    """Use case для дедупликации кандидатов."""

    def __init__(
        self,
        candidate_repo: CandidateRepository,
        dedup_repo: DedupRepository,
        application_repo: ApplicationRepository,
    ) -> None:
        self._candidate_repo = candidate_repo
        self._dedup_repo = dedup_repo
        self._application_repo = application_repo

    # -----------------------------------------------------------------------
    # JUGO-150: Точные проверки
    # -----------------------------------------------------------------------

    async def register_contact(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        kind: ContactKind,
        value: str,
        is_primary: bool = False,
    ) -> Result[ContactHash]:
        """Зарегистрировать контакт кандидата (с HMAC-хэшем для дедупа)."""
        if not value.strip():
            return Result.err(ErrorCode.VALIDATION, "Значение контакта не может быть пустым")
        value_hash = hash_contact(kind, value)
        contact = ContactHash(
            candidate_id=candidate_id.value,
            tenant_id=tenant_id.value,
            kind=kind,
            value_hash=value_hash,
            is_primary=is_primary,
        )
        await self._dedup_repo.add_contact_hash(contact)
        return Result.ok(contact)

    async def find_exact_duplicates(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
    ) -> list[DuplicateMatch]:
        """Найти точные дубликаты кандидата по хэшам контактов.

        Возвращает пары, где другой кандидат имеет совпадающий контакт.
        """
        contacts = await self._dedup_repo.list_contact_hashes(tenant_id, candidate_id)
        if not contacts:
            return []

        matches: list[DuplicateMatch] = []
        seen_duplicates: set[UUID] = set()

        for contact in contacts:
            found = await self._dedup_repo.find_by_contact_hash(
                tenant_id, contact.kind.value, contact.value_hash
            )
            for other in found:
                if other.candidate_id == candidate_id.value:
                    continue
                if other.candidate_id in seen_duplicates:
                    continue
                seen_duplicates.add(other.candidate_id)

                # Survivor — старший по дате
                survivor = await self._candidate_repo.get(tenant_id, candidate_id)
                duplicate = await self._candidate_repo.get(
                    tenant_id, CandidateId.from_string(str(other.candidate_id))
                )
                if survivor is None or duplicate is None:
                    continue

                if survivor.created_at <= duplicate.created_at:
                    surv_id, dup_id = survivor.id.value, duplicate.id.value
                else:
                    surv_id, dup_id = duplicate.id.value, survivor.id.value

                matches.append(
                    DuplicateMatch(
                        survivor_id=surv_id,
                        duplicate_id=dup_id,
                        confidence=DuplicateConfidence.EXACT,
                        score=100.0,
                        matched_fields=[contact.kind.value],
                    )
                )
        return matches

    async def check_contact_exists(
        self,
        tenant_id: TenantId,
        kind: ContactKind,
        value: str,
    ) -> list[CandidateId]:
        """Проверить, существует ли уже контакт (при создании/импорте).

        ТЗ §5.4: точное совпадение → модальное окно «кандидат уже существует».
        """
        value_hash = hash_contact(kind, value)
        found = await self._dedup_repo.find_by_contact_hash(tenant_id, kind.value, value_hash)
        return [CandidateId.from_string(str(ch.candidate_id)) for ch in found]

    # -----------------------------------------------------------------------
    # JUGO-151: Нечёткий скоринг
    # -----------------------------------------------------------------------

    async def find_fuzzy_duplicates(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
        limit: int = 50,
    ) -> list[DuplicateMatch]:
        """Найти нечёткие дубликаты кандидата (fuzzy scoring).

        Сравнивает кандидата со всеми остальными в тенанте.
        """
        target = await self._candidate_repo.get(tenant_id, candidate_id)
        if target is None:
            return []

        others = await self._candidate_repo.list_by_tenant(tenant_id, limit=limit + 1)
        matches: list[DuplicateMatch] = []

        for other in others:
            if other.id == candidate_id:
                continue
            score, matched = score_pair(target, other)
            if score >= 85.0:
                if target.created_at <= other.created_at:
                    surv_id, dup_id = target.id.value, other.id.value
                else:
                    surv_id, dup_id = other.id.value, target.id.value
                matches.append(
                    DuplicateMatch(
                        survivor_id=surv_id,
                        duplicate_id=dup_id,
                        confidence=(
                            DuplicateConfidence.HIGH
                            if score >= 95.0
                            else DuplicateConfidence.MEDIUM
                        ),
                        score=score,
                        matched_fields=matched,
                    )
                )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    async def find_all_duplicates(
        self,
        tenant_id: TenantId,
        limit: int = 100,
    ) -> list[DuplicateMatch]:
        """Фоновый поиск всех дублей в тенанте (JUGO-151: воркер)."""
        candidates = await self._candidate_repo.list_by_tenant(tenant_id, limit=limit)
        return find_fuzzy_duplicates(candidates)

    # -----------------------------------------------------------------------
    # JUGO-152: Мердж кандидатов
    # -----------------------------------------------------------------------

    async def merge_candidates(
        self,
        tenant_id: TenantId,
        survivor_id: CandidateId,
        absorbed_id: CandidateId,
        merged_by: UserId | None = None,
    ) -> Result[MergeResult]:
        """Объединить двух кандидатов: absorbed → survivor.

        Переносит:
        - Отклики (Applications): candidate_id → survivor_id
        - Факты: candidate_id → survivor_id (без дублей)
        - Теги: переносятся
        - Хэши контактов: переносятся (без дублей)
        - Резюме provenance: переносится, если у survivor нет

        Сохраняет merge_log со снапшотом для отката.
        Поглощённый кандидат мягко удаляется (delete).
        """
        if survivor_id == absorbed_id:
            return Result.err(ErrorCode.VALIDATION, "Нельзя объединить кандидата с самим собой")

        survivor = await self._candidate_repo.get(tenant_id, survivor_id)
        absorbed = await self._candidate_repo.get(tenant_id, absorbed_id)
        if survivor is None:
            return Result.err(ErrorCode.NOT_FOUND, "Кандидат-наследник не найден")
        if absorbed is None:
            return Result.err(ErrorCode.NOT_FOUND, "Поглощаемый кандидат не найден")

        # Проверяем, не был ли absorbed уже поглощён ранее
        existing_merge = await self._dedup_repo.find_active_merge_by_absorbed(
            tenant_id, absorbed_id
        )
        if existing_merge is not None:
            return Result.err(
                ErrorCode.CONFLICT,
                "Кандидат уже был поглощён в другом мердже",
            )

        # Снапшот для отката
        snapshot = {
            "survivor": survivor.to_registry_dict(),
            "absorbed": absorbed.to_registry_dict(),
            "merged_at": datetime.now(UTC).isoformat(),
        }

        transferred_applications = 0
        transferred_facts = 0
        transferred_tags = 0

        # 1. Перенос откликов
        applications = await self._application_repo.list_by_candidate(tenant_id, absorbed_id)
        for app in applications:
            # Проверяем, нет ли уже отклика на эту же вакансию у survivor
            existing = await self._application_repo.find_by_candidate_and_vacancy(
                tenant_id, survivor_id, app.vacancy_id
            )
            if existing is not None:
                # Дублирующий отклик: оставляем существующий, поглощённый удаляется
                continue
            # Переносим: меняем candidate_id и сохраняем
            app.candidate_id = survivor_id
            await self._application_repo.save(app)
            transferred_applications += 1

        # 2. Перенос фактов
        absorbed_facts = await self._candidate_repo.list_facts(tenant_id, absorbed_id)
        survivor_facts = await self._candidate_repo.list_facts(tenant_id, survivor_id)
        survivor_fact_keys = {(f.fact_type.value, json_key(f.content)) for f in survivor_facts}
        for fact in absorbed_facts:
            key = (fact.fact_type.value, json_key(fact.content))
            if key in survivor_fact_keys:
                continue
            # Создаём новый факт с новым ID, привязанный к survivor
            from ats.modules.candidates.domain.facts import FactId

            transferred_fact = type(fact)(
                id=FactId(value=uuid4()),
                tenant_id=fact.tenant_id,
                candidate_id=survivor_id,
                fact_type=fact.fact_type,
                source=fact.source,
                content=fact.content,
                pinned=fact.pinned,
                confidence=fact.confidence,
                source_ref=fact.source_ref,
            )
            await self._candidate_repo.add_fact(transferred_fact)
            survivor_fact_keys.add(key)
            transferred_facts += 1

        # 3. Перенос тегов
        absorbed_tags = await self._candidate_repo.list_tags(tenant_id, absorbed_id)
        survivor_tags = await self._candidate_repo.list_tags(tenant_id, survivor_id)
        survivor_tag_names = {t.name for t in survivor_tags}
        for tag in absorbed_tags:
            if tag.name in survivor_tag_names:
                continue
            from ats.modules.candidates.domain.tags import TagId

            transferred_tag = type(tag)(
                id=TagId(value=uuid4()),
                tenant_id=tag.tenant_id,
                candidate_id=survivor_id,
                name=tag.name,
                color=tag.color,
                created_at=tag.created_at,
            )
            await self._candidate_repo.add_tag(transferred_tag)
            survivor_tag_names.add(tag.name)
            transferred_tags += 1

        # 4. Перенос хэшей контактов
        transferred_contact_hashes = await self._dedup_repo.transfer_contact_hashes(
            tenant_id, absorbed_id, survivor_id
        )

        # 5. Перенос резюме provenance (если у survivor нет)
        if survivor.resume_provenance is None and absorbed.resume_provenance is not None:
            survivor.attach_resume(absorbed.resume_provenance)
            snapshot["transferred_resume_provenance"] = str(absorbed.resume_provenance)

        snapshot["transferred"] = {
            "applications": transferred_applications,
            "facts": transferred_facts,
            "tags": transferred_tags,
            "contact_hashes": transferred_contact_hashes,
        }

        # Сохраняем обновлённого survivor
        await self._candidate_repo.save(survivor)

        # Создаём merge_log
        merge_log = MergeLog.create(
            tenant_id=tenant_id,
            survivor_id=survivor_id,
            absorbed_id=absorbed_id,
            snapshot=snapshot,
            merged_by=merged_by,
        )
        await self._dedup_repo.save_merge_log(merge_log)

        # Мягкое удаление поглощённого кандидата
        await self._candidate_repo.delete(tenant_id, absorbed_id)

        return Result.ok(
            MergeResult(
                merge_log=merge_log,
                transferred_applications=transferred_applications,
                transferred_facts=transferred_facts,
                transferred_contact_hashes=transferred_contact_hashes,
                transferred_tags=transferred_tags,
            )
        )

    # -----------------------------------------------------------------------
    # JUGO-153: Откат мерджа
    # -----------------------------------------------------------------------

    async def rollback_merge(
        self,
        tenant_id: TenantId,
        merge_log_id: str,
    ) -> Result[MergeLog]:
        """Откатить мердж (в пределах 30 дней).

        Восстанавливает поглощённого кандидата из снапшота.
        Примечание: перенесённые данные (отклики/факты) остаются у survivor —
        откат только восстанавливает запись поглощённого кандидата.
        Полный перенос данных обратно не делается (данные не потеряны, просто
        принадлежат survivor).
        """
        merge_log = await self._dedup_repo.get_merge_log(tenant_id, merge_log_id)
        if merge_log is None:
            return Result.err(ErrorCode.NOT_FOUND, "Запись мерджа не найдена")

        try:
            merge_log.rollback()
        except ValueError as e:
            return Result.err(ErrorCode.CONFLICT, str(e))

        await self._dedup_repo.save_merge_log(merge_log)

        # Восстанавливаем поглощённого кандидата из снапшота
        snapshot = merge_log.get_snapshot()
        absorbed_data = snapshot.get("absorbed", {})
        restored = _restore_candidate_from_snapshot(absorbed_data)
        if restored is not None:
            await self._candidate_repo.save(restored)

        return Result.ok(merge_log)

    # -----------------------------------------------------------------------
    # JUGO-155: Автомердж для точных совпадений
    # -----------------------------------------------------------------------

    async def auto_merge_exact(
        self,
        tenant_id: TenantId,
        candidate_id: CandidateId,
    ) -> Result[MergeResult | None]:
        """Автоматически объединить точных дублей (фича-флаг).

        Условия (ТЗ §5.4):
        - Точное совпадение по контактам (EXACT confidence)
        - Нет активных откликов у поглощаемого
        - Фича-флаг ATS_DEDUP_AUTO_MERGE=1

        Returns:
            Result[MergeResult | None] — None если дублей не найдено.
        """
        import os

        if os.getenv("ATS_DEDUP_AUTO_MERGE", "0") != "1":
            return Result.err(
                ErrorCode.FORBIDDEN,
                "Автомердж отключён (ATS_DEDUP_AUTO_MERGE!=1)",
            )

        exact_matches = await self.find_exact_duplicates(tenant_id, candidate_id)
        if not exact_matches:
            return Result.ok(None)

        merged_any = False
        for match in exact_matches:
            # Определяем, кто survivor, кто absorbed
            if match.survivor_id == candidate_id.value:
                absorbed_id = CandidateId.from_string(str(match.duplicate_id))
                survivor_id = candidate_id
            else:
                absorbed_id = CandidateId.from_string(str(match.survivor_id))
                survivor_id = candidate_id

            # Проверяем отсутствие активных откликов у поглощаемого
            absorbed_apps = await self._application_repo.list_by_candidate(tenant_id, absorbed_id)
            has_active = any(app.is_active for app in absorbed_apps)
            if has_active:
                continue

            result = await self.merge_candidates(tenant_id, survivor_id, absorbed_id)
            if not _is_error(result):
                merged_any = True
                return result  # Объединяем только первую пару за раз

        if not merged_any:
            return Result.ok(None)
        return Result.ok(None)


def json_key(content: dict) -> str:
    """Стабильный ключ для сравнения фактов."""
    import json

    return json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)


def _is_error(result) -> bool:
    from ats.shared.result import is_error

    return is_error(result)


def _restore_candidate_from_snapshot(data: dict) -> Candidate | None:
    """Восстановить кандидата из снапшота merge_log."""
    if not data or "id" not in data:
        return None
    from ats.modules.candidates.domain.candidate import CandidateSource

    return Candidate(
        id=CandidateId.from_string(data["id"]),
        tenant_id=TenantId.from_string(data["tenant_id"]),
        full_name=data.get("full_name", ""),
        source=CandidateSource(data.get("source", "other")),
        pii_token=data.get("pii_token"),
        headline=data.get("headline", ""),
        skills=data.get("skills", []),
        location=data.get("location", ""),
        resume_provenance=(
            UUID(data["resume_provenance"]) if data.get("resume_provenance") else None
        ),
        created_at=(
            datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC)
        ),
        updated_at=(
            datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC)
        ),
    )
