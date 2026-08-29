"""Антивирус: заглушка NoOpAntivirus (Wave 0).

Реализация антивирусного сканирования запланирована на E-61 (ClamAV/внешний сервис).
Сейчас — no-op: всегда возвращает SKIPPED, не блокирует загрузку.
SECURE FIRST: интерфейс готов, реализация подключается без изменения call-сайтов.
"""

from __future__ import annotations

import logging

from ats.infra.storage.models import ScanResult, ScanStatus

logger = logging.getLogger(__name__)


class NoOpAntivirus:
    """No-op антивирус: не сканирует, возвращает SKIPPED.

    Используется когда ATS_STORAGE_ANTIVIRUS_ENABLED=false (по умолчанию).
    """

    async def scan(self, content: bytes, filename: str) -> ScanResult:
        """Не сканировать — вернуть SKIPPED.

        Args:
            content: байты файла (не используется в no-op).
            filename: имя файла (для логирования).

        Returns:
            ScanResult(status=SKIPPED).
        """
        logger.debug("Antivirus scan skipped (no-op): %s", filename)
        return ScanResult(status=ScanStatus.SKIPPED)
