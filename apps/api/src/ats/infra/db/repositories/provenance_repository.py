"""Postgres-реализация provenance ledger (whitebox AI)."""

from __future__ import annotations

from sqlalchemy import select, update

from ats.infra.db.models.ai_core import ProvenanceORM
from ats.infra.db.session import tenant_session
from ats.modules.ai_core.domain.models import ProvenanceRecord
from ats.modules.ai_core.ports.provenance import ProvenanceLedger
from ats.shared.ids import ProvenanceId, TenantId


def _record_to_orm(rec: ProvenanceRecord) -> ProvenanceORM:
    return ProvenanceORM(
        id=rec.provenance_id.value,
        tenant_id=rec.tenant_id.value,
        skill=rec.skill,
        prompt_id=rec.prompt_id,
        prompt_version=rec.prompt_version,
        model=rec.model,
        input_hash=rec.input_hash,
        input_refs=rec.input_refs,
        raw_output=rec.raw_output,
        parsed_output=rec.parsed_output,
        confidence=rec.confidence,
        latency_ms=rec.latency_ms,
        tokens_in=rec.tokens_in,
        tokens_out=rec.tokens_out,
        cost_usd=rec.cost_usd,
        human_verified=rec.human_verified,
        reasoning_trace=rec.reasoning_trace,
        non_ai=rec.non_ai,
        timestamp=rec.timestamp,
    )


def _orm_to_record(row: ProvenanceORM) -> ProvenanceRecord:
    return ProvenanceRecord(
        provenance_id=ProvenanceId(row.id),
        tenant_id=TenantId(row.tenant_id),
        skill=row.skill,
        prompt_id=row.prompt_id,
        prompt_version=row.prompt_version,
        model=row.model,
        input_hash=row.input_hash,
        input_refs=dict(row.input_refs or {}),
        raw_output=row.raw_output,
        parsed_output=row.parsed_output,
        confidence=row.confidence,
        latency_ms=row.latency_ms,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_usd=row.cost_usd,
        timestamp=row.timestamp,
        human_verified=row.human_verified,
        reasoning_trace=row.reasoning_trace,
        non_ai=row.non_ai,
    )


class PgProvenanceLedger(ProvenanceLedger):
    """Append-only provenance ledger в Postgres. RLS изолирует тенанты."""

    async def append(self, record: ProvenanceRecord) -> ProvenanceId:
        orm = _record_to_orm(record)
        async with tenant_session(record.tenant_id.value) as session:
            session.add(orm)
            await session.commit()
        return record.provenance_id

    async def get(
        self, tenant_id: TenantId, provenance_id: ProvenanceId
    ) -> ProvenanceRecord | None:
        async with tenant_session(tenant_id.value) as session:
            stmt = select(ProvenanceORM).where(ProvenanceORM.id == provenance_id.value)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return _orm_to_record(row)

    async def mark_verified(self, tenant_id: TenantId, provenance_id: ProvenanceId) -> None:
        async with tenant_session(tenant_id.value) as session:
            stmt = (
                update(ProvenanceORM)
                .where(ProvenanceORM.id == provenance_id.value)
                .values(human_verified=True)
            )
            await session.execute(stmt)
            await session.commit()
