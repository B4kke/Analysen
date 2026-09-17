import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import get_settings
from apps.api.app.domain.models import (
    InvestigationClaimRecord,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationEntityRecord,
    InvestigationRecord,
    Lead,
)
from apps.api.app.domain.scope import InvestigationModuleRecord, ScopeModule, ScopeUpdate
from apps.api.app.services.lead_gate import gate_lead


class InvestigationNotFound(LookupError):
    pass


def _record(row) -> InvestigationRecord:
    values = dict(row)
    values["target"] = values.pop("target_input")
    return InvestigationRecord.model_validate(values)


_RECORD_COLUMNS = """
    id, target_input, purpose, legal_basis_note, status, created_at, updated_at,
    scope_modules, expansion_policy, max_relation_depth
"""


async def _audit(session: AsyncSession, investigation_id: UUID, event: str, payload: dict) -> None:
    await session.execute(
        text("""
            INSERT INTO audit_log (investigation_id, event_type, actor, payload)
            VALUES (:id, :event, 'local-operator', CAST(:payload AS jsonb))
        """),
        {"id": investigation_id, "event": event, "payload": json.dumps(payload)},
    )


async def _sync_modules(
    session: AsyncSession, investigation_id: UUID, modules: list[ScopeModule]
) -> None:
    for module in ScopeModule:
        await session.execute(
            text("""
                INSERT INTO investigation_modules (investigation_id, module, enabled)
                VALUES (:id, :module, :enabled)
                ON CONFLICT (investigation_id, module) DO UPDATE SET enabled = EXCLUDED.enabled
            """),
            {"id": investigation_id, "module": module.value, "enabled": module in modules},
        )


def _scope_payload(record: InvestigationRecord) -> dict:
    return record.model_dump(
        mode="json", include={"scope_modules", "expansion_policy", "max_relation_depth"}
    )


async def create_investigation(
    session: AsyncSession, request: InvestigationCreate
) -> InvestigationRecord:
    row = (
        await session.execute(
            text(f"""
                INSERT INTO investigations (
                    target_type, target_input, purpose, legal_basis_note,
                    scope_modules, expansion_policy, max_relation_depth
                ) VALUES (
                    :target_type, CAST(:target_input AS jsonb), :purpose, :legal_basis_note,
                    :scope_modules, :expansion_policy, :max_relation_depth
                ) RETURNING {_RECORD_COLUMNS}
            """),
            {
                "target_type": request.target.type.value,
                "target_input": request.target.model_dump_json(),
                "purpose": request.purpose,
                "legal_basis_note": request.legal_basis_note,
                "scope_modules": [module.value for module in request.scope_modules],
                "expansion_policy": request.expansion_policy.value,
                "max_relation_depth": request.max_relation_depth,
            },
        )
    ).mappings().one()
    record = _record(row)
    await _sync_modules(session, record.id, request.scope_modules)
    await _audit(session, record.id, "CREATED", {"scope": _scope_payload(record)})
    return record


