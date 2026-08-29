"""Каркас воркеров arq (JUGO-012).

Пулы очередей: ai, index, webhooks, analytics, scheduler.
Graceful shutdown, идемпотентные хендлеры (BaseTask), дедупликация через Redis.

Точка входа: `python -m ats.infra.workers.cli <queue> [--queue ai,index]`
или через arq CLI: `arq ats.infra.workers.worker_settings.IndexWorkerSettings`.
"""

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
)

__all__ = [
    "BaseTask",
    "TaskContext",
    "TaskResult",
    "EventConsumerTask",
    "OutboxRelayTask",
    "get_redis",
    "close_redis",
    "redis_settings",
    "QUEUE_REGISTRY",
    "AIWorkerSettings",
    "IndexWorkerSettings",
    "WebhooksWorkerSettings",
    "AnalyticsWorkerSettings",
    "SchedulerWorkerSettings",
]
