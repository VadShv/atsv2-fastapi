"""Порты модуля кандидатов."""

from ats.modules.candidates.ports.candidate_repository import CandidateRepository
from ats.modules.candidates.ports.dedup_repository import DedupRepository
from ats.modules.candidates.ports.resume_repository import ResumeRepository

__all__ = ["CandidateRepository", "DedupRepository", "ResumeRepository"]
