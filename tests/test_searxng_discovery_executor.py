"""SearXNG discovery executor contract tests.

An admitted PENDING searxng_discovery lead runs through the injected search
function: the query is recorded in search_queries with full provenance
metadata, coverage is bumped, and the outcome is audited. Snippets stay
discovery-only -- they are never persisted as evidence. Failures (bad value,
unknown query class, source error) are explicit FAILED terminal states.
Opt-in: TEST_DATABASE_URL.
"""

import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.fixture
async def searxng_client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
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


async def _create_web_media_company(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {
                "type": "company",
                "name": "Discovery Probe AS",
                "known_orgnrs": ["974760673"],
            },
            "purpose": "Verify deterministic discovery execution",
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _admit_discovery_lead(http: httpx.AsyncClient, investigation_id: str, value: dict) -> str:
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": "searxng_discovery",
            "value": value,
            "reason": "Locate open web coverage of the target",
            "priority": 0.7,
            "depth": 0,
            "scope_area": "WEB_MEDIA",
            "trigger_type": "CONTRADICTION",
            "information_need": "Find web sources mentioning the target organization",
            "relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    return response.json()["lead_id"]


def _fake_search(
    results: list,
) -> tuple[Callable[[str], Awaitable[list]], list[str]]:
    calls: list[str] = []

    async def search(query: str):
        calls.append(query)
        return results

    return search, calls


async def _run_executor(factory, investigation_id: str, lead_id: str, search) -> str:
    from apps.api.app.domain.models import Lead
    from apps.api.app.repositories import investigations as repository
    from apps.api.app.services.executors.searxng_discovery import execute_searxng_discovery

    async with factory() as session:
        row = await repository.get_lead(session, uuid.UUID(investigation_id), uuid.UUID(lead_id))
        lead = Lead.model_validate(
            {
                "lead_type": row["lead_type"],
                "value": row["value"],
                "reason": row["reason"],
                "priority": row["priority"],
                "depth": row["depth"],
                "originating_claim_id": row["originating_claim_id"],
                "scope_area": row["scope_area"],
                "trigger_type": row["trigger_type"],
                "information_need": row["information_need"],
                "relation_depth": row["relation_depth"],
            }
        )
        status = await execute_searxng_discovery(
            session, uuid.UUID(investigation_id), uuid.UUID(lead_id), lead, search
        )
        await session.commit()
    return status


def _discovery_results():
    from apps.api.app.sources.base import DiscoveryResult

    return [
        DiscoveryResult(
            provider="searxng",
            url="https://example.com/a",
            title="Target in the news",
            snippet="Snippet mentioning the target organization",
            rank=1,
        ),
        DiscoveryResult(
            provider="searxng",
            url="https://example.com/b",
            title="More coverage",
            snippet="Another snippet mentioning the target",
            rank=2,
        ),
    ]


async def test_discovery_completes_with_query_row_coverage_and_audit(searxng_client) -> None:
    http, created, factory = searxng_client
    investigation_id = await _create_web_media_company(http, created)
    query = "Discovery Probe AS"
    lead_id = await _admit_discovery_lead(http, investigation_id, {"query": query})
    search, calls = _fake_search(_discovery_results())

    status = await _run_executor(factory, investigation_id, lead_id, search)
    assert status == "COMPLETED"
    assert calls == [query]

    async with factory() as session:
        lead = (
            (
                await session.execute(
                    text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                    {"id": lead_id},
                )
            )
            .mappings()
            .one()
        )
        search_row = (
            (
                await session.execute(
                    text(
                        "SELECT provider, query, query_hash, originating_lead_id, "
                        "scope_area, query_class, information_need, reason "
                        "FROM search_queries WHERE investigation_id = CAST(:id AS uuid)"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
        module = (
            (
                await session.execute(
                    text(
                        "SELECT status, coverage FROM investigation_modules "
                        "WHERE investigation_id = CAST(:id AS uuid) AND module = 'WEB_MEDIA'"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
        evidence_count = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS n FROM evidence e "
                        "JOIN investigation_documents d ON d.document_id = e.document_id "
                        "WHERE d.investigation_id = CAST(:id AS uuid)"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
        audits = (
            (
                await session.execute(
                    text(
                        "SELECT event_type, payload FROM audit_log "
                        "WHERE investigation_id = CAST(:id AS uuid) ORDER BY id"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .all()
        )

    assert lead["status"] == "COMPLETED"
    assert lead["blocked_reason"] is None
    assert search_row["provider"] == "searxng"
    assert search_row["query"] == query
    assert search_row["query_hash"] == hashlib.sha256(query.encode("utf-8")).hexdigest()
    assert str(search_row["originating_lead_id"]) == lead_id
    assert search_row["scope_area"] == "WEB_MEDIA"
    assert search_row["query_class"] == "DISCOVERY_BROAD"
    assert search_row["information_need"] == "Find web sources mentioning the target organization"
    assert search_row["reason"] == "Locate open web coverage of the target"
    assert module["status"] == "IN_PROGRESS"
    assert module["coverage"]["query_count"] == 1
    assert "searxng" in module["coverage"]["providers"]
    # Discovery stays discovery-only: snippets never become evidence.
    assert evidence_count["n"] == 0
    assert [row["event_type"] for row in audits] == [
        "CREATED",
        "LEAD_PROPOSED",
        "LEAD_EXECUTED",
    ]
    executed = audits[-1]["payload"]
    assert executed["lead_id"] == lead_id
    assert executed["status"] == "COMPLETED"
    assert executed["provider"] == "searxng"
    assert executed["query"] == query
    assert executed["result_count"] == 2


async def test_discovery_respects_explicit_query_class(searxng_client) -> None:
    http, created, factory = searxng_client
    investigation_id = await _create_web_media_company(http, created)
    query = "Discovery Probe AS styreleder"
    lead_id = await _admit_discovery_lead(
        http, investigation_id, {"query": query, "query_class": "ENTITY_ALIAS_EXACT"}
    )
    search, _calls = _fake_search([])

    status = await _run_executor(factory, investigation_id, lead_id, search)
    assert status == "COMPLETED"

    async with factory() as session:
        search_row = (
            (
                await session.execute(
                    text(
                        "SELECT query_class, query_hash FROM search_queries "
                        "WHERE investigation_id = CAST(:id AS uuid)"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
    assert search_row["query_class"] == "ENTITY_ALIAS_EXACT"
    assert search_row["query_hash"] == hashlib.sha256(query.encode("utf-8")).hexdigest()


async def test_discovery_source_error_fails_with_reason(searxng_client) -> None:
    http, created, factory = searxng_client
    investigation_id = await _create_web_media_company(http, created)
    lead_id = await _admit_discovery_lead(http, investigation_id, {"query": "Discovery Probe AS"})

    async def failing_search(query: str):
        raise TimeoutError("upstream unreachable")

    status = await _run_executor(factory, investigation_id, lead_id, failing_search)
    assert status == "FAILED"

    async with factory() as session:
        lead = (
            (
                await session.execute(
                    text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                    {"id": lead_id},
                )
            )
            .mappings()
            .one()
        )
        query_count = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS n FROM search_queries "
                        "WHERE investigation_id = CAST(:id AS uuid)"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
    assert lead["status"] == "FAILED"
    assert lead["blocked_reason"] == "source_error:TimeoutError"
    assert query_count["n"] == 0


async def test_discovery_invalid_value_fails_without_search(searxng_client) -> None:
    http, created, factory = searxng_client
    investigation_id = await _create_web_media_company(http, created)
    lead_id = await _admit_discovery_lead(http, investigation_id, {"query": "x"})
    search, calls = _fake_search(_discovery_results())

    status = await _run_executor(factory, investigation_id, lead_id, search)
    assert status == "FAILED"
    assert calls == []

    async with factory() as session:
        lead = (
            (
                await session.execute(
                    text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                    {"id": lead_id},
                )
            )
            .mappings()
            .one()
        )
    assert lead["status"] == "FAILED"
    assert lead["blocked_reason"] == "invalid_discovery_value"


async def test_discovery_invalid_query_class_fails_without_search(searxng_client) -> None:
    http, created, factory = searxng_client
    investigation_id = await _create_web_media_company(http, created)
    lead_id = await _admit_discovery_lead(
        http, investigation_id, {"query": "Discovery Probe AS", "query_class": "NOT_A_CLASS"}
    )
    search, calls = _fake_search(_discovery_results())

    status = await _run_executor(factory, investigation_id, lead_id, search)
    assert status == "FAILED"
    assert calls == []

    async with factory() as session:
        lead = (
            (
                await session.execute(
                    text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                    {"id": lead_id},
                )
            )
            .mappings()
            .one()
        )
    assert lead["status"] == "FAILED"
    assert lead["blocked_reason"] == "invalid_query_class"
