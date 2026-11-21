#!/usr/bin/env python3
"""Rate-bounded live adapter contract checks, no personal inputs or raw output.

Run from repo root: python -m scripts.source_smoke [--searxng] [--output PATH].
A successful live probe is not a full research or evidence-chain certification.
"""
import argparse
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from apps.api.app.core.config import get_settings
from apps.api.app.services.brreg_normalization import normalize_brreg_organization
from apps.api.app.sources.brreg import BrregAdapter
from apps.api.app.sources.commoncrawl import CommonCrawlAdapter
from apps.api.app.sources.gdelt import GdeltAdapter
from apps.api.app.sources.gleif import GleifAdapter
from apps.api.app.sources.national_library import NationalLibraryClient
from apps.api.app.sources.rdap import RdapAdapter
from apps.api.app.sources.regnskap import RegnskapsregisterAdapter
from apps.api.app.sources.searxng import SearxngAdapter

PUBLIC_AGENCY = "974760673"  # Registerenheten i Brønnøysund
PUBLIC_COMPANY = "923609016"  # Equinor ASA
PUBLIC_TERM = "Stortinget"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


async def brreg() -> dict[str, int]:
    async with BrregAdapter() as adapter:
        record = await adapter.fetch(PUBLIC_AGENCY)
        normalized = normalize_brreg_organization(record.payload)
        require(record.external_id == PUBLIC_AGENCY, "identifier mismatch")
        require(bool(normalized.model_dump()), "normalization failed")
        return {"records": 1}


async def nb() -> dict[str, int]:
    client = NationalLibraryClient()
    try:
        total, candidates, _ = await client.search_newspapers(
            PUBLIC_TERM, limit=2
        )
        require(total > 0 and bool(candidates), "no candidates for public test term")
        return {"total": total, "candidates": len(candidates)}
    finally:
        await client.aclose()


async def commoncrawl() -> dict[str, int]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        rows = await CommonCrawlAdapter(client).indexes()
        require(bool(rows) and bool(rows[0].get("cdx-api")), "missing index endpoint")
        return {"indexes": len(rows)}


async def accounts() -> dict[str, int]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        years = await RegnskapsregisterAdapter(client).available_years(PUBLIC_COMPANY)
        require(bool(years), "no available public annual accounts")
        require(all(1900 < year <= datetime.now(UTC).year for year in years), "invalid year")
        return {"years": len(years)}


async def gleif() -> dict[str, int]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        payload = await GleifAdapter(client).search_legal_name("EQUINOR ASA", page_size=2)
        records = payload.get("data")
        require(isinstance(records, list) and bool(records), "no public LEI matches")
        return {"records": len(records)}


async def gdelt() -> dict[str, int]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        rows = await GdeltAdapter(client).search("renewable energy", maxrecords=5)
        return {"results": len(rows)}


async def rdap() -> dict[str, int]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=3) as client:
        record = await RdapAdapter(client=client).fetch("example.com")
        require(record.payload.get("objectClassName") == "domain", "not a domain object")
        return {"records": 1}


async def searxng() -> dict[str, int]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        rows = await SearxngAdapter(settings.searxng_base_url, client).search(PUBLIC_TERM)
        return {"results": len(rows)}


PROBES: dict[str, Callable[[], Awaitable[dict[str, int]]]] = {
    "brreg_entities": brreg,
    "national_library_no": nb,
    "common_crawl": commoncrawl,
    "brreg_accounts": accounts,
    "gleif": gleif,
    "gdelt": gdelt,
    "rdap": rdap,
    "searxng": searxng,
}


async def run(include_searxng: bool) -> list[dict[str, Any]]:
    _, sources, _ = get_settings().validate_yaml_configs()
    results: list[dict[str, Any]] = []
    for source, probe in PROBES.items():
        configured = sources.sources.get(source)
        if configured is None or not configured.enabled:
            results.append({"source": source, "status": "disabled"})
            continue
        if source == "searxng" and not include_searxng:
            results.append({"source": source, "status": "requires_local_runtime"})
            continue
        started = time.monotonic()
        try:
            async with asyncio.timeout(25):
                metrics = await probe()
            result: dict[str, Any] = {"status": "passed", "metrics": metrics}
        except httpx.HTTPStatusError as exc:
            result = {"status": "failed", "http_status": exc.response.status_code}
        except Exception as exc:
            result = {"status": "failed", "error_type": type(exc).__name__}
        results.append({
            "source": source,
            "duration_ms": round((time.monotonic() - started) * 1000),
            **result,
        })
        # Sequential probes; no aggressive upstream retry or personal record retention.
        await asyncio.sleep(1)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--searxng", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = asyncio.run(run(args.searxng))
    report = json.dumps(
        {"checked_at": datetime.now(UTC).isoformat(), "probes": results},
        indent=2,
        ensure_ascii=False,
    )
    print(report)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    return int(any(row["status"] == "failed" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
