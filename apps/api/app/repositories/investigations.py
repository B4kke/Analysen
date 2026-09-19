import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import get_settings
from apps.api.app.domain.models import (
    ClaimEvidenceDetail,
    InvestigationClaimRecord,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationEntityRecord,
    InvestigationLeadRecord,
    InvestigationRecord,
    Lead,
    ResearchPassState,
)
from apps.api.app.domain.scope import InvestigationModuleRecord, ScopeModule, ScopeUpdate
from apps.api.app.services.lead_gate import gate_lead
from apps.api.app.services.research_state import reduce_research_events


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
        (
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
        )
        .mappings()
        .one()
    )
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
        (
            await session.execute(
                text(f"SELECT {_RECORD_COLUMNS} FROM investigations WHERE id = :id{lock}"),
                {"id": investigation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise InvestigationNotFound(str(investigation_id))
    return _record(row)


async def get_modules(
    session: AsyncSession, investigation_id: UUID
) -> list[InvestigationModuleRecord]:
    await get_investigation_record(session, investigation_id)
    rows = (
        (
            await session.execute(
                text("""
                SELECT module, enabled, status, coverage, stop_reason
                FROM investigation_modules WHERE investigation_id = :id ORDER BY module
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    return [InvestigationModuleRecord.model_validate(row) for row in rows]


async def get_research_state(
    session: AsyncSession,
    investigation_id: UUID,
    *,
    has_activity: bool | None = None,
) -> ResearchPassState:
    """Return the reducer state without recursively loading investigation detail."""
    await get_investigation_record(session, investigation_id)
    audit_rows = (
        (
            await session.execute(
                text("""
                SELECT id, event_type, payload, created_at
                FROM audit_log
                WHERE investigation_id = :id
                  AND event_type IN (
                    'RESEARCH_PASS_REQUESTED', 'RESEARCH_PASS_ENQUEUED',
                    'RESEARCH_PASS_STARTED', 'RESEARCH_PASS_COMPLETED',
                    'RESEARCH_PASS_FAILED'
                  )
                ORDER BY id
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    if has_activity is None:
        has_activity = bool(
            await session.scalar(
                text("""
                    SELECT EXISTS (
                        SELECT 1 FROM claims WHERE investigation_id = :id
                    ) OR EXISTS (
                        SELECT 1 FROM investigation_entities WHERE investigation_id = :id
                    ) OR EXISTS (
                        SELECT 1 FROM investigation_modules
                        WHERE investigation_id = :id
                          AND (status <> 'NOT_STARTED' OR stop_reason IS NOT NULL
                            OR coverage @? '$.query_count ? (@ > 0)'
                            OR coverage @? '$.document_count ? (@ > 0)'
                            OR coverage->'providers' NOT IN ('[]'::jsonb, 'null'::jsonb)
                            OR coverage->'gaps' NOT IN ('[]'::jsonb, 'null'::jsonb)
                            OR coverage->'unavailable_sources' NOT IN ('[]'::jsonb, 'null'::jsonb))
                    ) OR EXISTS (
                        SELECT 1 FROM investigation_documents WHERE investigation_id = :id
                    ) OR EXISTS (
                        SELECT 1 FROM leads WHERE investigation_id = :id
                          AND status IN ('RUNNING', 'COMPLETED', 'FAILED')
                    ) OR EXISTS (
                        SELECT 1 FROM audit_log WHERE investigation_id = :id
                          AND event_type = 'LEAD_EXECUTED'
                    )
                """),
                {"id": investigation_id},
            )
        )
    return reduce_research_events([dict(row) for row in audit_rows], has_activity=has_activity)


async def get_investigation(session: AsyncSession, investigation_id: UUID) -> InvestigationDetail:
    record = await get_investigation_record(session, investigation_id)
    entity_rows = (
        (
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
        )
        .mappings()
        .all()
    )
    claim_rows = (
        (
            await session.execute(
                text("""
                SELECT id, subject_entity_id, predicate, value, status, created_at
                FROM claims WHERE investigation_id = :id ORDER BY created_at, predicate
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    evidence_rows = (
        (
            await session.execute(
                text("""
                SELECT ce.claim_id, ce.evidence_id, ce.relation,
                    e.document_id, e.locator_type, e.locator, e.excerpt,
                    e.structured_value, d.original_url, d.canonical_url,
                    d.fetched_at, d.sha256, d.raw_storage_key,
                    s.id AS source_id, s.name AS source_name
                FROM claims c
                JOIN claim_evidence ce ON ce.claim_id = c.id
                JOIN evidence e ON e.id = ce.evidence_id
                JOIN documents d ON d.id = e.document_id
                JOIN investigation_documents ind
                    ON ind.document_id = d.id AND ind.investigation_id = c.investigation_id
                LEFT JOIN sources s ON s.id = d.source_id
                WHERE c.investigation_id = :id
                ORDER BY ce.claim_id, e.created_at, ce.evidence_id
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    evidence_by_claim: dict[UUID, list[ClaimEvidenceDetail]] = {}
    for row in evidence_rows:
        evidence_by_claim.setdefault(row["claim_id"], []).append(
            ClaimEvidenceDetail.model_validate(
                {key: row[key] for key in ClaimEvidenceDetail.model_fields}
            )
        )
    lead_rows = (
        (
            await session.execute(
                text("""
                SELECT id, lead_type, value, reason, originating_claim_id,
                    priority, depth, status, scope_area, trigger_type,
                    information_need, relation_depth, blocked_reason, created_at
                FROM leads
                WHERE investigation_id = :id
                ORDER BY created_at, id
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    counts = (
        (
            await session.execute(
                text("""
        SELECT count(DISTINCT d.document_id) AS document_count,
               count(DISTINCT e.id) AS evidence_count
        FROM investigation_documents d LEFT JOIN evidence e ON e.document_id = d.document_id
        WHERE d.investigation_id = :id
    """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .one()
    )
    return InvestigationDetail(
        **record.model_dump(),
        document_count=counts["document_count"],
        evidence_count=counts["evidence_count"],
        entities=[InvestigationEntityRecord.model_validate(item) for item in entity_rows],
        claims=[
            InvestigationClaimRecord.model_validate(
                {**item, "evidence": evidence_by_claim.get(item["id"], [])}
            )
            for item in claim_rows
        ],
        modules=await get_modules(session, investigation_id),
        research=await get_research_state(session, investigation_id),
        leads=[InvestigationLeadRecord.model_validate(item) for item in lead_rows],
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
    await _audit(
        session,
        investigation_id,
        "SCOPE_CHANGED",
        {
            "before": _scope_payload(before),
            "after": _scope_payload(after),
            "reason": request.reason,
        },
    )
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


async def export_investigation(session: AsyncSession, investigation_id: UUID) -> dict:
    """Full data export for one investigation (GDPR data portability).

    Includes record, modules, entities, claims, leads, documents (with raw
    snapshot keys), media mentions (with evidence/document/anchor references)
    and audit events. Raw bytes stay in the object store; the export
    references them by hash so integrity can be verified after import.
    """
    from datetime import UTC, datetime

    detail = await get_investigation(session, investigation_id)
    lead_rows = (
        (
            await session.execute(
                text("""
                SELECT id, lead_type, value, reason, originating_claim_id, priority,
                    depth, status, scope_area, trigger_type, information_need,
                    relation_depth, blocked_reason, created_at
                FROM leads WHERE investigation_id = :id ORDER BY created_at
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    document_rows = (
        (
            await session.execute(
                text("""
                SELECT doc.id, doc.sha256, doc.raw_storage_key, doc.original_url,
                    doc.canonical_url, doc.mime_type, doc.fetched_at
                FROM investigation_documents d
                JOIN documents doc ON doc.id = d.document_id
                WHERE d.investigation_id = :id ORDER BY doc.fetched_at
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    audit_rows = (
        (
            await session.execute(
                text("""
                SELECT event_type, actor, payload, created_at
                FROM audit_log WHERE investigation_id = :id ORDER BY id
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    mention_rows = (
        (
            await session.execute(
                text("""
                SELECT id, target_query, publication, published_at,
                    page_number, issue_urn, page_urn, headline, summary,
                    text_excerpt, text_availability, identity_state, source_url,
                    access_class, license_code, image_document_id,
                    image_embeddable, evidence_id, xywh_anchors, created_at
                FROM media_mentions WHERE investigation_id = :id
                ORDER BY published_at NULLS LAST, page_number NULLS LAST
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        "investigation": detail.model_dump(mode="json"),
        "modules": [module.model_dump(mode="json") for module in detail.modules],
        "entities": [entity.model_dump(mode="json") for entity in detail.entities],
        "claims": [claim.model_dump(mode="json") for claim in detail.claims],
        "leads": [dict(row) for row in lead_rows],
        "documents": [dict(row) for row in document_rows],
        "media_mentions": [dict(row) for row in mention_rows],
        "audit_log": [dict(row) for row in audit_rows],
        "exported_at": datetime.now(UTC).isoformat(),
    }


async def delete_investigation(session: AsyncSession, investigation_id: UUID) -> None:
    """Delete one investigation and all cascade-owned data (GDPR erasure).

    Deletion relies on ON DELETE CASCADE from investigations. Raw snapshots in
    the object store are content-addressed and shared between documents; they
    are intentionally not removed here. The deletion itself is audited on the
    surviving audit row (investigation_id becomes NULL via ON DELETE SET NULL).
    """
    await get_investigation_record(session, investigation_id, for_update=True)
    await _audit(
        session,
        investigation_id,
        "INVESTIGATION_DELETED",
        {"reason": "operator requested erasure"},
    )
    await session.execute(
        text("DELETE FROM investigations WHERE id = :id"), {"id": investigation_id}
    )


async def get_lead(session: AsyncSession, investigation_id: UUID, lead_id: UUID) -> dict:
    """Load one lead row; raises InvestigationNotFound when missing or foreign."""
    row = (
        (
            await session.execute(
                text("""
                SELECT id, lead_type, value, reason, originating_claim_id, priority,
                    depth, status, scope_area, trigger_type, information_need,
                    relation_depth, blocked_reason
                FROM leads WHERE id = :lead_id AND investigation_id = :id
            """),
                {"lead_id": lead_id, "id": investigation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise InvestigationNotFound(str(lead_id))
    return dict(row)


async def set_lead_status(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    status: str,
    blocked_reason: str | None = None,
) -> None:
    await session.execute(
        text("""
            UPDATE leads SET status = :status, blocked_reason = :blocked_reason
            WHERE id = :lead_id AND investigation_id = :id
        """),
        {
            "status": status,
            "blocked_reason": blocked_reason,
            "lead_id": lead_id,
            "id": investigation_id,
        },
    )


# Coverage counter keys the ledger accepts from executors. Unknown keys are
# ignored so a source can never invent ledger fields.
COVERAGE_COUNTER_KEYS = frozenset(
    {
        "candidate_count",
        "located_count",
        "concordance_count",
        "fulltext_count",
        "restricted_count",
        "fetched_count",
    }
)


async def bump_module_coverage(
    session: AsyncSession,
    investigation_id: UUID,
    module: ScopeModule,
    *,
    provider: str,
    query_class: str | None = None,
    endpoints: list[str] | None = None,
    counters: dict[str, int] | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
) -> None:
    """Record one executed fetch in the module coverage ledger.

    Beyond the base query/document counts and provider, executors may report
    the query class used, source endpoints attempted, per-source result
    counters (only ``COVERAGE_COUNTER_KEYS`` are accepted) and the ISO date
    range their sources cover. Counters accumulate; string lists stay
    deduplicated; the time range widens monotonically. Unknown counter keys
    are ignored.
    """
    clean_counters = {
        key: max(0, int(value))
        for key, value in (counters or {}).items()
        if key in COVERAGE_COUNTER_KEYS
    }
    core = """jsonb_set(
        jsonb_set(
            coverage,
            '{query_count}',
            to_jsonb(COALESCE((coverage->>'query_count')::int, 0) + 1)
        ),
        '{document_count}',
        to_jsonb(COALESCE((coverage->>'document_count')::int, 0) + 1)
    )"""
    for key in sorted(clean_counters):
        core = (
            f"jsonb_set({core}, '{{{key}}}', "
            f"to_jsonb(COALESCE((coverage->>'{key}')::int, 0) + {clean_counters[key]}))"
        )
    await session.execute(
        text(f"""
            UPDATE investigation_modules
            SET status = CASE WHEN status = 'NOT_STARTED' THEN 'IN_PROGRESS' ELSE status END,
                started_at = COALESCE(started_at, now()),
                coverage = {core} || jsonb_build_object(
                    'providers',
                    (SELECT COALESCE(jsonb_agg(DISTINCT value), '[]'::jsonb)
                     FROM jsonb_array_elements_text(
                         COALESCE(coverage->'providers', '[]'::jsonb)
                             || to_jsonb(CAST(:provider AS text))
                     ) AS value),
                    'query_classes',
                    (SELECT COALESCE(jsonb_agg(DISTINCT value), '[]'::jsonb)
                     FROM jsonb_array_elements_text(
                         COALESCE(coverage->'query_classes', '[]'::jsonb)
                             || CASE WHEN CAST(:query_class AS text) IS NULL THEN '[]'::jsonb
                                     ELSE to_jsonb(CAST(:query_class AS text)) END
                     ) AS value),
                    'endpoints',
                    (SELECT COALESCE(jsonb_agg(DISTINCT value), '[]'::jsonb)
                     FROM jsonb_array_elements_text(
                         COALESCE(coverage->'endpoints', '[]'::jsonb)
                             || COALESCE(CAST(:endpoints AS jsonb), '[]'::jsonb)
                     ) AS value)
                )
                || CASE WHEN CAST(:time_from AS text) IS NULL
                    THEN '{{}}'::jsonb ELSE jsonb_build_object(
                    'time_from', LEAST(
                        COALESCE(coverage->>'time_from', '9999-12-31'), CAST(:time_from AS text))
                ) END
                || CASE WHEN CAST(:time_to AS text) IS NULL
                    THEN '{{}}'::jsonb ELSE jsonb_build_object(
                    'time_to', GREATEST(
                        COALESCE(coverage->>'time_to', '0001-01-01'), CAST(:time_to AS text))
                ) END
            WHERE investigation_id = :id AND module = :module
        """),
        {
            "id": investigation_id,
            "module": module.value,
            "provider": provider,
            "query_class": query_class,
            "endpoints": json.dumps(sorted(set(endpoints or []))),
            "time_from": time_from,
            "time_to": time_to,
        },
    )


async def list_pending_leads(session: AsyncSession, investigation_id: UUID) -> list[dict]:
    """All PENDING leads for frontier selection, highest priority first."""
    rows = (
        (
            await session.execute(
                text("""
                SELECT id, lead_type, value, reason, originating_claim_id, priority,
                    depth, status, scope_area, trigger_type, information_need,
                    relation_depth, blocked_reason
                FROM leads
                WHERE investigation_id = :id AND status = 'PENDING'
                ORDER BY priority DESC, depth ASC
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def list_lead_identity_rows(
    session: AsyncSession, investigation_id: UUID
) -> list[dict]:
    """Minimal identity of every lead for planner dedup across reruns."""
    rows = (
        (
            await session.execute(
                text("""
                SELECT lead_type, scope_area, value, status
                FROM leads
                WHERE investigation_id = :id
            """),
                {"id": investigation_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
