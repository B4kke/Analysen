import asyncio
from pathlib import Path
from typing import Any

import dramatiq

from apps.api.app.services.role_index_import import import_role_inventory
from apps.api.app.sources.brreg import BrregAdapter

# Configure the broker before any actor decorator registers an actor.
from apps.worker.app import broker as _broker  # noqa: F401


@dramatiq.actor(max_retries=2, time_limit=6 * 60 * 60 * 1000)
def refresh_brreg_role_inventory(
    destination: str = "data/ingest/brreg-roles.json.gz",
) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with BrregAdapter() as adapter:
            download = await adapter.download_role_inventory(Path(destination))
        result = await import_role_inventory(
            download.path,
            etag=download.etag,
            last_modified=download.last_modified,
        )
        return {
            "snapshot_id": str(result.snapshot_id),
            "sha256": result.sha256,
            "record_count": result.record_count,
            "reused": result.reused,
            "etag": download.etag,
            "last_modified": download.last_modified,
        }

    return asyncio.run(run())


@dramatiq.actor(max_retries=0, time_limit=30 * 60 * 1000)
def run_research_pass_actor(
    investigation_id: str, max_leads: int = 10, job_id: str | None = None
) -> dict[str, Any]:
    """Execute one bounded research pass for an investigation.

    Thin wrapper over services.research_loop: opens a session, runs the pass
    with the live BRREG adapter, and returns the audited summary. No retries:
    every lead outcome is already terminal and committed separately.
    """
    from uuid import UUID

    from apps.api.app.core.database import get_session_factory
    from apps.api.app.services.research_loop import run_research_pass

    async def run() -> dict[str, Any]:
        factory = get_session_factory()
        async with BrregAdapter() as adapter, factory() as session:
            return await run_research_pass(
                session,
                UUID(investigation_id),
                adapter.fetch,
                max_leads=max_leads,
                job_id=UUID(job_id) if job_id else None,
            )

    return asyncio.run(run())
