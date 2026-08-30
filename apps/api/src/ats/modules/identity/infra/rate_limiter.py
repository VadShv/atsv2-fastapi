"""Ограничение попыток входа (SECURE FIRST, ТЗ §15).

Rate limit: 5 попыток / 5 минут / IP.
Блокировка аккаунта после N неудачных попыток (AccountLockout).

УСТОЙЧИВОСТЬ: in-memory хранилище (dev/тесты). В prod — Redis.
Секреты не логируются. IP определяется из request.client.host или X-Forwarded-For.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Параметры по умолчанию (ТЗ §15)
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_WINDOW_SECONDS = 300  # 5 минут
DEFAULT_LOCKOUT_SECONDS = 900  # 15 минут блокировки аккаунта


@dataclass
class _AttemptRecord:
    """Запись о попытках входа с IP."""

    attempts: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginRateLimiter:
    """Rate limiter для endpoint /auth/login.

    Ограничивает количество попыток входа с одного IP за временное окно.
    При превышении — отклоняет запрос (429 Too Many Requests).

    SECURE FIRST: не раскрывает, существует ли email (одинаковое сообщение
    для "неверный пароль" и "rate limited").
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._records: dict[str, _AttemptRecord] = {}

    def is_rate_limited(self, ip: str) -> bool:
        """Проверить, превышен ли лимит попыток для IP."""
        record = self._records.get(ip)
        if record is None:
            return False
        now = time.monotonic()
        # Очистка старых попыток
        record.attempts = [t for t in record.attempts if now - t < self._window_seconds]
        return len(record.attempts) >= self._max_attempts

    def record_attempt(self, ip: str) -> None:
        """Зафиксировать попытку входа с IP."""
        record = self._records.get(ip)
        if record is None:
            record = _AttemptRecord()
            self._records[ip] = record
        record.attempts.append(time.monotonic())

    def remaining_attempts(self, ip: str) -> int:
        """Сколько попыток осталось для IP."""
        record = self._records.get(ip)
        if record is None:
            return self._max_attempts
        now = time.monotonic()
        record.attempts = [t for t in record.attempts if now - t < self._window_seconds]
        return max(0, self._max_attempts - len(record.attempts))

    def reset(self, ip: str) -> None:
        """Сбросить счётчик для IP (после успешного входа)."""
        self._records.pop(ip, None)

    def clear_all(self) -> None:
        """Очистить все записи (для тестов)."""
        self._records.clear()


class AccountLockout:
    """Блокировка аккаунта после N неудачных попыток.

    SECURE FIRST: после DEFAULT_MAX_ATTEMPTS неудачных входов аккаунт
    блокируется на DEFAULT_LOCKOUT_SECONDS. Защищает от brute-force.
    """

    def __init__(
        self,
        max_failures: int = DEFAULT_MAX_ATTEMPTS,
        lockout_seconds: int = DEFAULT_LOCKOUT_SECONDS,
    ) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._failures: dict[str, _AttemptRecord] = {}

    def is_locked(self, email: str) -> bool:
        """Проверить, заблокирован ли аккаунт."""
        record = self._failures.get(email)
        if record is None:
            return False
        now = time.monotonic()
        if record.locked_until > now:
            return True
        # Блокировка истекла — сбрасываем
        if record.locked_until > 0 and record.locked_until <= now:
            self._failures.pop(email, None)
            return False
        return False

    def record_failure(self, email: str) -> None:
        """Зафиксировать неудачную попытку входа для email."""
        record = self._failures.get(email)
        if record is None:
            record = _AttemptRecord()
            self._failures[email] = record
        record.attempts.append(time.monotonic())
        # Блокируем при достижении лимита
        if len(record.attempts) >= self._max_failures:
            record.locked_until = time.monotonic() + self._lockout_seconds
            logger.warning(
                "Account locked due to %d failed attempts: %s",
                len(record.attempts),
                email,
            )

    def record_success(self, email: str) -> None:
        """Сбросить счётчик неудач после успешного входа."""
        self._failures.pop(email, None)

    def remaining_attempts(self, email: str) -> int:
        """Сколько попыток осталось до блокировки."""
        record = self._failures.get(email)
        if record is None:
            return self._max_failures
        return max(0, self._max_failures - len(record.attempts))

    def lockout_remaining_seconds(self, email: str) -> int:
        """Сколько секунд осталось до разблокировки."""
        record = self._failures.get(email)
        if record is None or record.locked_until == 0:
            return 0
        now = time.monotonic()
        return max(0, int(record.locked_until - now))

    def clear_all(self) -> None:
        """Очистить все записи (для тестов)."""
        self._failures.clear()
