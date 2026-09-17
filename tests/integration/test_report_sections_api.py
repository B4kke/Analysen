"""Integration test for the dynamic report sections endpoint (AQ-006).

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
async def report_client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
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


async def test_report_sections_separate_selected_and_unselected(report_client) -> None:
    http, created, factory = report_client
    payload = {
        "target": {"type": "company", "name": "Report Probe AS", "known_orgnrs": []},
        "purpose": "Verify dynamic report sections",
        "scope_modules": ["WEB_MEDIA", "BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await http.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))

    async with factory() as session:
        await session.execute(
            text(
                """
                UPDATE investigation_modules
                SET status = 'COMPLETE',
                    coverage = jsonb_build_object('providers', jsonb_build_array('probe'),
                                                  'query_count', 2,
                                                  'document_count', 1)
                WHERE investigation_id = :id AND module = 'WEB_MEDIA'
                """
            ),
            {"id": investigation_id},
        )
        await session.execute(
            text(
                """
                UPDATE investigation_modules
                SET status = 'PARTIAL', stop_reason = 'source_rate_limited'
                WHERE investigation_id = :id AND module = 'BUSINESS_ROLES'
                """
            ),
            {"id": investigation_id},
        )
        await session.commit()

    report = await http.get(f"/api/v1/investigations/{investigation_id}/report/sections")
    assert report.status_code == 200, report.text
    sections = report.json()

    assert [item["module"] for item in sections["Undersøkt"]] == ["WEB_MEDIA"]
    assert sections["Undersøkt"][0]["coverage"]["query_count"] == 2
    assert [item["module"] for item in sections["Undersøkt med mangler"]] == [
        "BUSINESS_ROLES"
    ]
    assert sections["Undersøkt med mangler"][0]["stop_reason"] == "source_rate_limited"
    assert [item["module"] for item in sections["Ikke valgt"]] == [
        "ANNOUNCEMENTS_STATUS", "COMPANY_NETWORK", "DOMAINS_DIGITAL", "FINANCIALS",
        "HISTORICAL_WEB", "PUBLIC_PROFILES", "SANCTIONS",
    ]
    assert sections["Ikke undersøkt"] == []
    assert sections["Utilgjengelig"] == []


async def test_report_endpoint_404_for_unknown_investigation(report_client) -> None:
    http, _created, _factory = report_client
    response = await http.get(
        f"/api/v1/investigations/{uuid.uuid4()}/report/sections"
    )
    assert response.status_code == 404
