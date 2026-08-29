"""CLI для запуска arq-воркеров.

Использование:
    python -m ats.infra.workers.cli index              # одна очередь
    python -m ats.infra.workers.cli ai,index            # несколько очередей
    python -m ats.infra.workers.cli --list              # список доступных очередей

В stub-режиме (нет Redis/arq) --list работает, запуск требует arq.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ats.infra.workers.settings import settings as redis_cfg
from ats.infra.workers.worker_settings import QUEUE_REGISTRY

logger = logging.getLogger(__name__)

# Короткие имена очередей → полные имена из настроек
_SHORT_NAMES: dict[str, str] = {
    "ai": redis_cfg.queue_ai,
    "index": redis_cfg.queue_index,
    "webhooks": redis_cfg.queue_webhooks,
    "analytics": redis_cfg.queue_analytics,
    "scheduler": redis_cfg.queue_scheduler,
}


def _resolve_queue(name: str) -> str:
    """Разрешить короткое имя очереди в полное."""
    if name in _SHORT_NAMES:
        return _SHORT_NAMES[name]
    # Уже полное имя
    if name in QUEUE_REGISTRY:
        return name
    raise SystemExit(f"Unknown queue: {name}. Available: {list(_SHORT_NAMES)}")


def list_queues() -> None:
    """Вывести список доступных очередей."""
    print("Available arq worker queues:")
    for short, full in _SHORT_NAMES.items():
        settings_cls = QUEUE_REGISTRY[full]
        functions = getattr(settings_cls, "functions", [])
        func_names = [getattr(f, "__name__", str(f)) for f in functions]
        print(f"  {short:12s} → {full}")
        print(f"               functions: {func_names or '(none yet)'}")
        print(f"               max_jobs:  {getattr(settings_cls, 'max_jobs', '?')}")


async def _run_worker(queue_name: str) -> None:
    """Запустить один arq-воркер для очереди."""
    try:
        from arq.worker import Worker
    except ImportError as exc:
        raise SystemExit(
            "arq is not installed. Install with: pip install arq"
        ) from exc

    settings_cls = QUEUE_REGISTRY[queue_name]
    worker = Worker(
        functions=settings_cls.functions,
        redis_settings=settings_cls.redis_settings,
        queue_name=queue_name,
        max_jobs=settings_cls.max_jobs,
        job_timeout=settings_cls.job_timeout,
        on_startup=settings_cls.on_startup,
        on_shutdown=settings_cls.on_shutdown,
        on_job_failure=settings_cls.on_job_failure,
    )
    try:
        await worker.async_run()
    except KeyboardInterrupt:
        worker.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run ATS arq workers (JUGO-012)",
    )
    parser.add_argument(
        "queues",
        nargs="?",
        help="Comma-separated queue names (e.g. 'ai,index')",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available queues and exit",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if args.list:
        list_queues()
        return 0

    if not args.queues:
        parser.error("queues argument required (or use --list)")

    import asyncio

    queue_names = [_resolve_queue(q.strip()) for q in args.queues.split(",")]
    logger.info("Starting workers for queues: %s", queue_names)

    async def _run_all() -> None:
        tasks = [asyncio.create_task(_run_worker(q)) for q in queue_names]
        await asyncio.gather(*tasks)

    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        logger.info("Workers interrupted, shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
