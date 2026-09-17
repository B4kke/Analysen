from typing import Any

import httpx

from apps.api.app.sources.base import DiscoveryAdapter, DiscoveryResult


class SearxngAdapter(DiscoveryAdapter):
    provider_id = "searxng"

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    async def search(self, query: str, **kwargs: Any) -> list[DiscoveryResult]:
        params = {"q": query, "format": "json", **kwargs}
        response = await self.client.get(f"{self.base_url}/search", params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        return [
            DiscoveryResult(
                provider=self.provider_id,
                url=item["url"],
                title=item.get("title"),
                snippet=item.get("content"),
                rank=index + 1,
            )
            for index, item in enumerate(results)
            if item.get("url")
        ]
