"""Use case: агрегированный таймлайн заявки (JUGO-144).

Объединяет переходы, решения, комментарии и ИИ-события в единую ленту
для карточки кандидата. Сортировка по времени (хронологическая).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ats.modules.recruitment.ports.application_repository import ApplicationRepository
from ats.modules.recruitment.ports.comment_repository import CommentRepository
from ats.shared.ids import TenantId
from ats.shared.result import ErrorCode, Result

logger = logging.getLogger(__name__)


@dataclass
class TimelineEntry:
    """Запись в таймлайне заявки."""

    event_type: str  # transition, comment, decision, ai_event, rejection
    timestamp: datetime
    title: str
    description: str = ""
    actor: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApplicationTimeline:
    """Агрегированная лента событий заявки (JUGO-144)."""

    application_id: UUID
    entries: list[TimelineEntry] = field(default_factory=list)

    @property
    def sorted_entries(self) -> list[TimelineEntry]:
        """Хронологически отсортированные записи (новые — последние)."""
        return sorted(self.entries, key=lambda e: e.timestamp)


class ApplicationTimelineUseCase:
    """Построить таймлайн заявки (JUGO-144)."""

    def __init__(
        self,
        applications: ApplicationRepository,
        comments: CommentRepository,
    ) -> None:
        self._applications = applications
        self._comments = comments

    async def execute(
        self, tenant_id: TenantId, application_id: UUID
    ) -> Result[ApplicationTimeline]:
        app = await self._applications.get(tenant_id, application_id)
        if app is None:
            return Result.err(
                ErrorCode.NOT_FOUND,
                "Заявка не найдена",
                {"application_id": str(application_id)},
            )

        timeline = ApplicationTimeline(application_id=application_id)

        # 1. Создание заявки
        timeline.entries.append(
            TimelineEntry(
                event_type="created",
                timestamp=app.created_at,
                title="Заявка создана",
                description=f"Кандидат подан на вакансию (origin: {app.origin.value})",
                actor="system",
                metadata={"origin": app.origin.value, "stage": app.stage.value},
            )
        )

        # 2. Переходы по стадиям
        for transition in app.transitions:
            ai_note = " (AI-инициирован)" if transition.ai_provenance else ""
            timeline.entries.append(
                TimelineEntry(
                    event_type="transition",
                    timestamp=transition.at,
                    title=f"Переход: {transition.from_stage.value} → {transition.to_stage.value}",
                    description=transition.reason or "Без указания причины" + ai_note,
                    actor="ai_agent" if transition.ai_provenance else "user",
                    metadata={
                        "from_stage": transition.from_stage.value,
                        "to_stage": transition.to_stage.value,
                        "ai_provenance": str(transition.ai_provenance)
                        if transition.ai_provenance
                        else None,
                    },
                )
            )

        # 3. Отклонение (если есть)
        if app.is_rejected and app.rejection_reason_code:
            timeline.entries.append(
                TimelineEntry(
                    event_type="rejection",
                    timestamp=app.updated_at,
                    title=f"Отклонено: {app.rejection_reason_label or app.rejection_reason_code}",
                    description=f"Причина: {app.rejection_reason_code}",
                    actor="user",
                    metadata={
                        "reason_code": app.rejection_reason_code,
                        "reason_label": app.rejection_reason_label,
                    },
                )
            )

        # 4. AI-скрининг (если есть)
        if app.score is not None:
            timeline.entries.append(
                TimelineEntry(
                    event_type="ai_event",
                    timestamp=app.updated_at,
                    title=f"AI-скрининг: score={app.score:.2f}",
                    description=f"Уровень риска: {app.risk_level.value}",
                    actor="ai_agent",
                    metadata={
                        "score": app.score,
                        "risk_level": app.risk_level.value,
                        "provenance": str(app.score_provenance) if app.score_provenance else None,
                    },
                )
            )

        # 5. Комментарии
        threads = await self._comments.list_by_application(tenant_id, application_id)
        for thread in threads:
            for comment in thread.comments:
                visibility = "приватный" if comment.is_private else "публичный"
                timeline.entries.append(
                    TimelineEntry(
                        event_type="comment",
                        timestamp=comment.created_at,
                        title=f"Комментарий ({visibility})",
                        description=comment.body[:200],
                        actor=str(comment.author_id.value),
                        metadata={
                            "thread_id": str(comment.thread_id),
                            "comment_id": str(comment.id),
                            "mentions": comment.mentions,
                            "is_private": comment.is_private,
                        },
                    )
                )

        logger.info(
            "Timeline built: application=%s entries=%d",
            application_id,
            len(timeline.entries),
        )
        return Result.ok(timeline)
