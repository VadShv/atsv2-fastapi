"""M1 Screening — Уровень 0: детерминированные правила очистки (JUGO-403).

До вызова LLM кандидат проходит формальные проверки:
- Дубликат (обрабатывается модулем дедупликации, здесь — флаг)
- Нечитаемое/пустое резюме
- Спам (по эвристикам)
- Жёсткие дисквалификаторы по формальным полям

Чистые функции → unit-тесты на граничные случаи. Без LLM, без побочных эффектов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ats.modules.m1_screening.domain.screening import Level0Result

# ---------------------------------------------------------------------------
# Конфигурация правил (детерминированные пороги)
# ---------------------------------------------------------------------------

MIN_RESUME_LENGTH: int = 50  # меньше — считаем нечитаемым/пустым
MAX_SPAM_KEYWORDS: int = 1  # >= 1 спам-маркера → спам

# Эвристики спама: повторяющиеся слова, капс, ссылки
_SPAM_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_SPAM_CAPS_PATTERN = re.compile(r"\b[A-ZА-Я]{15,}\b")
_SPAM_REPEAT_PATTERN = re.compile(r"(.{1,40})\1{4,}")  # 5+ повторов одного блока

# Жёсткие дисквалификаторы по формальным полям (enum причин из ТЗ §8.3)
HARD_DISQUALIFY_REASONS: frozenset[str] = frozenset(
    {
        "underage",
        "no_work_permit",
        "conflict_of_interest",
        "blacklisted",
    }
)


# ---------------------------------------------------------------------------
# Чистые функции проверки
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Level0Input:
    """Входные данные для уровня 0.

    resume_text: текст резюме кандидата (ParsedResume.searchable_text).
    is_blacklisted: кандидат в чёрном списке.
    is_duplicate: кандидат — дубликат (из модуля дедупликации).
    hard_disqualify_reasons: список формальных причин дисквалификации.
    """

    resume_text: str
    is_blacklisted: bool = False
    is_duplicate: bool = False
    hard_disqualify_reasons: list[str] | None = None


def check_unreadable(resume_text: str) -> bool:
    """Резюме нечитаемое/пустое: длина < MIN_RESUME_LENGTH или только пробелы."""
    cleaned = (resume_text or "").strip()
    return len(cleaned) < MIN_RESUME_LENGTH


def check_spam(resume_text: str) -> tuple[bool, list[str]]:
    """Эвристическая проверка спама. Возвращает (is_spam, matched_rules)."""
    text = resume_text or ""
    matched: list[str] = []

    if len(_SPAM_URL_PATTERN.findall(text)) >= 5:
        matched.append("too_many_urls")
    if _SPAM_CAPS_PATTERN.search(text):
        matched.append("excessive_caps")
    if _SPAM_REPEAT_PATTERN.search(text):
        matched.append("repeated_blocks")

    return len(matched) >= MAX_SPAM_KEYWORDS, matched


def check_hard_disqualify(reasons: list[str] | None) -> list[str]:
    """Проверить формальные причины дисквалификации. Возвращает совпавшие."""
    if not reasons:
        return []
    return [r for r in reasons if r in HARD_DISQUALIFY_REASONS]


def run_level0(input_data: Level0Input) -> Level0Result:
    """Запустить все детерминированные правила уровня 0.

    Порядок проверок (приоритет):
    1. Чёрный список → reject (reason=blacklisted)
    2. Жёсткие дисквалификаторы → reject (reason=hard_disqualify)
    3. Дубликат → reject (reason=duplicate)
    4. Нечитаемое резюме → reject (reason=unreadable)
    5. Спам → reject (reason=spam)

    Если ни одно правило не сработало → rejected=False, кандидат идёт на AI.
    """
    matched: list[str] = []

    # 1. Чёрный список
    if input_data.is_blacklisted:
        matched.append("blacklisted")
        return Level0Result(rejected=True, reason="blacklisted", matched_rules=matched)

    # 2. Жёсткие дисквалификаторы
    hard_reasons = check_hard_disqualify(input_data.hard_disqualify_reasons)
    if hard_reasons:
        matched.extend(hard_reasons)
        return Level0Result(
            rejected=True,
            reason=f"hard_disqualify:{hard_reasons[0]}",
            matched_rules=matched,
        )

    # 3. Дубликат
    if input_data.is_duplicate:
        matched.append("duplicate")
        return Level0Result(rejected=True, reason="duplicate", matched_rules=matched)

    # 4. Нечитаемое резюме
    if check_unreadable(input_data.resume_text):
        matched.append("unreadable")
        return Level0Result(rejected=True, reason="unreadable", matched_rules=matched)

    # 5. Спам
    is_spam, spam_rules = check_spam(input_data.resume_text)
    if is_spam:
        matched.extend(spam_rules)
        return Level0Result(rejected=True, reason="spam", matched_rules=matched)

    return Level0Result(rejected=False, reason="", matched_rules=matched)
