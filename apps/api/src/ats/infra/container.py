"""DI-контейнер: сборка графа зависимостей.

В dev-режиме (ATS_STUB_MODE=1) использует in-memory/stub адаптеры.
В prod — реальные адаптеры (Postgres, LiteLLM, Redis).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ats.infra.events.bus import InProcessEventBus
from ats.infra.search.in_memory_search_engine import InMemorySearchEngine
from ats.infra.stubs import (
    InMemoryProvenanceLedger,
    InMemoryVacancyRepository,
    StubAIGateway,
)
from ats.infra.stubs_dedup import InMemoryDedupRepository
from ats.infra.stubs_funnel_repositories import (
    InMemoryFunnelPresetRepository,
    InMemoryFunnelSnapshotRepository,
    InMemoryHMDecisionRepository,
    InMemoryStageTransitionRepository,
)
from ats.infra.stubs_org import (
    InMemoryLegalEntityRepository,
    InMemoryOrgUnitRepository,
)
from ats.infra.stubs_repositories import (
    InMemoryApplicationRepository,
    InMemoryCandidateRepository,
    InMemoryCommentRepository,
)
from ats.infra.stubs_requirement_set_repository import (
    InMemoryRequirementSetRepository,
)
from ats.infra.stubs_resume_repository import InMemoryResumeRepository
from ats.infra.stubs_search import InMemorySynonymRepository
from ats.infra.stubs_webhooks import (
    InMemoryWebhookDeliveryRepository,
    InMemoryWebhookSubscriptionRepository,
)
from ats.modules.ai_core.domain.gateway import AIGateway
from ats.modules.ai_core.ports.provenance import ProvenanceLedger
from ats.modules.ai_core.skills.generate_screening_criteria import (
    GenerateScreeningCriteria,
)
from ats.modules.ai_core.skills.parse_resume import ParseResume
from ats.modules.audit.infra.in_memory_audit_logger import InMemoryAuditLogger
from ats.modules.audit.infra.in_memory_audit_reader import InMemoryAuditReader
from ats.modules.audit.ports.audit_logger import AuditLogger
from ats.modules.audit.ports.audit_reader import AuditReader
from ats.modules.candidates.application.candidate_crud import (
    BulkImportCandidatesUseCase,
    CandidateCrudUseCase,
)
from ats.modules.candidates.application.dedup_use_cases import DedupUseCase
from ats.modules.candidates.application.upload_candidate_resume import (
    UploadCandidateResumeUseCase,
)
from ats.modules.candidates.application.upload_resume import UploadResumeUseCase
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.candidates.ports.dedup_repository import DedupRepository
from ats.modules.candidates.ports.resume_repository import ResumeRepository
from ats.modules.funnel.application.funnel_use_cases import (
    FunnelPresetUseCase,
    FunnelTransitionUseCase,
    HMDecisionUseCase,
)
from ats.modules.funnel.ports.funnel_preset_repository import (
    FunnelPresetRepository,
)
from ats.modules.funnel.ports.funnel_snapshot_repository import (
    FunnelSnapshotRepository,
)
from ats.modules.funnel.ports.funnel_transition_repository import (
    HMDecisionRepository,
    StageTransitionRepository,
)
from ats.modules.organization.application.org_use_cases import (
    LegalEntityUseCase,
    OrgUnitUseCase,
)
from ats.modules.organization.ports import (
    LegalEntityRepository,
    OrgUnitRepository,
)
from ats.modules.recruitment.application.application_timeline import (
    ApplicationTimelineUseCase,
)
from ats.modules.recruitment.application.comment_use_case import CommentUseCase
from ats.modules.recruitment.application.create_application import (
    CreateApplicationUseCase,
)
from ats.modules.recruitment.application.create_vacancy import CreateVacancyUseCase
from ats.modules.recruitment.application.manage_requirement_sets import (
    RequirementSetUseCase,
)
from ats.modules.recruitment.application.move_application import (
    MoveApplicationUseCase,
)
from ats.modules.recruitment.application.reject_application import (
    RejectApplicationUseCase,
)
from ats.modules.recruitment.application.vacancy_crud import VacancyCrudUseCase
from ats.modules.recruitment.ports.application_repository import (
    ApplicationRepository,
)
from ats.modules.recruitment.ports.comment_repository import CommentRepository
from ats.modules.recruitment.ports.requirement_set_repository import (
    RequirementSetRepository,
)
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.modules.search.application.search_candidates import SearchCandidatesUseCase
from ats.modules.search.ports.search_engine import SearchEngine
from ats.modules.search.ports.synonym_repository import SynonymRepository
from ats.modules.webhooks.application.webhook_use_cases import (
    WebhookDispatcher,
    WebhookManagementUseCase,
)
from ats.modules.webhooks.ports.webhook_repository import (
    WebhookDeliveryRepository,
    WebhookSubscriptionRepository,
)


@dataclass
class Container:
    """Граф зависимостей приложения."""

    vacancy_repository: VacancyRepository
    candidate_repository: CandidateRepository
    application_repository: ApplicationRepository
    resume_repository: ResumeRepository
    requirement_set_repository: RequirementSetRepository
    funnel_preset_repository: FunnelPresetRepository
    funnel_snapshot_repository: FunnelSnapshotRepository
    stage_transition_repository: StageTransitionRepository
    hm_decision_repository: HMDecisionRepository
    provenance_ledger: ProvenanceLedger
    ai_gateway: AIGateway
    search_engine: SearchEngine
    synonym_repository: SynonymRepository
    audit_logger: AuditLogger
    audit_reader: AuditReader
    event_bus: InProcessEventBus
    webhook_subscription_repository: WebhookSubscriptionRepository
    webhook_delivery_repository: WebhookDeliveryRepository
    webhook_management: WebhookManagementUseCase
    webhook_dispatcher: WebhookDispatcher
    create_vacancy: CreateVacancyUseCase
    vacancy_crud: VacancyCrudUseCase
    requirement_set_use_case: RequirementSetUseCase
    funnel_preset_use_case: FunnelPresetUseCase
    funnel_transition_use_case: FunnelTransitionUseCase
    hm_decision_use_case: HMDecisionUseCase
    create_application: CreateApplicationUseCase
    move_application: MoveApplicationUseCase
    reject_application: RejectApplicationUseCase
    comment_use_case: CommentUseCase
    application_timeline: ApplicationTimelineUseCase
    upload_resume: UploadResumeUseCase
    upload_candidate_resume: UploadCandidateResumeUseCase
    search_candidates: SearchCandidatesUseCase
    candidate_crud: CandidateCrudUseCase
    bulk_import_candidates: BulkImportCandidatesUseCase
    dedup_repository: DedupRepository
    dedup_use_case: DedupUseCase
    legal_entity_repository: LegalEntityRepository
    org_unit_repository: OrgUnitRepository
    legal_entity_use_case: LegalEntityUseCase
    org_unit_use_case: OrgUnitUseCase


def build_container() -> Container:
    """Собрать контейнер по окружению."""
    stub_mode = os.getenv("ATS_STUB_MODE", "1") == "1"

    if stub_mode:
        vacancy_repo: VacancyRepository = InMemoryVacancyRepository()
        candidate_repo: CandidateRepository = InMemoryCandidateRepository()
        application_repo: ApplicationRepository = InMemoryApplicationRepository()
        comment_repo: CommentRepository = InMemoryCommentRepository()
        resume_repo: ResumeRepository = InMemoryResumeRepository()
        req_set_repo: RequirementSetRepository = InMemoryRequirementSetRepository()
        funnel_preset_repo: FunnelPresetRepository = InMemoryFunnelPresetRepository()
        funnel_snapshot_repo: FunnelSnapshotRepository = InMemoryFunnelSnapshotRepository()
        stage_transition_repo: StageTransitionRepository = InMemoryStageTransitionRepository()
        hm_decision_repo: HMDecisionRepository = InMemoryHMDecisionRepository()
        provenance: ProvenanceLedger = InMemoryProvenanceLedger()
        gateway: AIGateway = StubAIGateway()
        search_engine: SearchEngine = InMemorySearchEngine()
        synonym_repo: SynonymRepository = InMemorySynonymRepository()
        webhook_sub_repo: WebhookSubscriptionRepository = InMemoryWebhookSubscriptionRepository()
        webhook_deliv_repo: WebhookDeliveryRepository = InMemoryWebhookDeliveryRepository()
        legal_entity_repo: LegalEntityRepository = InMemoryLegalEntityRepository()
        org_unit_repo: OrgUnitRepository = InMemoryOrgUnitRepository()
        dedup_repo: DedupRepository = InMemoryDedupRepository()
    else:
        from ats.infra.ai.litellm_gateway import LiteLLMGateway
        from ats.infra.db.repositories.provenance_repository import (
            PgProvenanceLedger,
        )
        from ats.infra.db.repositories.vacancy_repository import PgVacancyRepository
        from ats.infra.search.pgvector_search_engine import PgVectorSearchEngine

        vacancy_repo = PgVacancyRepository()
        candidate_repo = InMemoryCandidateRepository()  # Pg-реализация в след. фазе
        application_repo = InMemoryApplicationRepository()
        comment_repo = InMemoryCommentRepository()  # Pg-реализация в след. фазе
        resume_repo = InMemoryResumeRepository()  # Pg-реализация в след. фазе
        req_set_repo = InMemoryRequirementSetRepository()  # Pg-реализация в след. фазе
        funnel_preset_repo = InMemoryFunnelPresetRepository()
        funnel_snapshot_repo = InMemoryFunnelSnapshotRepository()
        stage_transition_repo = InMemoryStageTransitionRepository()
        hm_decision_repo = InMemoryHMDecisionRepository()
        provenance = PgProvenanceLedger()
        from ats.infra.ai.redis_cache import RedisCacheStore

        cache = RedisCacheStore()
        gateway = LiteLLMGateway(provenance, cache=cache)
        search_engine = PgVectorSearchEngine()
        synonym_repo = InMemorySynonymRepository()  # Pg-реализация в след. фазе
        webhook_sub_repo: WebhookSubscriptionRepository = InMemoryWebhookSubscriptionRepository()
        webhook_deliv_repo: WebhookDeliveryRepository = InMemoryWebhookDeliveryRepository()
        legal_entity_repo = InMemoryLegalEntityRepository()  # Pg-реализация в след. фазе
        org_unit_repo = InMemoryOrgUnitRepository()  # Pg-реализация в след. фазе
        dedup_repo = InMemoryDedupRepository()  # Pg-реализация в след. фазе

    audit_logger: AuditLogger = InMemoryAuditLogger()
    audit_reader: AuditReader = InMemoryAuditReader()
    event_bus = InProcessEventBus()

    screening_skill = GenerateScreeningCriteria(gateway)
    parse_skill = ParseResume(gateway)
    create_vacancy = CreateVacancyUseCase(vacancy_repo, screening_skill)
    vacancy_crud = VacancyCrudUseCase(vacancy_repo)
    requirement_set_use_case = RequirementSetUseCase(req_set_repo, vacancy_repo)
    funnel_preset_use_case = FunnelPresetUseCase(funnel_preset_repo, funnel_snapshot_repo)
    funnel_transition_use_case = FunnelTransitionUseCase(
        funnel_snapshot_repo, stage_transition_repo
    )
    hm_decision_use_case = HMDecisionUseCase(hm_decision_repo)
    create_application = CreateApplicationUseCase(application_repo)
    move_application = MoveApplicationUseCase(application_repo, vacancy_repo)
    reject_application = RejectApplicationUseCase(application_repo)
    comment_use_case = CommentUseCase(comment_repo, application_repo)
    application_timeline = ApplicationTimelineUseCase(application_repo, comment_repo)
    upload_resume = UploadResumeUseCase(candidate_repo, parse_skill, search_engine, gateway)
    upload_candidate_resume = UploadCandidateResumeUseCase(
        candidate_repo, resume_repo, parse_skill, search_engine, gateway
    )
    search_candidates = SearchCandidatesUseCase(search_engine, gateway, synonym_repo)
    candidate_crud = CandidateCrudUseCase(candidate_repo)
    bulk_import_candidates = BulkImportCandidatesUseCase(candidate_repo)

    dedup_use_case = DedupUseCase(candidate_repo, dedup_repo, application_repo)

    webhook_management = WebhookManagementUseCase(webhook_sub_repo, webhook_deliv_repo)
    webhook_dispatcher = WebhookDispatcher(webhook_sub_repo, webhook_deliv_repo, webhook_management)

    legal_entity_use_case = LegalEntityUseCase(legal_entity_repo)
    org_unit_use_case = OrgUnitUseCase(org_unit_repo, legal_entity_repo)

    return Container(
        vacancy_repository=vacancy_repo,
        candidate_repository=candidate_repo,
        application_repository=application_repo,
        resume_repository=resume_repo,
        requirement_set_repository=req_set_repo,
        funnel_preset_repository=funnel_preset_repo,
        funnel_snapshot_repository=funnel_snapshot_repo,
        stage_transition_repository=stage_transition_repo,
        hm_decision_repository=hm_decision_repo,
        provenance_ledger=provenance,
        ai_gateway=gateway,
        search_engine=search_engine,
        synonym_repository=synonym_repo,
        audit_logger=audit_logger,
        audit_reader=audit_reader,
        event_bus=event_bus,
        webhook_subscription_repository=webhook_sub_repo,
        webhook_delivery_repository=webhook_deliv_repo,
        webhook_management=webhook_management,
        webhook_dispatcher=webhook_dispatcher,
        create_vacancy=create_vacancy,
        vacancy_crud=vacancy_crud,
        requirement_set_use_case=requirement_set_use_case,
        funnel_preset_use_case=funnel_preset_use_case,
        funnel_transition_use_case=funnel_transition_use_case,
        hm_decision_use_case=hm_decision_use_case,
        create_application=create_application,
        move_application=move_application,
        reject_application=reject_application,
        comment_use_case=comment_use_case,
        application_timeline=application_timeline,
        upload_resume=upload_resume,
        upload_candidate_resume=upload_candidate_resume,
        search_candidates=search_candidates,
        candidate_crud=candidate_crud,
        bulk_import_candidates=bulk_import_candidates,
        dedup_repository=dedup_repo,
        dedup_use_case=dedup_use_case,
        legal_entity_repository=legal_entity_repo,
        org_unit_repository=org_unit_repo,
        legal_entity_use_case=legal_entity_use_case,
        org_unit_use_case=org_unit_use_case,
    )
