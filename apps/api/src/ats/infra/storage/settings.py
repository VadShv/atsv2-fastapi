"""Настройки хранения файлов (SECURE FIRST: лимиты, whitelist из env).

S3-совместимое хранилище: MinIO в dev, Cloud.ru Object Storage в prod.
Все секреты (access_key, secret_key) — только из env, никогда в коде.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATS_STORAGE_", env_file=".env", extra="ignore")

    # --- S3 endpoint ---
    endpoint_url: str = Field(
        default="http://localhost:9000",
        description="S3-совместимый endpoint (MinIO в dev, Cloud.ru в prod)",
    )
    access_key: str = Field(default="", description="S3 access key (из env/vault)")
    secret_key: str = Field(default="", description="S3 secret key (из env/vault)")
    region: str = Field(default="ru-1", description="Регион S3")

    # --- Buckets ---
    bucket_name: str = Field(
        default="ats-files",
        description="Бакет для загруженных файлов (резюме, документы)",
    )

    # --- Security: лимиты ---
    max_file_size_bytes: int = Field(
        default=25 * 1024 * 1024,  # 25 MB
        description="Максимальный размер загружаемого файла в байтах",
    )

    # --- Security: presigned URLs ---
    presigned_url_expiry_seconds: int = Field(
        default=3600,
        description="Срок действия presigned URL в секундах (1 час по умолчанию)",
    )

    # --- Антивирус ---
    antivirus_enabled: bool = Field(
        default=False,
        description="Включить антивирусное сканирование (заглушка в Wave 0, реализация в E-61)",
    )

    # --- Режим ---
    use_stub: bool = Field(
        default=True,
        description="True = InMemoryFileStorage (тесты/dev), False = S3FileStorage",
    )


settings = StorageSettings()