async def get_investigation_record(
    session: AsyncSession, investigation_id: UUID, *, for_update: bool = False
) -> InvestigationRecord:
    # The execution boundary holds this same lock until commit, serializing scope updates.
    lock = " FOR UPDATE" if for_update else ""
    row = (
        await session.execute(
            text(f"SELECT {_RECORD_COLUMNS} FROM investigations WHERE id = :id{lock}"),
            {"id": investigation_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise InvestigationNotFound(str(investigation_id))
    return _record(row)


async def get_modules(
    session: AsyncSession, investigation_id: UUID
) -> list[InvestigationModuleRecord]:
    await get_investigation_record(session, investigation_id)
    rows = (
        await session.execute(
            text("""
                SELECT module, enabled, status, coverage, stop_reason
                FROM investigation_modules WHERE investigation_id = :id ORDER BY module
            """),
            {"id": investigation_id},
        )
    ).mappings().all()
    return [InvestigationModuleRecord.model_validate(row) for row in rows]


async def get_investigation(
    session: AsyncSession, investigation_id: UUID
) -> InvestigationDetail:
    record = await get_investigation_record(session, investigation_id)
    entity_rows = (
        await session.execute(
            text("""
                SELECT e.id, e.schema, e.canonical_name, e.attributes, e.resolution_state,
                    ie.relation_depth, ie.expansion_state, ie.material_reason
                FROM investigation_entities ie JOIN entities e ON e.id = ie.entity_id
                WHERE ie.investigation_id = :id
                ORDER BY ie.discovered_at, e.canonical_name NULLS LAST
            """),
            {"id": investigation_id},
        )
    ).mappings().all()
    claim_rows = (
        await session.execute(
            text("""
                SELECT id, subject_entity_id, predicate, value, status, created_at
                FROM claims WHERE investigation_id = :id ORDER BY created_at, predicate
            """),
            {"id": investigation_id},
        )
    ).mappings().all()
    return InvestigationDetail(
        **record.model_dump(),
        entities=[InvestigationEntityRecord.model_validate(item) for item in entity_rows],
        claims=[InvestigationClaimRecord.model_validate(item) for item in claim_rows],
        modules=await get_modules(session, investigation_id),
    )


async def update_scope(
    session: AsyncSession, investigation_id: UUID, request: ScopeUpdate
) -> InvestigationDetail:
    before = await get_investigation_record(session, investigation_id, for_update=True)
    await session.execute(
        text("""
            UPDATE investigations SET scope_modules = :modules, expansion_policy = :policy,
                max_relation_depth = :depth, updated_at = now() WHERE id = :id
        """),
        {
            "id": investigation_id,
            "modules": [module.value for module in request.scope_modules],
            "policy": request.expansion_policy.value,
            "depth": request.max_relation_depth,
        },
    )
    await _sync_modules(session, investigation_id, request.scope_modules)
    # Queued work for disabled modules cannot survive a scope narrowing.
    await session.execute(
        text("""
            UPDATE leads SET status = 'BLOCKED', blocked_reason = 'module_disabled'
            WHERE investigation_id = :id AND status = 'PENDING'
              AND NOT (scope_area = ANY(CAST(:modules AS text[])))
        """),
        {"id": investigation_id, "modules": [module.value for module in request.scope_modules]},
    )
    after = await get_investigation(session, investigation_id)
    await _audit(session, investigation_id, "SCOPE_CHANGED", {
        "before": _scope_payload(before), "after": _scope_payload(after), "reason": request.reason,
    })
    return after


async def mark_investigation_active(session: AsyncSession, investigation_id: UUID) -> None:
    await get_investigation_record(session, investigation_id)
    await session.execute(
        text("UPDATE investigations SET status = 'ACTIVE', updated_at = now() WHERE id = :id"),
        {"id": investigation_id},
    )


def _lead_row(lead: Lead) -> dict:
    return {
        "lead_type": lead.lead_type,
        "value": json.dumps(lead.value, default=str),
        "reason": lead.reason,
        "originating_claim_id": lead.originating_claim_id,
        "priority": lead.priority,
        "depth": lead.depth,
        "scope_area": lead.scope_area.value,
        "trigger_type": lead.trigger_type.value,
        "information_need": lead.information_need,
        "relation_depth": lead.relation_depth,
    }


def _source_enabled(module: ScopeModule) -> bool:
    """Any enabled source counts today; per-module routing arrives with AQ-006."""
    _, sources, _ = get_settings().validate_yaml_configs()
    return any(source.enabled for source in sources.sources.values())


async def propose_lead(
    session: AsyncSession, investigation_id: UUID, lead: Lead
) -> tuple[UUID, str]:
    """Admit a planner/model-proposed lead through the deterministic gate.

    The investigation row is locked so a concurrent scope narrowing cannot race
    the admission. Gated leads are stored with status BLOCKED and the refusal
    reason; only admitted leads are PENDING. The decision is always audited.
    """
    investigation = await get_investigation_record(session, investigation_id, for_update=True)
    decision = gate_lead(
        investigation,
        lead,
        source_enabled=_source_enabled(lead.scope_area),
    )
    row = _lead_row(lead)
    status = "PENDING" if decision is None else "BLOCKED"
    result = await session.execute(
        text("""
            INSERT INTO leads (
                investigation_id, lead_type, value, reason, originating_claim_id,
                priority, depth, status, scope_area, trigger_type, information_need,
                relation_depth, blocked_reason
            ) VALUES (
                :investigation_id, :lead_type, CAST(:value AS jsonb), :reason,
                :originating_claim_id, :priority, :depth, :status, :scope_area,
                :trigger_type, :information_need, :relation_depth, :blocked_reason
            ) RETURNING id
        """),
        {
            "investigation_id": investigation_id,
            "status": status,
            "blocked_reason": decision,
            **row,
        },
    )
    lead_id = result.scalar_one()
    await _audit(
        session,
        investigation_id,
        "LEAD_PROPOSED",
        {
            "lead_id": str(lead_id),
            "status": status,
            "scope_area": lead.scope_area.value,
            "trigger_type": lead.trigger_type.value,
            "decision": decision,
        },
    )
    return lead_id, status
