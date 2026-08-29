"""Базовый класс идемпотентного хендлера arq (JUGO-012).

Все фоновые задачи наследуются от BaseTask и реализуют `execute()`.
Идемпотентность: хендлер может быть вызван повторно (at-least-once доставка),
поэтому должен безопасно обрабатывать дубликаты.

Контракт:
- `task_id` — уникальный идентификатор задачи (для дедупликации).
- `dedup_key` — ключ идемпотентности (если None — дедупликация не выполняется).
- `execute(ctx, **params)` — основная логика, вызывается в контексте воркера.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Результат выполнения задачи."""

    success: bool
    task_id: str
    dedup_key: str | None = None
    processed: bool = True
    duration_ms: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    """Контекст выполнения задачи: доступ к Redis, БД, контейнеру."""

    redis: Any | None = None
    container: Any | None = None
    worker_name: str = ""
    job_id: str = ""
    attempt: int = 1


class BaseTask(ABC):
    """Базовый идемпотентный хендлер фоновых задач.

    Подклассы реализуют `execute()`. Базовый класс обеспечивает:
    - логирование старта/завершения (observability)
    - расчёт длительности
    - graceful обработку ошибок (не падает воркер)
    - опциональную дедупликацию через Redis SET
    """

    #: Уникальное имя функции arq (для регистрации в WorkerSettings)
    name: str = ""

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define a non-empty 'name'")

    async def __call__(self, ctx: dict[str, Any], **params: Any) -> dict[str, Any]:
        """Точка входа для arq: ctx — контекст воркера, params — аргументы job."""
        task_ctx = TaskContext(
            redis=ctx.get("redis"),
            container=ctx.get("container"),
            worker_name=ctx.get("worker_name", ""),
            job_id=ctx.get("job_id", ""),
            attempt=ctx.get("job_try", 1),
        )
        dedup_key = self._dedup_key(params)
        result = await self._run_with_dedup(task_ctx, dedup_key, params)
        return {
            "success": result.success,
            "task_id": result.task_id,
            "dedup_key": result.dedup_key,
            "processed": result.processed,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "metadata": result.metadata,
        }

    async def _run_with_dedup(
        self,
        ctx: TaskContext,
        dedup_key: str | None,
        params: dict[str, Any],
    ) -> TaskResult:
        """Выполнить с дедупликацией (если задан dedup_key и есть Redis)."""
        if dedup_key and ctx.redis is not None:
            # SET NX: если ключ уже есть — задача уже выполнялась (идемпотентность)
            added = await ctx.redis.set(f"task:dedup:{dedup_key}", "1", ex=86400, nx=True)
            if not added:
                logger.info("Task %s already processed (dedup=%s)", self.name, dedup_key)
                return TaskResult(
                    success=True,
                    task_id=self.name,
                    dedup_key=dedup_key,
                    processed=False,
                )
        return await self._execute_safe(ctx, params, dedup_key)

    async def _execute_safe(
        self,
        ctx: TaskContext,
        params: dict[str, Any],
        dedup_key: str | None,
    ) -> TaskResult:
        """Выполнить execute() с обработкой ошибок и замером времени."""
        import time

        start = time.monotonic()
        try:
            logger.info(
                "Task %s started (job=%s, attempt=%d)",
                self.name, ctx.job_id, ctx.attempt,
            )
            metadata = await self.execute(ctx, **params)
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info("Task %s completed in %dms", self.name, duration_ms)
            return TaskResult(
                success=True,
                task_id=self.name,
                dedup_key=dedup_key,
                duration_ms=duration_ms,
                metadata=metadata or {},
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Task %s failed after %dms", self.name, duration_ms)
            return TaskResult(
                success=False,
                task_id=self.name,
                dedup_key=dedup_key,
                duration_ms=duration_ms,
                error=str(exc)[:500],
            )

    def _dedup_key(self, params: dict[str, Any]) -> str | None:
        """Ключ идемпотентности. Переопределяется в подклассах.

        По умолчанию — None (без дедупликации).
        """
        return None

    @abstractmethod
    async def execute(
        self, ctx: TaskContext, **params: Any
    ) -> dict[str, Any] | None:
        """Основная логика задачи. Должна быть идемпотентной."""
        ...
