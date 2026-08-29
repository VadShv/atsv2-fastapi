"""Shared kernel — базовые примитивы всех модулей.

Содержит: идентификаторы, Result-тип, доменные ошибки, базовый агрегат, события.
Не зависит ни от инфраструктуры, ни от других модулей.
"""

from ats.shared.aggregate import AggregateRoot
from ats.shared.ids import (
    CandidateId,
    IdempotencyKey,
    ProvenanceId,
    TenantId,
    UserId,
    VacancyId,
)
from ats.shared.result import Error, ErrorCode, Result, is_error

__all__ = [
    "AggregateRoot",
    "CandidateId",
    "Error",
    "ErrorCode",
    "IdempotencyKey",
    "ProvenanceId",
    "Result",
    "TenantId",
    "UserId",
    "VacancyId",
    "is_error",
]
