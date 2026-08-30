"""Извлечение сырого текста из файлов резюме (PDF, TXT, DOCX).

Изоляция инфраструктуры: домен не знает про форматы файлов.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 32_000  # ограничение против перерасхода токенов


class UnsupportedFormatError(Exception):
    pass


class TextExtractionError(Exception):
    pass


def extract_text(content: bytes, filename: str) -> str:
    """Извлечь текст из содержимого файла по расширению."""
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return _extract_txt(content)
    if ext == ".pdf":
        return _extract_pdf(content)
    if ext in (".docx",):
        return _extract_docx(content)
    raise UnsupportedFormatError(f"Неподдерживаемый формат: {ext}")


def _extract_txt(content: bytes) -> str:
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            return content.decode(encoding)[:MAX_TEXT_LENGTH]
        except UnicodeDecodeError:
            continue
    raise TextExtractionError("Не удалось декодировать текстовый файл")


def _extract_pdf(content: bytes) -> str:
    try:
        import io

        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if not text:
            # Fallback на pdfplumber, если pypdf не извлёк текст
            return _extract_pdf_plumber(content)
        return text[:MAX_TEXT_LENGTH]
    except ImportError:
        return _extract_pdf_plumber(content)
    except Exception as exc:
        logger.warning("pypdf extraction failed, trying pdfplumber: %s", exc)
        return _extract_pdf_plumber(content)


def _extract_pdf_plumber(content: bytes) -> str:
    try:
        import io

        import pdfplumber

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts).strip()
        if not text:
            raise TextExtractionError("PDF не содержит извлекаемого текста (скан?)")
        return text[:MAX_TEXT_LENGTH]
    except Exception as exc:
        raise TextExtractionError(f"Не удалось извлечь текст из PDF: {exc}") from exc


def _extract_docx(content: bytes) -> str:
    try:
        import io

        from docx import Document

        doc = Document(io.BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs)
        return text[:MAX_TEXT_LENGTH]
    except ImportError:
        raise UnsupportedFormatError(
            "Поддержка DOCX требует python-docx. Установите: pip install python-docx"
        ) from None
