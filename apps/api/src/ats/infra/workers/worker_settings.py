"""Конфигурация arq-воркеров: WorkerSettings для пулов очередей (JUGO-012).

Очереди:
- ai         — AI-задачи (генерация критериев, парсинг резюме, реранк)
- index      — индексация (outbox-relay, переиндексация поиска)
- webhooks   — отправка внешних вебхуков
- analytics  — агрегация метрик, отчёты
- scheduler  — cron-задачи (напоминания, эскалация, автозакрытие)

Graceful shutdown: arq обрабатывает SIGTERM, дожидается активных job
в пределах job_timeout / shutdown_timeout.

Примечание: arq импортируется лениво (не установлен в dev/stub).
Модуль импортируется без arq для тестов и метаданных очередей.
"""

from __future__ import annotations

import logging
from typing import Any

from ats.infra.workers.builtin_tasks import EventConsumerTask, OutboxRelayTask
from ats.infra.workers.redis_client import get_redis
from ats.infra.workers.settings import settings as redis_cfg

logger = logging.getLogger(__name__)

# --- Реестр задач (имя → функция) ---
_relay_task = OutboxRelayTask()
_consumer_task = EventConsumerTask()


async def outbox_relay(ctx: dict[str, Any], **params: Any) -> dict[str, Any]:
    """arq-функция: цикл outbox-relay."""
    return await _relay_task(ctx, **params)


async def event_consumer(ctx: dict[str, Any], **params: Any) -> dict[str, Any]:
    """arq-функция: цикл event-consumer."""
    return await _consumer_task(ctx, **params)


def _build_arq_redis_settings() -> Any:
    """Создать ArqRedisSettings из URL (SECURE FIRST: из env).

    Ленивый импорт arq: в dev/stub arq не установлен → возвращаем None.
    """
    try:
        from arq.connections import RedisSettings as ArqRedisSettings

        return ArqRedisSettings.from_dsn(redis_cfg.url)
    except ImportError:
        logger.debug("arq not installed — redis_settings=None (stub)")
        return None


# Вычисляем один раз при импорте модуля (настройки статичны из env)
_ARQ_REDIS_SETTINGS: Any = _build_arq_redis_settings()


async def on_startup(ctx: dict[str, Any]) -> None:
    """Инициализация контекста воркера: Redis, контейнер."""
    logger.info("Worker %s starting", ctx.get("worker_name", "unknown"))
    ctx["redis"] = await get_redis()


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Очистка при остановке воркера."""
    from ats.infra.workers.redis_client import close_redis

    logger.info("Worker %s shutting down", ctx.get("worker_name", "unknown"))
    await close_redis()


async def handle_exception(ctx: dict[str, Any], exc: Exception) -> None:
    """Глобальный обработчик ошибок (observability)."""
    logger.exception(
        "Job %s failed permanently: %s", ctx.get("job_id", "?"), exc
    )


class _WorkerSettingsBase:
    """Общие атрибуты WorkerSettings для всех очередей."""

    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)
    on_job_failure = staticmethod(handle_exception)
    redis_settings = _ARQ_REDIS_SETTINGS
    max_jobs: int = 5
    job_timeout = redis_cfg.job_timeout
    graceful_shutdown_timeout = redis_cfg.shutdown_timeout


class AIWorkerSettings(_WorkerSettingsBase):
    """Очередь ai: AI-задачи (генерация критериев, парсинг резюме)."""
    functions = [event_consumer]
    queue_name = redis_cfg.queue_ai
    max_jobs = 10


class IndexWorkerSettings(_WorkerSettingsBase):
    """Очередь index: индексация, outbox-relay."""
    functions = [outbox_relay]
    queue_name = redis_cfg.queue_index
    max_jobs = 5


class WebhooksWorkerSettings(_WorkerSettingsBase):
    """Очередь webhooks: отправка внешних вебхуков."""
    functions: list = []
    queue_name = redis_cfg.queue_webhooks


class AnalyticsWorkerSettings(_WorkerSettingsBase):
    """Очередь analytics: агрегация метрик, отчёты."""
    functions: list = []
    queue_name = redis_cfg.queue_analytics
    max_jobs = 3


class SchedulerWorkerSettings(_WorkerSettingsBase):
    """Очередь scheduler: cron-задачи (напоминания, эскалация)."""
    functions: list = []
    cron_jobs: list = []
    queue_name = redis_cfg.queue_scheduler
    max_jobs = 2


# Реестр очередей (для управления и метрик)
QUEUE_REGISTRY: dict[str, type] = {
    redis_cfg.queue_ai: AIWorkerSettings,
    redis_cfg.queue_index: IndexWorkerSettings,
    redis_cfg.queue_webhooks: WebhooksWorkerSettings,
    redis_cfg.queue_analytics: AnalyticsWorkerSettings,
    redis_cfg.queue_scheduler: SchedulerWorkerSettings,
}
