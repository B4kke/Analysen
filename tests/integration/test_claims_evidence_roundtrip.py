"""Claims/evidence roundtrip against the reconciled schema (AQ-020).

Exercises the repository chain source -> raw snapshot -> document ->
investigation link -> evidence -> claim, then verifies idempotency,
claims without evidence, and legacy PARTIAL evidence roles. Opt-in: requires
TEST_DATABASE_URL.
"""

import hashlib
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
async def claims_client(
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
        "purpose": "Verify claims/evidence persistence",
        "scope_modules": ["BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await http.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    investigation_id = uuid.UUID(response.json()["id"])
    created.append(investigation_id)
    return investigation_id


async def _run_chain(
    factory,
    *,
    investigation_id: uuid.UUID,
    source_id: str,
    raw_payload: str,
    url: str,
    locator: dict,
    excerpt: str,
    predicate: str,
    value: dict,
    status: str,
    evidence_role: str = "SUPPORTS",
) -> tuple[str, str, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Run source -> raw -> document -> evidence -> claim; return all ids."""
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.raw_store import store_raw_snapshot

    source = SourceRegistryRecord(
        id=source_id,
        name=f"{source_id} name",
        evidence_tier=2,
        access_class="OPEN",
        base_url=url,
        license="test-fixture",
        metadata={"fixture": "claims-evidence-roundtrip"},
    )
    async with factory() as session:
        await repo.upsert_source(session, source)
        digest, storage_key = store_raw_snapshot(raw_payload)
        document_id = await repo.upsert_document(
            session,
            source_id=source.id,
            original_url=url,
            canonical_url=url,
            mime_type="application/json",
            sha256=digest,
            raw_storage_key=storage_key,
            extracted_text=excerpt,
            parser_metadata={"fixture": "roundtrip"},
        )
        await repo.attach_document(session, investigation_id, document_id)
        evidence_id = await repo.store_evidence(
            session, document_id, "json_path", locator, excerpt, None
        )
        claim_id = await repo.upsert_claim(
            session,
            investigation_id,
            None,
            predicate,
            value,
            status,
            [evidence_id],
            evidence_role,
        )
        await session.commit()
    return digest, storage_key, document_id, evidence_id, claim_id


def _canonical_payload(name: str) -> str:
    return json.dumps(
        {"organisasjonsnummer": "974760673", "navn": name},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def test_claim_source_to_claim_roundtrip_is_idempotent(claims_client) -> None:
    http, created, factory = claims_client
    settings_dir = os.environ["RAW_EVIDENCE_DIR"]
    investigation_id = await _create_investigation(http, created, "Roundtrip Probe AS")

    from apps.api.app.repositories import claims_evidence as repo

    name = "Roundtrip Probe AS"
    raw_payload = _canonical_payload(name)
    locator = {"section": "navn", "offset": 0}
    excerpt = name
    predicate = "company.registered_name"
    value = {"name": name}
    url = "https://example.invalid/roundtrip/enheter/974760673"

    first = await _run_chain(
        factory,
        investigation_id=investigation_id,
        source_id="test_roundtrip_source",
        raw_payload=raw_payload,
        url=url,
        locator=locator,
        excerpt=excerpt,
        predicate=predicate,
        value=value,
        status="SUPPORTED",
    )
    digest, storage_key, _document_id, evidence_id, claim_id = first

    expected_hash = repo.evidence_content_hash(_document_id, "json_path", locator, excerpt)
    async with factory() as session:
        evidence_row = (
            await session.execute(
                text("SELECT id, content_hash FROM evidence WHERE id = :id"),
                {"id": evidence_id},
            )
        ).mappings().one()
    assert evidence_row["content_hash"] == expected_hash

    async with factory() as session:
        claim = await repo.get_claim(session, claim_id)
    assert claim is not None
    assert claim["fingerprint"] == repo.claim_fingerprint(
        investigation_id, None, predicate, value
    )

    async with factory() as session:
        listed = await repo.list_claims_for_investigation(session, investigation_id)
    match = [row for row in listed if row["id"] == claim_id]
    assert len(match) == 1
    assert expected_hash in list(match[0]["evidence_hashes"])

    stored_path = os.path.join(settings_dir, storage_key)
    assert os.path.isfile(stored_path), f"expected snapshot at {stored_path}"
    with open(stored_path, "rb") as handle:
        stored_bytes = handle.read()
    assert stored_bytes.decode("utf-8") == raw_payload
    assert hashlib.sha256(stored_bytes).hexdigest() == digest

    second = await _run_chain(
        factory,
        investigation_id=investigation_id,
        source_id="test_roundtrip_source",
        raw_payload=raw_payload,
        url=url,
        locator=locator,
        excerpt=excerpt,
        predicate=predicate,
        value=value,
        status="SUPPORTED",
    )
    assert second == first


async def test_claim_without_evidence_has_empty_hashes(claims_client) -> None:
    http, created, factory = claims_client
    investigation_id = await _create_investigation(http, created, "No Evidence Probe AS")

    from apps.api.app.repositories import claims_evidence as repo

    predicate = "company.registered_name"
    value = {"name": "No Evidence Probe AS"}
    async with factory() as session:
        claim_id = await repo.upsert_claim(
            session, investigation_id, None, predicate, value, "UNVERIFIED_LEAD", []
        )
        await session.commit()

    async with factory() as session:
        listed = await repo.list_claims_for_investigation(session, investigation_id)
    match = [row for row in listed if row["id"] == claim_id]
    assert len(match) == 1
    assert list(match[0]["evidence_hashes"]) == []

    async with factory() as session:
        claim = await repo.get_claim(session, claim_id)
    assert claim is not None
    assert claim["predicate"] == predicate


async def test_material_claim_without_evidence_is_rejected(claims_client) -> None:
    http, created, factory = claims_client
    investigation_id = await _create_investigation(http, created, "Evidence Gate Probe AS")

    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        with pytest.raises(ValueError, match="require at least one evidence"):
            await repo.upsert_claim(
                session,
                investigation_id,
                None,
                "company.registered_name",
                {"name": "Evidence Gate Probe AS"},
                "SUPPORTED",
                [],
            )
        await session.rollback()


async def test_partial_evidence_role_links_as_context(claims_client) -> None:
    http, created, factory = claims_client
    investigation_id = await _create_investigation(http, created, "Partial Probe AS")

    from apps.api.app.repositories import claims_evidence as repo

    name = "Partial Probe AS"
    locator = {"section": "navn", "offset": 0}
    _digest, _storage_key, _document_id, evidence_id, claim_id = await _run_chain(
        factory,
        investigation_id=investigation_id,
        source_id="test_partial_source",
        raw_payload=_canonical_payload(name),
        url="https://example.invalid/partial/enheter/974760673",
        locator=locator,
        excerpt=name,
        predicate="company.registered_name",
        value={"name": name},
        status="UNVERIFIED_LEAD",
        evidence_role="PARTIAL",
    )

    async with factory() as session:
        relation = (
            await session.execute(
                text(
                    """
                    SELECT relation FROM claim_evidence
                    WHERE claim_id = :cid AND evidence_id = :eid
                    """
                ),
                {"cid": claim_id, "eid": evidence_id},
            )
        ).mappings().one()["relation"]
    assert relation == "context"

    expected_hash = repo.evidence_content_hash(_document_id, "json_path", locator, name)
    async with factory() as session:
        listed = await repo.list_claims_for_investigation(session, investigation_id)
    match = [row for row in listed if row["id"] == claim_id]
    assert len(match) == 1
    assert expected_hash in list(match[0]["evidence_hashes"])


async def test_same_excerpt_in_two_documents_yields_distinct_evidence(
    claims_client,
) -> None:
    """Identical excerpts in different documents must not alias (provenance)."""
    http, created, factory = claims_client
    await _create_investigation(http, created, "Distinct Evidence AS")

    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.raw_store import store_raw_snapshot

    source = SourceRegistryRecord(
        id="test_distinct_source",
        name="test_distinct_source name",
        evidence_tier=2,
        access_class="OPEN",
        base_url="https://example.invalid/distinct",
        license="test-fixture",
        metadata={"fixture": "claims-evidence-distinct"},
    )
    locator = {"section": "navn", "offset": 0}
    excerpt = "Same Excerpt AS"
    async with factory() as session:
        await repo.upsert_source(session, source)
        document_ids = []
        for idx in range(2):
            raw_payload = _canonical_payload(f"Distinct Payload {idx} {uuid.uuid4().hex}")
            url = f"https://example.invalid/distinct/{idx}/{uuid.uuid4().hex}"
            digest, storage_key = store_raw_snapshot(raw_payload)
            document_ids.append(
                await repo.upsert_document(
                    session,
                    source_id=source.id,
                    original_url=url,
                    canonical_url=url,
                    mime_type="application/json",
                    sha256=digest,
                    raw_storage_key=storage_key,
                    extracted_text=excerpt,
                    parser_metadata={"fixture": "distinct"},
                )
            )
        assert document_ids[0] != document_ids[1]
        evidence_ids = [
            await repo.store_evidence(
                session, document_id, "json_path", locator, excerpt, None
            )
            for document_id in document_ids
        ]
        await session.commit()

    assert evidence_ids[0] != evidence_ids[1]
    async with factory() as session:
        hashes = [
            (
                await session.execute(
                    text("SELECT content_hash FROM evidence WHERE id = :id"),
                    {"id": evidence_id},
                )
            )
            .mappings()
            .one()["content_hash"]
            for evidence_id in evidence_ids
        ]
    assert hashes[0] != hashes[1]


async def test_document_reingest_preserves_first_provenance(claims_client) -> None:
    _http, _created, factory = claims_client
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence as repo

    source = SourceRegistryRecord(
        id="test_document_immutability",
        name="test_document_immutability",
        evidence_tier=1,
        access_class="OPEN",
        base_url="https://example.invalid/first",
        license="test-fixture",
        metadata={},
    )
    from apps.api.app.services.raw_store import store_raw_snapshot

    digest, storage_key = store_raw_snapshot('{"stable":true}')
    async with factory() as session:
        await repo.upsert_source(session, source)
        first_id = await repo.upsert_document(
            session,
            source_id=source.id,
            original_url="https://example.invalid/first",
            canonical_url="https://example.invalid/first",
            mime_type="application/json",
            sha256=digest,
            raw_storage_key=storage_key,
            extracted_text=None,
            parser_metadata={"origin": "first"},
        )
        second_id = await repo.upsert_document(
            session,
            source_id=None,
            original_url="https://example.invalid/changed",
            canonical_url="https://example.invalid/changed",
            mime_type="text/plain",
            sha256=digest,
            raw_storage_key="changed-key",
            extracted_text="enriched",
            parser_metadata={"origin": "second"},
        )
        await session.commit()

    assert second_id == first_id
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT source_id, original_url, canonical_url, mime_type, "
                    "raw_storage_key, extracted_text, parser_metadata "
                    "FROM documents WHERE id = :id"
                ),
                {"id": first_id},
            )
        ).mappings().one()
    assert row["source_id"] == source.id
    assert row["original_url"] == "https://example.invalid/first"
    assert row["canonical_url"] == "https://example.invalid/first"
    assert row["mime_type"] == "application/json"
    assert row["raw_storage_key"] == storage_key
    assert row["extracted_text"] == "enriched"
    assert row["parser_metadata"] == {"origin": "first"}
