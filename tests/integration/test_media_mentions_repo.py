"""Media mentions repository roundtrip on the migrated schema (AQ-031).

Exercises upsert_media_mention / list_media_mentions against real PostgreSQL
with the 0006_nb_media schema as fixed by 0008 (UNIQUE NULLS NOT DISTINCT):
the media_mentions_idempotency_key unique constraint (investigation_id,
page_urn, target_query) deduplicates both located and issue-level
(page_urn=None) rows, the text_availability check, the documents FK and the
ON DELETE CASCADE from investigations.

Opt-in: requires TEST_DATABASE_URL.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from apps.api.app.repositories.media_mentions import (
    list_media_mentions,
    upsert_media_mention,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)


@pytest.fixture
async def repo_env(monkeypatch) -> AsyncIterator[tuple[Any, list[UUID], list[UUID]]]:
    """Point DATABASE_URL at the test database and clean up created rows after."""
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])

    from apps.api.app.core import config, database

    config.get_settings.cache_clear()
    factory = database.get_session_factory()
    created_investigations: list[UUID] = []
    created_documents: list[UUID] = []
    try:
        yield factory, created_investigations, created_documents
    finally:
        async with factory() as session:
            for investigation_id in created_investigations:
                await session.execute(
                    text("DELETE FROM investigations WHERE id = :id"),
                    {"id": investigation_id},
                )
            for document_id in created_documents:
                await session.execute(
                    text("DELETE FROM documents WHERE id = :id"), {"id": document_id}
                )
            await session.commit()
        await database.dispose_database()
        config.get_settings.cache_clear()


async def _upsert(factory, **kwargs: Any) -> UUID:
    """Call upsert_media_mention in its own session and commit.

    The repository function does not commit; each test call must commit its
    own transaction so a later session can read the row back.
    """
    async with factory() as session:
        row_id = await upsert_media_mention(session, **kwargs)
        await session.commit()
        return row_id


async def _list(factory, investigation_id: UUID) -> list[dict[str, Any]]:
    async with factory() as session:
        return await list_media_mentions(session, investigation_id)


async def _create_investigation(factory, created: list[UUID], *, name: str) -> UUID:
    async with factory() as session:
        investigation_id = (
            await session.execute(
                text("""
                    INSERT INTO investigations (target_type, target_input, purpose)
                    VALUES ('person', CAST(:input AS jsonb), 'Verify media mention repository')
                    RETURNING id
                """),
                {"input": f'{{"name":"{name}"}}'},
            )
        ).scalar_one()
        await session.commit()
    created.append(investigation_id)
    return investigation_id


async def _create_document(factory, created: list[UUID]) -> UUID:
    """Minimal document row for the image_document_id provenance reference.

    media_mentions never duplicate raw content; the derived page/crop snapshot
    lives in documents and is referenced by id.
    """
    async with factory() as session:
        document_id = (
            await session.execute(
                text("""
                    INSERT INTO documents (sha256, title, mime_type)
                    VALUES (:sha256, 'NB page snapshot fixture', 'image/jpeg')
                    RETURNING id
                """),
                {"sha256": uuid.uuid4().hex},
            )
        ).scalar_one()
        await session.commit()
    created.append(document_id)
    return document_id


async def _create_evidence(factory, document_id: UUID) -> UUID:
    """Minimal evidence row on a document for the evidence_id reference."""
    async with factory() as session:
        evidence_id = (
            await session.execute(
                text("""
                    INSERT INTO evidence (document_id, locator_type, locator, content_hash)
                    VALUES (:did, 'nb_article_crop', CAST(:locator AS jsonb), :ch)
                    RETURNING id
                """),
                {
                    "did": document_id,
                    "locator": '{"provider": "nb_catalog"}',
                    "ch": uuid.uuid4().hex,
                },
            )
        ).scalar_one()
        await session.commit()
    return evidence_id


async def test_upsert_and_read_back_all_columns(repo_env) -> None:
    factory, created_investigations, created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Readback Probe"
    )
    document_id = await _create_document(factory, created_documents)
    evidence_id = await _create_evidence(factory, document_id)
    published_at = date(2026, 5, 19)
    anchors = ["xywh=1200,800,400,50", "xywh=1250,860,350,45"]

    row_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query="Media Mention Readback Probe",
        publication="Romerikes Blad",
        published_at=published_at,
        page_number=30,
        issue_urn="URN:NBN:no-nb_romerikesblad_20260519",
        page_urn="URN:NBN:no-nb_romerikesblad_20260519_30",
        headline="Lokal overskrift",
        summary="Sammenfatning av treffet",
        text_excerpt="... kontekst rundt target ...",
        text_availability="PARTIAL_CONTEXT",
        identity_state="UNRESOLVED",
        source_url="https://www.nb.no/items/fixture",
        access_class="PUBLIC_VIEW_ONLY",
        license_code="CC BY-NC-ND 4.0",
        image_document_id=document_id,
        image_embeddable=False,
        evidence_id=evidence_id,
        xywh_anchors=anchors,
    )

    rows = await _list(factory, investigation_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == row_id
    assert row["investigation_id"] == investigation_id
    assert row["target_query"] == "Media Mention Readback Probe"
    assert row["publication"] == "Romerikes Blad"
    assert row["published_at"] == published_at
    assert row["page_number"] == 30
    assert row["issue_urn"] == "URN:NBN:no-nb_romerikesblad_20260519"
    assert row["page_urn"] == "URN:NBN:no-nb_romerikesblad_20260519_30"
    assert row["headline"] == "Lokal overskrift"
    assert row["summary"] == "Sammenfatning av treffet"
    assert row["text_excerpt"] == "... kontekst rundt target ..."
    assert row["text_availability"] == "PARTIAL_CONTEXT"
    assert row["identity_state"] == "UNRESOLVED"
    assert row["source_url"] == "https://www.nb.no/items/fixture"
    assert row["access_class"] == "PUBLIC_VIEW_ONLY"
    assert row["license_code"] == "CC BY-NC-ND 4.0"
    assert row["image_document_id"] == document_id
    # Fail-closed: access metadata never upgrades to embeddable on its own.
    assert row["image_embeddable"] is False
    assert row["evidence_id"] == evidence_id
    assert row["xywh_anchors"] == anchors
    assert row["created_at"] is not None


async def test_idempotent_upsert_same_key_refreshes_values(repo_env) -> None:
    factory, created_investigations, _created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Idempotency Probe"
    )
    page_urn = "URN:NBN:no-nb_hadeland_20070806_23"
    query = "Media Mention Idempotency Probe"

    first_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=page_urn,
        publication="Hadeland",
        text_availability="UNAVAILABLE",
    )
    second_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=page_urn,
        publication="Hadeland",
        page_number=23,
        headline="Oppdatert overskrift",
        text_availability="PARTIAL_CONTEXT",
        source_url="https://www.nb.no/items/fixture-2",
    )

    rows = await _list(factory, investigation_id)
    assert len(rows) == 1, "same idempotency key must not create a second row"
    row = rows[0]
    assert row["id"] == first_id == second_id
    assert row["page_number"] == 23
    assert row["headline"] == "Oppdatert overskrift"
    assert row["text_availability"] == "PARTIAL_CONTEXT"
    assert row["source_url"] == "https://www.nb.no/items/fixture-2"


async def test_anchor_and_evidence_refresh_on_rerun_without_duplicates(repo_env) -> None:
    """Rerun refreshes anchors/evidence on the same row (AQ-033/AQ-032)."""
    factory, created_investigations, created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Anchor Refresh Probe"
    )
    document_id = await _create_document(factory, created_documents)
    evidence_id = await _create_evidence(factory, document_id)
    page_urn = "URN:NBN:no-nb_anchor_refresh_30"
    query = "Media Mention Anchor Refresh Probe"

    first_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=page_urn,
        text_availability="UNAVAILABLE",
    )
    second_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=page_urn,
        text_availability="PARTIAL_CONTEXT",
        text_excerpt="... kontekst ...",
        image_document_id=document_id,
        evidence_id=evidence_id,
        xywh_anchors=["xywh=1,2,3,4"],
    )

    rows = await _list(factory, investigation_id)
    assert len(rows) == 1
    assert rows[0]["id"] == first_id == second_id
    assert rows[0]["xywh_anchors"] == ["xywh=1,2,3,4"]
    assert rows[0]["evidence_id"] == evidence_id


async def test_blank_anchors_store_as_null(repo_env) -> None:
    """Empty/blank anchor lists persist as NULL and read back as None."""
    factory, created_investigations, _created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Blank Anchor Probe"
    )
    await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query="Media Mention Blank Anchor Probe",
        page_urn="URN:NBN:no-nb_blank_anchor_1",
        xywh_anchors=["  ", ""],
    )
    rows = await _list(factory, investigation_id)
    assert len(rows) == 1
    assert rows[0]["xywh_anchors"] is None


async def test_upsert_without_page_urn_is_idempotent(repo_env) -> None:
    """page_urn=None rows deduplicate on (investigation_id, target_query).

    The idempotency key is UNIQUE NULLS NOT DISTINCT (migration 0008), so
    the ON CONFLICT arbiter matches issue-level rows exactly like located
    rows: repeated upserts refresh one row instead of inserting duplicates.
    """
    factory, created_investigations, _created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Null URN Probe"
    )
    query = "Media Mention Null URN Probe"

    first_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=None,
        text_availability="UNAVAILABLE",
    )
    second_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=None,
        publication="Hadeland",
        text_availability="PARTIAL_CONTEXT",
        source_url="https://www.nb.no/items/fixture-null",
    )

    rows = await _list(factory, investigation_id)
    assert len(rows) == 1, "NULL page_urn must hit the same idempotency key"
    assert first_id == second_id
    row = rows[0]
    assert row["publication"] == "Hadeland"
    assert row["text_availability"] == "PARTIAL_CONTEXT"
    assert row["source_url"] == "https://www.nb.no/items/fixture-null"
    # A third identical rerun still refreshes the same single row.
    third_id = await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query=query,
        page_urn=None,
        text_availability="PARTIAL_CONTEXT",
    )
    assert len(await _list(factory, investigation_id)) == 1
    assert third_id == first_id


async def test_invalid_text_availability_raises(repo_env) -> None:
    factory, created_investigations, _created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Validation Probe"
    )

    with pytest.raises(ValueError, match="invalid text_availability"):
        await _upsert(
            factory,
            investigation_id=investigation_id,
            target_query="Media Mention Validation Probe",
            text_availability="FULL_ARTICLE",
        )
    with pytest.raises(ValueError, match="invalid text_availability"):
        await _upsert(
            factory,
            investigation_id=investigation_id,
            target_query="Media Mention Validation Probe",
            text_availability="",
        )

    # Validation happens before the INSERT: no partial row was written.
    assert len(await _list(factory, investigation_id)) == 0


async def test_list_ordering_published_then_page_nulls_last(repo_env) -> None:
    factory, created_investigations, _created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Ordering Probe"
    )

    # Distinct (published_at, page_number) combos so the expected order is
    # unambiguous: published_at ascending with NULLs last, then page_number
    # ascending with NULLs last.
    expected = [
        ("early-page", date(2026, 1, 1), 9),
        ("early-no-page", date(2026, 1, 1), None),
        ("later-page", date(2026, 2, 1), 5),
        ("no-date-page", None, 1),
        ("no-date-no-page", None, None),
    ]
    for target_query, published_at, page_number in expected:
        await _upsert(
            factory,
            investigation_id=investigation_id,
            target_query=target_query,
            published_at=published_at,
            page_number=page_number,
        )

    rows = await _list(factory, investigation_id)
    assert [row["target_query"] for row in rows] == [name for name, _d, _p in expected]


async def test_cascade_delete_removes_media_mentions(repo_env) -> None:
    factory, created_investigations, _created_documents = repo_env
    investigation_id = await _create_investigation(
        factory, created_investigations, name="Media Mention Cascade Probe"
    )
    await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query="Media Mention Cascade Probe",
        page_urn="URN:NBN:no-nb_hadeland_20071005_35",
    )
    await _upsert(
        factory,
        investigation_id=investigation_id,
        target_query="Media Mention Cascade Probe",
        page_urn="URN:NBN:no-nb_hadeland_20080229_17",
    )
    assert len(await _list(factory, investigation_id)) == 2

    async with factory() as session:
        await session.execute(
            text("DELETE FROM investigations WHERE id = :id"), {"id": investigation_id}
        )
        await session.commit()
    created_investigations.remove(investigation_id)

    rows = await _list(factory, investigation_id)
    assert rows == [], "media mentions are cascade-owned by the investigation"
