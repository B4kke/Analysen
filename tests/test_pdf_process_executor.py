"""PDF process executor contract tests.

One admitted lead carrying a document_id runs through the injected
pdf_extract boundary: the attached document's raw bytes are read, pages
become extracted text, tables are counted, and the document row is
refreshed with merged parser metadata. Failures are explicit terminal
states, never silent. Opt-in: TEST_DATABASE_URL. No network, no browsers.
"""

import hashlib
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
async def pdf_client(
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


async def _create_pdf_investigation(http: httpx.AsyncClient, created: list) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {
                "type": "company",
                "name": "PDF Process Probe AS",
                "known_orgnrs": ["974760673"],
            },
            "purpose": "Verify PDF extraction executor",
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _admit_pdf_lead(http: httpx.AsyncClient, investigation_id: str, value: dict) -> str:
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads",
        json={
            "lead_type": "pdf_document_process",
            "value": value,
            "reason": "Extract text and tables from the attached PDF",
            "priority": 0.7,
            "depth": 0,
            "scope_area": "WEB_MEDIA",
            "trigger_type": "DOCUMENT_QUALITY",
            "information_need": "Make the attached PDF text available for review",
            "relation_depth": 0,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING", response.text
    return response.json()["lead_id"]


async def _ingest_pdf_document(
    factory, investigation_id: str, raw_bytes: bytes, metadata: dict
) -> str:
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence
    from apps.api.app.services.raw_store import store_raw_bytes

    digest, storage_key = store_raw_bytes(raw_bytes)
    async with factory() as session:
        await claims_evidence.upsert_source(
            session,
            SourceRegistryRecord(
                id="web_direct",
                name="Direct web fetch",
                evidence_tier=3,
                access_class="PUBLIC_WEB",
                base_url=None,
                license=None,
                metadata={},
            ),
        )
        document_id = await claims_evidence.upsert_document(
            session,
            source_id="web_direct",
            original_url="https://example.com/doc.pdf",
            canonical_url="https://example.com/doc.pdf",
            mime_type="application/pdf",
            sha256=digest,
            raw_storage_key=storage_key,
            extracted_text=None,
            parser_metadata=metadata,
        )
        await claims_evidence.attach_document(session, uuid.UUID(investigation_id), document_id)
        await session.commit()
    return str(document_id)


async def _execute_with_extract(factory, investigation_id: str, lead_id: str, extract_fn):
    from apps.api.app.domain.models import Lead
    from apps.api.app.repositories import investigations as repo
    from apps.api.app.services.executors.pdf_process import execute_pdf_process

    calls: list[bytes] = []

    def recording_extract(raw: bytes):
        calls.append(raw)
        return extract_fn(raw)

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
        status = await execute_pdf_process(
            session, uuid.UUID(investigation_id), uuid.UUID(lead_id), lead, recording_extract
        )
        await session.commit()
    return status, calls


async def _fake_document() -> object:
    from apps.api.app.services.pdf_extraction import ExtractedDocument, ExtractedPage

    return ExtractedDocument(
        pages=[
            ExtractedPage(page_number=1, text="Page one", tables=[[["a", "b"]]]),
            ExtractedPage(page_number=2, text="Page two", tables=[]),
        ],
        metadata={},
        sha256="extracted",
    )


async def test_pdf_process_happy_path_merges_metadata_and_coverage(pdf_client) -> None:
    http, created, factory = pdf_client
    investigation_id = await _create_pdf_investigation(http, created)
    raw_bytes = b"%PDF-1.4 fake pdf bytes for executor test"
    document_id = await _ingest_pdf_document(
        factory,
        investigation_id,
        raw_bytes,
        {"fetcher": "direct", "final_url": "https://example.com/doc.pdf"},
    )
    lead_id = await _admit_pdf_lead(http, investigation_id, {"document_id": document_id})

    extracted = await _fake_document()

    def fake_extract(raw: bytes):
        assert raw == raw_bytes
        return extracted

    status, calls = await _execute_with_extract(factory, investigation_id, lead_id, fake_extract)
    assert status == "COMPLETED"
    assert calls == [raw_bytes]

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
                        "SELECT sha256, raw_storage_key, extracted_text, parser_metadata "
                        "FROM documents WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": document_id},
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
                        "SELECT count(*) AS n FROM claims "
                        "WHERE investigation_id = CAST(:id AS uuid)"
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
    assert document["extracted_text"] == "Page one\n\nPage two"
    assert document["parser_metadata"]["pdf_pages"] == 2
    assert document["parser_metadata"]["pdf_tables"] == 1
    assert document["parser_metadata"]["fetcher"] == "direct"
    assert document["parser_metadata"]["final_url"] == "https://example.com/doc.pdf"
    assert module["status"] == "IN_PROGRESS"
    assert module["coverage"]["query_count"] == 1
    assert module["coverage"]["document_count"] == 1
    assert "pdf_extract" in module["coverage"]["providers"]
    assert counts["n"] == 0
    executed = [row for row in audits if row["event_type"] == "LEAD_EXECUTED"]
    assert len(executed) == 1
    assert executed[0]["payload"]["status"] == "COMPLETED"
    assert executed[0]["payload"]["provider"] == "pdf_extract"
    assert executed[0]["payload"]["document_id"] == document_id
    assert executed[0]["payload"]["lead_id"] == lead_id


async def test_pdf_process_invalid_value_fails_without_extract(pdf_client) -> None:
    http, created, factory = pdf_client
    investigation_id = await _create_pdf_investigation(http, created)
    lead_id = await _admit_pdf_lead(http, investigation_id, {"document_id": "not-a-uuid"})

    def exploding_extract(raw: bytes):
        raise AssertionError("extract must not be called")

    status, calls = await _execute_with_extract(
        factory, investigation_id, lead_id, exploding_extract
    )
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
    assert lead["blocked_reason"] == "invalid_pdf_value"


async def test_pdf_process_unknown_document_fails_without_extract(pdf_client) -> None:
    http, created, factory = pdf_client
    investigation_id = await _create_pdf_investigation(http, created)
    missing = str(uuid.uuid4())
    lead_id = await _admit_pdf_lead(http, investigation_id, {"document_id": missing})

    def exploding_extract(raw: bytes):
        raise AssertionError("extract must not be called")

    status, calls = await _execute_with_extract(
        factory, investigation_id, lead_id, exploding_extract
    )
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
    assert lead["blocked_reason"] == "document_not_found"


async def test_pdf_process_missing_snapshot_fails_without_extract(pdf_client) -> None:
    http, created, factory = pdf_client
    investigation_id = await _create_pdf_investigation(http, created)

    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence

    digest = hashlib.sha256(b"missing-snapshot-probe").hexdigest()
    bogus_key = f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    async with factory() as session:
        await claims_evidence.upsert_source(
            session,
            SourceRegistryRecord(
                id="web_direct",
                name="Direct web fetch",
                evidence_tier=3,
                access_class="PUBLIC_WEB",
                base_url=None,
                license=None,
                metadata={},
            ),
        )
        document_id = await claims_evidence.upsert_document(
            session,
            source_id="web_direct",
            original_url="https://example.com/missing.pdf",
            canonical_url="https://example.com/missing.pdf",
            mime_type="application/pdf",
            sha256=digest,
            raw_storage_key=bogus_key,
            extracted_text=None,
            parser_metadata={},
        )
        await claims_evidence.attach_document(session, uuid.UUID(investigation_id), document_id)
        await session.commit()
    lead_id = await _admit_pdf_lead(http, investigation_id, {"document_id": str(document_id)})

    def exploding_extract(raw: bytes):
        raise AssertionError("extract must not be called")

    status, calls = await _execute_with_extract(
        factory, investigation_id, lead_id, exploding_extract
    )
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
    assert lead["blocked_reason"] == "raw_snapshot_missing"


async def test_pdf_process_dependency_unavailable_fails(pdf_client) -> None:
    http, created, factory = pdf_client
    investigation_id = await _create_pdf_investigation(http, created)
    raw_bytes = b"%PDF-1.4 dependency probe"
    document_id = await _ingest_pdf_document(factory, investigation_id, raw_bytes, {})
    lead_id = await _admit_pdf_lead(http, investigation_id, {"document_id": document_id})

    from apps.api.app.services.pdf_extraction import PdfDependenciesMissing

    def missing_stack(raw: bytes):
        raise PdfDependenciesMissing("no research stack")

    status, calls = await _execute_with_extract(factory, investigation_id, lead_id, missing_stack)
    assert status == "FAILED"
    assert calls == [raw_bytes]

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
    assert lead["blocked_reason"] == "dependency_unavailable"


async def test_pdf_process_extraction_error_fails_with_name(pdf_client) -> None:
    http, created, factory = pdf_client
    investigation_id = await _create_pdf_investigation(http, created)
    raw_bytes = b"%PDF-1.4 broken probe"
    document_id = await _ingest_pdf_document(factory, investigation_id, raw_bytes, {})
    lead_id = await _admit_pdf_lead(http, investigation_id, {"document_id": document_id})

    def broken_extract(raw: bytes):
        raise ValueError("corrupt pdf")

    status, calls = await _execute_with_extract(factory, investigation_id, lead_id, broken_extract)
    assert status == "FAILED"
    assert calls == [raw_bytes]

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
    assert lead["blocked_reason"] == "source_error:ValueError"
