"""Database-backed scope narrowing regression tests for AQ-004.

These tests are opt-in: they require TEST_DATABASE_URL and clean up the
investigation IDs they create.
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
async def scope_client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
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
    client: httpx.AsyncClient, created: list[uuid.UUID]
) -> dict:
    payload = {
        "target": {"type": "company", "name": "Scope Narrow Probe AS", "known_orgnrs": []},
        "purpose": "Verify deterministic scope narrowing",
        "scope_modules": ["BUSINESS_ROLES", "WEB_MEDIA"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await client.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    created.append(uuid.UUID(body["id"]))
    return body


async def test_scope_narrowing_blocks_pending_leads_and_keeps_coverage(
    scope_client,
) -> None:
    http, created, factory = scope_client
    body = await _create_company(http, created)
    investigation_id = body["id"]

    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO leads (
                    investigation_id, lead_type, value, reason, status,
                    scope_area, trigger_type, information_need
                )
                VALUES
                    (:id, 'brreg_role_lookup', CAST('{}' AS jsonb), 'verify roles', 'PENDING',
                     'BUSINESS_ROLES', 'MATERIAL_RELATION', 'Documented role history'),
                    (:id, 'web_media_lookup', CAST('{}' AS jsonb), 'verify coverage', 'PENDING',
                     'WEB_MEDIA', 'MEDIA_CORROBORATION', 'Independent media coverage')
                """
            ),
            {"id": investigation_id},
        )
        await session.execute(
            text(
                """
                UPDATE investigation_modules
                SET status = 'PARTIAL',
                    coverage = jsonb_build_object('providers', jsonb_build_array('probe')),
                    stop_reason = 'budget_exhausted_probe'
                WHERE investigation_id = :id AND module = 'BUSINESS_ROLES'
                """
            ),
            {"id": investigation_id},
        )
        await session.commit()

    narrowed = await http.patch(
        f"/api/v1/investigations/{investigation_id}/scope",
        json={
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
            "reason": "Pause media research",
        },
    )
    assert narrowed.status_code == 200, narrowed.text

    async with factory() as session:
        leads = (
            await session.execute(
                text(
                    """
                    SELECT scope_area, status, blocked_reason FROM leads
                    WHERE investigation_id = :id ORDER BY scope_area
                    """
                ),
                {"id": investigation_id},
            )
        ).mappings().all()
        module = (
            await session.execute(
                text(
                    """
                    SELECT status, coverage, stop_reason FROM investigation_modules
                    WHERE investigation_id = :id AND module = 'BUSINESS_ROLES'
                    """
                ),
                {"id": investigation_id},
            )
        ).mappings().one()
        audit = (
            await session.execute(
                text(
                    """
                    SELECT event_type, payload FROM audit_log
                    WHERE investigation_id = :id AND event_type = 'SCOPE_CHANGED'
                    """
                ),
                {"id": investigation_id},
            )
        ).mappings().one()

    assert [(row["status"], row["blocked_reason"]) for row in leads] == [
        ("PENDING", None),
        ("BLOCKED", "module_disabled"),
    ]
    assert module["status"] == "PARTIAL"
    assert module["coverage"]["providers"] == ["probe"]
    assert module["stop_reason"] == "budget_exhausted_probe"
    assert audit["payload"]["after"]["scope_modules"] == ["BUSINESS_ROLES"]
    assert audit["payload"]["before"]["scope_modules"] == ["BUSINESS_ROLES", "WEB_MEDIA"]
    assert audit["payload"]["reason"] == "Pause media research"


async def test_scope_update_without_audit_persists_is_rolled_back(scope_client) -> None:
    http, created, factory = scope_client
    body = await _create_company(http, created)
    investigation_id = body["id"]

    from unittest.mock import patch as unittest_patch

    from apps.api.app.repositories import investigations as repository

    with unittest_patch.object(
        repository, "_audit", side_effect=RuntimeError("audit sink unavailable")
    ), pytest.raises(RuntimeError, match="audit sink unavailable"):
        await http.patch(
            f"/api/v1/investigations/{investigation_id}/scope",
            json={
                "scope_modules": [],
                "expansion_policy": "CONTEXT_ONLY",
                "max_relation_depth": 0,
                "reason": "Attempt invalid narrowing",
            },
        )

    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT scope_modules, expansion_policy, max_relation_depth "
                    "FROM investigations WHERE id = :id"
                ),
                {"id": uuid.UUID(investigation_id)},
            )
        ).mappings().one()
        lead_counts = (
            await session.execute(
                text(
                    "SELECT status, count(*) FROM leads "
                    "WHERE investigation_id = :id GROUP BY status"
                ),
                {"id": uuid.UUID(investigation_id)},
            )
        ).all()
        module_states = (
            await session.execute(
                text(
                    "SELECT module, enabled FROM investigation_modules "
                    "WHERE investigation_id = :id AND enabled"
                ),
                {"id": uuid.UUID(investigation_id)},
            )
        ).all()

    assert row["scope_modules"] == ["BUSINESS_ROLES", "WEB_MEDIA"]
    assert row["expansion_policy"] == "DIRECT_RELATIONS"
    assert row["max_relation_depth"] == 1
    assert lead_counts == []
    assert sorted(module_states) == [("BUSINESS_ROLES", True), ("WEB_MEDIA", True)]
