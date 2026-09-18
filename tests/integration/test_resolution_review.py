"""Manual resolution review contract tests (AQ-022).

The scorer proposes; a human disposes. Only guarded transitions are allowed
and every decision is audited. Opt-in: TEST_DATABASE_URL.
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
async def review_client(
    monkeypatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
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


async def _create_investigation(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "person", "name": "Review Probe Person"},
            "purpose": "Verify manual resolution review",
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "CONTEXT_ONLY",
            "max_relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _seed_candidate(
    factory, investigation_id: str, status: str = "PROBABLE_MATCH"
) -> tuple[str, str]:
    entity_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    async with factory() as session:
        for eid in (entity_id, candidate_id):
            await session.execute(
                text(
                    "INSERT INTO entities (id, schema, canonical_name, attributes) "
                    "VALUES (:id, 'Person', 'Probe Person', CAST('{}' AS jsonb))"
                ),
                {"id": eid},
            )
        await session.execute(
            text(
                "INSERT INTO entity_resolution_candidates ("
                "investigation_id, entity_id, candidate_entity_id, "
                "match_score, resolution_status, negative_signals) "
                "VALUES (:iid, :eid, :cid, 0.7, :status, CAST('[]' AS jsonb))"
            ),
            {"iid": uuid.UUID(investigation_id), "eid": entity_id, "cid": candidate_id,
             "status": status},
        )
        await session.commit()
    return str(entity_id), str(candidate_id)


async def test_list_candidates_shows_scores_and_signals(review_client) -> None:
    http, created, _factory = review_client
    investigation_id = await _create_investigation(http, created)
    entity_id, candidate_id = await _seed_candidate(_factory, investigation_id)

    response = await http.get(f"/api/v1/investigations/{investigation_id}/resolution/candidates")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["entity_id"] == entity_id
    assert rows[0]["candidate_entity_id"] == candidate_id
    assert rows[0]["match_score"] == 0.7
    assert rows[0]["resolution_status"] == "PROBABLE_MATCH"


async def test_approve_probable_match_is_audited(review_client) -> None:
    http, created, factory = review_client
    investigation_id = await _create_investigation(http, created)
    entity_id, candidate_id = await _seed_candidate(factory, investigation_id)

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/resolution/{entity_id}/{candidate_id}",
        json={"status": "MATCH", "reason": "Verified against registry entry"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["to"] == "MATCH"

    async with factory() as session:
        status = (
            await session.execute(
                text(
                    "SELECT resolution_status FROM entity_resolution_candidates "
                    "WHERE investigation_id = CAST(:iid AS uuid)"
                ),
                {"iid": investigation_id},
            )
        ).scalar_one()
        audit = (
            await session.execute(
                text(
                    "SELECT event_type, payload FROM audit_log "
                    "WHERE investigation_id = CAST(:iid AS uuid) "
                    "AND event_type = 'RESOLUTION_REVIEWED'"
                ),
                {"iid": investigation_id},
            )
        ).mappings().one()
    assert status == "MATCH"
    assert audit["payload"]["to"] == "MATCH"
    assert audit["payload"]["reason"] == "Verified against registry entry"


async def test_reject_unresolved_candidate(review_client) -> None:
    http, created, factory = review_client
    investigation_id = await _create_investigation(http, created)
    entity_id, candidate_id = await _seed_candidate(factory, investigation_id, status="UNRESOLVED")

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/resolution/{entity_id}/{candidate_id}",
        json={"status": "NOT_MATCH", "reason": "Different birth year in registry"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "entity_id": entity_id,
        "candidate_entity_id": candidate_id,
        "from": "UNRESOLVED",
        "to": "NOT_MATCH",
    }


async def test_unresolved_cannot_be_forged_to_match(review_client) -> None:
    http, created, _factory = review_client
    investigation_id = await _create_investigation(http, created)
    entity_id, candidate_id = await _seed_candidate(_factory, investigation_id, status="UNRESOLVED")

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/resolution/{entity_id}/{candidate_id}",
        json={"status": "MATCH", "reason": "Trying to force a match"},
    )
    assert response.status_code == 409, response.text


async def test_terminal_states_are_final(review_client) -> None:
    http, created, _factory = review_client
    investigation_id = await _create_investigation(http, created)
    entity_id, candidate_id = await _seed_candidate(_factory, investigation_id, status="NOT_MATCH")

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/resolution/{entity_id}/{candidate_id}",
        json={"status": "MATCH", "reason": "Second thoughts"},
    )
    assert response.status_code == 409, response.text


async def test_unknown_candidate_returns_404(review_client) -> None:
    http, created, _factory = review_client
    investigation_id = await _create_investigation(http, created)
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/resolution/{uuid.uuid4()}/{uuid.uuid4()}",
        json={"status": "NOT_MATCH", "reason": "No such candidate"},
    )
    assert response.status_code == 404


async def test_unknown_investigation_returns_404(review_client) -> None:
    http, _created, _factory = review_client
    response = await http.get(f"/api/v1/investigations/{uuid.uuid4()}/resolution/candidates")
    assert response.status_code == 404
