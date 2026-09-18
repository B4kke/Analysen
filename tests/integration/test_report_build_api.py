"""Report-document builder integration test (AQ-027 slice).

Builds a ReportDocument from stored rows (source -> document -> evidence ->
claim, one PENDING lead, one BLOCKED lead, one context-only entity) and
asserts findings carry citations with url+sha256, coverage lists all 9
modules, the context entity appears by name only, pending leads surface as
unverified leads, and UNVERIFIED_LEAD claims never become findings.

Opt-in: requires TEST_DATABASE_URL.
"""

import json
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
async def report_build_client(
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


async def _create_investigation(
    http: httpx.AsyncClient, created: list[uuid.UUID], name: str
) -> uuid.UUID:
    payload = {
        "target": {
            "type": "company",
            "name": name,
            "known_orgnrs": ["974760673"],
        },
        "purpose": "Verify deterministic report JSON",
        "scope_modules": ["BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await http.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    investigation_id = uuid.UUID(response.json()["id"])
    created.append(investigation_id)
    return investigation_id


async def test_build_report_document_from_stored_rows(report_build_client) -> None:
    from apps.api.app.domain.models import ClaimStatus, SourceRegistryRecord
    from apps.api.app.domain.scope import ScopeModule
    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.raw_store import store_raw_snapshot
    from apps.api.app.services.report_build import build_report_document

    http, created, factory = report_build_client
    suffix = uuid.uuid4().hex[:8]
    target_name = f"Rapport Probe {suffix} AS"
    investigation_id = await _create_investigation(http, created, target_name)

    source_id = f"test_report_build_source_{suffix}"
    url = f"https://example.invalid/report-build/{suffix}/enheter/974760673"
    subject_name = f"Rapport Subjekt {suffix} AS"
    context_name = f"Kontekst {suffix} AS"
    predicate = "company.registered_name"
    unverified_predicate = "company.unverified_rumor"
    information_need = f"Trenger organisasjonsnummer for {suffix}"

    async with factory() as session:
        await repo.upsert_source(
            session,
            SourceRegistryRecord(
                id=source_id,
                name=f"{source_id} name",
                evidence_tier=1,
                access_class="OPEN",
                base_url=url,
                license="test-fixture",
                metadata={"fixture": "report-build"},
            ),
        )
        subject_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Company",
            canonical_name=subject_name,
            attributes={},
            resolution_state="UNRESOLVED",
        )
        raw_payload = json.dumps(
            {"organisasjonsnummer": "974760673", "navn": subject_name},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest, storage_key = store_raw_snapshot(raw_payload)
        document_id = await repo.upsert_document(
            session,
            source_id=source_id,
            original_url=url,
            canonical_url=url,
            mime_type="application/json",
            sha256=digest,
            raw_storage_key=storage_key,
            extracted_text=subject_name,
            parser_metadata={"fixture": "report-build"},
        )
        await repo.attach_document(session, investigation_id, document_id)
        evidence_id = await repo.store_evidence(
            session, document_id, "json_path", {"section": "navn"}, subject_name, None
        )
        await repo.upsert_claim(
            session,
            investigation_id,
            subject_id,
            predicate,
            {"name": subject_name},
            "SUPPORTED",
            [evidence_id],
        )
        # Open work stays a lead, never a finding.
        await repo.upsert_claim(
            session,
            investigation_id,
            None,
            unverified_predicate,
            {"note": f"ubekreftet {suffix}"},
            "UNVERIFIED_LEAD",
            [],
        )
        context_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Company",
            canonical_name=context_name,
            attributes={},
            resolution_state="UNRESOLVED",
        )
        await session.execute(
            text("""
                INSERT INTO investigation_entities
                    (investigation_id, entity_id, expansion_state)
                VALUES (:iid, :eid, 'CONTEXT_ONLY')
                ON CONFLICT (investigation_id, entity_id) DO UPDATE
                SET expansion_state = EXCLUDED.expansion_state
            """),
            {"iid": investigation_id, "eid": context_id},
        )
        await session.execute(
            text("""
                INSERT INTO leads (
                    investigation_id, lead_type, value, reason, priority,
                    depth, status, scope_area, trigger_type, information_need,
                    relation_depth
                ) VALUES (
                    :iid, 'probe', CAST(:value AS jsonb), :reason, 0.5,
                    0, 'PENDING', 'BUSINESS_ROLES', 'WEAK_SOURCE_ONLY', :need, 0
                )
            """),
            {
                "iid": investigation_id,
                "value": json.dumps({"probe": suffix}),
                "reason": f"Svak kilde {suffix}",
                "need": information_need,
            },
        )
        # Decided leads are graveyards: the report must not list them.
        await session.execute(
            text("""
                INSERT INTO leads (
                    investigation_id, lead_type, value, reason, priority,
                    depth, status, blocked_reason, relation_depth
                ) VALUES (
                    :iid, 'probe', CAST(:value AS jsonb), :reason, 0.1,
                    0, 'BLOCKED', 'scope_changed', 0
                )
            """),
            {
                "iid": investigation_id,
                "value": json.dumps({"probe": f"blocked-{suffix}"}),
                "reason": f"Avvist {suffix}",
            },
        )
        await session.commit()

    async with factory() as session:
        document = await build_report_document(session, investigation_id)

    assert document.investigation_id == investigation_id
    assert document.target_name == target_name
    assert document.target_type == "company"
    assert document.purpose == "Verify deterministic report JSON"
    assert document.expansion_policy == "DIRECT_RELATIONS"
    assert document.max_relation_depth == 1
    assert document.scope_modules == ["BUSINESS_ROLES"]

    findings = [item for item in document.findings if item.predicate == predicate]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.status == ClaimStatus.SUPPORTED
    assert finding.subject_name == subject_name
    assert len(finding.citations) >= 1
    citation = finding.citations[0]
    assert citation.url == url
    assert citation.sha256 == digest
    assert citation.evidence_id is not None
    assert citation.document_id == document_id

    assert not [item for item in document.findings if item.predicate == unverified_predicate]
    assert all(item.status != ClaimStatus.UNVERIFIED_LEAD for item in document.findings)

    assert len(document.coverage) == len(ScopeModule)
    assert {entry.module for entry in document.coverage} == {
        module.value for module in ScopeModule
    }
    assert all(
        entry.outcome
        in {
            "UNDERSØKT",
            "UNDERSØKT_MED_GAPS",
            "IKKE_UNDERSØKT",
            "BLOKKERT_UTILGJENGELIG",
            "IKKE_VALGT",
        }
        for entry in document.coverage
    )

    context = [item for item in document.context_entities if item.name == context_name]
    assert len(context) == 1
    assert context[0].entity_schema == "Company"
    assert context[0].relation is None

    assert len(document.unverified_leads) == 1
    assert document.unverified_leads[0].information_need == information_need
    assert all(lead.predicate is None for lead in document.unverified_leads)


async def test_report_json_html_pdf_endpoints(report_build_client) -> None:
    http, created, _factory = report_build_client
    investigation_id = await _create_investigation(http, created, "Report Routes AS")

    payload = (
        await http.get(f"/api/v1/investigations/{investigation_id}/report.json")
    ).json()
    assert str(payload["investigation_id"]) == str(investigation_id)
    assert payload["target_name"] == "Report Routes AS"
    assert len(payload["coverage"]) == 9

    html_response = await http.get(f"/api/v1/investigations/{investigation_id}/report.html")
    assert html_response.status_code == 200, html_response.text
    assert "text/html" in html_response.headers["content-type"]
    assert 'lang="nb"' in html_response.text
    assert "Report Routes AS" in html_response.text

    pdf_response = await http.get(f"/api/v1/investigations/{investigation_id}/report.pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.content.startswith(b"%PDF")


async def test_report_endpoints_404_for_unknown_investigation(report_build_client) -> None:
    http, _created, _factory = report_build_client
    missing = uuid.uuid4()
    for suffix in ("report.json", "report.html", "report.pdf"):
        response = await http.get(f"/api/v1/investigations/{missing}/{suffix}")
        assert response.status_code == 404, suffix
