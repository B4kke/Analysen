from typing import Any

import httpx

from apps.api.app.sources.base import SourceAdapter, SourceRecord


class GleifAdapter(SourceAdapter):
    source_id = "gleif"
    base_url = "https://api.gleif.org/api/v1"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    async def fetch(self, identifier: str) -> SourceRecord:
        url = f"{self.base_url}/lei-records/{identifier}"
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord(self.source_id, identifier, response.json(), url)

    async def search_legal_name(self, name: str, page_size: int = 20) -> dict[str, Any]:
        url = f"{self.base_url}/lei-records"
        params = {
            "filter[entity.legalName]": name,
            "page[size]": page_size,
        }
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()
