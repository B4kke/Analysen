from pathlib import Path

import httpx


class RegnskapsregisterAdapter:
    source_id = "brreg_accounts"
    base_url = "https://data.brreg.no/regnskapsregisteret/regnskap"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=60.0, follow_redirects=False)

    async def available_years(self, orgnr: str) -> list[int]:
        url = f"{self.base_url}/aarsregnskap/kopi/{orgnr}/aar"
        response = await self.client.get(url)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return sorted({int(item) for item in data}, reverse=True)
        if isinstance(data, dict):
            values = data.get("aar") or data.get("years") or []
            return sorted({int(item) for item in values}, reverse=True)
        raise ValueError("Unexpected annual-account year response")

    async def download_pdf(self, orgnr: str, year: int, destination: Path) -> Path:
        url = f"{self.base_url}/aarsregnskap/kopi/{orgnr}/{year}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    handle.write(chunk)
        return destination
