from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.api.app.domain.identifiers import normalize_orgnr
from apps.api.app.sources.base import SourceAdapter, SourceRecord


@dataclass(frozen=True)
class RoleInventoryDownload:
    path: Path
    etag: str | None
    last_modified: str | None
    content_type: str | None


class BrregAdapter(SourceAdapter):
    source_id = "brreg_entities"
    base_url = "https://data.brreg.no/enhetsregisteret/api"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                "User-Agent": "Analysen/0.1 (+https://github.com/B4kke/Analysen)",
            },
        )

    async def __aenter__(self) -> "BrregAdapter":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=2.0),
        reraise=True,
    )
    async def _get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    async def search_entities(self, **params: Any) -> dict[str, Any]:
        return await self._get_json(f"{self.base_url}/enheter", params=params)

    async def search_by_name(self, name: str, *, page: int = 0, size: int = 20) -> dict[str, Any]:
        return await self.search_entities(
            navn=name,
            navnMetodeForSoek="FORTLOEPENDE",
            page=page,
            size=min(max(size, 1), 100),
        )

    async def fetch(self, identifier: str) -> SourceRecord:
        orgnr = normalize_orgnr(identifier)
        url = f"{self.base_url}/enheter/{orgnr}"
        payload = await self._get_json(url)
        return SourceRecord(self.source_id, orgnr, payload, url)

    async def get_roles(self, orgnr: str) -> SourceRecord:
        normalized = normalize_orgnr(orgnr)
        url = f"{self.base_url}/enheter/{normalized}/roller"
        payload = await self._get_json(url)
        return SourceRecord("brreg_roles", normalized, payload, url)

    async def get_legal_roles(self, orgnr: str) -> SourceRecord:
        normalized = normalize_orgnr(orgnr)
        url = f"{self.base_url}/roller/enheter/{normalized}/juridiskeroller"
        payload = await self._get_json(url)
        return SourceRecord("brreg_legal_roles", normalized, payload, url)

    async def get_group_structure(self, orgnr: str) -> SourceRecord:
        normalized = normalize_orgnr(orgnr)
        url = f"{self.base_url}/konsernstruktur/{normalized}"
        payload = await self._get_json(url)
        return SourceRecord("brreg_group_structure", normalized, payload, url)

    async def download_role_inventory(self, destination: Path) -> RoleInventoryDownload:
        url = f"{self.base_url}/roller/totalbestand"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.part")
        try:
            async with self.client.stream(
                "GET",
                url,
                headers={"Accept": "application/gzip, application/octet-stream, */*"},
                timeout=None,
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
                metadata = RoleInventoryDownload(
                    path=destination,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    content_type=response.headers.get("content-type"),
                )
            temporary.replace(destination)
            return metadata
        finally:
            temporary.unlink(missing_ok=True)
