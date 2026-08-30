"""Извлечение сырого текста из файлов резюме (PDF, TXT, DOCX, HTML).

Изоляция инфраструктуры: домен не знает про форматы файлов.
"""

from __future__ import annotations

import logging
from html.parser import HTMLParser
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 32_000  # ограничение против перерасхода токенов

HTML_SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "meta", "link", "title"})


class UnsupportedFormatError(Exception):
    pass


class TextExtractionError(Exception):
    pass


class _HTMLTextExtractor(HTMLParser):
    """Извлечение видимого текста из HTML, минуя script/style/head."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in HTML_SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in HTML_SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def extract_text(content: bytes, filename: str) -> str:
    """Извлечь текст из содержимого файла по расширению."""
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return _extract_txt(content)
    if ext == ".pdf":
        return _extract_pdf(content)
    if ext in (".docx",):
        return _extract_docx(content)
    if ext in (".html", ".htm"):
        return _extract_html(content)
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


def _extract_html(content: bytes) -> str:
    """Извлечь видимый текст из HTML через stdlib html.parser.

    Без внешних зависимостей. Script/style/head/meta пропускаются.
    """
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            html_text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise TextExtractionError("Не удалось декодировать HTML файл")

    parser = _HTMLTextExtractor()
    parser.feed(html_text)
    parser.close()
    text = parser.get_text().strip()
    if not text:
        raise TextExtractionError("HTML не содержит видимого текста")
    return text[:MAX_TEXT_LENGTH]
