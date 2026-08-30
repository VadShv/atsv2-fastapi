"""Application-слой candidates: use cases."""

from ats.modules.candidates.application.candidate_crud import (
    BulkImportCandidatesUseCase,
    CandidateCrudUseCase,
)
from ats.modules.candidates.application.dedup_use_cases import DedupUseCase, MergeResult
from ats.modules.candidates.application.upload_candidate_resume import (
    UploadCandidateResumeUseCase,
)
from ats.modules.candidates.application.upload_resume import UploadResumeUseCase

__all__ = [
    "BulkImportCandidatesUseCase",
    "CandidateCrudUseCase",
    "DedupUseCase",
    "MergeResult",
    "UploadCandidateResumeUseCase",
    "UploadResumeUseCase",
]
