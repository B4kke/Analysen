import asyncio
from datetime import date
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import (
    BrregPersonRoleMatch,
    BrregPersonRoleSearch,
)
from apps.api.app.repositories.role_index import (
    find_active_person_roles,
    get_active_snapshot,
)
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.services.entity_resolution import normalize_name
from apps.api.app.services.norway_business_context import is_business_role_context
from apps.api.app.sources.brreg import BrregAdapter


class RoleIndexUnavailable(RuntimeError):
    pass


async def search_person_business_roles(
    session: AsyncSession,
    *,
    name: str,
    birth_date: date,
    limit: int = 250,
) -> BrregPersonRoleSearch:
    snapshot = await get_active_snapshot(session)
    if snapshot is None:
        raise RoleIndexUnavailable("No active BRREG role snapshot is available")

    rows = await find_active_person_roles(
        session,
        normalized_name=normalize_name(name),
        birth_date=birth_date,
        limit=limit,
    )
    if not rows:
        return BrregPersonRoleSearch(
            query_name=name,
            birth_date=birth_date,
            snapshot_id=snapshot["id"],
        )

    rows_by_orgnr: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_orgnr.setdefault(str(row["orgnr"]), []).append(row)

    semaphore = asyncio.Semaphore(6)
    verified: dict[str, Any] = {}
    unverified: list[str] = []

    async with BrregAdapter() as adapter:

        async def verify_organization(orgnr: str) -> None:
            async with semaphore:
                try:
                    record = await adapter.fetch(orgnr)
                    organization = normalize_brreg_organization(record.payload)
                except (httpx.HTTPError, ValueError):
                    unverified.append(orgnr)
                    return
                if is_business_role_context(organization):
                    verified[orgnr] = organization

        await asyncio.gather(*(verify_organization(orgnr) for orgnr in rows_by_orgnr))

    matches: list[BrregPersonRoleMatch] = []
    for orgnr, organization in verified.items():
        for row in rows_by_orgnr[orgnr]:
            row_birth_date = row.get("birth_date")
            if row_birth_date != birth_date:
                continue
            matches.append(
                BrregPersonRoleMatch(
                    person_name=str(row["display_name"]),
                    birth_date=birth_date,
                    organization_number=orgnr,
                    organization_name=organization.name,
                    organization_form_code=organization.organization_form_code,
                    role_code=str(row["role_code"]),
                    role_description=row.get("role_description"),
                )
            )

    matches.sort(key=lambda item: (item.organization_name, item.role_code))
    unverified.sort()
    return BrregPersonRoleSearch(
        query_name=name,
        birth_date=birth_date,
        snapshot_id=snapshot["id"],
        matches=matches,
        incomplete=bool(unverified),
        unverified_organization_numbers=unverified,
    )
