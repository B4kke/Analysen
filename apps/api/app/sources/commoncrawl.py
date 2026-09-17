import httpx


class CommonCrawlAdapter:
    collinfo_url = "https://index.commoncrawl.org/collinfo.json"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    async def indexes(self) -> list[dict]:
        response = await self.client.get(self.collinfo_url)
        response.raise_for_status()
        return response.json()

    async def search_latest(self, url_pattern: str) -> list[dict]:
        indexes = await self.indexes()
        if not indexes:
            return []
        api = indexes[0]["cdx-api"]
        response = await self.client.get(api, params={"url": url_pattern, "output": "json"})
        response.raise_for_status()
        records: list[dict] = []
        for line in response.text.splitlines():
            if line.strip():
                import json
                records.append(json.loads(line))
        return records
