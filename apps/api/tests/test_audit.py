"""Тесты модуля аудита: доменная модель, InMemoryAuditLogger, helper."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ats.modules.audit.domain.audit import AuditEntry
from ats.modules.audit.infra.in_memory_audit_logger import InMemoryAuditLogger


def test_audit_entry_create():
    tenant_id = uuid4()
    actor_id = uuid4()
    entry = AuditEntry.create(
        tenant_id=tenant_id,
        action="vacancy.create",
        entity_type="vacancy",
        entity_id="v-1",
        actor_id=actor_id,
        details={"title": "Backend"},
        ip_address="10.0.0.1",
        user_agent="Mozilla/5.0",
        trace_id="trace-abc",
    )
    assert entry.action == "vacancy.create"
    assert entry.entity_type == "vacancy"
    assert entry.entity_id == "v-1"
    assert entry.actor_id == actor_id
    assert entry.ip_address == "10.0.0.1"
    assert entry.trace_id == "trace-abc"
    assert entry.details == {"title": "Backend"}


def test_audit_entry_defaults():
    entry = AuditEntry.create(
        tenant_id=uuid4(),
        action="candidate.contacts.read",
        entity_type="candidate",
        entity_id="c-1",
    )
    assert entry.actor_id is None
    assert entry.ip_address == ""
    assert entry.trace_id == ""
    assert entry.details == {}


@pytest.mark.asyncio
async def test_in_memory_audit_logger_stores_entries():
    logger = InMemoryAuditLogger()
    entry = AuditEntry.create(
        tenant_id=uuid4(),
        action="vacancy.create",
        entity_type="vacancy",
        entity_id="v-1",
    )
    await logger.log(entry)
    assert len(logger.entries) == 1
    assert logger.entries[0] is entry


@pytest.mark.asyncio
async def test_in_memory_audit_logger_clear():
    logger = InMemoryAuditLogger()
    await logger.log(
        AuditEntry.create(
            tenant_id=uuid4(), action="x", entity_type="y", entity_id="z"
        )
    )
    assert len(logger.entries) == 1
    logger.clear()
    assert len(logger.entries) == 0


def test_audit_logger_protocol():
    """InMemoryAuditLogger соответствует порту AuditLogger (runtime_checkable)."""
    from ats.modules.audit.ports.audit_logger import AuditLogger

    logger = InMemoryAuditLogger()
    assert isinstance(logger, AuditLogger)
