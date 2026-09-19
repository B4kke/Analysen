"""End-to-end MVP vertical chain (AQ-028).

Proves create -> planner -> gate -> frontier -> source router -> fetch ->
raw -> document -> evidence -> claim -> verifier -> coverage -> report
against real PostgreSQL. Only the external network/model boundary is
faked (BRREG fetch callable, NIM planner provider). Opt-in:
TEST_DATABASE_URL.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.fixture
async def e2e_client(
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


async def _create_company(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {
                "type": "company",
                "name": "E2E Probe AS",
                "known_orgnrs": ["974760673"],
            },
            "purpose": "Prove the vertical company chain end to end",
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _create_person(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "person", "name": "E2E Probe Person"},
            "purpose": "Prove identity resolution inside the E2E flow",
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "CONTEXT_ONLY",
            "max_relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


def _fake_fetch(payload: dict):
    from apps.api.app.sources.base import SourceRecord

    calls: list[str] = []

    async def fetch(orgnr: str):
        calls.append(orgnr)
        return SourceRecord(
            source_id="brreg_entities",
            external_id=orgnr,
            source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
            payload=payload,
        )

    return fetch, calls


class _FakePlanner:
    """Deterministic stand-in for the NIM chat provider."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def chat_json(self, **kwargs):
        return self.payload


def _brreg_proposal(**overrides) -> dict:
    payload = {
        "lead_type": "brreg_organization_lookup",
        "value": {"orgnr": "974760673"},
        "reason": "Verify the explicitly identified target organization",
        "information_need": "Confirm registered details of the target organization",
        "scope_area": "BUSINESS_ROLES",
        "trigger_type": "WEAK_SOURCE_ONLY",
        "relation_depth": 0,
        "priority": 0.8,
        "expected_information_gain": "Confirms target identity from the primary registry",
    }
    payload.update(overrides)
    return payload


async def _run_pass(factory, investigation_id: str, fetch, **kwargs) -> dict:
    from apps.api.app.services.lead_executor import ExecutorTools
    from apps.api.app.services.research_loop import run_research_pass

    async with factory() as session:
        tools = ExecutorTools(brreg_fetch=fetch)
        return await run_research_pass(session, uuid.UUID(investigation_id), tools, **kwargs)


