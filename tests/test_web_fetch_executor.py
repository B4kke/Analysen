"""Web fetch executor contract tests.

One admitted WEB_MEDIA lead runs through the injected fetch boundary:
validated, fetched, raw-stored, persisted as a web_direct document and
recorded with status, coverage and audit. Failures are explicit terminal
states, never silent. Opt-in: TEST_DATABASE_URL. No network, no browsers.
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
async def web_client(
    monkeypatch, tmp_path
) -> AsyncIterator[tuple[httpx.AsyncClient, list, object]]:
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


async def _create_web_investigation(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {
                "type": "company",
                "name": "Web Fetch Probe AS",
                "known_orgnrs": ["974760673"],
            },
            "purpose": "Verify direct web fetch executor",
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _admit_web_lead(http: httpx.AsyncClient, investigation_id: str, value: dict) -> str:
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": "web_document_fetch",
            "value": value,
            "reason": "Fetch the directly referenced article",
            "priority": 0.8,
            "depth": 0,
            "scope_area": "WEB_MEDIA",
            "trigger_type": "CONTRADICTION",
            "information_need": "Disconfirm the conflicting claim with the original page",
            "relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING", response.text
    return response.json()["lead_id"]


async def _execute_with_fake(
    factory, investigation_id: str, lead_id: str, fetch_result=None, exc=None
):
    from apps.api.app.domain.models import Lead
    from apps.api.app.repositories import investigations as repo
    from apps.api.app.services.executors.web_fetch import execute_web_fetch

    calls: list[str] = []

    async def fake_fetch(url: str):
        calls.append(url)
        if exc is not None:
            raise exc
        return fetch_result

    async with factory() as session:
        row = await repo.get_lead(session, uuid.UUID(investigation_id), uuid.UUID(lead_id))
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
        status = await execute_web_fetch(
            session, uuid.UUID(investigation_id), uuid.UUID(lead_id), lead, fake_fetch
        )
        await session.commit()
    return status, calls


async def test_web_fetch_happy_path_persists_document_and_coverage(web_client) -> None:
    http, created, factory = web_client
    investigation_id = await _create_web_investigation(http, created)
    url = "https://example.com/article"
    lead_id = await _admit_web_lead(http, investigation_id, {"url": url})

    from apps.api.app.services.url_canonicalization import FetchResult

    content = "<html><body>Original article body</body></html>"
    result = FetchResult(
        url=url,
        final_url="https://example.com/article",
        content=content,
        content_type="text/html",
        status_code=200,
        metadata={},
        error=None,
    )
    status, calls = await _execute_with_fake(
        factory, investigation_id, lead_id, fetch_result=result
    )
    assert status == "COMPLETED"
    assert calls == [url]

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
        document = (
            (
                await session.execute(
                    text(
                        "SELECT d.source_id, d.original_url, d.canonical_url, d.mime_type, "
                        "d.sha256, d.raw_storage_key, d.extracted_text, d.parser_metadata "
                        "FROM investigation_documents link JOIN documents d "
                        "ON d.id = link.document_id "
                        "WHERE link.investigation_id = CAST(:id AS uuid)"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
        source = (
            (
                await session.execute(
                    text(
                        "SELECT id, name, evidence_tier, access_class FROM sources WHERE id = :id"
                    ),
                    {"id": "web_direct"},
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
        counts = (
            (
                await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM claims "
                        "WHERE investigation_id = CAST(:id AS uuid)) AS claims, "
                        "(SELECT count(*) FROM evidence e JOIN investigation_documents link "
                        "ON link.document_id = e.document_id "
                        "WHERE link.investigation_id = CAST(:id AS uuid)) AS evidence"
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
    assert document["source_id"] == "web_direct"
    assert document["original_url"] == url
    assert document["canonical_url"] == "https://example.com/article"
    assert document["mime_type"] == "text/html"
    assert document["raw_storage_key"]
    assert document["extracted_text"] is None
    assert document["parser_metadata"]["fetcher"] == "direct"
    assert document["parser_metadata"]["final_url"] == "https://example.com/article"
    assert source["name"] == "Direct web fetch"
    assert source["evidence_tier"] == 3
    assert source["access_class"] == "PUBLIC_WEB"
    assert module["status"] == "IN_PROGRESS"
    assert module["coverage"]["query_count"] == 1
    assert module["coverage"]["document_count"] == 1
    assert "web_direct" in module["coverage"]["providers"]
    assert counts["claims"] == 0
    assert counts["evidence"] == 0
    executed = [row for row in audits if row["event_type"] == "LEAD_EXECUTED"]
    assert len(executed) == 1
    assert executed[0]["payload"]["status"] == "COMPLETED"
    assert executed[0]["payload"]["provider"] == "web_direct"
    assert executed[0]["payload"]["url"] == url
    assert executed[0]["payload"]["lead_id"] == lead_id

    import hashlib

    expected_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert document["sha256"] == expected_digest
    from apps.api.app.core.config import get_settings

    stored = (get_settings().raw_evidence_dir / document["raw_storage_key"]).read_bytes()
    assert stored.decode("utf-8") == content


async def test_web_fetch_invalid_url_fails_without_fetch(web_client) -> None:
    http, created, factory = web_client
    investigation_id = await _create_web_investigation(http, created)
    lead_id = await _admit_web_lead(http, investigation_id, {"url": "ftp://example.com/file"})

    status, calls = await _execute_with_fake(factory, investigation_id, lead_id, fetch_result=None)
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
        audits = (
            (
                await session.execute(
                    text(
                        "SELECT payload FROM audit_log WHERE investigation_id = CAST(:id AS uuid) "
                        "AND event_type = 'LEAD_EXECUTED' ORDER BY id"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .all()
        )
    assert lead["status"] == "FAILED"
    assert lead["blocked_reason"] == "invalid_fetch_url"
    assert audits[-1]["payload"]["reason"] == "invalid_fetch_url"


async def test_web_fetch_missing_url_key_fails_without_fetch(web_client) -> None:
    http, created, factory = web_client
    investigation_id = await _create_web_investigation(http, created)
    lead_id = await _admit_web_lead(http, investigation_id, {"not_url": "https://example.com/x"})

    status, calls = await _execute_with_fake(factory, investigation_id, lead_id, fetch_result=None)
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
    assert lead["blocked_reason"] == "invalid_fetch_url"


async def test_web_fetch_source_error_fails_with_reason(web_client) -> None:
    http, created, factory = web_client
    investigation_id = await _create_web_investigation(http, created)
    url = "https://example.com/gone"
    lead_id = await _admit_web_lead(http, investigation_id, {"url": url})

    from apps.api.app.services.url_canonicalization import FetchResult

    result = FetchResult(
        url=url,
        final_url=url,
        content="",
        content_type=None,
        status_code=404,
        metadata={},
        error="http: unavailable",
    )
    status, calls = await _execute_with_fake(
        factory, investigation_id, lead_id, fetch_result=result
    )
    assert status == "FAILED"
    assert calls == [url]

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
        doc_count = (
            (
                await session.execute(
                    text(
                        "SELECT count(*) AS n FROM investigation_documents "
                        "WHERE investigation_id = CAST(:id AS uuid)"
                    ),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .one()
        )
    assert lead["status"] == "FAILED"
    assert lead["blocked_reason"] == "source_error:FetchFailed"
    assert doc_count["n"] == 0


async def test_web_fetch_empty_content_fails_with_reason(web_client) -> None:
    http, created, factory = web_client
    investigation_id = await _create_web_investigation(http, created)
    url = "https://example.com/empty"
    lead_id = await _admit_web_lead(http, investigation_id, {"url": url})

    from apps.api.app.services.url_canonicalization import FetchResult

    result = FetchResult(
        url=url,
        final_url=url,
        content="   ",
        content_type="text/html",
        status_code=200,
        metadata={},
        error=None,
    )
    status, calls = await _execute_with_fake(
        factory, investigation_id, lead_id, fetch_result=result
    )
    assert status == "FAILED"
    assert calls == [url]

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
    assert lead["blocked_reason"] == "source_error:FetchFailed"
