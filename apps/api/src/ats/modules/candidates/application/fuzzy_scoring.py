"""Нечёткий скоринг кандидатов для дедупликации (JUGO-151, ТЗ §5.4).

Алгоритм:
- ФИО: нормализация + similarity (SequenceMatcher)
- Год рождения: точное совпадение
- Город: точное совпадение (normalize)
- Работодатель: similarity

Пороги (ТЗ §5.4):
- score >= 95 → HIGH (требование подтверждения)
- 85 <= score < 95 → MEDIUM (мягкое предупреждение)
- score < 85 → LOW

В prod заменяется на pg_trgm (ТЗ), но интерфейс тот же.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from ats.modules.candidates.domain.candidate import Candidate
from ats.modules.candidates.domain.dedup import DuplicateConfidence, DuplicateMatch

# Веса компонентов скоринга (сумма = 100)
WEIGHT_FULL_NAME = 50.0
WEIGHT_BIRTH_YEAR = 20.0
WEIGHT_LOCATION = 15.0
WEIGHT_EMPLOYER = 15.0

# Пороги
THRESHOLD_HIGH = 95.0
THRESHOLD_MEDIUM = 85.0


def _normalize_name(name: str) -> str:
    """Нормализовать ФИО: lowercase, trim, схлопнуть пробелы."""
    return " ".join(name.lower().split())


def _normalize_text(text: str) -> str:
    """Нормализовать текст: lowercase, trim."""
    return text.strip().lower()


def _string_similarity(a: str, b: str) -> float:
    """Сходство строк 0..1 (SequenceMatcher)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _extract_birth_year(candidate: Candidate) -> int | None:
    """Извлечь год рождения из headline или skills (упрощённо).

    В реальной системе — из CandidateFact(experience) или отдельного поля.
    Здесь — эвристика: ищем 4-значное число 1940..2010 в headline.
    """
    import re

    text = f"{candidate.headline} {candidate.location}"
    matches = re.findall(r"\b(19[4-9]\d|200\d|201\d)\b", text)
    return int(matches[0]) if matches else None


def _extract_employer(candidate: Candidate) -> str:
    """Извлечь текущего работодателя из headline (упрощённо)."""
    # В реальной системе — из CandidateFact(experience, latest).
    return candidate.headline


def score_pair(a: Candidate, b: Candidate) -> tuple[float, list[str]]:
    """Вычислить fuzzy-скор пары кандидатов (0..100).

    Returns:
        (score, matched_fields) — скор и список совпавших полей.
    """
    score = 0.0
    matched: list[str] = []

    # ФИО (вес 50)
    name_a = _normalize_name(a.full_name)
    name_b = _normalize_name(b.full_name)
    name_sim = _string_similarity(name_a, name_b)
    name_points = name_sim * WEIGHT_FULL_NAME
    score += name_points
    if name_sim >= 0.85:
        matched.append("full_name")

    # Год рождения (вес 20)
    year_a = _extract_birth_year(a)
    year_b = _extract_birth_year(b)
    if year_a is not None and year_b is not None and year_a == year_b:
        score += WEIGHT_BIRTH_YEAR
        matched.append("birth_year")
    elif year_a is not None and year_b is not None and year_a != year_b:
        # Разные годы рождения — сильный сигнал против дубликата
        score -= WEIGHT_BIRTH_YEAR * 0.5

    # Город (вес 15)
    loc_a = _normalize_text(a.location)
    loc_b = _normalize_text(b.location)
    if loc_a and loc_b and loc_a == loc_b:
        score += WEIGHT_LOCATION
        matched.append("location")

    # Работодатель (вес 15)
    emp_a = _normalize_text(_extract_employer(a))
    emp_b = _normalize_text(_extract_employer(b))
    if emp_a and emp_b:
        emp_sim = _string_similarity(emp_a, emp_b)
        emp_points = emp_sim * WEIGHT_EMPLOYER
        score += emp_points
        if emp_sim >= 0.85:
            matched.append("employer")

    return min(max(score, 0.0), 100.0), matched


def classify_score(score: float) -> DuplicateConfidence:
    """Классифицировать скор в уровень уверенности."""
    if score >= THRESHOLD_HIGH:
        return DuplicateConfidence.HIGH
    if score >= THRESHOLD_MEDIUM:
        return DuplicateConfidence.MEDIUM
    return DuplicateConfidence.LOW


def find_fuzzy_duplicates(
    candidates: list[Candidate],
    threshold: float = THRESHOLD_MEDIUM,
) -> list[DuplicateMatch]:
    """Найти все fuzzy-дубликаты среди списка кандидатов.

    Сравнивает все пары (O(n²)), возвращает пары со скором >= threshold.
    Выживший (survivor) — старший по created_at.
    """
    matches: list[DuplicateMatch] = []
    n = len(candidates)
    for i in range(n):
        for j in range(i + 1, n):
            a = candidates[i]
            b = candidates[j]
            score, matched = score_pair(a, b)
            if score >= threshold:
                # Survivor — старший по дате создания
                if a.created_at <= b.created_at:
                    survivor, duplicate = a, b
                else:
                    survivor, duplicate = b, a
                matches.append(
                    DuplicateMatch(
                        survivor_id=survivor.id.value,
                        duplicate_id=duplicate.id.value,
                        confidence=classify_score(score),
                        score=score,
                        matched_fields=matched,
                    )
                )
    return matches
