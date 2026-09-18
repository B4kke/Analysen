import asyncio
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import get_settings
from apps.api.app.core.database import get_db_session
from apps.api.app.domain.identifiers import InvalidOrganizationNumber, normalize_orgnr
from apps.api.app.domain.models import (
    BrregIngestResult,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationRecord,
    Lead,
    ResolutionReview,
    TargetType,
)
from apps.api.app.domain.scope import (
    ExpansionPolicy,
    ExpansionState,
    InvestigationModuleRecord,
    ScopeModule,
    ScopeSettings,
    ScopeUpdate,
)
from apps.api.app.repositories import investigations as repository
from apps.api.app.repositories.brreg_ingest import persist_brreg_organization
from apps.api.app.repositories.investigations import (
    InvestigationNotFound,
    create_investigation,
    delete_investigation,
    export_investigation,
    get_investigation,
    get_investigation_record,
    get_modules,
    propose_lead,
    update_scope,
)
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.services.lead_executor import execute_lead
from apps.api.app.services.raw_store import RawSnapshotUnavailable, load_raw_bytes
from apps.api.app.services.report_sections import report_sections
from apps.api.app.services.scope_gate import check_research_scope
from apps.api.app.sources.brreg import BrregAdapter


def _scope_of(modules: list[InvestigationModuleRecord]) -> ScopeSettings:
    return ScopeSettings(
        scope_modules=[module.module for module in modules if module.enabled],
        expansion_policy=ExpansionPolicy.DIRECT_RELATIONS,
        max_relation_depth=1,
    )


router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("", response_model=InvestigationRecord, status_code=status.HTTP_201_CREATED)
async def create_investigation_endpoint(
    request: InvestigationCreate,
    session: DatabaseSession,
) -> InvestigationRecord:
    investigation = await create_investigation(session, request)
    await session.commit()
    return investigation


