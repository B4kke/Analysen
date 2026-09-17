from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.database import get_db_session
from apps.api.app.domain.identifiers import InvalidOrganizationNumber
from apps.api.app.domain.models import (
    BrregIngestResult,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationRecord,
)
from apps.api.app.repositories.brreg_ingest import persist_brreg_organization
from apps.api.app.repositories.investigations import (
    InvestigationNotFound,
    create_investigation,
    get_investigation,
)
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
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
        await get_investigation(session, parsed_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid investigation id") from exc
    except InvestigationNotFound as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc

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
    await session.commit()
    return result
