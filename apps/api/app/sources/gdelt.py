from typing import Any

import httpx

from apps.api.app.sources.base import DiscoveryAdapter, DiscoveryResult


class GdeltAdapter(DiscoveryAdapter):
    provider_id = "gdelt"
    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    async def search(self, query: str, **kwargs: Any) -> list[DiscoveryResult]:
        params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": 50, **kwargs}
        response = await self.client.get(self.base_url, params=params)
        response.raise_for_status()
        articles = response.json().get("articles", [])
        return [
            DiscoveryResult(
                provider=self.provider_id,
                url=item["url"],
                title=item.get("title"),
                snippet=None,
                rank=index + 1,
            )
            for index, item in enumerate(articles)
            if item.get("url")
        ]
