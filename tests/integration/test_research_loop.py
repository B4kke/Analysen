"""Bounded research pass contract tests (AQ-015).

A pass chains admitted PENDING leads through frontier selection, trigger
evaluation and execution, then stops deterministically. BLOCKED leads are
never touched. No live calls: the service takes an injected fetch function.
Opt-in: TEST_DATABASE_URL.
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
async def loop_client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
    test_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", test_url)

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


async def _create_company(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {
                "type": "company",
                "name": "Research Loop Probe AS",
                "known_orgnrs": ["974760673"],
            },
            "purpose": "Verify bounded research passes",
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _admit_brreg_lead(http: httpx.AsyncClient, investigation_id: str) -> str:
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": "brreg_organization_lookup",
            "value": {"orgnr": "974760673"},
            "reason": "Verify the explicitly identified target organization",
            "priority": 0.8,
            "depth": 0,
            "scope_area": "BUSINESS_ROLES",
            "trigger_type": "WEAK_SOURCE_ONLY",
            "information_need": "Confirm registered details of the target organization",
            "relation_depth": 0,
        },
    )
    assert response.json()["status"] == "PENDING"
    return response.json()["lead_id"]


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


async def _run_pass(factory, investigation_id: str, fetch, **kwargs) -> dict:
    from apps.api.app.services.research_loop import run_research_pass

    async with factory() as session:
        return await run_research_pass(
            session, uuid.UUID(investigation_id), fetch, **kwargs
        )


async def test_pass_executes_chained_pending_leads(loop_client) -> None:
    http, created, factory = loop_client
    investigation_id = await _create_company(http, created)
    await _admit_brreg_lead(http, investigation_id)
    await _admit_brreg_lead(http, investigation_id)
    fetch, calls = _fake_fetch(
        {
            "organisasjonsnummer": "974760673",
            "navn": "Research Loop Probe AS",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        }
    )

    summary = await _run_pass(factory, investigation_id, fetch)

    assert summary == {
        "executed": 2,
        "blocked": 0,
        "failed": 0,
        "stopped_reason": "no_executable_leads",
    }
    assert calls == ["974760673", "974760673"]

    async with factory() as session:
        statuses = (
            await session.execute(
                text(
                    "SELECT DISTINCT status FROM leads "
                    "WHERE investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).scalars().all()
        audits = (
            await session.execute(
                text(
                    "SELECT event_type FROM audit_log "
                    "WHERE investigation_id = CAST(:id AS uuid) ORDER BY id"
                ),
                {"id": investigation_id},
            )
        ).scalars().all()
    assert statuses == ["COMPLETED"]
    assert audits[-1] == "RESEARCH_PASS_COMPLETED"


async def test_pass_leaves_blocked_leads_untouched(loop_client) -> None:
    http, created, factory = loop_client
    investigation_id = await _create_company(http, created)
    pending_id = await _admit_brreg_lead(http, investigation_id)
    fetch, calls = _fake_fetch({"organisasjonsnummer": "974760673"})

    async with factory() as session:
        await session.execute(
            text(
                "UPDATE leads SET status = 'BLOCKED', blocked_reason = 'manual_probe' "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": pending_id},
        )
        await session.commit()

    summary = await _run_pass(factory, investigation_id, fetch)

    assert summary["executed"] == 0
    assert summary["stopped_reason"] == "no_executable_leads"
    assert calls == []


async def test_pass_respects_lead_cap(loop_client) -> None:
    http, created, factory = loop_client
    investigation_id = await _create_company(http, created)
    await _admit_brreg_lead(http, investigation_id)
    await _admit_brreg_lead(http, investigation_id)
    fetch, _calls = _fake_fetch({"organisasjonsnummer": "974760673"})

    summary = await _run_pass(factory, investigation_id, fetch, max_leads=1)

    assert summary["executed"] == 1
    assert summary["stopped_reason"] == "lead_cap_reached"


async def test_pass_on_empty_frontier_stops_cleanly(loop_client) -> None:
    http, created, factory = loop_client
    investigation_id = await _create_company(http, created)
    fetch, _calls = _fake_fetch({"organisasjonsnummer": "974760673"})

    summary = await _run_pass(factory, investigation_id, fetch)

    assert summary == {
        "executed": 0,
        "blocked": 0,
        "failed": 0,
        "stopped_reason": "no_executable_leads",
    }


async def test_run_route_enqueues_pass_without_side_effects(
    loop_client, monkeypatch
) -> None:
    http, created, _factory = loop_client
    investigation_id = await _create_company(http, created)

    from apps.worker.app import tasks as worker_tasks

    sent: list[str] = []
    monkeypatch.setattr(
        worker_tasks.run_research_pass_actor, "send", lambda iid: sent.append(iid)
    )
    response = await http.post(f"/api/v1/investigations/{investigation_id}/research/run")
    assert response.status_code == 202, response.text
    assert response.json() == {"investigation_id": investigation_id, "status": "ENQUEUED"}
    assert sent == [investigation_id]


async def test_run_route_404_for_unknown_investigation(loop_client) -> None:
    http, _created, _factory = loop_client
    response = await http.post(f"/api/v1/investigations/{uuid.uuid4()}/research/run")
    assert response.status_code == 404
