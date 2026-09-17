import httpx
from fastapi import APIRouter, HTTPException, Query

from apps.api.app.domain.identifiers import InvalidOrganizationNumber
from apps.api.app.domain.models import BrregOrganization
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.sources.brreg import BrregAdapter

router = APIRouter(prefix="/api/v1/brreg", tags=["brreg"])


@router.get("/search", response_model=list[BrregOrganization])
async def search_organizations(
    name: str = Query(min_length=2, max_length=200),
    page: int = Query(default=0, ge=0),
    size: int = Query(default=20, ge=1, le=100),
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
