import httpx

from apps.api.app.sources.base import SourceAdapter, SourceRecord


class RdapAdapter(SourceAdapter):
    source_id = "rdap"

    def __init__(self, resolver_base: str = "https://rdap.org/domain", client: httpx.AsyncClient | None = None) -> None:
        self.resolver_base = resolver_base.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True, max_redirects=3)

    async def fetch(self, identifier: str) -> SourceRecord:
        domain = identifier.strip().lower().rstrip(".")
        url = f"{self.resolver_base}/{domain}"
        response = await self.client.get(url)
        response.raise_for_status()
        return SourceRecord(self.source_id, domain, response.json(), str(response.url))
