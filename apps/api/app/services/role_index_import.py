from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.app.core.database import get_session_factory
from apps.api.app.repositories.role_index import (
    activate_role_snapshot,
    create_role_snapshot,
    fail_role_snapshot,
    find_snapshot_by_hash,
    insert_role_batch,
)
from apps.api.app.services.brreg_role_inventory import iter_person_role_rows, sha256_file


@dataclass(frozen=True)
class RoleIndexImportResult:
    snapshot_id: UUID
    sha256: str
    record_count: int
    reused: bool


async def import_role_inventory(
    path: Path,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    batch_size: int = 5000,
) -> RoleIndexImportResult:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    digest = sha256_file(path)
    session_factory = get_session_factory()

    async with session_factory() as session:
        existing = await find_snapshot_by_hash(session, digest)
        if existing and existing["status"] == "ACTIVE":
            return RoleIndexImportResult(
                snapshot_id=existing["id"],
                sha256=digest,
                record_count=existing["record_count"],
                reused=True,
            )
        if existing and existing["status"] == "SUPERSEDED":
            await activate_role_snapshot(session, existing["id"], existing["record_count"])
            await session.commit()
            return RoleIndexImportResult(
                snapshot_id=existing["id"],
                sha256=digest,
                record_count=existing["record_count"],
                reused=True,
            )
        if existing and existing["status"] == "IMPORTING":
            raise RuntimeError("This BRREG role snapshot is already being imported")
        if existing and existing["status"] == "FAILED":
            await session.execute(
                text("DELETE FROM brreg_role_snapshots WHERE id = :snapshot_id"),
                {"snapshot_id": existing["id"]},
            )
            await session.commit()

        snapshot_id = await create_role_snapshot(
            session,
            sha256=digest,
            storage_path=str(path),
            etag=etag,
            last_modified=last_modified,
        )
        await session.commit()

    record_count = 0
    batch: list[dict[str, Any]] = []
    try:
        for row in iter_person_role_rows(path):
            batch.append(row)
            if len(batch) < batch_size:
                continue
            async with session_factory() as session:
                record_count += await insert_role_batch(session, snapshot_id, batch)
                await session.commit()
            batch.clear()

        if batch:
            async with session_factory() as session:
                record_count += await insert_role_batch(session, snapshot_id, batch)
                await session.commit()

        async with session_factory() as session:
            await activate_role_snapshot(session, snapshot_id, record_count)
            await session.commit()
    except Exception as exc:
        async with session_factory() as session:
            await fail_role_snapshot(session, snapshot_id, str(exc))
            await session.commit()
        raise

    return RoleIndexImportResult(
        snapshot_id=snapshot_id,
        sha256=digest,
        record_count=record_count,
        reused=False,
    )
