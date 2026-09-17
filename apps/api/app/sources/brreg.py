from pathlib import Path
from typing import Any

import httpx

from apps.api.app.sources.base import SourceAdapter, SourceRecord


class BrregAdapter(SourceAdapter):
    source_id = "brreg_entities"
    base_url = "https://data.brreg.no/enhetsregisteret/api"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    async def search_entities(self, **params: Any) -> dict[str, Any]:
        response = await self.client.get(f"{self.base_url}/enheter", params=params)
        response.raise_for_status()
        return response.json()

    async def fetch(self, identifier: str) -> SourceRecord:
        url = f"{self.base_url}/enheter/{identifier}"
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord(self.source_id, identifier, response.json(), url)

    async def get_roles(self, orgnr: str) -> SourceRecord:
        url = f"{self.base_url}/enheter/{orgnr}/roller"
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord("brreg_roles", orgnr, response.json(), url)

    async def get_legal_roles(self, orgnr: str) -> SourceRecord:
        url = f"{self.base_url}/roller/enheter/{orgnr}/juridiskeroller"
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord("brreg_legal_roles", orgnr, response.json(), url)

    async def get_group_structure(self, orgnr: str) -> SourceRecord:
        url = f"{self.base_url}/konsernstruktur/{orgnr}"
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord("brreg_group_structure", orgnr, response.json(), url)

    async def download_role_inventory(self, destination: Path) -> Path:
        url = f"{self.base_url}/roller/totalbestand"
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    handle.write(chunk)
        return destination
