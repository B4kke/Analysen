"""Entity/relation/claim-verification paths for claims_evidence (AQ-020 repair).

Covers the repository paths the roundtrip file does not exercise:
upsert_entity insert+update, add_entity_alias first-write-wins,
add_entity_relation with dates and rejection of missing evidence, verified_at on
SUPPORTED insert, and the SUPPORTS/CONTRADICTS relation mappings.
Opt-in: requires TEST_DATABASE_URL.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.fixture
async def entities_client(
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
        "purpose": "Verify claims/evidence entity paths",
        "scope_modules": ["BUSINESS_ROLES"],
        "expansion_policy": "DIRECT_RELATIONS",
        "max_relation_depth": 1,
    }
    response = await http.post("/api/v1/investigations", json=payload)
    assert response.status_code == 201, response.text
    investigation_id = uuid.UUID(response.json()["id"])
    created.append(investigation_id)
    return investigation_id


async def _make_evidence(factory, tag: str, investigation_id: uuid.UUID | None = None) -> uuid.UUID:
    """Create a fresh source/document/evidence chain; return the evidence id."""
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.raw_store import store_raw_snapshot

    nonce = uuid.uuid4().hex
    source = SourceRegistryRecord(
        id=f"test_entities_source_{tag}",
        name=f"test_entities_source_{tag} name",
        evidence_tier=2,
        access_class="OPEN",
        base_url="https://example.invalid/entities",
        license="test-fixture",
        metadata={"fixture": "claims-evidence-entities"},
    )
    raw_payload = f'{{"fixture":"entities-{tag}","nonce":"{nonce}"}}'
    url = f"https://example.invalid/entities/{tag}/{nonce}"
    locator = {"section": "navn", "offset": 0}
    excerpt = f"Entities Probe {tag} {nonce}"
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
            parser_metadata={"fixture": "entities"},
        )
        evidence_id = await repo.store_evidence(
            session, document_id, "json_path", locator, excerpt, None
        )
        if investigation_id is not None:
            await repo.attach_document(session, investigation_id, document_id)
        await session.commit()
    return evidence_id


async def test_upsert_entity_maintains_normalized_name(entities_client) -> None:
    _http, _created, factory = entities_client
    from apps.api.app.repositories import claims_evidence as repo
    from apps.api.app.services.entity_resolution import normalize_name

    async with factory() as session:
        entity_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Organization",
            canonical_name="  Test Entity AS  ",
            attributes={"orgnr": "974760673"},
            resolution_state="UNRESOLVED",
        )
        await session.commit()

    async with factory() as session:
        row = (
            (
                await session.execute(
                    text("SELECT canonical_name, normalized_name FROM entities WHERE id = :id"),
                    {"id": entity_id},
                )
            )
            .mappings()
            .one()
        )
    assert row["normalized_name"] == normalize_name("  Test Entity AS  ")
    assert row["normalized_name"] == "test entity as"

    async with factory() as session:
        returned = await repo.upsert_entity(
            session,
            entity_id=entity_id,
            schema="Organization",
            canonical_name="Renamed Entity ASA",
            attributes={"orgnr": "974760673"},
            resolution_state="UNRESOLVED",
        )
        await session.commit()
    assert returned == entity_id

    async with factory() as session:
        updated = (
            (
                await session.execute(
                    text("SELECT canonical_name, normalized_name FROM entities WHERE id = :id"),
                    {"id": entity_id},
                )
            )
            .mappings()
            .one()
        )
    assert updated["canonical_name"] == "Renamed Entity ASA"
    assert updated["normalized_name"] == normalize_name("Renamed Entity ASA")
    assert updated["normalized_name"] == "renamed entity asa"


async def test_add_entity_alias_is_first_write_wins(entities_client) -> None:
    _http, _created, factory = entities_client
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        entity_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Organization",
            canonical_name="Alias Probe AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        await repo.add_entity_alias(session, entity_id, "Alias Probe AS")
        await repo.add_entity_alias(session, entity_id, "alias probe as")
        await session.commit()

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT alias FROM entity_aliases WHERE entity_id = :id"),
                    {"id": entity_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["alias"] == "Alias Probe AS"


async def test_add_alias_tolerates_preserved_legacy_duplicates(entities_client) -> None:
    _http, _created, factory = entities_client
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        entity_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Organization",
            canonical_name="Legacy Alias AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        for alias in ("Legacy Alias AS", "LEGACY ALIAS AS"):
            await session.execute(
                text("""
                    INSERT INTO entity_aliases (entity_id, alias, normalized_alias)
                    VALUES (:id, :alias, 'legacy alias as')
                """),
                {"id": entity_id, "alias": alias},
            )
        await repo.add_entity_alias(session, entity_id, "legacy alias as")
        assert (
            await session.scalar(
                text("SELECT count(*) FROM entity_aliases WHERE entity_id = :id"),
                {"id": entity_id},
            )
            == 2
        )
        # Keep this regression's global fixture data out of later checks.
        await session.rollback()


async def test_entity_relation_preserves_dates_and_rejects_missing_evidence(
    entities_client,
) -> None:
    _http, _created, factory = entities_client
    from apps.api.app.repositories import claims_evidence as repo

    evidence_id = await _make_evidence(factory, "relation")
    async with factory() as session:
        source_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Organization",
            canonical_name="Relation Source AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        target_id = await repo.upsert_entity(
            session,
            entity_id=None,
            schema="Organization",
            canonical_name="Relation Target AS",
            attributes={},
            resolution_state="UNRESOLVED",
        )
        dated_id = await repo.add_entity_relation(
            session,
            source_id,
            target_id,
            "subsidiary_of",
            0.9,
            [evidence_id],
            valid_from=date(2020, 1, 1),
            valid_to=date(2024, 12, 31),
        )
        with pytest.raises(ValueError, match="require evidence"):
            await repo.add_entity_relation(
                session,
                source_id,
                target_id,
                "affiliated_with",
                0.5,
                [],
            )
        with pytest.raises(ValueError, match="must exist"):
            await repo.add_entity_relation(
                session,
                source_id,
                target_id,
                "affiliated_with",
                0.5,
                [uuid.uuid4()],
            )
        await session.commit()

    async with factory() as session:
        dated = (
            (
                await session.execute(
                    text(
                        "SELECT subject_entity_id, object_entity_id, predicate,"
                        " confidence, evidence_ids, valid_from, valid_to"
                        " FROM relationships WHERE id = :id"
                    ),
                    {"id": dated_id},
                )
            )
            .mappings()
            .one()
        )
    assert dated["subject_entity_id"] == source_id
    assert dated["object_entity_id"] == target_id
    assert dated["predicate"] == "subsidiary_of"
    assert dated["valid_from"] == date(2020, 1, 1)
    assert dated["valid_to"] == date(2024, 12, 31)
    assert list(dated["evidence_ids"]) == [evidence_id]

    async with factory() as session:
        assert (
            await session.scalar(
                text("SELECT count(*) FROM relationships WHERE subject_entity_id = :id"),
                {"id": source_id},
            )
            == 1
        )


async def test_supported_claim_insert_sets_verified_at(entities_client) -> None:
    http, created, factory = entities_client
    investigation_id = await _create_investigation(http, created, "Verified Probe AS")

    from apps.api.app.repositories import claims_evidence as repo

    evidence_id = await _make_evidence(factory, "verified", investigation_id)
    async with factory() as session:
        claim_id = await repo.upsert_claim(
            session,
            investigation_id,
            None,
            "company.registered_name",
            {"name": "Verified Probe AS"},
            "SUPPORTED",
            [evidence_id],
        )
        await session.commit()

    async with factory() as session:
        row = (
            (
                await session.execute(
                    text("SELECT status, verified_at FROM claims WHERE id = :id"),
                    {"id": claim_id},
                )
            )
            .mappings()
            .one()
        )
    assert row["status"] == "SUPPORTED"
    assert row["verified_at"] is not None


async def test_supports_and_contradicts_relation_mappings(entities_client) -> None:
    http, created, factory = entities_client
    investigation_id = await _create_investigation(http, created, "Relation Map AS")

    from apps.api.app.repositories import claims_evidence as repo

    supports_evidence = await _make_evidence(factory, "supports", investigation_id)
    contradicts_evidence = await _make_evidence(factory, "contradicts", investigation_id)
    async with factory() as session:
        supports_claim = await repo.upsert_claim(
            session,
            investigation_id,
            None,
            "company.registered_name",
            {"name": "Relation Map AS"},
            "SUPPORTED",
            [supports_evidence],
            "SUPPORTS",
        )
        contradicts_claim = await repo.upsert_claim(
            session,
            investigation_id,
            None,
            "company.deleted",
            {"deleted": True},
            "CONTRADICTED",
            [contradicts_evidence],
            "CONTRADICTS",
        )
        await session.commit()

    async with factory() as session:
        supports_relation = (
            (
                await session.execute(
                    text(
                        "SELECT relation FROM claim_evidence"
                        " WHERE claim_id = :cid AND evidence_id = :eid"
                    ),
                    {"cid": supports_claim, "eid": supports_evidence},
                )
            )
            .mappings()
            .one()["relation"]
        )
        contradicts_relation = (
            (
                await session.execute(
                    text(
                        "SELECT relation FROM claim_evidence"
                        " WHERE claim_id = :cid AND evidence_id = :eid"
                    ),
                    {"cid": contradicts_claim, "eid": contradicts_evidence},
                )
            )
            .mappings()
            .one()["relation"]
        )
    assert supports_relation == "supports"
    assert contradicts_relation == "contradicts"


@pytest.mark.parametrize("foreign", [True, False])
async def test_claim_rejects_foreign_or_nonexistent_evidence_without_write(
    entities_client,
    foreign,
):
    http, created, factory = entities_client
    owner = await _create_investigation(http, created, "Evidence Owner AS")
    target = await _create_investigation(http, created, "Evidence Boundary AS")
    evidence_id = await _make_evidence(factory, "boundary", owner) if foreign else uuid.uuid4()
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        with pytest.raises(ValueError, match="attached to the investigation"):
            await repo.upsert_claim(
                session,
                target,
                None,
                "company.registered_name",
                {"name": "Evidence Boundary AS"},
                "SUPPORTED",
                [evidence_id],
            )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM claims WHERE investigation_id = :id"),
                {"id": target},
            )
            == 0
        )


@pytest.mark.parametrize(
    "status,role",
    [
        ("SUPPORTED", "CONTRADICTS"),
        ("SUPPORTED", "PARTIAL"),
        ("PARTIALLY_SUPPORTED", "CONTRADICTS"),
        ("CONTRADICTED", "SUPPORTS"),
        ("SUPPORTED", "invalid"),
    ],
)
async def test_claim_rejects_incompatible_relations_before_write(entities_client, status, role):
    http, created, factory = entities_client
    target = await _create_investigation(http, created, "Relation Gate AS")
    evidence_id = await _make_evidence(factory, "role-gate", target)
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        with pytest.raises(ValueError):
            await repo.upsert_claim(
                session,
                target,
                None,
                "company.registered_name",
                {"name": "Relation Gate AS"},
                status,
                [evidence_id],
                role,
            )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM claims WHERE investigation_id = :id"),
                {"id": target},
            )
            == 0
        )


async def test_claim_downgrade_clears_verification_timestamp(entities_client):
    http, created, factory = entities_client
    target = await _create_investigation(http, created, "Downgrade Gate AS")
    evidence_id = await _make_evidence(factory, "downgrade-gate", target)
    from apps.api.app.repositories import claims_evidence as repo

    async with factory() as session:
        claim_id = await repo.upsert_claim(
            session,
            target,
            None,
            "company.registered_name",
            {"name": "Downgrade Gate AS"},
            "SUPPORTED",
            [evidence_id],
        )
        assert (await repo.get_claim(session, claim_id))["verified_at"] is not None
        assert (
            await repo.upsert_claim(
                session,
                target,
                None,
                "company.registered_name",
                {"name": "Downgrade Gate AS"},
                "INSUFFICIENT_EVIDENCE",
                [],
            )
            == claim_id
        )
        row = await repo.get_claim(session, claim_id)
        assert row["status"] == "INSUFFICIENT_EVIDENCE"
        assert row["verified_at"] is None
        await session.commit()
