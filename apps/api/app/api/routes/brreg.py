from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.database import get_db_session
from apps.api.app.domain.identifiers import InvalidOrganizationNumber
from apps.api.app.domain.models import (
    BrregOrganization,
    BrregPersonRoleSearch,
    BrregRoleIndexStatus,
    BrregRoleLookup,
)
from apps.api.app.repositories.role_index import get_active_snapshot
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.services.brreg_roles import normalize_brreg_roles
from apps.api.app.services.person_role_search import (
    RoleIndexUnavailable,
    search_person_business_roles,
)
from apps.api.app.sources.brreg import BrregAdapter

router = APIRouter(prefix="/api/v1/brreg", tags=["brreg"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
SearchName = Annotated[str, Query(min_length=2, max_length=200)]
SearchPage = Annotated[int, Query(ge=0)]
SearchSize = Annotated[int, Query(ge=1, le=100)]
BirthDate = Annotated[date, Query()]
SearchLimit = Annotated[int, Query(ge=1, le=1000)]


@router.get("/search", response_model=list[BrregOrganization])
async def search_organizations(
    name: SearchName,
    page: SearchPage = 0,
    size: SearchSize = 20,
) -> list[BrregOrganization]:
    try:
        async with BrregAdapter() as adapter:
            payload = await adapter.search_by_name(name, page=page, size=size)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="BRREG returned an upstream error") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach BRREG") from exc

    items = (payload.get("_embedded") or {}).get("enheter") or []
    return [normalize_brreg_organization(item) for item in items if isinstance(item, dict)]


@router.get("/role-index/status", response_model=BrregRoleIndexStatus)
async def role_index_status(session: DatabaseSession) -> BrregRoleIndexStatus:
    snapshot = await get_active_snapshot(session)
    if snapshot is None:
        return BrregRoleIndexStatus(available=False)
    return BrregRoleIndexStatus(
        available=True,
        snapshot_id=snapshot["id"],
        sha256=snapshot["sha256"],
        record_count=snapshot["record_count"],
        last_modified=snapshot["last_modified"],
        completed_at=snapshot["completed_at"],
    )


@router.get("/person-roles", response_model=BrregPersonRoleSearch)
async def person_roles(
    session: DatabaseSession,
    name: SearchName,
    birth_date: BirthDate,
    limit: SearchLimit = 250,
) -> BrregPersonRoleSearch:
    try:
        return await search_person_business_roles(
            session,
            name=name,
            birth_date=birth_date,
            limit=limit,
        )
    except RoleIndexUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/organizations/{orgnr}/roles", response_model=BrregRoleLookup)
async def get_organization_roles(orgnr: str) -> BrregRoleLookup:
    try:
        async with BrregAdapter() as adapter:
            record = await adapter.get_roles(orgnr)
    except InvalidOrganizationNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Organization not found in BRREG") from exc
        raise HTTPException(status_code=502, detail="BRREG returned an upstream error") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach BRREG") from exc

    return normalize_brreg_roles(record.external_id, record.payload)


@router.get("/organizations/{orgnr}", response_model=BrregOrganization)
async def get_organization(orgnr: str) -> BrregOrganization:
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

    return normalize_brreg_organization(record.payload)
