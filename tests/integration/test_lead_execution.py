"""Lead executor contract tests (AQ-013).

One admitted PENDING lead runs end to end: re-gated at the tool boundary,
fetched, persisted, and recorded with status, coverage and audit. Refusals and
failures are explicit terminal states, never silent. Opt-in: TEST_DATABASE_URL.
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
async def exec_client(monkeypatch) -> AsyncIterator[tuple[httpx.AsyncClient, object, object]]:
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
                "name": "Executor Probe AS",
                "known_orgnrs": ["974760673"],
            },
            "purpose": "Verify deterministic lead execution",
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
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    return response.json()["lead_id"]


def _fake_fetch(payload: dict):
    from apps.api.app.sources.base import SourceRecord

    async def fetch(orgnr: str):
        return SourceRecord(
            source_id="brreg_entities",
            external_id=orgnr,
            source_url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}",
            payload=payload,
        )

    return fetch


async def _patch_fetch(monkeypatch, payload: dict) -> list[str]:
    from apps.api.app.api.routes import investigations as routes

    calls: list[str] = []
    real_fetch = _fake_fetch(payload)

    async def recording_fetch(orgnr: str):
        calls.append(orgnr)
        return await real_fetch(orgnr)

    async def adapter_fetch(self, orgnr: str):
        return await recording_fetch(orgnr)

    monkeypatch.setattr(routes.BrregAdapter, "fetch", adapter_fetch)
    return calls


async def test_execute_brreg_lead_completes_with_evidence_and_coverage(
    exec_client, monkeypatch
) -> None:
    http, created, factory = exec_client
    investigation_id = await _create_company(http, created)
    lead_id = await _admit_brreg_lead(http, investigation_id)
    calls = await _patch_fetch(
        monkeypatch,
        {
            "organisasjonsnummer": "974760673",
            "navn": "Executor Probe AS",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        },
    )

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"lead_id": lead_id, "status": "COMPLETED"}
    assert calls == ["974760673"]

    async with factory() as session:
        lead = (
            await session.execute(
                text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                {"id": lead_id},
            )
        ).mappings().one()
        module = (
            await session.execute(
                text(
                    "SELECT status, coverage FROM investigation_modules "
                    "WHERE investigation_id = CAST(:id AS uuid) AND module = 'BUSINESS_ROLES'"
                ),
                {"id": investigation_id},
            )
        ).mappings().one()
        counts = (
            await session.execute(
                text(
                    """SELECT (SELECT count(*) FROM evidence e
                        JOIN investigation_documents d ON d.document_id = e.document_id
                        WHERE d.investigation_id = CAST(:id AS uuid)) AS evidence,
                       (SELECT count(*) FROM claims
                        WHERE investigation_id = CAST(:id AS uuid)) AS claims"""
                ),
                {"id": investigation_id},
            )
        ).mappings().one()
        audits = (
            await session.execute(
                text(
                    "SELECT event_type FROM audit_log "
                    "WHERE investigation_id = CAST(:id AS uuid) ORDER BY id"
                ),
                {"id": investigation_id},
            )
        ).mappings().all()

    assert lead["status"] == "COMPLETED"
    assert lead["blocked_reason"] is None
    assert module["status"] == "IN_PROGRESS"
    assert module["coverage"]["query_count"] == 1
    assert module["coverage"]["document_count"] == 1
    assert "brreg_entities" in module["coverage"]["providers"]
    assert counts["evidence"] >= 1
    assert counts["claims"] >= 1
    assert [row["event_type"] for row in audits] == [
        "CREATED",
        "LEAD_PROPOSED",
        "LEAD_EXECUTED",
    ]


async def test_execute_after_scope_narrowing_is_blocked_without_fetch(
    exec_client, monkeypatch
) -> None:
    http, created, _factory = exec_client
    investigation_id = await _create_company(http, created)
    lead_id = await _admit_brreg_lead(http, investigation_id)
    calls = await _patch_fetch(monkeypatch, {"organisasjonsnummer": "974760673"})

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

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.json()["status"] == "BLOCKED"
    assert calls == []


async def test_execute_unsupported_lead_type_fails_closed(exec_client, monkeypatch) -> None:
    http, created, factory = exec_client
    investigation_id = await _create_company(http, created)
    admitted = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": "crawl_entire_internet",
            "value": {"url": "https://example.com"},
            "reason": "A planner hallucinated a tool",
            "priority": 0.9,
            "depth": 0,
            "scope_area": "WEB_MEDIA",
            "trigger_type": "CONTRADICTION",
            "information_need": "Disconfirm the conflicting claim",
            "relation_depth": 0,
        },
    )
    # WEB_MEDIA is not enabled, so admission itself refuses; use BUSINESS_ROLES.
    assert admitted.json()["status"] == "BLOCKED"

    admitted = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": "crawl_entire_internet",
            "value": {"orgnr": "974760673"},
            "reason": "A planner hallucinated a tool",
            "priority": 0.9,
            "depth": 0,
            "scope_area": "BUSINESS_ROLES",
            "trigger_type": "WEAK_SOURCE_ONLY",
            "information_need": "Confirm registered details of the target",
            "relation_depth": 0,
        },
    )
    assert admitted.json()["status"] == "PENDING"
    lead_id = admitted.json()["lead_id"]
    calls = await _patch_fetch(monkeypatch, {"organisasjonsnummer": "974760673"})

    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.json()["status"] == "FAILED"
    assert calls == []

    async with factory() as session:
        lead = (
            await session.execute(
                text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                {"id": lead_id},
            )
        ).mappings().one()
    assert lead["status"] == "FAILED"
    assert lead["blocked_reason"] == "unsupported_lead_type"


async def test_execute_source_error_fails_with_reason(exec_client, monkeypatch) -> None:
    http, created, _factory = exec_client
    investigation_id = await _create_company(http, created)
    lead_id = await _admit_brreg_lead(http, investigation_id)

    from apps.api.app.api.routes import investigations as routes

    async def failing_fetch(self, orgnr: str):
        raise TimeoutError("upstream unreachable")

    monkeypatch.setattr(routes.BrregAdapter, "fetch", failing_fetch)
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert response.json()["status"] == "FAILED"


async def test_execute_unknown_lead_returns_404(exec_client) -> None:
    http, created, _factory = exec_client
    investigation_id = await _create_company(http, created)
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{uuid.uuid4()}/execute"
    )
    assert response.status_code == 404


async def test_reexecute_completed_lead_does_not_refetch(
    exec_client, monkeypatch
) -> None:
    http, created, _factory = exec_client
    investigation_id = await _create_company(http, created)
    lead_id = await _admit_brreg_lead(http, investigation_id)
    calls = await _patch_fetch(
        monkeypatch,
        {
            "organisasjonsnummer": "974760673",
            "navn": "Executor Probe AS",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
        },
    )

    first = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    second = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads/{lead_id}/execute"
    )
    assert first.json()["status"] == "COMPLETED"
    assert second.json()["status"] == "COMPLETED"
    assert calls == ["974760673"]
