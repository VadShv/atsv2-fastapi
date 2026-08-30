"""Whitelist MIME-типов и валидация размера (SECURE FIRST).

Только разрешённые типы файлов могут быть загружены.
Размер ограничен для защиты от DoS и перерасхода ресурсов.
MIME-тип определяется по расширению (не доверяем заголовку Content-Type от клиента).
"""

from __future__ import annotations

from pathlib import Path

from ats.infra.storage.models import FileCategory


class FileValidationError(Exception):
    """Ошибка валидации файла: недопустимый тип или размер."""


# --- Whitelist: расширение → (MIME-тип, категории) ---
# Категории указывают, для каких целей разрешён этот тип.
# Если список категорий пуст — разрешён для всех категорий.

_ALLOWED_TYPES: dict[str, tuple[str, frozenset[FileCategory]]] = {
    # Текстовые резюме
    ".txt": ("text/plain", frozenset({FileCategory.RESUME, FileCategory.DOCUMENT})),
    ".pdf": ("application/pdf", frozenset()),
    # Документы Word
    ".doc": (
        "application/msword",
        frozenset({FileCategory.RESUME, FileCategory.DOCUMENT}),
    ),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        frozenset({FileCategory.RESUME, FileCategory.DOCUMENT}),
    ),
    # Изображения (аватары)
    ".jpg": ("image/jpeg", frozenset({FileCategory.AVATAR})),
    ".jpeg": ("image/jpeg", frozenset({FileCategory.AVATAR})),
    ".png": ("image/png", frozenset({FileCategory.AVATAR})),
    # Таблицы (документы)
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        frozenset({FileCategory.DOCUMENT, FileCategory.OFFER}),
    ),
    ".csv": ("text/csv", frozenset({FileCategory.DOCUMENT})),
    # HTML-резюме
    ".html": ("text/html", frozenset({FileCategory.RESUME})),
    ".htm": ("text/html", frozenset({FileCategory.RESUME})),
}


def get_allowed_extensions() -> list[str]:
    """Вернуть список всех разрешённых расширений."""
    return sorted(_ALLOWED_TYPES.keys())


def get_allowed_mime_types() -> list[str]:
    """Вернуть список всех разрешённых MIME-типов."""
    return sorted({mime for mime, _ in _ALLOWED_TYPES.values()})


def validate_extension(
    filename: str,
    category: FileCategory = FileCategory.OTHER,
) -> str:
    """Валидировать расширение файла и вернуть canonical MIME-тип.

    SECURE FIRST: MIME определяется по расширению, а не из заголовка клиента.
    Это предотвращает загрузку исполняемых файлов под видом документов.

    Args:
        filename: имя файла (с расширением).
        category: категория загрузки (для category-specific whitelist).

    Returns:
        Canonical MIME-тип (из whitelist, не от клиента).

    Raises:
        FileValidationError: если расширение не в whitelist или не разрешено
            для указанной категории.
    """
    if not filename or not filename.strip():
        raise FileValidationError("Имя файла не может быть пустым")

    ext = Path(filename).suffix.lower()
    if not ext:
        raise FileValidationError(f"Файл без расширения не разрешён: {filename}")

    entry = _ALLOWED_TYPES.get(ext)
    if entry is None:
        allowed = ", ".join(get_allowed_extensions())
        raise FileValidationError(f"Недопустимое расширение '{ext}'. Разрешены: {allowed}")

    mime, allowed_categories = entry

    # Если категории указаны и файл ограничен категориями — проверяем
    if allowed_categories and category not in allowed_categories:
        cat_names = ", ".join(c.value for c in allowed_categories)
        raise FileValidationError(
            f"Тип '{ext}' разрешён только для категорий: {cat_names}, не для '{category.value}'"
        )

    return mime


def validate_size(size_bytes: int, max_size: int) -> None:
    """Валидировать размер файла.

    SECURE FIRST: ограничение размера защищает от DoS и переполнения хранилища.

    Args:
        size_bytes: размер файла в байтах.
        max_size: максимально допустимый размер в байтах.

    Raises:
        FileValidationError: если размер превышает лимит или отрицательный.
    """
    if size_bytes <= 0:
        raise FileValidationError(f"Размер файла должен быть положительным, получено: {size_bytes}")
    if size_bytes > max_size:
        max_mb = max_size / (1024 * 1024)
        actual_mb = size_bytes / (1024 * 1024)
        raise FileValidationError(
            f"Размер файла {actual_mb:.1f} MB превышает лимит {max_mb:.1f} MB"
        )
