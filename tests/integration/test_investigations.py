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
@pytest.mark.asyncio
async def test_create_without_purpose_is_allowed(client):
    http, created, _factory = client
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "person", "name": "Frivillig Formål"},
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "CONTEXT_ONLY",
            "max_relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    created.append(UUID(body["id"]))
    assert body["purpose"] == ""


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


@pytest.mark.asyncio
async def test_coverage_bump_merges_lists_counters_and_time_range(client):
    """bump_module_coverage accumulates counters, dedupes lists, widens time.

    Unknown counter keys are ignored; a second bump adds to the counters,
    keeps each list deduplicated and widens (never narrows) the ISO date
    range. NULL time bounds are no-ops.
    """
    import json as jsonlib

    from apps.api.app.domain.scope import ScopeModule
    from apps.api.app.repositories import investigations as repository

    http, created, factory = client
    body = await _create(http, created, scope_modules=["WEB_MEDIA"])
    investigation_id = UUID(body["id"])

    async def coverage() -> dict:
        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT coverage FROM investigation_modules "
                        "WHERE investigation_id = :id AND module = 'WEB_MEDIA'"
                    ),
                    {"id": investigation_id},
                )
            ).mappings().one()
            return dict(row["coverage"])

    async with factory() as session:
        await repository.bump_module_coverage(
            session,
            investigation_id,
            ScopeModule.WEB_MEDIA,
            provider="nb_catalog",
            query_class="ENTITY_ALIAS_EXACT",
            endpoints=["nb_catalog", "nb_contentsearch"],
            counters={
                "candidate_count": 10,
                "located_count": 3,
                "restricted_count": 1,
                "fetched_count": 2,
                "invented_count": 99,
            },
            time_from="2005-12-13",
            time_to="2020-12-23",
        )
        await session.commit()

    first = await coverage()
    assert first["query_count"] == 1
    assert first["providers"] == ["nb_catalog"]
    assert first["query_classes"] == ["ENTITY_ALIAS_EXACT"]
    assert sorted(first["endpoints"]) == ["nb_catalog", "nb_contentsearch"]
    assert first["candidate_count"] == 10
    assert first["located_count"] == 3
    assert first["restricted_count"] == 1
    assert first["fetched_count"] == 2
    assert "invented_count" not in first
    assert first["time_from"] == "2005-12-13"
    assert first["time_to"] == "2020-12-23"

    async with factory() as session:
        await repository.bump_module_coverage(
            session,
            investigation_id,
            ScopeModule.WEB_MEDIA,
            provider="nb_catalog",
            query_class="ENTITY_ALIAS_EXACT",
            endpoints=["nb_catalog", "nb_dhlab"],
            counters={"candidate_count": 5, "located_count": 1},
            time_from="1994-12-16",
            time_to=None,
        )
        await session.commit()

    second = await coverage()
    assert second["query_count"] == 2
    assert second["providers"] == ["nb_catalog"]
    assert second["query_classes"] == ["ENTITY_ALIAS_EXACT"]
    assert sorted(second["endpoints"]) == ["nb_catalog", "nb_contentsearch", "nb_dhlab"]
    assert second["candidate_count"] == 15
    assert second["located_count"] == 4
    assert second["time_from"] == "1994-12-16"
    assert second["time_to"] == "2020-12-23"
    assert jsonlib.loads(jsonlib.dumps(second)) == second
