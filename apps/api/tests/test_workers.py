"""Тесты каркаса воркеров arq (JUGO-012).

Проверяют:
- BaseTask: идемпотентность, дедупликация, обработка ошибок, замер времени
- Builtin tasks: OutboxRelayTask, EventConsumerTask (stub-режим без Redis)
- WorkerSettings: конфигурация очередей, реестр
- Redis client: noop при отсутствии redis-модуля
- CLI: --list, разрешение имён очередей
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.workers.base_task import BaseTask, TaskContext, TaskResult
from ats.infra.workers.builtin_tasks import (
    EventConsumerTask,
    OutboxRelayTask,
)
from ats.infra.workers.redis_client import close_redis, get_redis
from ats.infra.workers.settings import settings as redis_settings
from ats.infra.workers.worker_settings import (
    QUEUE_REGISTRY,
    AIWorkerSettings,
    AnalyticsWorkerSettings,
    IndexWorkerSettings,
    SchedulerWorkerSettings,
    WebhooksWorkerSettings,
    event_consumer,
    outbox_relay,
)


# --- BaseTask ---

class SuccessTask(BaseTask):
    name = "test_success"

    async def execute(self, ctx: TaskContext, **params: Any) -> dict[str, Any] | None:
        return {"items": params.get("count", 1)}


class FailingTask(BaseTask):
    name = "test_fail"

    async def execute(self, ctx: TaskContext, **params: Any) -> dict[str, Any] | None:
        raise ValueError("intentional failure")


class DedupTask(BaseTask):
    name = "test_dedup"

    def _dedup_key(self, params: dict[str, Any]) -> str | None:
        return f"dedup:{params.get('key', 'default')}"

    async def execute(self, ctx: TaskContext, **params: Any) -> dict[str, Any] | None:
        return {"processed": True}


class TestBaseTask:
    """Тесты базового класса идемпотентных хендлеров."""

    @pytest.mark.asyncio
    async def test_name_required(self) -> None:
        """BaseTask без name → ValueError."""

        class NoName(BaseTask):
            async def execute(self, ctx: TaskContext, **params: Any) -> None:
                pass

        with pytest.raises(ValueError, match="non-empty 'name'"):
            NoName()

    @pytest.mark.asyncio
    async def test_success_returns_result(self) -> None:
        task = SuccessTask()
        ctx: dict[str, Any] = {"worker_name": "test", "job_id": "j1", "job_try": 1}
        result = await task(ctx, count=5)
        assert result["success"] is True
        assert result["task_id"] == "test_success"
        assert result["processed"] is True
        assert result["metadata"]["items"] == 5
        assert result["duration_ms"] >= 0
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_failure_handled_gracefully(self) -> None:
        """Ошибки в execute() не падают воркер — возвращают success=False."""
        task = FailingTask()
        ctx: dict[str, Any] = {"worker_name": "test", "job_id": "j1", "job_try": 1}
        result = await task(ctx)
        assert result["success"] is False
        assert result["task_id"] == "test_fail"
        assert "intentional failure" in result["error"]
        assert result["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_dedup_skips_duplicate(self) -> None:
        """Повторный запуск с тем же dedup_key → processed=False."""
        task = DedupTask()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # первый раз — добавлено
        ctx: dict[str, Any] = {"redis": mock_redis, "job_id": "j1", "job_try": 1}

        result1 = await task(ctx, key="abc")
        assert result1["success"] is True
        assert result1["processed"] is True
        assert result1["dedup_key"] == "dedup:abc"

        # Второй раз — ключ уже есть (set nx → False)
        mock_redis.set.return_value = False
        result2 = await task(ctx, key="abc")
        assert result2["success"] is True
        assert result2["processed"] is False  # пропущен

    @pytest.mark.asyncio
    async def test_no_redis_no_dedup(self) -> None:
        """Без Redis дедупликация не выполняется — задача выполняется всегда."""
        task = DedupTask()
        ctx: dict[str, Any] = {"redis": None, "job_id": "j1", "job_try": 1}

        result1 = await task(ctx, key="xyz")
        result2 = await task(ctx, key="xyz")
        assert result1["processed"] is True
        assert result2["processed"] is True

    @pytest.mark.asyncio
    async def test_no_dedup_key_executes_always(self) -> None:
        """Без _dedup_key задача выполняется каждый раз."""
        task = SuccessTask()
        ctx: dict[str, Any] = {"redis": AsyncMock(), "job_id": "j1", "job_try": 1}
        r1 = await task(ctx, count=1)
        r2 = await task(ctx, count=2)
        assert r1["processed"] is True
        assert r2["processed"] is True

    @pytest.mark.asyncio
    async def test_attempt_passed_in_context(self) -> None:
        """job_try из ctx прокидывается в TaskContext.attempt."""
        captured: list[int] = []

        class CaptureTask(BaseTask):
            name = "test_capture"

            async def execute(self, ctx: TaskContext, **params: Any) -> None:
                captured.append(ctx.attempt)

        task = CaptureTask()
        await task({"job_id": "j1", "job_try": 3})
        assert captured == [3]


# --- Builtin tasks ---

class TestOutboxRelayTask:
    @pytest.mark.asyncio
    async def test_name(self) -> None:
        assert OutboxRelayTask().name == "outbox_relay"

    @pytest.mark.asyncio
    async def test_in_registry_as_arq_function(self) -> None:
        """outbox_relay зарегистрирована в IndexWorkerSettings.functions."""
        assert outbox_relay in IndexWorkerSettings.functions

    @pytest.mark.asyncio
    async def test_callable_signature(self) -> None:
        """arq-функция принимает ctx и params."""
        assert callable(outbox_relay)
        assert hasattr(outbox_relay, "__name__")
        assert outbox_relay.__name__ == "outbox_relay"


class TestEventConsumerTask:
    @pytest.mark.asyncio
    async def test_name(self) -> None:
        assert EventConsumerTask().name == "event_consumer"

    @pytest.mark.asyncio
    async def test_in_registry_as_arq_function(self) -> None:
        assert event_consumer in AIWorkerSettings.functions

    @pytest.mark.asyncio
    async def test_no_redis_returns_noop(self) -> None:
        """Без Redis EventConsumerTask возвращает status=no_redis."""
        # Сбрасываем состояние redis-клиента
        await close_redis()
        task = EventConsumerTask()
        ctx: dict[str, Any] = {"redis": None, "job_id": "j1", "job_try": 1}
        result = await task(ctx, stream="events:core", group="test")
        assert result["success"] is True
        assert result["metadata"]["status"] == "no_redis"


# --- WorkerSettings ---

class TestWorkerSettings:
    def test_all_queues_registered(self) -> None:
        """Все 5 очередей зарегистрированы в QUEUE_REGISTRY."""
        assert len(QUEUE_REGISTRY) == 5

    def test_queue_names_match_settings(self) -> None:
        """Имена очередей соответствуют redis_settings."""
        assert QUEUE_REGISTRY[redis_settings.queue_ai] is AIWorkerSettings
        assert QUEUE_REGISTRY[redis_settings.queue_index] is IndexWorkerSettings
        assert QUEUE_REGISTRY[redis_settings.queue_webhooks] is WebhooksWorkerSettings
        assert QUEUE_REGISTRY[redis_settings.queue_analytics] is AnalyticsWorkerSettings
        assert QUEUE_REGISTRY[redis_settings.queue_scheduler] is SchedulerWorkerSettings

    def test_each_queue_has_name(self) -> None:
        for settings_cls in QUEUE_REGISTRY.values():
            assert hasattr(settings_cls, "queue_name")
            assert settings_cls.queue_name.startswith("arq:")

    def test_each_queue_has_max_jobs(self) -> None:
        for settings_cls in QUEUE_REGISTRY.values():
            assert isinstance(settings_cls.max_jobs, int)
            assert settings_cls.max_jobs > 0

    def test_each_queue_has_timeout(self) -> None:
        for settings_cls in QUEUE_REGISTRY.values():
            assert settings_cls.job_timeout == redis_settings.job_timeout

    def test_each_queue_has_lifecycle_hooks(self) -> None:
        for settings_cls in QUEUE_REGISTRY.values():
            assert settings_cls.on_startup is not None
            assert settings_cls.on_shutdown is not None
            assert settings_cls.on_job_failure is not None

    def test_index_queue_has_relay_function(self) -> None:
        assert outbox_relay in IndexWorkerSettings.functions

    def test_ai_queue_has_consumer_function(self) -> None:
        assert event_consumer in AIWorkerSettings.functions

    def test_empty_queues_have_no_functions(self) -> None:
        """webhooks, analytics, scheduler — пока без функций (заготовки)."""
        assert WebhooksWorkerSettings.functions == []
        assert AnalyticsWorkerSettings.functions == []
        assert SchedulerWorkerSettings.functions == []

    @pytest.mark.asyncio
    async def test_on_startup_sets_redis(self) -> None:
        """on_startup выставляет ctx['redis']."""
        await close_redis()
        ctx: dict[str, Any] = {}
        await AIWorkerSettings.on_startup(ctx)
        assert "redis" in ctx
        # В stub-режиме redis может быть None
        await close_redis()

    @pytest.mark.asyncio
    async def test_handle_exception_does_not_raise(self) -> None:
        """handle_exception логирует, но не поднимает исключение."""
        ctx: dict[str, Any] = {"job_id": "j1"}
        await AIWorkerSettings.on_job_failure(ctx, ValueError("test"))


# --- Redis client ---

class TestRedisClient:
    @pytest.mark.asyncio
    async def test_get_redis_noop_without_module(self) -> None:
        """Без redis-модуля get_redis возвращает None."""
        await close_redis()
        client = await get_redis()
        assert client is None

    @pytest.mark.asyncio
    async def test_get_redis_cached(self) -> None:
        """Повторный вызов get_redis возвращает кэшированный результат."""
        await close_redis()
        c1 = await get_redis()
        c2 = await get_redis()
        assert c1 is c2

    @pytest.mark.asyncio
    async def test_close_redis_resets_state(self) -> None:
        await close_redis()
        _ = await get_redis()
        await close_redis()
        # После close можно снова инициализировать
        c = await get_redis()
        assert c is None  # None в stub-режиме


# --- CLI ---

class TestCLI:
    def test_list_queues_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        from ats.infra.workers.cli import main

        rc = main(["--list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ai" in out
        assert "index" in out
        assert "webhooks" in out
        assert "scheduler" in out

    def test_resolve_short_name(self) -> None:
        from ats.infra.workers.cli import _resolve_queue

        assert _resolve_queue("ai") == redis_settings.queue_ai
        assert _resolve_queue("index") == redis_settings.queue_index

    def test_resolve_full_name(self) -> None:
        from ats.infra.workers.cli import _resolve_queue

        assert _resolve_queue(redis_settings.queue_ai) == redis_settings.queue_ai

    def test_resolve_unknown_raises(self) -> None:
        from ats.infra.workers.cli import _resolve_queue

        with pytest.raises(SystemExit, match="Unknown queue"):
            _resolve_queue("nonexistent")

    def test_no_args_errors(self) -> None:
        from ats.infra.workers.cli import main

        with pytest.raises(SystemExit):
            main([])
