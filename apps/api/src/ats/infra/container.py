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
from ats.infra.stubs_repositories import (
    InMemoryApplicationRepository,
    InMemoryCandidateRepository,
)
from ats.infra.stubs_requirement_set_repository import (
    InMemoryRequirementSetRepository,
)
from ats.infra.stubs_resume_repository import InMemoryResumeRepository
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
from ats.modules.candidates.application.upload_candidate_resume import (
    UploadCandidateResumeUseCase,
)
from ats.modules.candidates.application.upload_resume import UploadResumeUseCase
from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.candidates.ports.resume_repository import ResumeRepository
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
from ats.modules.recruitment.application.vacancy_crud import VacancyCrudUseCase
from ats.modules.recruitment.ports.application_repository import (
    ApplicationRepository,
)
from ats.modules.recruitment.ports.requirement_set_repository import (
    RequirementSetRepository,
)
from ats.modules.recruitment.ports.vacancy_repository import VacancyRepository
from ats.modules.search.application.search_candidates import SearchCandidatesUseCase
from ats.modules.search.ports.search_engine import SearchEngine


@dataclass
class Container:
    """Граф зависимостей приложения."""

    vacancy_repository: VacancyRepository
    candidate_repository: CandidateRepository
    application_repository: ApplicationRepository
    resume_repository: ResumeRepository
    requirement_set_repository: RequirementSetRepository
    provenance_ledger: ProvenanceLedger
    ai_gateway: AIGateway
    search_engine: SearchEngine
    audit_logger: AuditLogger
    audit_reader: AuditReader
    event_bus: InProcessEventBus
    create_vacancy: CreateVacancyUseCase
    vacancy_crud: VacancyCrudUseCase
    requirement_set_use_case: RequirementSetUseCase
    create_application: CreateApplicationUseCase
    move_application: MoveApplicationUseCase
    upload_resume: UploadResumeUseCase
    upload_candidate_resume: UploadCandidateResumeUseCase
    search_candidates: SearchCandidatesUseCase
    candidate_crud: CandidateCrudUseCase
    bulk_import_candidates: BulkImportCandidatesUseCase


def build_container() -> Container:
    """Собрать контейнер по окружению."""
    stub_mode = os.getenv("ATS_STUB_MODE", "1") == "1"

    if stub_mode:
        vacancy_repo: VacancyRepository = InMemoryVacancyRepository()
        candidate_repo: CandidateRepository = InMemoryCandidateRepository()
        application_repo: ApplicationRepository = InMemoryApplicationRepository()
        resume_repo: ResumeRepository = InMemoryResumeRepository()
        req_set_repo: RequirementSetRepository = InMemoryRequirementSetRepository()
        provenance: ProvenanceLedger = InMemoryProvenanceLedger()
        gateway: AIGateway = StubAIGateway()
        search_engine: SearchEngine = InMemorySearchEngine()
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
        resume_repo = InMemoryResumeRepository()  # Pg-реализация в след. фазе
        req_set_repo = InMemoryRequirementSetRepository()  # Pg-реализация в след. фазе
        provenance = PgProvenanceLedger()
        gateway = LiteLLMGateway(provenance)
        search_engine = PgVectorSearchEngine()

    audit_logger: AuditLogger = InMemoryAuditLogger()
    audit_reader: AuditReader = InMemoryAuditReader()
    event_bus = InProcessEventBus()

    screening_skill = GenerateScreeningCriteria(gateway)
    parse_skill = ParseResume(gateway)
    create_vacancy = CreateVacancyUseCase(vacancy_repo, screening_skill)
    vacancy_crud = VacancyCrudUseCase(vacancy_repo)
    requirement_set_use_case = RequirementSetUseCase(req_set_repo, vacancy_repo)
    create_application = CreateApplicationUseCase(application_repo)
    move_application = MoveApplicationUseCase(application_repo)
    upload_resume = UploadResumeUseCase(candidate_repo, parse_skill, search_engine, gateway)
    upload_candidate_resume = UploadCandidateResumeUseCase(
        candidate_repo, resume_repo, parse_skill, search_engine, gateway
    )
    search_candidates = SearchCandidatesUseCase(search_engine, gateway)
    candidate_crud = CandidateCrudUseCase(candidate_repo)
    bulk_import_candidates = BulkImportCandidatesUseCase(candidate_repo)

    return Container(
        vacancy_repository=vacancy_repo,
        candidate_repository=candidate_repo,
        application_repository=application_repo,
        resume_repository=resume_repo,
        requirement_set_repository=req_set_repo,
        provenance_ledger=provenance,
        ai_gateway=gateway,
        search_engine=search_engine,
        audit_logger=audit_logger,
        audit_reader=audit_reader,
        event_bus=event_bus,
        create_vacancy=create_vacancy,
        vacancy_crud=vacancy_crud,
        requirement_set_use_case=requirement_set_use_case,
        create_application=create_application,
        move_application=move_application,
        upload_resume=upload_resume,
        upload_candidate_resume=upload_candidate_resume,
        search_candidates=search_candidates,
        candidate_crud=candidate_crud,
        bulk_import_candidates=bulk_import_candidates,
    )
