"""Deterministic lead executor, first slice: BRREG target lookups (AQ-013).

Executes one admitted PENDING lead end to end: re-gates at the tool boundary
(scope may have narrowed since admission), fetches through the injected
adapter, persists via the normal ingest path, and records status, coverage
and audit. Only explicitly allowlisted lead types run; anything else fails
closed with a reason. No model calls.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.identifiers import InvalidOrganizationNumber, normalize_orgnr
from apps.api.app.domain.models import Lead, TargetType
from apps.api.app.domain.scope import ExpansionState, ScopeModule
from apps.api.app.repositories import investigations as repository
from apps.api.app.repositories.brreg_ingest import persist_brreg_organization
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.services.lead_gate import gate_lead
from apps.api.app.sources.base import SourceRecord

# The only lead types the executor knows how to run. Everything else fails
# closed instead of being guessed at.
SUPPORTED_LEAD_TYPES = frozenset({"brreg_organization_lookup"})

FetchFn = Callable[[str], Awaitable[SourceRecord]]


async def execute_lead(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    fetch: FetchFn,
) -> str:
    """Execute one PENDING lead; return the terminal status.

    Terminal statuses: COMPLETED, BLOCKED (gate refused at execution time),
    FAILED (unsupported type, bad reference, or source error). Every outcome
    is audited; failures carry a machine-readable blocked_reason.
    """
    investigation = await repository.get_investigation_record(
        session, investigation_id, for_update=True
    )
    lead_row = await repository.get_lead(session, investigation_id, lead_id)
    if lead_row["status"] != "PENDING":
        return lead_row["status"]

    lead = Lead.model_validate(
        {
            "lead_type": lead_row["lead_type"],
            "value": lead_row["value"],
            "reason": lead_row["reason"],
            "priority": lead_row["priority"],
            "depth": lead_row["depth"],
            "originating_claim_id": lead_row["originating_claim_id"],
            "scope_area": lead_row["scope_area"],
            "trigger_type": lead_row["trigger_type"],
            "information_need": lead_row["information_need"],
            "relation_depth": lead_row["relation_depth"],
        }
    )

    async def refuse(reason: str) -> str:
        await repository.set_lead_status(
            session, investigation_id, lead_id, "BLOCKED", reason
        )
        await repository._audit(
            session,
            investigation_id,
            "LEAD_EXECUTION_REFUSED",
            {"lead_id": str(lead_id), "reason": reason},
        )
        return "BLOCKED"

    if lead.lead_type not in SUPPORTED_LEAD_TYPES:
        return await _fail(
            session, investigation_id, lead_id, "unsupported_lead_type"
        )
    if lead.scope_area != ScopeModule.BUSINESS_ROLES:
        return await refuse("module_disabled")

    orgnr = (lead.value or {}).get("orgnr") if isinstance(lead.value, dict) else None
    try:
        orgnr = normalize_orgnr(str(orgnr)) if orgnr else None
    except InvalidOrganizationNumber:
        orgnr = None
    is_target = (
        investigation.target.type in (TargetType.ORGANIZATION, TargetType.COMPANY)
        and orgnr is not None
        and orgnr in investigation.target.known_orgnrs
        and len(investigation.target.known_orgnrs) == 1
    )
    if not is_target:
        # Related entities require the scheduler/materiality workflow (later):
        # the executor never follows a relation on its own.
        return await refuse("not_explicit_target")

    decision = gate_lead(
        investigation,
        lead,
        expansion_state=ExpansionState.TARGET,
        source_enabled=True,
    )
    if decision is not None:
        return await refuse(decision)

    await repository.set_lead_status(session, investigation_id, lead_id, "RUNNING")
    try:
        assert orgnr is not None
        record = await fetch(orgnr)
        organization = normalize_brreg_organization(record.payload)
        await persist_brreg_organization(session, investigation_id, record, organization)
    except Exception as exc:
        return await _fail(
            session, investigation_id, lead_id, f"source_error:{type(exc).__name__}"
        )
    await repository.set_lead_status(session, investigation_id, lead_id, "COMPLETED")
    await repository.bump_module_coverage(
        session, investigation_id, ScopeModule.BUSINESS_ROLES, provider="brreg_entities"
    )
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {"lead_id": str(lead_id), "status": "COMPLETED"},
    )
    return "COMPLETED"


async def _fail(
    session: AsyncSession, investigation_id: UUID, lead_id: UUID, reason: str
) -> str:
    await repository.set_lead_status(session, investigation_id, lead_id, "FAILED", reason)
    await repository._audit(
        session,
        investigation_id,
        "LEAD_EXECUTED",
        {"lead_id": str(lead_id), "status": "FAILED", "reason": reason},
    )
    return "FAILED"
