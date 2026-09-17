import json
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_active_snapshot(session: AsyncSession) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id, sha256, status, record_count, storage_path, etag,
                       last_modified, completed_at
                FROM brreg_role_snapshots
                WHERE status = 'ACTIVE'
                LIMIT 1
                """
            )
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def find_snapshot_by_hash(session: AsyncSession, sha256: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id, sha256, status, record_count, storage_path, etag, last_modified
                FROM brreg_role_snapshots
                WHERE sha256 = :sha256
                """
            ),
            {"sha256": sha256},
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def create_role_snapshot(
    session: AsyncSession,
    *,
    sha256: str,
    storage_path: str,
    etag: str | None,
    last_modified: str | None,
) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO brreg_role_snapshots (
                    sha256, etag, last_modified, storage_path, status
                )
                VALUES (:sha256, :etag, :last_modified, :storage_path, 'IMPORTING')
                RETURNING id
                """
            ),
            {
                "sha256": sha256,
                "etag": etag,
                "last_modified": last_modified,
                "storage_path": storage_path,
            },
        )
    ).mappings().one()
    return row["id"]


async def insert_role_batch(
    session: AsyncSession,
    snapshot_id: UUID,
    rows: Sequence[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    parameters = [
        {
            "snapshot_id": snapshot_id,
            "normalized_name": row["normalized_name"],
            "display_name": row["display_name"],
            "birth_date": row.get("birth_date"),
            "orgnr": row["orgnr"],
            "role_code": row["role_code"],
            "role_description": row.get("role_description"),
            "raw_record": json.dumps(row["raw_record"], ensure_ascii=False, sort_keys=True),
        }
        for row in rows
    ]
    await session.execute(
        text(
            """
            INSERT INTO brreg_role_index (
                snapshot_id,
                normalized_name,
                display_name,
                birth_date,
                orgnr,
                role_code,
                role_description,
                raw_record
            )
            VALUES (
                :snapshot_id,
                :normalized_name,
                :display_name,
                :birth_date,
                :orgnr,
                :role_code,
                :role_description,
                CAST(:raw_record AS jsonb)
            )
            """
        ),
        parameters,
    )
    return len(parameters)


async def activate_role_snapshot(
    session: AsyncSession,
    snapshot_id: UUID,
    record_count: int,
) -> None:
    await session.execute(
        text(
            """
            UPDATE brreg_role_snapshots
            SET status = 'SUPERSEDED'
            WHERE status = 'ACTIVE' AND id <> :snapshot_id
            """
        ),
        {"snapshot_id": snapshot_id},
    )
    result = await session.execute(
        text(
            """
            UPDATE brreg_role_snapshots
            SET status = 'ACTIVE',
                record_count = :record_count,
                completed_at = now(),
                error_message = NULL
            WHERE id = :snapshot_id AND status = 'IMPORTING'
            """
        ),
        {"snapshot_id": snapshot_id, "record_count": record_count},
    )
    if result.rowcount != 1:
        raise RuntimeError("Role snapshot could not be activated")


async def fail_role_snapshot(
    session: AsyncSession,
    snapshot_id: UUID,
    error_message: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE brreg_role_snapshots
            SET status = 'FAILED', completed_at = now(), error_message = :error_message
            WHERE id = :snapshot_id AND status = 'IMPORTING'
            """
        ),
        {"snapshot_id": snapshot_id, "error_message": error_message[:4000]},
    )


async def find_active_person_roles(
    session: AsyncSession,
    *,
    normalized_name: str,
    birth_date: date | None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT
                    i.display_name,
                    i.birth_date,
                    i.orgnr,
                    i.role_code,
                    i.role_description,
                    i.raw_record
                FROM brreg_role_index i
                JOIN brreg_role_snapshots s ON s.id = i.snapshot_id
                WHERE s.status = 'ACTIVE'
                  AND i.normalized_name = :normalized_name
                  AND (:birth_date IS NULL OR i.birth_date = :birth_date)
                ORDER BY i.orgnr, i.role_code
                LIMIT :limit
                """
            ),
            {
                "normalized_name": normalized_name,
                "birth_date": birth_date,
                "limit": min(max(limit, 1), 1000),
            },
        )
    ).mappings().all()
    return [dict(row) for row in rows]
