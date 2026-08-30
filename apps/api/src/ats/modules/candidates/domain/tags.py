"""Домен кандидатов: теги, категории, blacklist.

SECURE FIRST: blacklist — жёсткий список причин для блокировки кандидата.
УСТОЙЧИВОСТЬ: теги и категории управляются рекрутёром, не ИИ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from ats.shared.ids import CandidateId, TenantId, UserId


class BlacklistReason(StrEnum):
    """Жёсткий enum причин blacklist — нельзя указать произвольную причину."""

    FALSIFIED_DOCUMENTS = "falsified_documents"
    SECURITY_VIOLATION = "security_violation"
    UNPROFESSIONAL_CONDUCT = "unprofessional_conduct"
    POLICY_VIOLATION = "policy_violation"
    OTHER = "other"


@dataclass(frozen=True)
class TagId:
    value: UUID


@dataclass
class CandidateTag:
    """Тег кандидата — пользовательская метка для группировки."""

    id: TagId
    tenant_id: TenantId
    candidate_id: CandidateId
    name: str
    color: str = "#6b7280"
    created_by: UserId | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class BlacklistEntry:
    """Запись в blacklist — блокирует создание новых откликов.

    SECURE FIRST: только admin/head_of_recruiting может добавить в blacklist.
    """

    id: UUID
    tenant_id: TenantId
    candidate_id: CandidateId
    reason: BlacklistReason
    created_by: UserId
    note: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict[str, str]:
        return {
            "candidate_id": str(self.candidate_id.value),
            "reason": self.reason.value,
            "created_by": str(self.created_by.value),
        }
