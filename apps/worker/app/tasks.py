import asyncio
from pathlib import Path

import dramatiq

from apps.api.app.sources.brreg import BrregAdapter


@dramatiq.actor(max_retries=3)
def download_brreg_role_inventory(destination: str = "data/ingest/brreg-roles.zip") -> str:
    async def run() -> str:
        adapter = BrregAdapter()
        path = await adapter.download_role_inventory(Path(destination))
        await adapter.client.aclose()
        return str(path)

    return asyncio.run(run())
