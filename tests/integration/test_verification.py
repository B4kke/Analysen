"""Verifier integration tests against real PostgreSQL (AQ-026).

Seeds source -> document -> evidence -> claim via the claims_evidence
repository, then exercises verify_claim status transitions, verified_at
handling and VERIFICATION_DECIDED audit rows, plus detect_contradictions
pair detection. Opt-in: requires TEST_DATABASE_URL.
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
async def verification_client(
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
        "purpose": "Verify evidence-entailment verdicts",
        "scope_modules": ["BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await http.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    investigation_id = uuid.UUID(response.json()["id"])
    created.append(investigation_id)
    return investigation_id


async def _make_evidence(
    factory,
    investigation_id: uuid.UUID,
    tag: str,
    excerpt: str | None = "Registered excerpt",
    structured: dict | None = None,
) -> uuid.UUID:
    """Create a source/document/evidence chain attached to the investigation."""
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence as repo

    nonce = uuid.uuid4().hex
    source = SourceRegistryRecord(
        id=f"test_verification_source_{tag}_{nonce[:8]}",
        name=f"test_verification_source_{tag} name",
        evidence_tier=2,
        access_class="OPEN",
        base_url="https://example.invalid/verification",
        license="test-fixture",
        metadata={"fixture": "verification"},
    )
    url = f"https://example.invalid/verification/{tag}/{nonce}"
    digest = hashlib.sha256(f"verification-{tag}-{nonce}".encode()).hexdigest()
    async with factory() as session:
        await repo.upsert_source(session, source)
        document_id = await repo.upsert_document(
            session,
            source_id=source.id,
            original_url=url,
            canonical_url=url,
            mime_type="application/json",
            sha256=digest,
            raw_storage_key=None,
            extracted_text=excerpt,
            parser_metadata={"fixture": "verification"},
        )
        await repo.attach_document(session, investigation_id, document_id)
        evidence_id = await repo.store_evidence(
            session, document_id, "json_path", {"section": tag}, excerpt, structured
        )
        await session.commit()
    return evidence_id


async def _seed_claim(
    factory,
    investigation_id: uuid.UUID,
    predicate: str,
    value: dict,
    status: str,
    links: list[tuple[uuid.UUID, str]],
    subject: uuid.UUID | None = None,
) -> uuid.UUID:
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        claim_id: uuid.UUID | None = None
        for evidence_id, role in links:
            claim_id = await repo.upsert_claim(
                session, investigation_id, subject, predicate, value, status,
                [evidence_id], role,
            )
        if claim_id is None:
            claim_id = await repo.upsert_claim(
                session, investigation_id, subject, predicate, value, status, []
            )
        await session.commit()
        assert claim_id is not None
        return claim_id


async def _audit_payloads(factory, investigation_id: uuid.UUID) -> list[dict]:
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM audit_log WHERE investigation_id = :iid "
                    "AND event_type = 'VERIFICATION_DECIDED' ORDER BY id"
                ),
                {"iid": investigation_id},
            )
        ).mappings().all()
    return [dict(row)["payload"] for row in rows]


async def test_verify_supported_claim_transitions_and_audits(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Verifier Probe AS")

    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.verifier import verify_claim

    evidence_id = await _make_evidence(factory, investigation_id, "supports")
    claim_id = await _seed_claim(
        factory, investigation_id, "company.registered_name",
        {"name": "Verifier Probe AS"}, "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")],
    )

    async with factory() as session:
        result = await verify_claim(session, investigation_id, claim_id)
        await session.commit()

    assert result.status == "SUPPORTED"
    assert result.supporting_evidence_ids == [evidence_id]
    assert result.contradicting_evidence_ids == []
    assert "1" in result.rationale and "SUPPORTED" in result.rationale
    assert result.verified_at is not None

    async with factory() as session:
        stored = await repo.get_claim(session, claim_id)
    assert stored is not None
    assert stored["status"] == "SUPPORTED"
    assert stored["verified_at"] is not None

    payloads = await _audit_payloads(factory, investigation_id)
    assert len(payloads) == 1
    assert payloads[0]["claim_id"] == str(claim_id)
    assert payloads[0]["from"] == "UNVERIFIED_LEAD"
    assert payloads[0]["to"] == "SUPPORTED"
    assert payloads[0]["supporting"] == [str(evidence_id)]

    # Re-verification is idempotent: same row, same verdict.
    async with factory() as session:
        again = await verify_claim(session, investigation_id, claim_id)
        await session.commit()
    assert again.status == "SUPPORTED"
    async with factory() as session:
        assert (await repo.get_claim(session, claim_id))["id"] == claim_id


async def test_verify_contradicted_claim(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Contra Probe AS")

    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.verifier import verify_claim

    evidence_id = await _make_evidence(factory, investigation_id, "contradicts")
    claim_id = await _seed_claim(
        factory, investigation_id, "company.deleted",
        {"deleted": True}, "UNVERIFIED_LEAD", [(evidence_id, "CONTRADICTS")],
    )

    async with factory() as session:
        result = await verify_claim(session, investigation_id, claim_id)
        await session.commit()

    assert result.status == "CONTRADICTED"
    assert result.contradicting_evidence_ids == [evidence_id]
    assert result.verified_at is not None

    async with factory() as session:
        stored = await repo.get_claim(session, claim_id)
    assert stored is not None
    assert stored["status"] == "CONTRADICTED"
    assert stored["verified_at"] is not None

    payloads = await _audit_payloads(factory, investigation_id)
    assert len(payloads) == 1
    assert payloads[0]["to"] == "CONTRADICTED"


async def test_verify_context_only_claim_is_partial(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Partial Verdict AS")

    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.verifier import verify_claim

    evidence_id = await _make_evidence(factory, investigation_id, "context")
    claim_id = await _seed_claim(
        factory, investigation_id, "company.registered_name",
        {"name": "Partial Verdict AS"}, "UNVERIFIED_LEAD", [(evidence_id, "PARTIAL")],
    )

    async with factory() as session:
        result = await verify_claim(session, investigation_id, claim_id)
        await session.commit()

    assert result.status == "PARTIALLY_SUPPORTED"
    assert result.verified_at is not None

    async with factory() as session:
        stored = await repo.get_claim(session, claim_id)
    assert stored is not None
    assert stored["status"] == "PARTIALLY_SUPPORTED"
    assert stored["verified_at"] is not None


async def test_verify_claim_without_evidence_is_insufficient(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Empty Verdict AS")

    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.verifier import verify_claim

    claim_id = await _seed_claim(
        factory, investigation_id, "company.registered_name",
        {"name": "Empty Verdict AS"}, "UNVERIFIED_LEAD", [],
    )

    async with factory() as session:
        result = await verify_claim(session, investigation_id, claim_id)
        await session.commit()

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.supporting_evidence_ids == []
    assert result.contradicting_evidence_ids == []

    async with factory() as session:
        stored = await repo.get_claim(session, claim_id)
    assert stored is not None
    assert stored["status"] == "INSUFFICIENT_EVIDENCE"
    assert stored["verified_at"] is None


async def test_verify_supports_link_without_content_is_insufficient(
    verification_client,
) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Hollow Verdict AS")

    from apps.api.app.services.verifier import verify_claim

    evidence_id = await _make_evidence(
        factory, investigation_id, "hollow", excerpt=None, structured=None
    )
    claim_id = await _seed_claim(
        factory, investigation_id, "company.registered_name",
        {"name": "Hollow Verdict AS"}, "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")],
    )

    async with factory() as session:
        result = await verify_claim(session, investigation_id, claim_id)
        await session.commit()

    # The citation gate: a bare link without quotable content cannot support.
    assert result.status == "INSUFFICIENT_EVIDENCE"


async def test_verify_unknown_or_foreign_claim_raises_lookup_error(
    verification_client,
) -> None:
    http, created, factory = verification_client
    owner = await _create_investigation(http, created, "Verifier Owner AS")
    other = await _create_investigation(http, created, "Verifier Stranger AS")

    from apps.api.app.services.verifier import verify_claim

    evidence_id = await _make_evidence(factory, owner, "foreign")
    foreign_claim = await _seed_claim(
        factory, owner, "company.registered_name",
        {"name": "Verifier Owner AS"}, "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")],
    )

    async with factory() as session:
        with pytest.raises(LookupError):
            await verify_claim(session, owner, uuid.uuid4())
        await session.rollback()
        with pytest.raises(LookupError):
            await verify_claim(session, other, foreign_claim)
        await session.rollback()


async def test_detect_contradictions_finds_supported_pair(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Contra Pair AS")

    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.verifier import detect_contradictions

    async with factory() as session:
        subject = await repo.upsert_entity(
            session, entity_id=None, schema="Organization",
            canonical_name="Contra Pair AS", attributes={},
            resolution_state="UNRESOLVED",
        )
        await session.commit()

    evidence_a = await _make_evidence(factory, investigation_id, "pair-a")
    evidence_b = await _make_evidence(factory, investigation_id, "pair-b")
    claim_a = await _seed_claim(
        factory, investigation_id, "company.ceo", {"name": "Ada"},
        "SUPPORTED", [(evidence_a, "SUPPORTS")], subject,
    )
    claim_b = await _seed_claim(
        factory, investigation_id, "company.ceo", {"name": "Bo"},
        "UNVERIFIED_LEAD", [(evidence_b, "SUPPORTS")], subject,
    )

    async with factory() as session:
        pairs = await detect_contradictions(session, investigation_id)

    assert len(pairs) == 1
    pair = pairs[0]
    assert {pair["claim_a_id"], pair["claim_b_id"]} == {claim_a, claim_b}
    assert pair["predicate"] == "company.ceo"
    assert pair["subject_entity_id"] == subject


async def test_detect_contradictions_ignores_weak_and_subjectless_pairs(
    verification_client,
) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Weak Pair AS")

    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.verifier import detect_contradictions

    async with factory() as session:
        subject = await repo.upsert_entity(
            session, entity_id=None, schema="Organization",
            canonical_name="Weak Pair AS", attributes={},
            resolution_state="UNRESOLVED",
        )
        await session.commit()

    evidence_id = await _make_evidence(factory, investigation_id, "weak")
    # Two weak claims on one subject: no supported side, no pair.
    await _seed_claim(
        factory, investigation_id, "company.ceo", {"name": "Ada"},
        "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")], subject,
    )
    await _seed_claim(
        factory, investigation_id, "company.ceo", {"name": "Bo"},
        "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")], subject,
    )
    # Supported claims without a subject never pair either.
    await _seed_claim(
        factory, investigation_id, "company.founded", {"year": 2001},
        "SUPPORTED", [(evidence_id, "SUPPORTS")], None,
    )
    await _seed_claim(
        factory, investigation_id, "company.founded", {"year": 2002},
        "SUPPORTED", [(evidence_id, "SUPPORTS")], None,
    )

    async with factory() as session:
        pairs = await detect_contradictions(session, investigation_id)
    assert pairs == []


async def test_verify_endpoint_persists_verdict(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Verify Route AS")
    evidence_id = await _make_evidence(factory, investigation_id, "route")
    claim_id = await _seed_claim(
        factory, investigation_id, "company.registered_name",
        {"name": "Verify Route AS"}, "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")],
    )
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/claims/{claim_id}/verify"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUPPORTED"
    assert body["supporting_evidence_ids"] == [str(evidence_id)]
    assert body["contradicting_evidence_ids"] == []


async def test_verify_endpoint_404_for_unknown_claim(verification_client) -> None:
    http, created, _factory = verification_client
    investigation_id = await _create_investigation(http, created, "Verify 404 AS")
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/claims/{uuid.uuid4()}/verify"
    )
    assert response.status_code == 404


async def test_verify_endpoint_404_for_foreign_claim(verification_client) -> None:
    http, created, factory = verification_client
    first_id = await _create_investigation(http, created, "Verify Foreign A AS")
    second_id = await _create_investigation(http, created, "Verify Foreign B AS")
    evidence_id = await _make_evidence(factory, second_id, "foreign")
    claim_id = await _seed_claim(
        factory, second_id, "company.registered_name", {"name": "Verify Foreign B AS"},
        "UNVERIFIED_LEAD", [(evidence_id, "SUPPORTS")],
    )
    response = await http.post(
        f"/api/v1/investigations/{first_id}/claims/{claim_id}/verify"
    )
    assert response.status_code == 404


async def test_contradictions_endpoint_lists_pairs(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Contradiction Route AS")
    first_evidence = await _make_evidence(factory, investigation_id, "first")
    second_evidence = await _make_evidence(factory, investigation_id, "second")
    async with factory() as session:
        from apps.api.app.repositories import claims_evidence as repo

        subject = await repo.upsert_entity(
            session, entity_id=None, schema="Company", canonical_name="Contradiction Route AS",
            attributes={}, resolution_state="UNRESOLVED",
        )
        await session.commit()
    first_claim = await _seed_claim(
        factory, investigation_id, "company.status", {"status": "active"},
        "SUPPORTED", [(first_evidence, "SUPPORTS")], subject=subject,
    )
    second_claim = await _seed_claim(
        factory, investigation_id, "company.status", {"status": "dissolved"},
        "SUPPORTED", [(second_evidence, "SUPPORTS")], subject=subject,
    )
    response = await http.get(f"/api/v1/investigations/{investigation_id}/contradictions")
    assert response.status_code == 200, response.text
    pairs = response.json()
    assert len(pairs) == 1
    assert {pairs[0]["claim_a_id"], pairs[0]["claim_b_id"]} == {
        str(first_claim), str(second_claim),
    }


async def test_contradictions_endpoint_404_for_unknown_investigation(verification_client) -> None:
    http, _created, _factory = verification_client
    response = await http.get(f"/api/v1/investigations/{uuid.uuid4()}/contradictions")
    assert response.status_code == 404


async def test_verification_lead_created_through_gate(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Verification Lead AS")
    claim_id = await _seed_claim(
        factory, investigation_id, "company.registered_name",
        {"name": "Verification Lead AS"}, "UNVERIFIED_LEAD", [],
    )
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/claims/{claim_id}/verification-lead",
        json={"scope_area": "BUSINESS_ROLES"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT trigger_type, originating_claim_id, information_need "
                     "FROM leads WHERE id = CAST(:id AS uuid)"),
                {"id": body["lead_id"]},
            )
        ).mappings().one()
    assert row["trigger_type"] == "WEAK_SOURCE_ONLY"
    assert str(row["originating_claim_id"]) == str(claim_id)
    assert "company.registered_name" in row["information_need"]


async def test_verification_lead_uses_contradiction_trigger(verification_client) -> None:
    http, created, factory = verification_client
    investigation_id = await _create_investigation(http, created, "Lead Contradiction AS")
    first_evidence = await _make_evidence(factory, investigation_id, "lead-first")
    second_evidence = await _make_evidence(factory, investigation_id, "lead-second")
    async with factory() as session:
        from apps.api.app.repositories import claims_evidence as repo

        subject = await repo.upsert_entity(
            session, entity_id=None, schema="Company", canonical_name="Lead Contradiction AS",
            attributes={}, resolution_state="UNRESOLVED",
        )
        await session.commit()
    first_claim = await _seed_claim(
        factory, investigation_id, "company.status", {"status": "active"},
        "SUPPORTED", [(first_evidence, "SUPPORTS")], subject=subject,
    )
    await _seed_claim(
        factory, investigation_id, "company.status", {"status": "dissolved"},
        "SUPPORTED", [(second_evidence, "SUPPORTS")], subject=subject,
    )
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/claims/{first_claim}/verification-lead",
        json={"scope_area": "BUSINESS_ROLES"},
    )
    assert response.status_code == 201, response.text

    async with factory() as session:
        trigger = (
            await session.execute(
                text("SELECT trigger_type FROM leads WHERE id = CAST(:id AS uuid)"),
                {"id": response.json()["lead_id"]},
            )
        ).scalar_one()
    assert trigger == "CONTRADICTION"


async def test_verification_lead_404_for_unknown_claim(verification_client) -> None:
    http, created, _factory = verification_client
    investigation_id = await _create_investigation(http, created, "Lead 404 AS")
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/claims/{uuid.uuid4()}/verification-lead",
        json={"scope_area": "BUSINESS_ROLES"},
    )
    assert response.status_code == 404
