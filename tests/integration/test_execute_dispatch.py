"""Router dispatch contract tests (AQ-024).

Proves POST /leads/{lead_id}/execute routes each allowlisted lead type to
its executor: searxng discovery persists search metadata (never evidence),
web fetch persists documents, unknown types fail closed, and missing tools
fail as unavailable. External calls are monkeypatched fakes; only the
database is real. Opt-in: TEST_DATABASE_URL.
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
async def dispatch_client(
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


async def _create_company(
    http: httpx.AsyncClient, created: list, modules: list[str]
) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "company", "name": "Dispatch Probe AS"},
            "purpose": "Verify router dispatch",
            "scope_modules": modules,
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _admit(
    http: httpx.AsyncClient,
    investigation_id: str,
    lead_type: str,
    value: dict,
    scope_area: str,
) -> str:
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": lead_type,
            "value": value,
            "reason": "Verify router dispatch",
            "priority": 0.7,
            "depth": 0,
            "scope_area": scope_area,
            "trigger_type": "CONTRADICTION",
            "information_need": "Resolve the open contradiction",
            "relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING", response.json()
    return response.json()["lead_id"]


async def test_dispatch_searxng_discovery_completes(dispatch_client, monkeypatch) -> None:
    from apps.api.app.sources.base import DiscoveryResult

    async def fake_search(self, query: str, **kwargs):
        assert query == "Dispatch Probe AS registration"
        return [
            DiscoveryResult(
                provider="searxng",
                url="https://example.com/registration",
                title="Registration",
                snippet="A snippet that must never become evidence",
                rank=1,
            )
        ]

    from apps.api.app.sources import searxng as searxng_module

    monkeypatch.setattr(searxng_module.SearxngAdapter, "search", fake_search)

    http, created, factory = dispatch_client
    investigation_id = await _create_company(http, created, ["WEB_MEDIA"])
    lead_id = await _admit(
        http,
        investigation_id,
        "searxng_discovery",
        {"query": "Dispatch Probe AS registration"},
        "WEB_MEDIA",
    )
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.json()["status"] == "COMPLETED"

    async with factory() as session:
        query_row = (
            await session.execute(
                text(
                    "SELECT provider, query, query_hash, scope_area, originating_lead_id "
                    "FROM search_queries WHERE investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).mappings().one()
        evidence_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM evidence e "
                    "JOIN investigation_documents d ON d.document_id = e.document_id "
                    "WHERE d.investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).scalar_one()
    assert query_row["provider"] == "searxng"
    assert query_row["query"] == "Dispatch Probe AS registration"
    assert len(query_row["query_hash"]) == 64
    assert query_row["scope_area"] == "WEB_MEDIA"
    assert str(query_row["originating_lead_id"]) == lead_id
    assert evidence_count == 0


async def test_dispatch_web_fetch_completes(dispatch_client, monkeypatch) -> None:
    from apps.api.app.services.url_canonicalization import FetchResult

    async def fake_fetch(self, url: str):
        assert url == "https://example.com/company"
        return FetchResult(
            url=url,
            final_url=url,
            content="<html><body>Company profile</body></html>",
            content_type="text/html",
            status_code=200,
            metadata={},
            error=None,
        )

    from apps.api.app.services import document_fetcher as fetcher_module

    monkeypatch.setattr(fetcher_module.DocumentFetcher, "fetch", fake_fetch)

    http, created, factory = dispatch_client
    investigation_id = await _create_company(http, created, ["WEB_MEDIA"])
    lead_id = await _admit(
        http, investigation_id, "web_document_fetch", {"url": "https://example.com/company"},
        "WEB_MEDIA",
    )
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.json()["status"] == "COMPLETED"

    async with factory() as session:
        document = (
            await session.execute(
                text(
                    "SELECT d.mime_type, d.raw_storage_key, d.sha256 "
                    "FROM documents d JOIN investigation_documents idoc "
                    "ON idoc.document_id = d.id "
                    "WHERE idoc.investigation_id = CAST(:id AS uuid)"
                ),
                {"id": investigation_id},
            )
        ).mappings().one()
        claims = (
            await session.execute(
                text("SELECT count(*) FROM claims WHERE investigation_id = CAST(:id AS uuid)"),
                {"id": investigation_id},
            )
        ).scalar_one()
    assert document["mime_type"] == "text/html"
    assert document["raw_storage_key"]
    assert len(document["sha256"]) == 64
    assert claims == 0


async def test_dispatch_unknown_type_fails_closed(dispatch_client) -> None:
    http, created, _factory = dispatch_client
    investigation_id = await _create_company(http, created, ["WEB_MEDIA"])
    lead_id = await _admit(
        http, investigation_id, "crawl_entire_internet", {"url": "https://example.com"},
        "WEB_MEDIA",
    )
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.json()["status"] == "FAILED"


async def test_dispatch_without_tools_fails_unavailable(dispatch_client) -> None:
    from apps.api.app.services.lead_executor import ExecutorTools, execute_lead

    http, created, factory = dispatch_client
    investigation_id = await _create_company(http, created, ["WEB_MEDIA"])
    lead_id = await _admit(
        http,
        investigation_id,
        "searxng_discovery",
        {"query": "Dispatch Probe AS registration"},
        "WEB_MEDIA",
    )
    async with factory() as session:
        status = await execute_lead(
            session, uuid.UUID(investigation_id), uuid.UUID(lead_id), ExecutorTools()
        )
        await session.commit()
    assert status == "FAILED"

    async with factory() as session:
        reason = (
            await session.execute(
                text("SELECT blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                {"id": lead_id},
            )
        ).scalar_one()
    assert reason == "executor_unavailable"
