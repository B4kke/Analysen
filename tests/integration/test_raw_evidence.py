"""Immutable raw evidence storage for BRREG ingest (AQ-009).

The original upstream response must be persisted before any normalization, be
addressed by its SHA-256, and the document row must reference the stored
snapshot via raw_storage_key so every claim can be opened back to the raw
response. Opt-in: requires TEST_DATABASE_URL.
"""

import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.fixture
async def raw_client(
    monkeypatch, tmp_path
) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
    test_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", test_url)

    from apps.api.app.core import config, database

    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))
    config.get_settings.cache_clear()
    from apps.api.app.main import app

    factory = database.get_session_factory()
    created: list[uuid.UUID] = []

    async def override_session():
        async with factory() as session:
            yield session

    from apps.api.app.core.database import get_db_session

    app.dependency_overrides[get_db_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, created, factory
    app.dependency_overrides.clear()
    async with factory() as session:
        for investigation_id in created:
            await session.execute(
                text("DELETE FROM investigations WHERE id = :id"), {"id": investigation_id}
            )
        await session.commit()
    await database.dispose_database()
    config.get_settings.cache_clear()


async def test_brreg_ingest_stores_immutable_raw_snapshot(raw_client) -> None:
    http, created, factory = raw_client
    settings_dir = os.environ["RAW_EVIDENCE_DIR"]

    payload = {
        "target": {
            "type": "company",
            "name": "Raw Evidence Probe AS",
            "known_orgnrs": ["974760673"],
        },
        "purpose": "Verify raw evidence storage",
        "scope_modules": ["BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    created_response = await http.post("/api/v1/investigations", json=payload)
    assert created_response.status_code == 201, created_response.text
    investigation_id = created_response.json()["id"]
    created.append(uuid.UUID(investigation_id))

    raw_payload = {
        "organisasjonsnummer": "974760673",
        "navn": "Raw Evidence Probe AS",
        "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
    }

    from apps.api.app.sources.base import SourceRecord

    async def fake_fetch(_adapter, orgnr):
        return SourceRecord(
            source_id="brreg_entities",
            external_id=orgnr,
            source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
            payload=raw_payload,
        )

    from apps.api.app.api.routes import investigations as routes

    original_fetch = routes.BrregAdapter.fetch
    routes.BrregAdapter.fetch = fake_fetch
    try:
        response = await http.post(
            f"/api/v1/investigations/{investigation_id}/sources/brreg/organizations/974760673"
        )
    finally:
        routes.BrregAdapter.fetch = original_fetch
    assert response.status_code == 200, response.text

    canonical = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async with factory() as session:
        document = (
            (
                await session.execute(
                    text(
                        """
                    SELECT doc.sha256, doc.raw_storage_key, doc.fetched_at
                    FROM investigation_documents d
                    JOIN documents doc ON doc.id = d.document_id
                    WHERE d.investigation_id = CAST(:id AS uuid)
                    LIMIT 1
                    """
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )

    assert document["sha256"] == expected_digest
    assert document["raw_storage_key"], "raw_storage_key must be populated"

    stored_path = os.path.join(settings_dir, document["raw_storage_key"])
    assert os.path.isfile(stored_path), f"expected snapshot at {stored_path}"
    with open(stored_path, "rb") as handle:
        stored_bytes = handle.read()
    assert stored_bytes.decode("utf-8") == canonical
    assert hashlib.sha256(stored_bytes).hexdigest() == expected_digest


async def test_brreg_ingest_is_idempotent_for_same_payload(raw_client) -> None:
    http, created, factory = raw_client
    name = f"Raw Idempotent Probe {uuid.uuid4()} AS"
    payload = {
        "target": {"type": "company", "name": name, "known_orgnrs": ["974760673"]},
        "purpose": "Verify idempotent raw storage",
        "scope_modules": ["BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    created_response = await http.post("/api/v1/investigations", json=payload)
    assert created_response.status_code == 201, created_response.text
    investigation_id = created_response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    from apps.api.app.api.routes import investigations as routes
    from apps.api.app.sources.base import SourceRecord

    raw_payload = {"organisasjonsnummer": "974760673", "navn": name}
    fetch_count = 0

    async def fake_fetch(_adapter, orgnr):
        nonlocal fetch_count
        fetch_count += 1
        return SourceRecord(
            source_id="brreg_entities",
            external_id=orgnr,
            payload=raw_payload,
            source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"
            f"?attempt={fetch_count}",
        )

    async def snapshot():
        async with factory() as session:
            return dict(
                (
                    await session.execute(
                        text("""
                SELECT doc.id, sha256, raw_storage_key, original_url,
                       canonical_url, fetched_at, source_id
                FROM investigation_documents d JOIN documents doc ON doc.id = d.document_id
                WHERE d.investigation_id = CAST(:id AS uuid)
            """),
                        {"id": investigation_id},
                    )
                )
                .mappings()
                .one()
            )

    original_fetch = routes.BrregAdapter.fetch
    routes.BrregAdapter.fetch = fake_fetch
    try:
        url = f"/api/v1/investigations/{investigation_id}/sources/brreg/organizations/974760673"
        first = await http.post(url)
        assert first.status_code == 200, first.text
        before = await snapshot()
        second = await http.post(url)
        assert second.status_code == 200, second.text
        after = await snapshot()
    finally:
        routes.BrregAdapter.fetch = original_fetch
    assert fetch_count == 2
    assert before["original_url"].endswith("?attempt=1")
    assert before["raw_storage_key"]
    assert after == before
