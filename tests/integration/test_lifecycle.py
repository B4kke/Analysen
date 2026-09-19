"""Retention data lifecycle: full export and audited erasure (AQ-010).

Export must cover record, modules, entities, claims, leads, documents with raw
snapshot keys and audit events. Deletion removes all cascade-owned data in one
transaction and leaves a surviving audit trail row. Opt-in: TEST_DATABASE_URL.
"""

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
async def lifecycle_client(
    monkeypatch, tmp_path
) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
    test_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("RAW_EVIDENCE_DIR", str(tmp_path / "raw"))

    from apps.api.app.core import config, database

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


async def _create_company(http: httpx.AsyncClient, created: list, name: str) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "company", "name": name, "known_orgnrs": ["974760673"]},
            "purpose": "Verify retention lifecycle endpoints",
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def test_export_includes_modules_leads_documents_audit(lifecycle_client) -> None:
    http, created, _factory = lifecycle_client
    investigation_id = await _create_company(http, created, "Lifecycle Export Probe AS")

    export = await http.get(f"/api/v1/investigations/{investigation_id}/export")
    assert export.status_code == 200, export.text
    data = export.json()

    assert data["investigation"]["target"]["name"] == "Lifecycle Export Probe AS"
    assert data["investigation"]["purpose"] == "Verify retention lifecycle endpoints"
    assert {module["module"] for module in data["modules"] if module["enabled"]} == {
        "BUSINESS_ROLES"
    }
    assert data["leads"] == []
    assert data["entities"] == []
    assert data["claims"] == []
    assert data["documents"] == []
    assert [row["event_type"] for row in data["audit_log"]] == ["CREATED"]
    assert data["exported_at"]


async def test_export_lists_documents_with_raw_snapshot_key(lifecycle_client) -> None:
    http, created, _factory = lifecycle_client
    investigation_id = await _create_company(http, created, "Lifecycle Raw Probe AS")

    from apps.api.app.api.routes import investigations as routes
    from apps.api.app.sources.base import SourceRecord

    raw_payload = {
        "organisasjonsnummer": "974760673",
        "navn": "Lifecycle Raw Probe AS",
    }

    async def fake_fetch(_adapter, orgnr):
        return SourceRecord(
            source_id="brreg_entities",
            external_id=orgnr,
            source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
            payload=raw_payload,
        )

    original_fetch = routes.BrregAdapter.fetch
    routes.BrregAdapter.fetch = fake_fetch
    try:
        ingest = await http.post(
            f"/api/v1/investigations/{investigation_id}/sources/brreg/organizations/974760673"
        )
    finally:
        routes.BrregAdapter.fetch = original_fetch
    assert ingest.status_code == 200, ingest.text

    export = await http.get(f"/api/v1/investigations/{investigation_id}/export")
    data = export.json()
    assert len(data["documents"]) == 1
    document = data["documents"][0]
    assert document["raw_storage_key"]
    assert len(document["sha256"]) == 64
    assert document["original_url"].endswith("/974760673")


async def test_export_includes_media_mentions_with_evidence_refs(lifecycle_client) -> None:
    http, created, factory = lifecycle_client
    investigation_id = await _create_company(http, created, "Lifecycle Media Probe AS")

    from apps.api.app.repositories import media_mentions as store

    page_urn = "URN:NBN:no-nb_lifecycle_media_30"
    async with factory() as session:
        await store.upsert_media_mention(
            session,
            investigation_id=uuid.UUID(investigation_id),
            target_query="Lifecycle Media Probe AS",
            publication="Hadeland",
            page_urn=page_urn,
            text_availability="PARTIAL_CONTEXT",
            text_excerpt="... kontekst ...",
            identity_state="UNRESOLVED",
            access_class="PUBLIC_VIEW_ONLY",
            xywh_anchors=["xywh=1,2,3,4"],
        )
        await session.commit()

    export = await http.get(f"/api/v1/investigations/{investigation_id}/export")
    assert export.status_code == 200, export.text
    data = export.json()
    assert len(data["media_mentions"]) == 1
    mention = data["media_mentions"][0]
    assert mention["target_query"] == "Lifecycle Media Probe AS"
    assert mention["publication"] == "Hadeland"
    assert mention["page_urn"] == page_urn
    assert mention["text_availability"] == "PARTIAL_CONTEXT"
    assert mention["identity_state"] == "UNRESOLVED"
    assert mention["access_class"] == "PUBLIC_VIEW_ONLY"
    assert mention["xywh_anchors"] == ["xywh=1,2,3,4"]
    assert mention["evidence_id"] is None
    assert mention["created_at"]


async def test_export_lists_no_media_mentions_when_none_stored(lifecycle_client) -> None:
    http, created, _factory = lifecycle_client
    investigation_id = await _create_company(http, created, "Lifecycle Empty Media AS")

    export = await http.get(f"/api/v1/investigations/{investigation_id}/export")
    assert export.status_code == 200, export.text
    assert export.json()["media_mentions"] == []


async def test_delete_erases_data_and_leaves_audit_trail(lifecycle_client) -> None:
    http, created, factory = lifecycle_client
    investigation_id = await _create_company(http, created, "Lifecycle Delete Probe AS")

    async with factory() as session:
        orphaned_before = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE investigation_id IS NULL")
            )
        ).scalar_one()

    deleted = await http.delete(f"/api/v1/investigations/{investigation_id}")
    assert deleted.status_code == 204, deleted.text

    async with factory() as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM investigations WHERE id = CAST(:id AS uuid)"),
                {"id": investigation_id},
            )
        ).scalar_one() == 0
        assert (
            await session.execute(
                text(
                    "SELECT count(*) FROM investigation_modules "
                    "WHERE investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).scalar_one() == 0
        orphaned_after = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE investigation_id IS NULL")
            )
        ).scalar_one()
        # The owned rows are gone; the two audit rows survive with investigation_id
        # set to NULL per ON DELETE SET NULL, so the trail outlives the case data.
        assert orphaned_after - orphaned_before == 2
        trail = (
            await session.execute(
                text(
                    "SELECT event_type, actor FROM audit_log "
                    "WHERE investigation_id IS NULL ORDER BY id DESC LIMIT 2"
                )
            )
        ).mappings().all()

    assert [row["event_type"] for row in reversed(trail)] == [
        "CREATED",
        "INVESTIGATION_DELETED",
    ]
    assert trail[0]["actor"] == "local-operator"


async def test_delete_unknown_investigation_returns_404(lifecycle_client) -> None:
    http, _created, _factory = lifecycle_client
    response = await http.delete(f"/api/v1/investigations/{uuid.uuid4()}")
    assert response.status_code == 404

    export = await http.get(f"/api/v1/investigations/{uuid.uuid4()}/export")
    assert export.status_code == 404
