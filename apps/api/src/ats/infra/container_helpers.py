"""Хелпер единого доступа к контейнеру (singleton)."""

from __future__ import annotations

from ats.infra.container import Container, build_container

_container: Container | None = None


def get_container() -> Container:
    """Ленивая инициализация контейнера (singleton)."""
    global _container
    if _container is None:
        _container = build_container()
    return _container


def reset_container() -> None:
    """Сбросить контейнер (для тестов)."""
    global _container
    _container = None
