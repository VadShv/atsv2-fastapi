"""Идентификаторы домена.

Типизированные обёртки над UUID, чтобы нельзя было перепутать VacancyId и UserId.
Пустые/None-значения запрещены инвариантом.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class TenantId:
    value: UUID

    def __post_init__(self) -> None:
        if self.value is None:
            raise ValueError("TenantId cannot be None")

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> TenantId:
        return cls(uuid4())

    @classmethod
    def from_string(cls, raw: str) -> TenantId:
        return cls(UUID(raw))


@dataclass(frozen=True)
class UserId:
    value: UUID

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> UserId:
        return cls(uuid4())

    @classmethod
    def from_string(cls, raw: str) -> UserId:
        return cls(UUID(raw))


@dataclass(frozen=True)
class VacancyId:
    value: UUID

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> VacancyId:
        return cls(uuid4())

    @classmethod
    def from_string(cls, raw: str) -> VacancyId:
        return cls(UUID(raw))


@dataclass(frozen=True)
class CandidateId:
    value: UUID

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> CandidateId:
        return cls(uuid4())

    @classmethod
    def from_string(cls, raw: str) -> CandidateId:
        return cls(UUID(raw))


@dataclass(frozen=True)
class ProvenanceId:
    """Ссылка на запись в provenance ledger (whitebox AI)."""

    value: UUID

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def generate(cls) -> ProvenanceId:
        return cls(uuid4())

    @classmethod
    def from_string(cls, raw: str) -> ProvenanceId:
        return cls(UUID(raw))


@dataclass(frozen=True)
class IdempotencyKey:
    """Идемпотентный ключ команд (устойчивость)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("IdempotencyKey cannot be empty")

    def __str__(self) -> str:
        return self.value
