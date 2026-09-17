"""End-to-end tests for the planner/lead admission route (AQ-005).

Proposed leads must pass the deterministic scope gate before they can become
PENDING. Refused leads are stored as BLOCKED with the gate reason and audited.
Opt-in: requires TEST_DATABASE_URL.
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
async def lead_client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
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


async def _create_company(
    client: httpx.AsyncClient, created: list, *, modules: list[str]
) -> str:
    payload = {
        "target": {"type": "company", "name": "Lead Gate Probe AS", "known_orgnrs": []},
        "purpose": "Verify deterministic lead admission",
        "scope_modules": modules,
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await client.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    created.append(response.json()["id"])
    return response.json()["id"]


def _lead_payload(**overrides) -> dict:
    payload = {
        "lead_type": "web_media_lookup",
        "value": {"url": "https://example.com/article"},
        "reason": "Verifies registered status from an independent secondary source",
        "priority": 0.5,
        "depth": 1,
        "scope_area": "WEB_MEDIA",
        "trigger_type": "CONTRADICTION",
        "information_need": "Resolve contradiction between registered status and media claim",
        "relation_depth": 0,
    }
    payload.update(overrides)
    return payload


async def _lead_rows(factory, investigation_id: str) -> list[dict]:
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT scope_area, status, blocked_reason, trigger_type "
                    "FROM leads WHERE investigation_id = CAST(:id AS uuid) "
                    "ORDER BY scope_area"
                ),
                {"id": investigation_id},
            )
        ).mappings().all()
    return [dict(row) for row in rows]


async def test_proposed_lead_passes_gate_and_is_pending(lead_client) -> None:
    http, created, factory = lead_client
    investigation_id = await _create_company(http, created, modules=["WEB_MEDIA"])

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads", json=_lead_payload()
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"

    rows = await _lead_rows(factory, investigation_id)
    assert rows == [
        {
            "scope_area": "WEB_MEDIA",
            "status": "PENDING",
            "blocked_reason": None,
            "trigger_type": "CONTRADICTION",
        }
    ]

    async with factory() as session:
        audit = (
            await session.execute(
                text(
                    "SELECT payload FROM audit_log "
                    "WHERE investigation_id = CAST(:id AS uuid) "
                    "AND event_type = 'LEAD_PROPOSED'"
                ),
                {"id": investigation_id},
            )
        ).mappings().one()
    assert audit["payload"]["decision"] is None
    assert audit["payload"]["status"] == "PENDING"


async def test_passive_trigger_cannot_become_pending(lead_client) -> None:
    http, created, factory = lead_client
    investigation_id = await _create_company(http, created, modules=["WEB_MEDIA"])

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json=_lead_payload(trigger_type="MEDIA_CORROBORATION", relation_depth=1),
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "BLOCKED"

    rows = await _lead_rows(factory, investigation_id)
    assert rows[0]["status"] == "BLOCKED"
    assert rows[0]["blocked_reason"] == "passive_trigger_requires_review"


async def test_lead_outside_scope_is_blocked_not_executed(lead_client) -> None:
    http, created, factory = lead_client
    investigation_id = await _create_company(http, created, modules=["BUSINESS_ROLES"])

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads", json=_lead_payload()
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "BLOCKED"

    rows = await _lead_rows(factory, investigation_id)
    assert rows == [
        {
            "scope_area": "WEB_MEDIA",
            "status": "BLOCKED",
            "blocked_reason": "module_disabled",
            "trigger_type": "CONTRADICTION",
        }
    ]


async def test_scope_narrowing_after_admission_blocks_pending_lead(lead_client) -> None:
    http, created, factory = lead_client
    investigation_id = await _create_company(http, created, modules=["WEB_MEDIA"])

    admitted = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads", json=_lead_payload()
    )
    assert admitted.json()["status"] == "PENDING"

    narrowed = await http.patch(
        f"/api/v1/investigations/{investigation_id}/scope",
        json={
            "scope_modules": [],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
            "reason": "Pause all research",
        },
    )
    assert narrowed.status_code == 200, narrowed.text

    rows = await _lead_rows(factory, investigation_id)
    assert rows == [
        {
            "scope_area": "WEB_MEDIA",
            "status": "BLOCKED",
            "blocked_reason": "module_disabled",
            "trigger_type": "CONTRADICTION",
        }
    ]


async def test_unknown_investigation_returns_404(lead_client) -> None:
    http, _created, _factory = lead_client
    response = await http.post(
        f"/api/v1/investigations/{os.urandom(16).hex()}/leads", json=_lead_payload()
    )
    assert response.status_code == 404
