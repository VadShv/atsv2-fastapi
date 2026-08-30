"""Домен дедупликации кандидатов (JUGO-150..155, ТЗ §5.4).

Архитектура дедупликации:
1. Точные проверки: HMAC-SHA256 хэши контактов (email/phone) → точное совпадение.
2. Нечёткий скоринг: ФИО + год рождения + город + работодатель → пороги 85–94 / 95+.
3. Фоновый поиск: воркер находит пары-кандидаты на разбор.
4. Мердж: жёсткое объединение с мягким удалением, merge_log со снапшотом, откат 30 дней.
5. Автомердж: только точные совпадения контактов без активных откликов (фича-флаг).

WHITEBOX AI: неопределённые пары (85–94) может арбитрировать ИИ (dedup_arbiter).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from ats.shared.aggregate import AggregateRoot
from ats.shared.events import DomainEvent
from ats.shared.ids import CandidateId, TenantId, UserId

# Окно отката мерджа (ТЗ §5.4: 30 дней)
MERGE_ROLLBACK_WINDOW = timedelta(days=30)

# Секрет для HMAC-хэширования контактов (в prod — из настроек/env)
_DEFAULT_HMAC_KEY = b"ats-jugo-dedup-hmac-key-v1"


def get_hmac_key() -> bytes:
    """Получить ключ HMAC для хэширования контактов."""
    import os

    return os.getenv("ATS_DEDUP_HMAC_KEY", "").encode() or _DEFAULT_HMAC_KEY


class ContactKind(StrEnum):
    """Тип контакта (ТЗ §5.1: candidate_contacts.kind)."""

    PHONE = "phone"
    EMAIL = "email"
    TELEGRAM = "telegram"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    OTHER = "other"


class DuplicateConfidence(StrEnum):
    """Уровень уверенности в дубликате (ТЗ §5.4)."""

    EXACT = "exact"  # точное совпадение по контактам
    HIGH = "high"  # fuzzy >= 95 — требование подтверждения
    MEDIUM = "medium"  # fuzzy 85–94 — мягкое предупреждение
    LOW = "low"  # fuzzy < 85


class MergeStatus(StrEnum):
    """Статус записи в merge_log."""

    MERGED = "merged"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class CandidateMerged(DomainEvent):
    """Событие: кандидаты объединены (ТЗ: candidate.merged)."""

    survivor_id: UUID = field(default_factory=uuid4)
    absorbed_id: UUID = field(default_factory=uuid4)
    merge_log_id: UUID = field(default_factory=uuid4)
    merged_by: UUID | None = None


@dataclass(frozen=True)
class MergeRolledBack(DomainEvent):
    """Событие: мердж отменён."""

    merge_log_id: UUID = field(default_factory=uuid4)
    survivor_id: UUID = field(default_factory=uuid4)
    absorbed_id: UUID = field(default_factory=uuid4)


# ---------------------------------------------------------------------------
# Contact Hash (JUGO-150)
# ---------------------------------------------------------------------------


def normalize_contact(kind: ContactKind, value: str) -> str:
    """Нормализовать значение контакта перед хэшированием.

    Телефоны: только цифры (убираем +, пробелы, скобки, дефисы).
    Email: lowercase, trim.
    Прочие: lowercase, trim.
    """
    v = value.strip()
    if kind == ContactKind.PHONE:
        return "".join(c for c in v if c.isdigit())
    return v.lower()


def hash_contact(kind: ContactKind, value: str, key: bytes | None = None) -> str:
    """Вычислить HMAC-SHA256 хэш контакта для точного поиска/дедупа.

    ТЗ §5.1: value_hash = HMAC-SHA256 для точного поиска/дедупа.
    HMAC (а не обычный хэш) — для защиты от радужных таблиц.
    """
    secret = key or get_hmac_key()
    normalized = normalize_contact(kind, value)
    return hmac.new(secret, normalized.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ContactHash:
    """Хэш контакта кандидата для дедупликации.

    value_encrypted хранится отдельно (PII-vault), здесь — только хэш для поиска.
    """

    candidate_id: UUID
    tenant_id: UUID
    kind: ContactKind
    value_hash: str
    is_primary: bool = False


# ---------------------------------------------------------------------------
# Duplicate Match (JUGO-151)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateMatch:
    """Найденная пара-дубль кандидатов."""

    survivor_id: UUID  # предлагаемый «выживший» (обычно — старший по дате)
    duplicate_id: UUID  # предлагаемый «поглощаемый»
    confidence: DuplicateConfidence
    score: float  # 0..100
    matched_fields: list[str] = field(default_factory=list)
    # matched_fields: ["email", "phone", "full_name", "birth_year", ...]


# ---------------------------------------------------------------------------
# Merge Log (JUGO-152, JUGO-153)
# ---------------------------------------------------------------------------


@dataclass
class MergeLog(AggregateRoot):
    """Журнал объединения дублей (ТЗ §5.4: merge_log со снапшотом).

    Хранит:
    - survivor_id: кандидат, который остаётся (поглощает данные).
    - absorbed_id: кандидат, который мягко удаляется.
    - snapshot: JSON-снапшот состояния обоих кандидатов до мерджа.
    - expires_at: окно отката (30 дней), после — мердж необратим.
    - status: merged / rolled_back.
    """

    id: UUID
    tenant_id: TenantId
    survivor_id: CandidateId
    absorbed_id: CandidateId
    merged_by: UserId | None
    snapshot: str  # JSON-снапшот: {survivor: {...}, absorbed: {...}, transferred: [...]}
    status: MergeStatus = MergeStatus.MERGED
    merged_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    rolled_back_at: datetime | None = None
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + MERGE_ROLLBACK_WINDOW)
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        tenant_id: TenantId,
        survivor_id: CandidateId,
        absorbed_id: CandidateId,
        snapshot: dict,
        merged_by: UserId | None = None,
    ) -> MergeLog:
        log = cls(
            id=uuid4(),
            tenant_id=tenant_id,
            survivor_id=survivor_id,
            absorbed_id=absorbed_id,
            merged_by=merged_by,
            snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
        )
        log._record(
            CandidateMerged(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=tenant_id.value,
                payload={
                    "survivor_id": str(survivor_id.value),
                    "absorbed_id": str(absorbed_id.value),
                    "merge_log_id": str(log.id),
                },
                survivor_id=survivor_id.value,
                absorbed_id=absorbed_id.value,
                merge_log_id=log.id,
                merged_by=merged_by.value if merged_by else None,
            )
        )
        return log

    @property
    def is_rollbackable(self) -> bool:
        """Можно ли откатить мердж (в пределах окна 30 дней и ещё не откачен)."""
        if self.status != MergeStatus.MERGED:
            return False
        return datetime.now(UTC) < self.expires_at

    def rollback(self) -> None:
        """Откатить мердж. Бросает ValueError если окно истекло или уже откачен."""
        if self.status == MergeStatus.ROLLED_BACK:
            raise ValueError("Мердж уже откачен")
        if not self.is_rollbackable:
            raise ValueError("Окно отката истекло (30 дней)")
        self.status = MergeStatus.ROLLED_BACK
        self.rolled_back_at = datetime.now(UTC)
        self._record(
            MergeRolledBack(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                tenant_id=self.tenant_id.value,
                payload={
                    "merge_log_id": str(self.id),
                    "survivor_id": str(self.survivor_id.value),
                    "absorbed_id": str(self.absorbed_id.value),
                },
                merge_log_id=self.id,
                survivor_id=self.survivor_id.value,
                absorbed_id=self.absorbed_id.value,
            )
        )

    def get_snapshot(self) -> dict:
        """Десериализовать JSON-снапшот."""
        return json.loads(self.snapshot)
