"""Database backed investigation contract tests.

These tests are opt-in: the coordinator supplies TEST_DATABASE_URL after applying
the migrations. They clean up only the investigation IDs they create.
"""

import os
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.fixture
async def client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
    test_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", test_url)

    from apps.api.app.core import config, database
    config.get_settings.cache_clear()
    from apps.api.app.main import app

    factory = database.get_session_factory()
    created: list[UUID] = []

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


async def _create(client, created, target_type="company", *, scope_modules=None, orgnrs=None):
    payload = {
        "target": {
            "type": target_type,
            "name": "Test Company" if target_type != "person" else "Test Person",
            "known_orgnrs": orgnrs or [],
        },
        "purpose": "Validate investigation scope contract",
    }
    if scope_modules is not None:
        payload["scope_modules"] = scope_modules
    response = await client.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    created.append(UUID(body["id"]))
    return body


@pytest.mark.asyncio
async def test_create_detail_defaults_and_scope_audit(client):
    http, created, factory = client
    body = await _create(http, created)
    assert body["scope_modules"] == []
    assert body["expansion_policy"] == "DIRECT_RELATIONS"
    assert body["max_relation_depth"] == 1

    detail = await http.get(f"/api/v1/investigations/{body['id']}")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert {module["module"] for module in detail_body["modules"]} == {
        "WEB_MEDIA", "BUSINESS_ROLES", "COMPANY_NETWORK", "FINANCIALS",
        "ANNOUNCEMENTS_STATUS", "HISTORICAL_WEB", "DOMAINS_DIGITAL",
        "PUBLIC_PROFILES", "SANCTIONS",
    }
    assert all(module["enabled"] is False for module in detail_body["modules"])

    update = await http.patch(
        f"/api/v1/investigations/{body['id']}/scope",
        json={
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
            "reason": "Need documented company roles",
        },
    )
    assert update.status_code == 200, update.text
    assert update.json()["scope_modules"] == ["BUSINESS_ROLES"]

    async with factory() as session:
        audits = (
            await session.execute(
                text(
                    """SELECT event_type, actor, payload FROM audit_log
                    WHERE investigation_id = :id ORDER BY id"""
                ),
                {"id": body["id"]},
            )
        ).mappings().all()
    assert [(row["event_type"], row["actor"]) for row in audits] == [
        ("CREATED", "local-operator"),
        ("SCOPE_CHANGED", "local-operator"),
    ]
    assert audits[-1]["payload"]["reason"] == "Need documented company roles"

    modules = await http.get(f"/api/v1/investigations/{body['id']}/modules")
    assert modules.status_code == 200, modules.text
    assert {module["module"] for module in modules.json()} == {
        "WEB_MEDIA", "BUSINESS_ROLES", "COMPANY_NETWORK", "FINANCIALS",
        "ANNOUNCEMENTS_STATUS", "HISTORICAL_WEB", "DOMAINS_DIGITAL",
        "PUBLIC_PROFILES", "SANCTIONS",
    }


@pytest.mark.asyncio
async def test_person_defaults_and_scope_patch_requires_complete_contract(client):
    http, created, _factory = client
    body = await _create(http, created, target_type="person")
    assert body["expansion_policy"] == "CONTEXT_ONLY"
    assert body["max_relation_depth"] == 0
    response = await http.patch(
        f"/api/v1/investigations/{body['id']}/scope",
        json={"scope_modules": ["BUSINESS_ROLES"]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_brreg_ingest_person_is_blocked_before_upstream(client, monkeypatch):
    http, created, _factory = client
    body = await _create(
        http,
        created,
        target_type="person",
        scope_modules=["BUSINESS_ROLES"],
        orgnrs=["999999999"],
    )

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("BRREG must not be called for a person target")

    from apps.api.app.api.routes import investigations

    monkeypatch.setattr(investigations.BrregAdapter, "fetch", fail_if_called)
    response = await http.post(
        f"/api/v1/investigations/{body['id']}/sources/brreg/organizations/999999999"
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_brreg_ingest_requires_enabled_scope_before_upstream(client, monkeypatch):
    http, created, _factory = client
    body = await _create(http, created, orgnrs=["974760673"])

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("disabled BUSINESS_ROLES must gate before BRREG")

    from apps.api.app.api.routes import investigations

    monkeypatch.setattr(investigations.BrregAdapter, "fetch", fail_if_called)
    response = await http.post(
        f"/api/v1/investigations/{body['id']}/sources/brreg/organizations/974760673"
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_brreg_ingest_company_stores_evidence_and_claims(client, monkeypatch):
    http, created, factory = client
    body = await _create(
        http,
        created,
        scope_modules=["BUSINESS_ROLES"],
        orgnrs=["974760673"],
    )
    from apps.api.app.api.routes import investigations
    from apps.api.app.sources.base import SourceRecord

    async def fake_fetch(_adapter, orgnr):
        return SourceRecord(
            source_id="brreg_entities",
            external_id=orgnr,
            source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
            payload={
                "organisasjonsnummer": orgnr,
                "navn": "Test Company AS",
                "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
            },
        )

    monkeypatch.setattr(investigations.BrregAdapter, "fetch", fake_fetch)
    response = await http.post(
        f"/api/v1/investigations/{body['id']}/sources/brreg/organizations/974760673"
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["organization"]["organization_number"] == "974760673"

    async with factory() as session:
        evidence_count = (
            await session.execute(
                text(
                    """SELECT count(*) FROM evidence e
                    JOIN investigation_documents d ON d.document_id = e.document_id
                    WHERE d.investigation_id = :id"""
                ),
                {"id": body["id"]},
            )
        ).scalar_one()
        claim_count = (
            await session.execute(
                text("SELECT count(*) FROM claims WHERE investigation_id = :id"),
                {"id": body["id"]},
            )
        ).scalar_one()
    assert evidence_count >= 1
    assert claim_count >= 1

    narrowed = await http.patch(
        f"/api/v1/investigations/{body['id']}/scope",
        json={
            "scope_modules": [],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
            "reason": "Pause role research",
        },
    )
    assert narrowed.status_code == 200, narrowed.text
    detail = await http.get(f"/api/v1/investigations/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["entities"]
    assert detail.json()["claims"]

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("narrowed scope must gate new BRREG calls")

    monkeypatch.setattr(investigations.BrregAdapter, "fetch", fail_if_called)
    blocked = await http.post(
        f"/api/v1/investigations/{body['id']}/sources/brreg/organizations/974760673"
    )
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_brreg_unknown_investigation_and_bad_orgnr_are_rejected(client):
    http, _created, _factory = client
    response = await http.post(
        "/api/v1/investigations/00000000-0000-0000-0000-000000000000/"
        "sources/brreg/organizations/974760673"
    )
    assert response.status_code == 404

    body = await _create(http, _created, scope_modules=["BUSINESS_ROLES"], orgnrs=["974760673"])
    response = await http.post(
        f"/api/v1/investigations/{body['id']}/sources/brreg/organizations/not-an-orgnr"
    )
    assert response.status_code == 422
