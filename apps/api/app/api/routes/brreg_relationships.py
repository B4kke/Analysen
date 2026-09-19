from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query

from apps.api.app.domain.brreg_relationships import BrregGroupStructure, BrregLegalRoleLookup
from apps.api.app.domain.identifiers import InvalidOrganizationNumber
from apps.api.app.services.brreg_relationships import (
    normalize_brreg_group_structure,
    normalize_brreg_legal_roles,
)
from apps.api.app.sources.brreg import BrregAdapter

router = APIRouter(prefix="/api/v1/brreg", tags=["brreg"])
LegalRolePageSize = Annotated[int, Query(ge=1, le=1000)]
SearchAfter = Annotated[str | None, Query(min_length=1, max_length=100)]


@router.get("/organizations/{orgnr}/legal-roles", response_model=BrregLegalRoleLookup)
async def get_organization_legal_roles(
    orgnr: str,
    search_after: SearchAfter = None,
    size: LegalRolePageSize = 100,
) -> BrregLegalRoleLookup:
    try:
        async with BrregAdapter() as adapter:
            record = await adapter.get_legal_roles(orgnr, search_after=search_after, size=size)
    except InvalidOrganizationNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Organization not found in BRREG") from exc
        raise HTTPException(status_code=502, detail="BRREG returned an upstream error") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach BRREG") from exc

    return normalize_brreg_legal_roles(record.external_id, record.payload, page_size=size)


@router.get("/organizations/{orgnr}/group-structure", response_model=BrregGroupStructure)
async def get_organization_group_structure(orgnr: str) -> BrregGroupStructure:
    try:
        async with BrregAdapter() as adapter:
            record = await adapter.get_group_structure(orgnr)
    except InvalidOrganizationNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Group structure not found in BRREG",
            ) from exc
        raise HTTPException(status_code=502, detail="BRREG returned an upstream error") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach BRREG") from exc

    return normalize_brreg_group_structure(record.external_id, record.payload)