@router.get("/{investigation_id}", response_model=InvestigationDetail)
async def get_investigation_endpoint(
    investigation_id: str,
    response: Response,
    session: DatabaseSession,
) -> InvestigationDetail:
    try:
        parsed_id = UUID(investigation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid investigation id") from exc

    response.headers["Cache-Control"] = "no-store"
    # A pass may commit between queries. Read its activity, claims and coverage
    # from one snapshot so terminal status cannot hide newly committed findings.
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    try:
        return await get_investigation(session, parsed_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc


@router.get("/{investigation_id}/evidence/{evidence_id}/raw")
async def raw_evidence_endpoint(
    investigation_id: UUID,
    evidence_id: UUID,
    session: DatabaseSession,
) -> Response:
    """Download the original attached snapshot, never executable HTML inline."""
    try:
        await get_investigation_record(session, investigation_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    row = (
        (
            await session.execute(
                text("""
        SELECT d.sha256, d.raw_storage_key
        FROM evidence e JOIN documents d ON d.id = e.document_id
        JOIN investigation_documents link ON link.document_id = d.id
        WHERE e.id = :evidence_id AND link.investigation_id = :investigation_id
    """),
                {"evidence_id": evidence_id, "investigation_id": investigation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found in investigation")
    if not row["raw_storage_key"]:
        raise HTTPException(status_code=410, detail="Original snapshot is unavailable")
    try:
        content = await asyncio.to_thread(load_raw_bytes, row["raw_storage_key"], row["sha256"])
    except RawSnapshotUnavailable as exc:
        structlog.get_logger().warning("raw_snapshot_unavailable", evidence_id=str(evidence_id))
        raise HTTPException(status_code=410, detail="Original snapshot is unavailable") from exc
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="original-{row["sha256"]}.snapshot"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/{investigation_id}/scope", response_model=InvestigationDetail)
async def update_scope_endpoint(
    investigation_id: UUID, request: ScopeUpdate, session: DatabaseSession
) -> InvestigationDetail:
    try:
        record = await update_scope(session, investigation_id, request)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    await session.commit()
    return record


@router.get("/{investigation_id}/modules", response_model=list[InvestigationModuleRecord])
async def modules_endpoint(
    investigation_id: UUID, session: DatabaseSession
) -> list[InvestigationModuleRecord]:
    try:
        return await get_modules(session, investigation_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc


@router.get("/{investigation_id}/report/sections")
async def report_sections_endpoint(investigation_id: UUID, session: DatabaseSession) -> dict:
    """Dynamic report sections that separate investigated, incomplete,
    not investigated, unavailable and not selected modules.

    Absence of findings in a disabled module is never presented as a negative
    finding: it lands in its own section.
    """
    try:
        modules = await get_modules(session, investigation_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    return report_sections(_scope_of(modules), modules)


@router.post("/{investigation_id}/leads", status_code=status.HTTP_201_CREATED)
async def propose_lead_endpoint(
    investigation_id: UUID, request: Lead, session: DatabaseSession
) -> dict:
    """Persist a planner/model-proposed lead only after the deterministic scope gate.

    A refused lead is not an error: it is stored as BLOCKED with the gate's
    reason so that proposals and refusals remain auditable.
    """
    try:
        lead_id, lead_status = await propose_lead(session, investigation_id, request)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    await session.commit()
    return {"lead_id": str(lead_id), "status": lead_status}


@router.get("/{investigation_id}/export")
async def export_investigation_endpoint(investigation_id: UUID, session: DatabaseSession) -> dict:
    """Full per-investigation export for data portability and retention review."""
    try:
        return await export_investigation(session, investigation_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc


@router.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation_endpoint(investigation_id: UUID, session: DatabaseSession) -> None:
    """Erase one investigation with all cascade-owned data; audited on the way out."""
    try:
        await delete_investigation(session, investigation_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    await session.commit()


@router.post("/{investigation_id}/leads/{lead_id}/execute")
async def execute_lead_endpoint(
    investigation_id: UUID, lead_id: UUID, session: DatabaseSession
) -> dict:
    """Execute one admitted PENDING lead through the tool-boundary gate.

    Only allowlisted lead types run; the gate is re-checked at execution time
    because scope may have narrowed since admission. Terminal statuses
    (COMPLETED/BLOCKED/FAILED) are returned, never raised, so the frontier
    can keep working through refusals and failures.
    """
    try:
        async with BrregAdapter() as adapter:
            status = await execute_lead(session, investigation_id, lead_id, adapter.fetch)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation or lead not found") from exc
    await session.commit()
    return {"lead_id": str(lead_id), "status": status}


@router.post("/{investigation_id}/research/run", status_code=status.HTTP_202_ACCEPTED)
async def run_research_endpoint(investigation_id: UUID, session: DatabaseSession) -> dict:
    """Enqueue one bounded worker research pass over the admitted frontier.

    Returns immediately; the worker commits each lead separately and audits a
    RESEARCH_PASS_COMPLETED summary when the pass ends.
    """
    from apps.worker.app.tasks import run_research_pass_actor

    try:
        await get_investigation_record(session, investigation_id, for_update=True)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    current = await repository.get_research_state(session, investigation_id)
    if current.status in {"REQUESTED", "ENQUEUED", "RUNNING"}:
        raise HTTPException(status_code=409, detail="A research pass is already pending or running")
    job_id = uuid4()
    await repository._audit(
        session, investigation_id, "RESEARCH_PASS_REQUESTED", {"job_id": str(job_id)}
    )
    await session.commit()
    try:
        run_research_pass_actor.send(str(investigation_id), job_id=str(job_id))
    except Exception as exc:
        await repository._audit(
            session,
            investigation_id,
            "RESEARCH_PASS_FAILED",
            {"job_id": str(job_id), "error_code": "enqueue_failed"},
        )
        await session.commit()
        structlog.get_logger().error(
            "research_enqueue_failed", job_id=str(job_id), error_type=type(exc).__name__
        )
        raise HTTPException(status_code=503, detail="Could not enqueue research pass") from exc
    await repository._audit(
        session, investigation_id, "RESEARCH_PASS_ENQUEUED", {"job_id": str(job_id)}
    )
    await session.commit()
    return {"investigation_id": str(investigation_id), "status": "ENQUEUED", "job_id": str(job_id)}


@router.get("/{investigation_id}/resolution/candidates")
async def list_resolution_candidates_endpoint(
    investigation_id: UUID, session: DatabaseSession
) -> list[dict]:
    """List entity resolution candidates with scores and negative signals."""
    from apps.api.app.repositories import entity_resolution as resolution_repo

    try:
        await get_investigation_record(session, investigation_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    return await resolution_repo.list_resolution_candidates(session, investigation_id)


@router.post("/{investigation_id}/resolution/{entity_id}/{candidate_entity_id}")
async def review_resolution_candidate_endpoint(
    investigation_id: UUID,
    entity_id: UUID,
    candidate_entity_id: UUID,
    request: ResolutionReview,
    session: DatabaseSession,
) -> dict:
    """Apply a manual review decision to a resolution candidate.

    Only PROBABLE_MATCH -> MATCH/NOT_MATCH and UNRESOLVED -> NOT_MATCH are
    permitted; anything else is a 409 Conflict. The decision is audited.
    """
    from apps.api.app.repositories import entity_resolution as resolution_repo
    from apps.api.app.repositories.entity_resolution import IllegalResolutionTransition

    try:
        outcome = await resolution_repo.review_resolution_candidate(
            session,
            investigation_id,
            entity_id,
            candidate_entity_id,
            request.status,
            request.reason,
        )
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
    except IllegalResolutionTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return {"entity_id": str(entity_id), "candidate_entity_id": str(candidate_entity_id), **outcome}


@router.post(
    "/{investigation_id}/sources/brreg/organizations/{orgnr}",
    response_model=BrregIngestResult,
)
async def ingest_brreg_organization_endpoint(
    investigation_id: str,
    orgnr: str,
    session: DatabaseSession,
) -> BrregIngestResult:
    try:
        parsed_id = UUID(investigation_id)
        investigation = await get_investigation_record(session, parsed_id, for_update=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid investigation id") from exc
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc

    try:
        orgnr = normalize_orgnr(orgnr)
    except InvalidOrganizationNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Only the explicitly identified organization target is executable today.
    # Related entities require persisted provenance/materiality in the future scheduler.
    is_target = (
        investigation.target.type in (TargetType.ORGANIZATION, TargetType.COMPANY)
        and orgnr in investigation.target.known_orgnrs
        and len(investigation.target.known_orgnrs) == 1
    )
    _, sources, _ = get_settings().validate_yaml_configs()
    source = sources.sources.get("brreg_entities")
    decision = check_research_scope(
        investigation,
        module=ScopeModule.BUSINESS_ROLES,
        information_need="Verify the explicitly identified target organization in BRREG",
        expansion_state=ExpansionState.TARGET if is_target else ExpansionState.CONTEXT_ONLY,
        relation_depth=0 if is_target else 1,
        source_enabled=source is not None and source.enabled,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)

    try:
        async with BrregAdapter() as adapter:
            record = await adapter.fetch(orgnr)
    except InvalidOrganizationNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Organization not found in BRREG") from exc
        raise HTTPException(status_code=502, detail="BRREG returned an upstream error") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach BRREG") from exc

    organization = normalize_brreg_organization(record.payload)
    result = await persist_brreg_organization(session, parsed_id, record, organization)
    await session.execute(
        text("""
            UPDATE investigation_entities SET expansion_state = 'TARGET', relation_depth = 0
            WHERE investigation_id = :id AND entity_id = :entity_id
        """),
        {"id": parsed_id, "entity_id": result.entity_id},
    )
    await session.commit()
    return result
