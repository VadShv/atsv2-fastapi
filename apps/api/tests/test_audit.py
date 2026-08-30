"""Тесты audit_log: партиционирование + хелпер чтений (JUGO-033).

Проверяют:
- AuditEntry.create: создание immutable записи
- audit() helper: запись с автоматическим trace_id из contextvars
- AuditActions: стандартные имена действий
- InMemoryAuditReader: фильтрация по всем параметрам
- InMemoryAuditReader: пагинация (limit/offset)
- InMemoryAuditReader: count()
- AuditQuery: defaults и фильтры
- Append-only: InMemoryAuditLogger только добавляет
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.logging.context import clear_context, set_context
from ats.modules.audit.application.audit_helper import AuditActions, audit
from ats.modules.audit.domain.audit import AuditEntry
from ats.modules.audit.infra.in_memory_audit_logger import InMemoryAuditLogger
from ats.modules.audit.infra.in_memory_audit_reader import InMemoryAuditReader
from ats.modules.audit.ports.audit_reader import AuditQuery


def _make_entry(
    *,
    tenant_id: UUID,
    action: str = "test",
    entity_type: str = "test",
    entity_id: str = "1",
    actor_id: UUID | None = None,
    trace_id: str = "",
    created_at: datetime | None = None,
) -> AuditEntry:
    """Создать AuditEntry напрямую (с указанием created_at)."""
    return AuditEntry(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details={},
        ip_address="",
        user_agent="",
        trace_id=trace_id,
        created_at=created_at or datetime.now(UTC),
    )


# --- AuditEntry ---


class TestAuditEntry:
    def test_create_entry(self) -> None:
        tenant_id = uuid4()
        entry = AuditEntry.create(
            tenant_id=tenant_id,
            action="vacancy.create",
            entity_type="vacancy",
            entity_id="vac-123",
        )
        assert entry.tenant_id == tenant_id
        assert entry.action == "vacancy.create"
        assert entry.entity_type == "vacancy"
        assert entry.entity_id == "vac-123"
        assert entry.details == {}
        assert entry.trace_id == ""
        assert entry.created_at is not None

    def test_create_entry_with_all_fields(self) -> None:
        tenant_id = uuid4()
        actor_id = uuid4()
        entry = AuditEntry.create(
            tenant_id=tenant_id,
            action="candidate.contacts.read",
            entity_type="candidate",
            entity_id="cand-456",
            actor_id=actor_id,
            details={"field": "phone"},
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            trace_id="trace-abc",
        )
        assert entry.actor_id == actor_id
        assert entry.details == {"field": "phone"}
        assert entry.ip_address == "192.168.1.1"
        assert entry.user_agent == "Mozilla/5.0"
        assert entry.trace_id == "trace-abc"

    def test_entry_is_immutable(self) -> None:
        """AuditEntry — frozen dataclass (immutable)."""
        entry = AuditEntry.create(
            tenant_id=uuid4(),
            action="test",
            entity_type="test",
            entity_id="1",
        )
        with pytest.raises(AttributeError):
            entry.action = "modified"  # type: ignore[misc]

    def test_entry_has_unique_id(self) -> None:
        e1 = AuditEntry.create(tenant_id=uuid4(), action="a", entity_type="b", entity_id="1")
        e2 = AuditEntry.create(tenant_id=uuid4(), action="a", entity_type="b", entity_id="1")
        assert e1.id != e2.id


# --- audit() helper ---


class TestAuditHelper:
    async def test_audit_writes_entry(self) -> None:
        """audit() записывает entry через logger."""
        logger = InMemoryAuditLogger()
        tenant_id = uuid4()

        entry = await audit(
            logger_instance=logger,
            tenant_id=tenant_id,
            action="vacancy.create",
            entity_type="vacancy",
            entity_id="vac-1",
        )
        assert entry.action == "vacancy.create"
        assert len(logger._entries) == 1
        assert logger._entries[0].action == "vacancy.create"

    async def test_audit_auto_trace_id_from_contextvars(self) -> None:
        """audit() автоматически берёт trace_id из contextvars."""
        clear_context()
        set_context(trace_id="ctx-trace-123")

        logger = InMemoryAuditLogger()
        entry = await audit(
            logger_instance=logger,
            tenant_id=uuid4(),
            action="test",
            entity_type="test",
            entity_id="1",
        )
        assert entry.trace_id == "ctx-trace-123"
        clear_context()

    async def test_audit_explicit_trace_id_overrides(self) -> None:
        """Явный trace_id имеет приоритет над contextvars."""
        clear_context()
        set_context(trace_id="ctx-trace")

        logger = InMemoryAuditLogger()
        entry = await audit(
            logger_instance=logger,
            tenant_id=uuid4(),
            action="test",
            entity_type="test",
            entity_id="1",
            trace_id="explicit-trace",
        )
        assert entry.trace_id == "explicit-trace"
        clear_context()

    async def test_audit_does_not_raise_on_logger_error(self) -> None:
        """audit() не падает, если logger выбрасывает исключение (УСТОЙЧИВОСТЬ)."""

        class FailingLogger(InMemoryAuditLogger):
            async def log(self, entry: AuditEntry) -> None:
                raise RuntimeError("DB connection failed")

        logger = FailingLogger()
        entry = await audit(
            logger_instance=logger,
            tenant_id=uuid4(),
            action="test",
            entity_type="test",
            entity_id="1",
        )
        # Entry всё равно возвращается
        assert entry.action == "test"


# --- AuditActions ---


class TestAuditActions:
    def test_actions_are_strings(self) -> None:
        assert AuditActions.VACANCY_CREATE == "vacancy.create"
        assert AuditActions.CANDIDATE_CONTACTS_READ == "candidate.contacts.read"
        assert AuditActions.AUTH_LOGIN == "auth.login"

    def test_sensitive_actions_exist(self) -> None:
        """SECURE FIRST: действия чтения ПД определены."""
        assert hasattr(AuditActions, "CANDIDATE_CONTACTS_READ")
        assert "contacts.read" in AuditActions.CANDIDATE_CONTACTS_READ

    def test_ai_actions_exist(self) -> None:
        assert hasattr(AuditActions, "AI_SCREENING_GENERATE")
        assert hasattr(AuditActions, "AI_RESUME_PARSE")


# --- InMemoryAuditReader ---


class TestInMemoryAuditReader:
    def _make_entries(self, tenant_id: UUID, count: int = 5) -> list[AuditEntry]:
        entries = []
        for i in range(count):
            entry = _make_entry(
                tenant_id=tenant_id,
                action=f"action.{i}",
                entity_type="test",
                entity_id=str(i),
                trace_id=f"trace-{i}",
                created_at=datetime(2026, 8, 1 + i, tzinfo=UTC),
            )
            entries.append(entry)
        return entries

    async def test_query_by_tenant(self) -> None:
        tenant_id = uuid4()
        other_tenant = uuid4()
        entries = self._make_entries(tenant_id, 3)
        entries.append(
            _make_entry(
                tenant_id=other_tenant,
                action="other",
                entity_type="x",
                entity_id="1",
            )
        )
        reader = InMemoryAuditReader(entries)
        result = await reader.query(AuditQuery(tenant_id=tenant_id))
        assert len(result) == 3
        assert all(e.tenant_id == tenant_id for e in result)

    async def test_query_by_action(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        result = await reader.query(AuditQuery(tenant_id=tenant_id, action="action.2"))
        assert len(result) == 1
        assert result[0].action == "action.2"

    async def test_query_by_entity(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        result = await reader.query(
            AuditQuery(tenant_id=tenant_id, entity_type="test", entity_id="3")
        )
        assert len(result) == 1
        assert result[0].entity_id == "3"

    async def test_query_by_trace_id(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        result = await reader.query(AuditQuery(tenant_id=tenant_id, trace_id="trace-1"))
        assert len(result) == 1
        assert result[0].trace_id == "trace-1"

    async def test_query_by_date_range(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        result = await reader.query(
            AuditQuery(
                tenant_id=tenant_id,
                date_from=datetime(2026, 8, 2, tzinfo=UTC),
                date_to=datetime(2026, 8, 4, tzinfo=UTC),
            )
        )
        assert len(result) == 3  # Aug 2, 3, 4

    async def test_query_sorted_desc(self) -> None:
        """Результаты отсортированы по created_at DESC (newest first)."""
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        result = await reader.query(AuditQuery(tenant_id=tenant_id))
        assert result[0].created_at > result[-1].created_at

    async def test_query_pagination(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 10)
        reader = InMemoryAuditReader(entries)
        page1 = await reader.query(AuditQuery(tenant_id=tenant_id, limit=3, offset=0))
        page2 = await reader.query(AuditQuery(tenant_id=tenant_id, limit=3, offset=3))
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].id != page2[0].id

    async def test_query_empty_result(self) -> None:
        tenant_id = uuid4()
        reader = InMemoryAuditReader([])
        result = await reader.query(AuditQuery(tenant_id=tenant_id))
        assert result == []

    async def test_count(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        count = await reader.count(AuditQuery(tenant_id=tenant_id))
        assert count == 5

    async def test_count_with_filter(self) -> None:
        tenant_id = uuid4()
        entries = self._make_entries(tenant_id, 5)
        reader = InMemoryAuditReader(entries)
        count = await reader.count(AuditQuery(tenant_id=tenant_id, action="action.2"))
        assert count == 1


# --- AuditQuery defaults ---


class TestAuditQuery:
    def test_defaults(self) -> None:
        q = AuditQuery(tenant_id=uuid4())
        assert q.limit == 100
        assert q.offset == 0
        assert q.actor_id is None
        assert q.action is None

    def test_custom_values(self) -> None:
        tenant_id = uuid4()
        actor_id = uuid4()
        q = AuditQuery(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="vacancy.create",
            limit=50,
            offset=100,
        )
        assert q.actor_id == actor_id
        assert q.action == "vacancy.create"
        assert q.limit == 50
        assert q.offset == 100


# --- Append-only InMemoryAuditLogger ---


class TestAppendOnly:
    async def test_logger_only_appends(self) -> None:
        """InMemoryAuditLogger только добавляет, не изменяет."""
        logger = InMemoryAuditLogger()
        e1 = AuditEntry.create(tenant_id=uuid4(), action="a", entity_type="b", entity_id="1")
        e2 = AuditEntry.create(tenant_id=uuid4(), action="c", entity_type="d", entity_id="2")
        await logger.log(e1)
        await logger.log(e2)
        assert len(logger._entries) == 2
        assert logger._entries[0] == e1
        assert logger._entries[1] == e2
