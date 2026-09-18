"""Negative provenance guards for the web document ingest boundary."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.app.domain.models import SourceRegistryRecord
from apps.api.app.repositories import web_document_ingest as ingest
from apps.api.app.services.raw_store import store_raw_bytes
from apps.api.app.services.url_canonicalization import FetchResult


class _NoSqlSession:
    async def execute(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid ingest input reached SQL")


@pytest.fixture
def valid_fetch(monkeypatch, tmp_path: Path) -> tuple[FetchResult, SourceRegistryRecord, Path]:
    raw_root = tmp_path / "raw"
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(raw_root))
    source_config = tmp_path / "sources.yaml"
    source_config.write_text(
        """sources:
  fixture-web:
    enabled: true
    access: PUBLIC_WEB
    evidence_tier: 2
    base_url: http://fixture.test
    license: test-fixture
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOURCE_CONFIG_PATH", str(source_config))
    from apps.api.app.core import config

    config.get_settings.cache_clear()
    payload = b"original immutable fixture bytes"
    digest, storage_key = store_raw_bytes(payload)
    fetched_at = datetime.now(UTC)
    result = FetchResult(
        url="http://fixture.test/article",
        final_url="http://fixture.test/article",
        content="Extracted fixture text",
        content_type="text/html",
        status_code=200,
        metadata={
            "source_url": "http://fixture.test/article",
            "final_url": "http://fixture.test/article",
            "fetched_at": fetched_at.isoformat(),
            "raw_sha256": digest,
            "raw_storage_key": storage_key,
        },
        raw_bytes=payload,
        fetched_at=fetched_at,
    )
    source = SourceRegistryRecord(
        id="fixture-web",
        name="Fixture web",
        evidence_tier=2,
        access_class="PUBLIC_WEB",
        base_url="http://fixture.test",
        license="test-fixture",
    )

    async def allow_fixture(url: str) -> None:
        if not url.startswith("http://fixture.test"):
            raise ingest.UnsafeUrl("fixture validator rejected URL")

    monkeypatch.setattr(ingest, "validate_public_http_url", allow_fixture)
    return result, source, raw_root


async def _rejects(result: FetchResult, source: SourceRegistryRecord) -> None:
    with pytest.raises(ValueError):
        await ingest.persist_web_document(_NoSqlSession(), uuid4(), source, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["fetched_at", "metadata_time"])
async def test_missing_or_mismatched_timestamp_rejected(valid_fetch, field: str) -> None:
    result, source, _ = valid_fetch
    if field == "fetched_at":
        result = replace(result, fetched_at=None)
    else:
        result = replace(
            result,
            metadata={**result.metadata, "fetched_at": "2020-01-01T00:00:00+00:00"},
        )
    await _rejects(result, source)


@pytest.mark.asyncio
async def test_url_metadata_must_match_result(valid_fetch) -> None:
    result, source, _ = valid_fetch
    await _rejects(
        replace(result, metadata={**result.metadata, "source_url": "http://fixture.test/other"}),
        source,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_key",
    ["../../escape", "sha256/aa/bb/" + "0" * 64, "sha256/aa/bb/not-a-digest"],
)
async def test_storage_key_prefix_and_traversal_are_rejected(valid_fetch, storage_key: str) -> None:
    result, source, _ = valid_fetch
    await _rejects(
        replace(result, metadata={**result.metadata, "raw_storage_key": storage_key}),
        source,
    )


@pytest.mark.asyncio
async def test_corrupt_raw_blob_rejected_before_sql(valid_fetch) -> None:
    result, source, raw_root = valid_fetch
    path = raw_root / result.metadata["raw_storage_key"]
    path.write_bytes(b"tampered")
    await _rejects(result, source)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_yaml,source",
    [
        (
            """sources:
  fixture-web:
    enabled: true
    access: SELF_HOSTED
    evidence_tier: 2
    base_url: http://fixture.test
    license: test-fixture
""",
            SourceRegistryRecord(
                id="fixture-web", name="x", evidence_tier=2,
                access_class="PUBLIC_WEB", base_url="http://fixture.test",
                license="test-fixture",
            ),
        ),
        (
            """sources:
  fixture-web:
    enabled: false
    access: PUBLIC_WEB
    evidence_tier: 2
    base_url: http://fixture.test
    license: test-fixture
    reason: disabled for test
""",
            SourceRegistryRecord(
                id="fixture-web", name="x", evidence_tier=2,
                access_class="PUBLIC_WEB", base_url="http://fixture.test",
                license="test-fixture",
            ),
        ),
        (
            """sources:
  fixture-web:
    enabled: true
    access: PUBLIC_WEB
    evidence_tier: 2
    base_url: http://fixture.test
    license: test-fixture
    discovery_only: true
""",
            SourceRegistryRecord(
                id="fixture-web", name="x", evidence_tier=2,
                access_class="PUBLIC_WEB", base_url="http://fixture.test",
                license="test-fixture",
            ),
        ),
    ],
)
async def test_source_policy_must_be_enabled_evidence_source(
    valid_fetch, monkeypatch, source_yaml: str, source: SourceRegistryRecord
) -> None:
    result, _, _ = valid_fetch
    from apps.api.app.core import config

    config_path = config.get_settings().source_config_path
    config_path.write_text(source_yaml, encoding="utf-8")
    config.get_settings.cache_clear()
    await _rejects(result, source)


@pytest.mark.asyncio
async def test_private_url_rejected_at_ingest_boundary(valid_fetch) -> None:
    result, source, _ = valid_fetch
    await _rejects(replace(result, url="http://127.0.0.1/private"), source)
