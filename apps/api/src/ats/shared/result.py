"""Result-тип и доменные ошибки.

Вместо выброса исключений use cases возвращают Result[Value] / Result[None].
Это делает поток ошибок явным и тестируемым (whitebox).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class ErrorCode(str, Enum):
    """Канонические коды ошибок домена."""

    # Общие
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"

    # AI-специфичные
    AI_UNAVAILABLE = "ai_unavailable"
    AI_INVALID_OUTPUT = "ai_invalid_output"
    AI_BUDGET_EXCEEDED = "ai_budget_exceeded"
    AI_RATE_LIMITED = "ai_rate_limited"

    # Инфраструктурные
    PERSISTENCE = "persistence"
    INTEGRATION = "integration"


@dataclass(frozen=True)
class Error:
    code: ErrorCode
    message: str
    details: dict[str, str] | None = None

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


@dataclass(frozen=True)
class Result(Generic[T]):
    """Результат операции: успех со значением или провал с ошибкой.

    Использование:
        ok = Result.ok(value)
        err = Result.err(ErrorCode.VALIDATION, "...")
        if is_error(err): ...
    """

    _value: T | None
    _error: Error | None

    @classmethod
    def ok(cls, value: T | None = None) -> Result[T]:
        return cls(_value=value, _error=None)

    @classmethod
    def err(
        cls,
        code: ErrorCode,
        message: str,
        details: dict[str, str] | None = None,
    ) -> Result[T]:
        return cls(_value=None, _error=Error(code=code, message=message, details=details))

    @property
    def value(self) -> T:
        if self._error is not None:
            raise ValueError(f"Result is error: {self._error}")
        return self._value  # type: ignore[return-value]

    @property
    def error(self) -> Error | None:
        return self._error


def is_error(result: Result[T]) -> bool:
    return result.error is not None
