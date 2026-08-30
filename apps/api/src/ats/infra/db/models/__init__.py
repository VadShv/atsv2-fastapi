"""Все ORM-модели. Импорт этого модуля регистрирует метаданные для Alembic."""

from ats.infra.db.models.ai_core import ProvenanceORM
from ats.infra.db.models.applications import ApplicationORM
from ats.infra.db.models.candidates import CandidateORM, CandidateSearchORM
from ats.infra.db.models.comment_threads import CommentThreadORM
from ats.infra.db.models.events import AuditLogORM, OutboxMessageORM
from ats.infra.db.models.identity import Role, Tenant, User
from ats.infra.db.models.recruitment import PipelineStageORM, VacancyORM

__all__ = [
    "ApplicationORM",
    "AuditLogORM",
    "CandidateORM",
    "CandidateSearchORM",
    "CommentThreadORM",
    "OutboxMessageORM",
    "PipelineStageORM",
    "ProvenanceORM",
    "Role",
    "Tenant",
    "User",
    "VacancyORM",
]
