"""Конфигурация БД (secure-first: URL и параметры из env)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DBSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATS_DB_", env_file=".env", extra="ignore")

    url: str = Field(
        default="postgresql+asyncpg://ats:ats@localhost:5432/ats",
        description="Async SQLAlchemy URL",
    )
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True
    echo: bool = False


settings = DBSettings()
