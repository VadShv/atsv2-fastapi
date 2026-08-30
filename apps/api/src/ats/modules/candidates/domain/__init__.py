"""Домен кандидатов."""

from ats.modules.candidates.domain.dedup import (
    MERGE_ROLLBACK_WINDOW,
    CandidateMerged,
    ContactHash,
    ContactKind,
    DuplicateConfidence,
    DuplicateMatch,
    MergeLog,
    MergeRolledBack,
    MergeStatus,
    get_hmac_key,
    hash_contact,
    normalize_contact,
)

__all__ = [
    "MERGE_ROLLBACK_WINDOW",
    "CandidateMerged",
    "ContactHash",
    "ContactKind",
    "DuplicateConfidence",
    "DuplicateMatch",
    "MergeLog",
    "MergeRolledBack",
    "MergeStatus",
    "get_hmac_key",
    "hash_contact",
    "normalize_contact",
]