async def test_e2e_company_case(e2e_client) -> None:
    http, created, factory = e2e_client
    investigation_id = await _create_company(http, created)
    fetch, calls = _fake_fetch(
        {
            "organisasjonsnummer": "974760673",
            "navn": "E2E Probe AS",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        }
    )
    planner = _FakePlanner({"actions": [_brreg_proposal()]})

    summary = await _run_pass(
        factory, investigation_id, fetch, planner_provider=planner, planner_model="test"
    )
    assert summary["executed"] == 1
    assert summary["planned"] == 1

    async with factory() as session:
        statuses = (
            await session.execute(
                text(
                    "SELECT status FROM leads "
                    "WHERE investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).scalars().all()
        claim_ids = (
            await session.execute(
                text("SELECT id FROM claims WHERE investigation_id = CAST(:id AS uuid)"),
                {"id": investigation_id},
            )
        ).scalars().all()
    assert list(statuses) == ["COMPLETED"]
    assert len(claim_ids) >= 1

    verify = await http.post(
        f"/api/v1/investigations/{investigation_id}/claims/{claim_ids[0]}/verify"
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["status"] == "SUPPORTED"

    modules = await http.get(f"/api/v1/investigations/{investigation_id}/modules")
    assert modules.status_code == 200, modules.text
    business = [row for row in modules.json() if row["module"] == "BUSINESS_ROLES"]
    assert len(business) == 1
    assert business[0]["coverage"]["query_count"] >= 1

    report = await http.get(f"/api/v1/investigations/{investigation_id}/report.json")
    assert report.status_code == 200, report.text
    findings = report.json()["findings"]
    supported = [entry for entry in findings if entry["status"] == "SUPPORTED"]
    assert len(supported) >= 1
    assert any(
        any(citation.get("url") and citation.get("sha256") for citation in entry["citations"])
        for entry in supported
    )

    rerun = await _run_pass(
        factory, investigation_id, fetch, planner_provider=planner, planner_model="test"
    )
    assert rerun["executed"] == 0
    assert rerun["planned"] == 0
    assert calls == ["974760673"]
    async with factory() as session:
        rerun_statuses = (
            await session.execute(
                text(
                    "SELECT status FROM leads "
                    "WHERE investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).scalars().all()
    assert list(rerun_statuses) == ["COMPLETED"]


async def _insert_entities(factory, count: int) -> list[uuid.UUID]:
    entity_ids = [uuid.uuid4() for _ in range(count)]
    async with factory() as session:
        for entity_id in entity_ids:
            await session.execute(
                text(
                    "INSERT INTO entities (id, schema, canonical_name, attributes) "
                    "VALUES (:id, 'Person', 'E2E Probe Person', CAST('{}' AS jsonb))"
                ),
                {"id": entity_id},
            )
        await session.commit()
    return entity_ids


async def test_e2e_person_identity_case(e2e_client) -> None:
    from apps.api.app.domain.models import ResolutionState
    from apps.api.app.repositories import entity_resolution as resolution_repo
    from apps.api.app.services.entity_resolution import (
        PersonCandidate,
        negative_signals,
        resolve_person,
    )

    http, _created, factory = e2e_client
    investigation_id = await _create_person(http, _created)

    target = PersonCandidate(name="Ola Nordmann", birth_date=date(1975, 5, 17))
    same_birth = PersonCandidate(name="Ola Nordmann", birth_date=date(1975, 5, 17))
    different_birth = PersonCandidate(name="Ola Nordmann", birth_date=date(1980, 1, 1))

    positive = resolve_person(target, same_birth)
    assert positive.state in (ResolutionState.MATCH, ResolutionState.PROBABLE_MATCH)

    negative = resolve_person(target, different_birth)
    assert negative.state == ResolutionState.NOT_MATCH

    entity_id, candidate_id = await _insert_entities(factory, 2)
    async with factory() as session:
        await resolution_repo.upsert_resolution_candidate(
            session,
            uuid.UUID(investigation_id),
            entity_id,
            candidate_id,
            positive.score,
            ResolutionState.PROBABLE_MATCH.value,
            list(negative_signals(positive)),
        )
        await session.commit()

    approve = await http.post(
        f"/api/v1/investigations/{investigation_id}/resolution/{entity_id}/{candidate_id}",
        json={"status": "MATCH", "reason": "Verified against registry entry"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["to"] == "MATCH"

    async with factory() as session:
        status = (
            await session.execute(
                text(
                    "SELECT resolution_status FROM entity_resolution_candidates "
                    "WHERE investigation_id = CAST(:iid AS uuid) "
                    "AND entity_id = :eid AND candidate_entity_id = :cid"
                ),
                {"iid": investigation_id, "eid": entity_id, "cid": candidate_id},
            )
        ).scalar_one()
        audit = (
            await session.execute(
                text(
                    "SELECT event_type FROM audit_log "
                    "WHERE investigation_id = CAST(:iid AS uuid) "
                    "AND event_type = 'RESOLUTION_REVIEWED'"
                ),
                {"iid": investigation_id},
            )
        ).mappings().all()
    assert status == "MATCH"
    assert len(audit) >= 1

    blocked_entity_id, blocked_candidate_id = await _insert_entities(factory, 2)
    async with factory() as session:
        await resolution_repo.upsert_resolution_candidate(
            session,
            uuid.UUID(investigation_id),
            blocked_entity_id,
            blocked_candidate_id,
            0.0,
            ResolutionState.UNRESOLVED.value,
            list(negative_signals(negative)),
        )
        await session.commit()

    forged = await http.post(
        f"/api/v1/investigations/{investigation_id}"
        f"/resolution/{blocked_entity_id}/{blocked_candidate_id}",
        json={"status": "MATCH", "reason": "Trying to force a match"},
    )
    assert forged.status_code == 409, forged.text
