"""Общие fixtures для тестов.

Сбрасывает identity runtime (sessions, rate limiter, lockout) между тестами,
чтобы state не «протекал» из одного теста в другой.
"""

from __future__ import annotations

import pytest

from ats.modules.identity.infra.runtime import reset_runtime


@pytest.fixture(autouse=True)
def _reset_identity_runtime():
    """Сбросить identity state перед каждым тестом (autouse)."""
    reset_runtime()
    yield
    reset_runtime()
