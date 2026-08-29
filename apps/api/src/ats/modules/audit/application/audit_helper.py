"""Хелпер audit() — удобная запись в журнал аудита из use cases (JUGO-033).

УСТОЙЧИВОСТЬ: ошибки записи аудита не прерывают бизнес-логику (best-effort).
WHITEBOX AI: action/entity_type/entity_id — структурированные, для поиска.
SECURE FIRST: trace_id автоматически берётся из contextvars (JUGO-030).

Использование:
    from ats.modules.audit.application.audit_helper import audit

    await audit(
        logger=container.audit_logger,
        tenant_id=tenant_id,
        action="vacancy.create",
        entity_type="vacancy",
        entity_id=str(vacancy.id),
        actor_id=user_id,
        details={"title": vacancy.title},
    )
"""

from __future__ import annotations

import logging
from uuid import UUID

from ats.infra.logging.context import get_log_context
from ats.infra.tracing.context import get_current_trace_id
from ats.modules.audit.domain.audit import AuditEntry
from ats.modules.audit.ports.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


async def audit(
    *,
    logger_instance: AuditLogger,
    tenant_id: UUID,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_id: UUID | None = None,
    details: dict[str, object] | None = None,
    ip_address: str = "",
    user_agent: str = "",
    trace_id: str | None = None,
) -> AuditEntry:
    """Записать действие в журнал аудита.

    Args:
        logger_instance: AuditLogger (из контейнера).
        tenant_id: ID тенанта.
        action: действие (напр. "vacancy.create", "candidate.contacts.read").
        entity_type: тип сущности (напр. "vacancy", "candidate").
        entity_id: ID сущности.
        actor_id: ID пользователя (None для system).
        details: детали (до/после, контекст).
        ip_address: IP субъекта.
        user_agent: User-Agent субъекта.
        trace_id: trace_id (если None — берётся из contextvars).

    Returns:
        Созданная AuditEntry.
    """
    # Автоматически получить trace_id из contextvars (JUGO-030)
    if trace_id is None:
        trace_id = get_current_trace_id() or get_log_context("trace_id") or ""

    entry = AuditEntry.create(
        tenant_id=tenant_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
        trace_id=trace_id,
    )

    try:
        await logger_instance.log(entry)
    except Exception:
        # УСТОЙЧИВОСТЬ: ошибки аудита не прерывают бизнес-логику
        logger.exception("Failed to write audit log: %s on %s:%s", action, entity_type, entity_id)

    return entry


# Predefined actions для консистентности (SECURE FIRST: стандартизированные имена)
class AuditActions:
    """Стандартные имена действий аудита (dot.notation)."""

    # Vacancy
    VACANCY_CREATE = "vacancy.create"
    VACANCY_UPDATE = "vacancy.update"
    VACANCY_PUBLISH = "vacancy.publish"
    VACANCY_CLOSE = "vacancy.close"
    VACANCY_DELETE = "vacancy.delete"

    # Candidate
    CANDIDATE_CREATE = "candidate.create"
    CANDIDATE_UPDATE = "candidate.update"
    CANDIDATE_DELETE = "candidate.delete"
    CANDIDATE_CONTACTS_READ = "candidate.contacts.read"  # SECURE FIRST: чтение ПД
    CANDIDATE_RESUME_UPLOAD = "candidate.resume.upload"

    # Application
    APPLICATION_CREATE = "application.create"
    APPLICATION_MOVE = "application.move"
    APPLICATION_REJECT = "application.reject"
    APPLICATION_HIRE = "application.hire"

    # AI
    AI_SCREENING_GENERATE = "ai.screening.generate"
    AI_RESUME_PARSE = "ai.resume.parse"
    AI_EMBEDDING_GENERATE = "ai.embedding.generate"

    # Auth
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_LOGIN_FAILED = "auth.login.failed"
    AUTH_2FA_ENABLE = "auth.2fa.enable"
    AUTH_2FA_VERIFY = "auth.2fa.verify"

    # System
    SYSTEM_TENANT_CREATE = "system.tenant.create"
    SYSTEM_USER_INVITE = "system.user.invite"
    SYSTEM_USER_ROLE_CHANGE = "system.user.role.change"
