from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
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
    TargetType,
)
from apps.api.app.domain.scope import (
    ExpansionState,
    InvestigationModuleRecord,
    ScopeModule,
    ScopeUpdate,
)
from apps.api.app.repositories.brreg_ingest import persist_brreg_organization
from apps.api.app.repositories.investigations import (
    InvestigationNotFound,
    create_investigation,
    get_investigation,
    get_investigation_record,
    get_modules,
    propose_lead,
    update_scope,
)
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.services.scope_gate import check_research_scope
from apps.api.app.sources.brreg import BrregAdapter

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
    session: DatabaseSession,
) -> InvestigationDetail:
    try:
        parsed_id = UUID(investigation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid investigation id") from exc

    try:
        return await get_investigation(session, parsed_id)
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc


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
