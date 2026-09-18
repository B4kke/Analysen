"""Controlled web-fetch fixture integration and provenance DB roundtrip."""

import os
import uuid

import httpx
import pytest
from sqlalchemy import text

from apps.api.app.services.document_fetcher import DocumentFetcher, FetchConfig
from tests.test_fetch_policy import _RewriteFixtureTransport

pytest_plugins = ("tests.test_fetch_policy",)


@pytest.mark.asyncio
async def test_fixture_fetch_preserves_source_final_time_and_raw_provenance(
    fixture_server, fixture_validator, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
    from apps.api.app.core import config

    config.get_settings.cache_clear()
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=100),
        client=httpx.AsyncClient(transport=_RewriteFixtureTransport(fixture_server)),
    )
    try:
        result = await fetcher.fetch_raw("http://fixture.test/redirect")
        assert result.error is None
        assert result.url == "http://fixture.test/redirect"
        assert result.final_url == "http://fixture.test/article"
        assert result.metadata["raw_sha256"]
        assert result.metadata["raw_storage_key"].startswith("sha256/")
        # The ingest layer can carry these fields into a Document without
        # consulting model output or treating the URL as raw evidence.
        assert result.metadata.get("source_url", result.url) == result.url
        assert result.metadata.get("fetched_at") is not None
    finally:
        await fetcher.__aexit__(None, None, None)
        config.get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)
async def test_web_document_ingest_roundtrip(
    fixture_server, fixture_validator, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
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
    from apps.api.app.core import config, database
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import web_document_ingest
    from apps.api.app.repositories.web_document_ingest import persist_web_document
    from apps.api.app.services import document_fetcher

    monkeypatch.setattr(
        web_document_ingest, "validate_public_http_url", document_fetcher.validate_public_http_url
    )

    config.get_settings.cache_clear()
    factory = database.get_session_factory()
    investigation_id = uuid.uuid4()
    client = httpx.AsyncClient(transport=_RewriteFixtureTransport(fixture_server))
    fetcher = DocumentFetcher(
        FetchConfig(obey_robots=False, rate_limit_per_domain=100), client=client
    )
    try:
        async with factory() as session:
            await session.execute(
                text("""
                    INSERT INTO investigations (id, target_type, target_input, purpose)
                    VALUES (:id, 'company', CAST(:target AS jsonb), :purpose)
                """),
                {
                    "id": investigation_id,
                    "target": '{"name":"fixture"}',
                    "purpose": "AQ021 fixture provenance",
                },
            )
            original_url = f"http://fixture.test/article?nonce={investigation_id}"
            result = await fetcher.fetch_raw(original_url)
            source = SourceRegistryRecord(
                id="fixture-web",
                name="Fixture web",
                evidence_tier=2,
                access_class="PUBLIC_WEB",
                base_url="http://fixture.test",
                license="test-fixture",
            )
            document_id, evidence_id = await persist_web_document(
                session, investigation_id, source, result
            )
            await session.commit()
            row = (
                (
                    await session.execute(
                        text("""
                        SELECT d.original_url, d.canonical_url, d.sha256,
                               d.raw_storage_key, d.fetched_at, e.document_id
                        FROM documents d
                        JOIN evidence e ON e.document_id = d.id
                        WHERE d.id = :document_id AND e.id = :evidence_id
                    """),
                        {"document_id": document_id, "evidence_id": evidence_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["original_url"] == original_url
            assert row["canonical_url"] == original_url.replace("http:", "https:", 1)
            assert row["sha256"] == result.metadata["raw_sha256"]
            assert row["raw_storage_key"] == result.metadata["raw_storage_key"]
            assert row["fetched_at"] == result.fetched_at
            assert row["document_id"] == document_id
    finally:
        await fetcher.__aexit__(None, None, None)
        async with factory() as session:
            await session.execute(
                text("DELETE FROM investigations WHERE id = :id"),
                {"id": investigation_id},
            )
            await session.commit()
        await database.dispose_database()
        config.get_settings.cache_clear()
