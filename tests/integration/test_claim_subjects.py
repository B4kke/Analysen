"""Subject-scoped claim identity contract tests (AQ-030).

Two different entities with the same predicate/value keep separate claims;
re-ingest of the same subject is idempotent. Opt-in: TEST_DATABASE_URL.
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
async def subject_client(
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


async def _create_investigation(http: httpx.AsyncClient, created: list) -> uuid.UUID:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "company", "name": "Subject Probe AS"},
            "purpose": "Verify subject-scoped claim identity",
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = uuid.UUID(response.json()["id"])
    created.append(investigation_id)
    return investigation_id


async def _make_evidence(factory, investigation_id: uuid.UUID) -> uuid.UUID:
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.raw_store import store_raw_snapshot

    async with factory() as session:
        await repo.upsert_source(
            session,
            SourceRegistryRecord(
                id="test_subject_source",
                name="Subject Test Source",
                evidence_tier=2,
                access_class="OPEN_NO_KEY",
                base_url="https://example.invalid",
                license="test-fixture",
                metadata={},
            ),
        )
        raw = '{"organisasjonsnummer":"974760673"}'
        digest, storage_key = store_raw_snapshot(raw)
        document_id = await repo.upsert_document(
            session,
            source_id="test_subject_source",
            original_url="https://example.invalid/subject",
            canonical_url="https://example.invalid/subject",
            mime_type="application/json",
            sha256=digest,
            raw_storage_key=storage_key,
            extracted_text=None,
            parser_metadata={},
        )
        await repo.attach_document(session, investigation_id, document_id)
        evidence_id = await repo.store_evidence(
            session, document_id, "json_path", {"section": "orgnr"}, "974760673", None
        )
        await session.commit()
    return evidence_id


async def _upsert_subject_claim(
    factory,
    investigation_id: uuid.UUID,
    subject: uuid.UUID | None,
    evidence_id: uuid.UUID,
    predicate: str = "company.registered_orgnr",
    value: dict | None = None,
) -> uuid.UUID:
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        claim_id = await repo.upsert_claim(
            session,
            investigation_id,
            subject,
            predicate,
            value or {"orgnr": "974760673"},
            "SUPPORTED",
            [evidence_id],
        )
        await session.commit()
    return claim_id


async def test_two_subjects_keep_separate_claims(subject_client) -> None:
    http, created, factory = subject_client
    investigation_id = await _create_investigation(http, created)

    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        first_entity = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Company",
            canonical_name="First AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        second_entity = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Company",
            canonical_name="Second AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        await session.commit()

    evidence_id = await _make_evidence(factory, investigation_id)
    first_claim = await _upsert_subject_claim(
        factory, investigation_id, first_entity, evidence_id
    )
    second_claim = await _upsert_subject_claim(
        factory, investigation_id, second_entity, evidence_id
    )

    assert first_claim != second_claim

    async with factory() as session:
        listed = await repo.list_claims_for_investigation(session, investigation_id)
    assert len(listed) == 2


async def test_reingest_same_subject_is_idempotent(subject_client) -> None:
    http, created, factory = subject_client
    investigation_id = await _create_investigation(http, created)

    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        entity = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Company",
            canonical_name="Stable AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        await session.commit()

    evidence_id = await _make_evidence(factory, investigation_id)
    first = await _upsert_subject_claim(factory, investigation_id, entity, evidence_id)
    second = await _upsert_subject_claim(factory, investigation_id, entity, evidence_id)
    assert first == second

    none_first = await _upsert_subject_claim(factory, investigation_id, None, evidence_id)
    none_second = await _upsert_subject_claim(factory, investigation_id, None, evidence_id)
    assert none_first == none_second
    assert none_first != first
