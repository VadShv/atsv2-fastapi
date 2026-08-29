"""Управление async-сессиями БД с поддержкой RLS (SECURE FIRST).

Паттерн: на каждый request создаётся сессия, в которой выставляется
GUC app.tenant_id — тогда RLS-политики фильтруют строки автоматически.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ats.infra.db.base import Base
from ats.infra.db.settings import settings as db_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            db_settings.url,
            pool_size=db_settings.pool_size,
            max_overflow=db_settings.max_overflow,
            pool_pre_ping=db_settings.pool_pre_ping,
            echo=db_settings.echo,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def init_db() -> None:
    """Создать схемы (для dev/тестов без Alembic). В prod — через миграции."""
    engine = get_engine()
    from ats.infra.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def tenant_session(
    tenant_id: UUID,
) -> AsyncIterator[AsyncSession]:
    """Сессия с выставленным app.tenant_id для RLS.

    Использование:
        async with tenant_session(tenant_id) as session:
            ...  # все запросы фильтруются RLS по tenant_id
    """
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        yield session


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
