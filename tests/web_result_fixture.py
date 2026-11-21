"""A real immutable raw-store snapshot behind a fake network response."""
from datetime import UTC, datetime

from apps.api.app.services.raw_store import store_raw_bytes
from apps.api.app.services.url_canonicalization import FetchResult


def web_result_fixture(url: str, raw: bytes, content: str) -> FetchResult:
    stamp = datetime.now(UTC)
    digest, key = store_raw_bytes(raw)
    return FetchResult(
        url=url,
        final_url=url,
        content=content,
        content_type="text/html",
        status_code=200,
        metadata={
            "source_url": url,
            "final_url": url,
            "raw_sha256": digest,
            "raw_storage_key": key,
            "fetched_at": stamp.isoformat(),
        },
        raw_bytes=raw,
        fetched_at=stamp,
    )
