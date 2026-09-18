"""Deterministic lead executor with typed source routing (AQ-013/AQ-024).

Executes one admitted PENDING lead end to end: routes the lead type to
exactly one executor via services.source_router, re-gates at the tool
boundary (scope may have narrowed since admission), runs the type-specific
handler with injected tools, and records status, coverage and audit. Only
explicitly allowlisted lead types run; anything else fails closed with a
reason. No model calls.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
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

if TYPE_CHECKING:
    from apps.api.app.services.pdf_extraction import ExtractedDocument
    from apps.api.app.services.url_canonicalization import FetchResult
    from apps.api.app.sources.base import DiscoveryResult

FetchFn = Callable[[str], Awaitable[SourceRecord]]
SearxngSearchFn = Callable[[str], Awaitable[list["DiscoveryResult"]]]
WebFetchFn = Callable[[str], Awaitable["FetchResult"]]
PdfExtractFn = Callable[[bytes], "ExtractedDocument"]


@dataclass(frozen=True)
class ExecutorTools:
    """Injected source capabilities; absent tools fail closed as unavailable."""

    brreg_fetch: FetchFn | None = None
    searxng_search: SearxngSearchFn | None = None
    web_fetch: WebFetchFn | None = None
    pdf_extract: PdfExtractFn | None = None


async def execute_lead(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    tools: ExecutorTools | None = None,
) -> str:
    """Execute one PENDING lead; return the terminal status.

    Terminal statuses: COMPLETED, BLOCKED (gate refused at execution time),
    FAILED (unknown type, unavailable executor, bad reference, or source
    error). Every outcome is audited; failures carry a machine-readable
    blocked_reason.
    """
    tools = tools if tools is not None else ExecutorTools()
    # Deferred imports: the router and executors land as independent
    # deliverables; execute_lead must stay importable without them.
    from apps.api.app.services.source_router import UnknownLeadType, route_lead

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

    try:
        executor_name = route_lead(lead.lead_type)
    except UnknownLeadType:
        return await _fail(
            session, investigation_id, lead_id, "unsupported_lead_type"
        )

    decision = gate_lead(
        investigation,
        lead,
        expansion_state=ExpansionState.TARGET,
        source_enabled=True,
    )
    if decision is not None:
        return await refuse(decision)

    if executor_name == "brreg":
        return await _execute_brreg(
            session, investigation_id, lead_id, investigation, lead, tools
        )
    if executor_name == "searxng":
        if tools.searxng_search is None:
            return await _fail(session, investigation_id, lead_id, "executor_unavailable")
        from apps.api.app.services.executors.searxng_discovery import (
            execute_searxng_discovery,
        )

        return await execute_searxng_discovery(
            session, investigation_id, lead_id, lead, tools.searxng_search
        )
    if executor_name == "web_fetch":
        if tools.web_fetch is None:
            return await _fail(session, investigation_id, lead_id, "executor_unavailable")
        from apps.api.app.services.executors.web_fetch import execute_web_fetch

        return await execute_web_fetch(
            session, investigation_id, lead_id, lead, tools.web_fetch
        )
    if executor_name == "pdf":
        if tools.pdf_extract is None:
            return await _fail(session, investigation_id, lead_id, "executor_unavailable")
        from apps.api.app.services.executors.pdf_process import execute_pdf_process

        return await execute_pdf_process(
            session, investigation_id, lead_id, lead, tools.pdf_extract
        )
    return await _fail(session, investigation_id, lead_id, "unsupported_lead_type")


async def _execute_brreg(
    session: AsyncSession,
    investigation_id: UUID,
    lead_id: UUID,
    investigation: Any,
    lead: Lead,
    tools: ExecutorTools,
) -> str:
    """BRREG target lookup: the original AQ-013 path, unchanged in behavior."""
    if tools.brreg_fetch is None:
        return await _fail(session, investigation_id, lead_id, "executor_unavailable")
    if lead.scope_area != ScopeModule.BUSINESS_ROLES:
        await repository.set_lead_status(
            session, investigation_id, lead_id, "BLOCKED", "module_disabled"
        )
        await repository._audit(
            session,
            investigation_id,
            "LEAD_EXECUTION_REFUSED",
            {"lead_id": str(lead_id), "reason": "module_disabled"},
        )
        return "BLOCKED"

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
        await repository.set_lead_status(
            session, investigation_id, lead_id, "BLOCKED", "not_explicit_target"
        )
        await repository._audit(
            session,
            investigation_id,
            "LEAD_EXECUTION_REFUSED",
            {"lead_id": str(lead_id), "reason": "not_explicit_target"},
        )
        return "BLOCKED"

    await repository.set_lead_status(session, investigation_id, lead_id, "RUNNING")
    try:
        assert orgnr is not None
        assert tools.brreg_fetch is not None
        record = await tools.brreg_fetch(orgnr)
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
