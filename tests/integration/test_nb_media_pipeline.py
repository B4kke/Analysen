"""Integration tests for the NB media pipeline (AQ-031).

Exercises the full NB chain against real PostgreSQL: HTTP lead admission
(deterministic gate) -> source router -> NB adapter bridge -> media_mentions
rows. The external NB boundary is faked with sanitized fixtures over
``httpx.MockTransport`` -- no live NB in CI. Opt-in: TEST_DATABASE_URL.
"""

import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from apps.api.app.domain.models import Lead
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.executors.nb_media import (
    NBCatalogResult,
    NBIssueCandidate,
    NBPageLocator,
    execute_nb_media_lead,
)
from apps.api.app.services.lead_executor import ExecutorTools, execute_lead
from apps.api.app.services.nb_access_policy import decide_access
from apps.api.app.sources import national_library
from apps.api.app.sources.national_library import (
    NationalLibraryClient,
    NBClientError,
    NBMediaClientAdapter,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "nb")

# Canonical regression shapes from tests/fixtures/nb (Maylen Sorkness
# Andersen / Romerikes Blad 2026-05-19: locator available, content restricted).
RESTRICTED_ITEM_ID = "URN:NBN:no-nb_digavis_romerikesblad_20260519_0030"
RESTRICTED_PAGE_URN = "URN:NBN:no-nb_digavis_romerikesblad_20260519_0030_0030"
PERMITTED_ITEM_ID = "URN:NBN:no-nb_digavis_hadeland_20201223_0025"
PERMITTED_PAGE_URN = "URN:NBN:no-nb_digavis_hadeland_20201223_0025_0025"


def _load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def _fixture_transport(image_calls: list[str] | None = None) -> httpx.MockTransport:
    """Serve sanitized NB fixtures; record every page-image resolver call."""

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/contentfragments" in url:
            return httpx.Response(200, json=_load_fixture("content_fragments_regression.json"))
        if "/contentsearch/" in url:
            return httpx.Response(200, json=_load_fixture("iiif_search_maylen.json"))
        if "/search" in url and "FULL_TEXT_SEARCH" in url:
            return httpx.Response(200, json=_load_fixture("catalog_search_maylen.json"))
        if "/conc" in url and request.method == "POST":
            return httpx.Response(200, json=_load_fixture("dhlab_concordance_maylen.json"))
        if "/resolver/" in url:
            if image_calls is not None:
                image_calls.append(url)
            return httpx.Response(
                200,
                headers={"content-type": "image/jpeg"},
                content=b"\xff\xd8\xff\xe0fixture-page-bytes",
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture
async def nb_pipeline_client(
    monkeypatch, tmp_path
) -> AsyncIterator[tuple[httpx.AsyncClient, list[uuid.UUID], Any]]:
    test_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", test_url)
    # Raw snapshots (catalog JSON, fetched page bytes) never leave the test.
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

    # Image fetch URL validation follows the established allow-fixture
    # pattern (see tests/test_document_fetcher.py): no live DNS in tests.
    async def allow_url(url: str) -> None:
        return None

    monkeypatch.setattr(national_library, "validate_public_http_url", allow_url)

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


async def _create_company(
    http: httpx.AsyncClient, created: list[uuid.UUID], *, name: str
) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "company", "name": name, "known_orgnrs": ["974760673"]},
            "purpose": "Verify NB pipeline",
            "scope_modules": ["BUSINESS_ROLES"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _admit_lead(
    http: httpx.AsyncClient,
    investigation_id: str,
    *,
    query: str,
    scope_area: str = "BUSINESS_ROLES",
) -> str:
    """Admit one deterministic NB lead through the HTTP gate; return lead_id."""
    payload = {
        "lead_type": "nb_newspaper_search",
        "value": {"query": query},
        "reason": "Verify NB pipeline from lead gate to media mention",
        "priority": 0.8,
        "depth": 0,
        "scope_area": scope_area,
        "trigger_type": "DIRECT_SOURCE_LOOKUP",
        "information_need": "Confirm registered details of target organization",
        "relation_depth": 0,
    }
    response = await http.post(
        f"/api/v1/investigations/{investigation_id}/leads", json=payload
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PENDING"
    return body["lead_id"]


async def _lead_from_row(factory: Any, investigation_id: str, lead_id: str) -> Lead:
    """Rebuild the admitted Lead exactly as the executor contract expects."""
    async with factory() as session:
        row = await repository.get_lead(
            session, uuid.UUID(investigation_id), uuid.UUID(lead_id)
        )
    return Lead.model_validate(
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


async def _execute_with_fixture_adapter(
    factory: Any, investigation_id: str, lead_id: str, image_calls: list[str]
) -> str:
    """Run the admitted lead through lead gate -> router -> NB adapter bridge."""
    client = NationalLibraryClient(
        catalog_base_url="https://api.nb.no/catalog/v1",
        dhlab_base_url="https://api.nb.no/dhlab",
        client=httpx.AsyncClient(transport=_fixture_transport(image_calls)),
    )
    adapter = NBMediaClientAdapter(client)
    try:
        async with factory() as session:
            status = await execute_lead(
                session,
                uuid.UUID(investigation_id),
                uuid.UUID(lead_id),
                ExecutorTools(nb_media_client=adapter),
            )
            await session.commit()
    finally:
        await client.aclose()
    return status


def _canonical_item_decider(candidate: Any) -> SimpleNamespace:
    """Canonical per-item access decision mapped onto the executor verdict."""
    access = getattr(candidate, "access", None)
    if not isinstance(access, dict):
        access = {}
    decision = decide_access(access)
    return SimpleNamespace(
        access_class=decision.state.value,
        license_code=decision.upstream.get("license"),
        allow_metadata=decision.allow_metadata,
        allow_context=decision.allow_context,
        allow_full_text_storage=decision.allow_full_text_storage,
        allow_page_fetch=decision.allow_page_fetch,
        allow_report_embed=decision.allow_report_embed,
        reason=decision.reason,
    )


class _RestrictedItemFakeClient:
    """Fake NBMediaClient: one permitted and one LIBRARY_ONLY restricted item.

    DH-lab returns nothing for this run, so neither mention carries lawful
    context; the fake records every page-image call so the rights gate can be
    proven, not assumed.
    """

    def __init__(self) -> None:
        self.image_calls: list[str] = []

    async def catalog_search(self, query: str) -> NBCatalogResult:
        issues = [
            NBIssueCandidate(
                item_id=PERMITTED_ITEM_ID,
                publication="Hadeland",
                issued_at="2020-12-23",
                issue_urn="URN:NBN:no-nb_digavis_hadeland_20201223",
                source_url=f"https://api.nb.no/catalog/v1/items/{PERMITTED_ITEM_ID}",
                access={
                    "accessAllowedFrom": "EVERYWHERE",
                    "viewability": "ALL",
                    "isPublicDomain": False,
                    "license": "NLOD-2.0",
                },
                rank=1,
            ),
            NBIssueCandidate(
                item_id=RESTRICTED_ITEM_ID,
                publication="Romerikes Blad",
                issued_at="2026-05-19",
                issue_urn="URN:NBN:no-nb_digavis_romerikesblad_20260519",
                source_url=f"https://api.nb.no/catalog/v1/items/{RESTRICTED_ITEM_ID}",
                # Canonical LIBRARY_ONLY shape (tests/test_nb_access_policy.py):
                # accessAllowedFrom=LIBRARY without viewability=ALL.
                access={
                    "accessAllowedFrom": "LIBRARY",
                    "isPublicDomain": False,
                    "license": "NLOD-2.0",
                },
                rank=2,
            ),
        ]
        return NBCatalogResult(
            raw_text=json.dumps({"total": 2}, ensure_ascii=False), issues=issues
        )

    async def content_fragments(self, item_id: str, query: str) -> list[Any]:
        page_urn = (
            PERMITTED_PAGE_URN if item_id == PERMITTED_ITEM_ID else RESTRICTED_PAGE_URN
        )
        page_number = 25 if item_id == PERMITTED_ITEM_ID else 30
        return [NBPageLocator(item_id=item_id, page_urn=page_urn, page_number=page_number)]

    async def iiif_search(self, item_id: str, query: str) -> list[Any]:
        return []

    async def dhlab_conc(
        self, urns: list[str], query: str, *, window: int = 10, limit: int = 5
    ) -> list[Any]:
        return []

    async def fetch_page_image(self, page_urn: str) -> bytes:
        self.image_calls.append(page_urn)
        return b"fake-permitted-page-image-bytes"


async def test_nb_search_to_media_mention_roundtrip(nb_pipeline_client) -> None:
    """Lead gate -> source router -> NB adapter -> media_mention in PostgreSQL."""
    http, created, factory = nb_pipeline_client
    investigation_id = await _create_company(http, created, name="NB Pipeline Probe AS")
    lead_id = await _admit_lead(http, investigation_id, query="Pipeline Probe AS")

    image_calls: list[str] = []
    status = await _execute_with_fixture_adapter(
        factory, investigation_id, lead_id, image_calls
    )
    assert status == "COMPLETED"

    async with factory() as session:
        lead = (
            await session.execute(
                text("SELECT status, blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
                {"id": lead_id},
            )
        ).mappings().one()
        rows = (
            await session.execute(
                text(
                    """
                    SELECT target_query, publication, published_at, page_urn,
                           text_excerpt, text_availability, identity_state,
                           access_class, source_url, xywh_anchors
                    FROM media_mentions
                    WHERE investigation_id = CAST(:id AS uuid)
                    """
                ),
                {"id": investigation_id},
            )
        ).mappings().all()
        module = (
            await session.execute(
                text(
                    "SELECT status, coverage FROM investigation_modules "
                    "WHERE investigation_id = CAST(:id AS uuid) AND module = 'BUSINESS_ROLES'"
                ),
                {"id": investigation_id},
            )
        ).mappings().one()

    assert lead["status"] == "COMPLETED"
    assert lead["blocked_reason"] is None
    assert module["coverage"]["query_count"] == 1
    assert "nb_catalog" in module["coverage"]["providers"]
    # Enriched NB coverage (AQ-034): query class, endpoints, result counters
    # and documented time range flow from the executor bump into the ledger.
    assert module["coverage"]["query_classes"] == ["ENTITY_ALIAS_EXACT"]
    assert sorted(module["coverage"]["endpoints"]) == [
        "nb_catalog",
        "nb_contentfragments",
        "nb_contentsearch",
        "nb_dhlab",
    ]
    assert module["coverage"]["candidate_count"] == 10
    assert module["coverage"]["located_count"] == 10
    assert module["coverage"]["concordance_count"] == 10
    assert module["coverage"]["fulltext_count"] == 0
    assert module["coverage"]["restricted_count"] == 1
    assert module["coverage"]["fetched_count"] == 9
    assert module["coverage"]["time_from"] == "1994-12-16"
    assert module["coverage"]["time_to"] == "2026-05-19"

    # The same ledger flows through the real report builder into report.json.
    report = (
        await http.get(f"/api/v1/investigations/{investigation_id}/report.json")
    ).json()
    entry = next(e for e in report["coverage"] if e["module"] == "BUSINESS_ROLES")
    assert entry["query_classes"] == ["ENTITY_ALIAS_EXACT"]
    assert sorted(entry["endpoints"]) == [
        "nb_catalog",
        "nb_contentfragments",
        "nb_contentsearch",
        "nb_dhlab",
    ]
    assert entry["candidate_count"] == 10
    assert entry["located_count"] == 10
    assert entry["concordance_count"] == 10
    assert entry["restricted_count"] == 1
    assert entry["fetched_count"] == 9
    assert entry["time_from"] == "1994-12-16"
    assert entry["time_to"] == "2026-05-19"

    assert len(rows) >= 1, "expected at least one media_mention row"
    row = rows[0]
    assert row["identity_state"] == "UNRESOLVED"
    # contentfragments locator + DH-lab context: PARTIAL_CONTEXT, never FULL.
    assert row["text_availability"] == "PARTIAL_CONTEXT"
    assert row["text_excerpt"] is not None and "Maylen" in row["text_excerpt"]
    assert row["page_urn"] == RESTRICTED_PAGE_URN
    # The adapter bridge delivered the upstream issue date as a real date.
    assert str(row["published_at"]) == "2026-05-19"
    assert row["publication"] == "Romerikes Blad"
    assert row["source_url"] == f"https://api.nb.no/catalog/v1/items/{RESTRICTED_ITEM_ID}"
    # accessAllowedFrom=LIBRARY is restrictive regardless of viewability=ALL
    # (canonical policy, fail closed): LIBRARY_ONLY for the Romerikes issue.
    assert row["access_class"] == "LIBRARY_ONLY"
    # Canvas-fallback anchor correlation (AQ-033): the fixture IIIF anchors
    # live on the Romerikes canvas URL while the fragment locator is a URN.
    # The surviving (last-written Romerikes) row carries all three anchors
    # typed next to the parent page URN — even without a validated crop.
    assert row["xywh_anchors"] == [
        "xywh=1200,800,400,50",
        "xywh=1250,860,350,45",
        "xywh=1300,920,300,40",
    ]
    # The fixture serves one page locator for every issue, so each of the 9
    # permitted issues (EVERYWHERE) fetches it once; the LIBRARY_ONLY issue
    # must not contribute a call. 10 calls would mean the rights gate leaked.
    assert len(image_calls) == 9


async def test_nb_media_deduplication_on_rerun(nb_pipeline_client) -> None:
    """Re-running the same lead/query must not duplicate media_mentions."""
    http, created, factory = nb_pipeline_client
    investigation_id = await _create_company(http, created, name="Dedup Probe AS")

    lead_id_1 = await _admit_lead(http, investigation_id, query="Dedup Probe AS")
    lead_id_2 = await _admit_lead(http, investigation_id, query="Dedup Probe AS")

    image_calls: list[str] = []
    first = await _execute_with_fixture_adapter(
        factory, investigation_id, lead_id_1, image_calls
    )
    second = await _execute_with_fixture_adapter(
        factory, investigation_id, lead_id_2, image_calls
    )
    assert first == "COMPLETED"
    assert second == "COMPLETED"

    async with factory() as session:
        mention_count = await session.scalar(
            text(
                "SELECT count(*) FROM media_mentions "
                "WHERE investigation_id = CAST(:id AS uuid)"
            ),
            {"id": investigation_id},
        )
        query_count = await session.scalar(
            text(
                "SELECT count(*) FROM search_queries "
                "WHERE investigation_id = CAST(:id AS uuid) AND provider = 'nb_catalog'"
            ),
            {"id": investigation_id},
        )

    assert mention_count == 1, f"expected 1 media_mention, got {mention_count}"
    assert query_count == 1, "same query must not create a second search_queries row"


async def test_nb_media_policy_blocks_restricted_item(nb_pipeline_client) -> None:
    """Restricted item (LIBRARY_ONLY): page-image downloader never called for
    it, text state UNAVAILABLE and never FULL, while the permitted control
    item in the same run is fetched through the canonical access decision."""
    http, created, factory = nb_pipeline_client
    investigation_id = await _create_company(http, created, name="Restricted Policy Probe AS")
    lead_id = await _admit_lead(http, investigation_id, query="restricted test item")
    lead = await _lead_from_row(factory, investigation_id, lead_id)

    fake = _RestrictedItemFakeClient()
    async with factory() as session:
        status = await execute_nb_media_lead(
            session,
            uuid.UUID(investigation_id),
            uuid.UUID(lead_id),
            lead,
            client=fake,
            access_decider=_canonical_item_decider,
        )
        await session.commit()
    assert status == "COMPLETED"

    # The downloader ran only for the permitted page; the restricted item's
    # page was never requested.
    assert fake.image_calls == [PERMITTED_PAGE_URN]
    assert RESTRICTED_PAGE_URN not in fake.image_calls

    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT page_urn, text_availability, access_class, identity_state
                    FROM media_mentions
                    WHERE investigation_id = CAST(:id AS uuid)
                    """
                ),
                {"id": investigation_id},
            )
        ).mappings().all()

    assert len(rows) == 2
    by_urn = {row["page_urn"]: row for row in rows}
    restricted = by_urn[RESTRICTED_PAGE_URN]
    assert restricted["access_class"] == "LIBRARY_ONLY"
    assert restricted["text_availability"] == "UNAVAILABLE"
    assert restricted["identity_state"] == "UNRESOLVED"
    permitted = by_urn[PERMITTED_PAGE_URN]
    assert permitted["access_class"] == "PUBLIC_VIEW_ONLY"
    assert all(row["text_availability"] != "FULL" for row in rows)


async def test_adapter_fetch_page_image_contract(monkeypatch) -> None:
    """fetch_page_image returns image bytes and fails typed, never bypassing
    access control or reading past the bounded size."""

    async def allow_url(url: str) -> None:
        return None

    monkeypatch.setattr(national_library, "validate_public_http_url", allow_url)

    async def build(handler) -> tuple[NBMediaClientAdapter, NationalLibraryClient]:
        client = NationalLibraryClient(
            iiif_image_base_url="https://resolver.test",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        return NBMediaClientAdapter(client), client

    async def image_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8\xff\xe0jpeg"
        )

    adapter, client = await build(image_handler)
    try:
        assert await adapter.fetch_page_image(PERMITTED_PAGE_URN) == b"\xff\xd8\xff\xe0jpeg"
    finally:
        await client.aclose()

    # A 200 with a non-image content type (the live 404-page shape) is typed.
    async def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html;charset=utf-8"}, content=b"<html>404</html>"
        )

    adapter, client = await build(html_handler)
    try:
        with pytest.raises(NBClientError) as exc:
            await adapter.fetch_page_image(PERMITTED_PAGE_URN)
        assert exc.value.code == "unexpected_content_type"
    finally:
        await client.aclose()

    # Access denied is typed; nothing is retried or bypassed.
    async def denied_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "access denied"})

    adapter, client = await build(denied_handler)
    try:
        with pytest.raises(NBClientError) as exc:
            await adapter.fetch_page_image(PERMITTED_PAGE_URN)
        assert exc.value.code == "http_error"
        assert exc.value.status_code == 403
    finally:
        await client.aclose()

    # The incremental size cap is enforced while reading.
    monkeypatch.setattr(national_library, "MAX_PAGE_IMAGE_BYTES", 8)

    async def oversized_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=b"x" * 32
        )

    adapter, client = await build(oversized_handler)
    try:
        with pytest.raises(NBClientError) as exc:
            await adapter.fetch_page_image(PERMITTED_PAGE_URN)
        assert exc.value.code == "image_too_large"
    finally:
        await client.aclose()

    # A redirect leaving the resolver host is refused (never followed).
    async def cross_host_redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.test/URN:NBN:x"})

    adapter, client = await build(cross_host_redirect)
    try:
        with pytest.raises(NBClientError) as exc:
            await adapter.fetch_page_image(PERMITTED_PAGE_URN)
        assert exc.value.code == "redirect_error"
    finally:
        await client.aclose()

    # A missing page urn is typed.
    adapter, client = await build(image_handler)
    try:
        with pytest.raises(NBClientError) as exc:
            await adapter.fetch_page_image("   ")
        assert exc.value.code == "invalid_page_urn"
    finally:
        await client.aclose()


async def test_permitted_crop_links_mention_evidence_and_report_citation(
    nb_pipeline_client,
) -> None:
    """Permitted crop (fake OCR, real PostgreSQL) links mention -> evidence.

    The crop path persists Document + Evidence with the IIIF anchors; the
    mention row carries ``evidence_id``; the real report builder exposes
    exactly one clickable citation for that mention. Mentions without stored
    evidence keep an empty citation list — never fabricated links.
    """
    import io

    from PIL import Image

    from apps.api.app.repositories import media_mentions as mention_store
    from apps.api.app.services.executors import nb_media as executor
    from apps.api.app.services.executors.nb_media import NBAccessVerdict
    from apps.api.app.services.nb_article_extract import NBOcrWord
    from apps.api.app.services.report_build import build_report_document

    http, created, factory = nb_pipeline_client
    investigation_id = await _create_company(http, created, name="Citation Probe AS")
    lead_id = await _admit_lead(http, investigation_id, query="Citation Probe AS")
    iid = uuid.UUID(investigation_id)

    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color="white").save(buffer, format="PNG")
    page_bytes = buffer.getvalue()

    def page_ocr(_page: bytes) -> list[NBOcrWord]:
        return [
            NBOcrWord(text="Maylen", x=100, y=60, w=60, h=18, confidence=95.0),
            NBOcrWord(text="Sorkness", x=165, y=60, w=60, h=18, confidence=95.0),
        ]

    def crop_ocr(_crop: bytes) -> list[NBOcrWord]:
        return [
            NBOcrWord(text="Maylen", x=5, y=5, w=60, h=18, confidence=95.0),
            NBOcrWord(text="Sorkness", x=70, y=5, w=60, h=18, confidence=95.0),
            NBOcrWord(text="Andersen", x=150, y=5, w=60, h=18, confidence=95.0),
        ]

    verdict = NBAccessVerdict(
        access_class="PUBLIC_VIEW_ONLY",
        license_code="NLOD-2.0",
        allow_metadata=True,
        allow_context=True,
        allow_page_fetch=True,
        allow_derived_crop=True,
        allow_report_embed=True,
        reason="test",
    )
    async with factory() as session:
        document_id, crop_text, evidence_id = await executor._extract_and_persist_crop(
            session,
            iid,
            item_id=PERMITTED_ITEM_ID,
            issue_urn="URN:NBN:no-nb_digavis_hadeland_20201223",
            page_urn=PERMITTED_PAGE_URN,
            page_number=25,
            publication="Hadeland",
            issued_at="2020-12-23",
            source_url=f"https://api.nb.no/catalog/v1/items/{PERMITTED_ITEM_ID}",
            query="Maylen Sorkness Andersen",
            anchors=["xywh=100,60,120,20"],
            page_bytes=page_bytes,
            verdict=verdict,
            upstream_license=None,
            page_ocr_fn=page_ocr,
            crop_ocr_fn=crop_ocr,
        )
        assert document_id is not None and evidence_id is not None
        assert crop_text is not None and "Maylen" in crop_text

        await executor._persist_mention(
            session,
            iid,
            uuid.UUID(lead_id),
            mention_store.upsert_media_mention,
            target_query="Maylen Sorkness Andersen",
            publication="Hadeland",
            published_at="2020-12-23",
            page_number=25,
            issue_urn="URN:NBN:no-nb_digavis_hadeland_20201223",
            page_urn=PERMITTED_PAGE_URN,
            headline=None,
            summary=None,
            text_excerpt=crop_text,
            text_availability="PARTIAL_CONTEXT",
            source_url=f"https://api.nb.no/catalog/v1/items/{PERMITTED_ITEM_ID}",
            verdict=verdict,
            upstream_license=None,
            image_document_id=document_id,
            evidence_id=evidence_id,
            xywh_anchors=["xywh=100,60,120,20"],
        )
        # A mention without stored evidence: citations must stay empty.
        await mention_store.upsert_media_mention(
            session,
            investigation_id=iid,
            target_query="Maylen Sorkness Andersen",
            publication="Romerikes Blad",
            page_urn=RESTRICTED_PAGE_URN,
            text_availability="UNAVAILABLE",
            identity_state="UNRESOLVED",
        )
        await session.commit()

    async with factory() as session:
        stored = (
            await session.execute(
                text(
                    "SELECT page_urn, evidence_id, image_document_id, xywh_anchors "
                    "FROM media_mentions WHERE investigation_id = :id"
                ),
                {"id": iid},
            )
        ).mappings().all()
        by_urn = {row["page_urn"]: row for row in stored}
        assert by_urn[PERMITTED_PAGE_URN]["evidence_id"] == evidence_id
        assert by_urn[PERMITTED_PAGE_URN]["image_document_id"] == document_id
        assert by_urn[PERMITTED_PAGE_URN]["xywh_anchors"] == ["xywh=100,60,120,20"]
        assert by_urn[RESTRICTED_PAGE_URN]["evidence_id"] is None

        document = await build_report_document(session, iid)

    cited = [m for m in document.media_mentions if m.page_urn == PERMITTED_PAGE_URN]
    assert len(cited) == 1
    assert cited[0].xywh_anchors == ["xywh=100,60,120,20"]
    assert len(cited[0].citations) == 1
    citation = cited[0].citations[0]
    assert citation.claim_id is None
    assert citation.evidence_id == evidence_id
    assert citation.document_id == document_id
    assert citation.source_id == "nb_catalog"
    assert citation.url == f"https://api.nb.no/catalog/v1/items/{PERMITTED_ITEM_ID}"
    assert citation.excerpt is not None and "Maylen" in citation.excerpt
    assert citation.sha256 is not None

    image_response = await http.get(
        f"/api/v1/investigations/{investigation_id}/media/image/{document_id}"
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert image_response.headers["content-disposition"] == "inline"
    assert image_response.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(image_response.content).hexdigest() == citation.sha256

    html_response = await http.get(
        f"/api/v1/investigations/{investigation_id}/report.html"
    )
    assert html_response.status_code == 200
    assert '<img class="media-image"' in html_response.text
    assert f"/media/image/{document_id}" in html_response.text

    pdf_response = await http.get(
        f"/api/v1/investigations/{investigation_id}/report.pdf"
    )
    assert pdf_response.status_code == 200
    assert b"/Subtype /Image" in pdf_response.content

    other_investigation_id = await _create_company(
        http, created, name="Other Media Case AS"
    )
    denied = await http.get(
        f"/api/v1/investigations/{other_investigation_id}/media/image/{document_id}"
    )
    assert denied.status_code == 404

    async with factory() as session:
        await session.execute(
            text(
                "UPDATE media_mentions SET evidence_id = NULL "
                "WHERE investigation_id = :iid AND page_urn = :page_urn"
            ),
            {"iid": iid, "page_urn": PERMITTED_PAGE_URN},
        )
        await session.commit()
    provenance_denied = await http.get(
        f"/api/v1/investigations/{investigation_id}/media/image/{document_id}"
    )
    assert provenance_denied.status_code == 404

    async with factory() as session:
        await session.execute(
            text(
                "UPDATE media_mentions "
                "SET evidence_id = :evidence_id, image_embeddable = FALSE "
                "WHERE investigation_id = :iid AND page_urn = :page_urn"
            ),
            {
                "iid": iid,
                "page_urn": PERMITTED_PAGE_URN,
                "evidence_id": evidence_id,
            },
        )
        await session.commit()
    policy_denied = await http.get(
        f"/api/v1/investigations/{investigation_id}/media/image/{document_id}"
    )
    assert policy_denied.status_code == 404

    bare = [m for m in document.media_mentions if m.page_urn == RESTRICTED_PAGE_URN]
    assert len(bare) == 1
    assert bare[0].citations == []


class _OriginalUrlFakeClient:
    """Catalog issues carrying original nettavis URLs (AQ-035).

    One good URL, one missing, one non-web scheme. No pages, so the
    page-image downloader must never be invoked and every mention stays
    issue-level UNAVAILABLE.
    """

    async def catalog_search(self, query: str) -> NBCatalogResult:
        def issue(item: str, issued: str, original_url: str | None) -> NBIssueCandidate:
            return NBIssueCandidate(
                item_id=item,
                publication="Nettavis",
                issued_at=issued,
                issue_urn="URN:NBN:net",
                source_url=f"https://api.nb.no/catalog/v1/items/{item}",
                access={},
                rank=1,
                original_url=original_url,
            )

        return NBCatalogResult(
            raw_text="{}",
            issues=[
                issue("URN:NBN:net:1", "2024-01-05", "https://nettavis.test/artikkel/1"),
                issue("URN:NBN:net:2", "2024-01-06", None),
                issue("URN:NBN:net:3", "2024-01-07", "ftp://files.test/x"),
            ],
        )

    async def content_fragments(self, item_id: str, query: str) -> list[Any]:
        return []

    async def iiif_search(self, item_id: str, query: str) -> list[Any]:
        return []

    async def dhlab_conc(
        self, urns: list[str], query: str, *, window: int = 10, limit: int = 5
    ) -> list[Any]:
        return []

    async def fetch_page_image(self, page_urn: str) -> bytes:
        raise AssertionError("no pages located, downloader must stay idle")


async def _create_web_media_company(
    http: httpx.AsyncClient, created: list[uuid.UUID], *, name: str
) -> str:
    response = await http.post(
        "/api/v1/investigations",
        json={
            "target": {"type": "company", "name": name, "known_orgnrs": ["974760673"]},
            "purpose": "Verify NB original-URL bridge",
            "scope_modules": ["WEB_MEDIA"],
            "expansion_policy": "DIRECT_RELATIONS",
            "max_relation_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    investigation_id = response.json()["id"]
    created.append(uuid.UUID(investigation_id))
    return investigation_id


async def _bridged_fetch_rows(factory: Any, investigation_id: str) -> list[Any]:
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT id, status, value, trigger_type, scope_area, blocked_reason "
                    "FROM leads WHERE investigation_id = CAST(:id AS uuid) "
                    "AND lead_type = 'web_document_fetch'"
                ),
                {"id": investigation_id},
            )
        ).mappings().all()


async def test_original_url_bridge_proposes_gated_web_fetch(nb_pipeline_client) -> None:
    """NB COMPLETED proposes one PENDING web_document_fetch for the good URL.

    The missing and ftp URLs never become leads. The proposal passes the
    deterministic gate (PENDING, DIRECT_SOURCE_LOOKUP, WEB_MEDIA) instead of
    fetching anything itself.
    """
    http, created, factory = nb_pipeline_client
    investigation_id = await _create_web_media_company(http, created, name="Bro Probe AS")
    lead_id = await _admit_lead(
        http, investigation_id, query="Bro Probe", scope_area="WEB_MEDIA"
    )
    lead = await _lead_from_row(factory, investigation_id, lead_id)

    async with factory() as session:
        status = await execute_nb_media_lead(
            session,
            uuid.UUID(investigation_id),
            uuid.UUID(lead_id),
            lead,
            client=_OriginalUrlFakeClient(),
        )
        await session.commit()
    assert status == "COMPLETED"

    rows = await _bridged_fetch_rows(factory, investigation_id)
    assert len(rows) == 1, [dict(row) for row in rows]
    row = rows[0]
    assert row["status"] == "PENDING"
    assert row["value"]["url"] == "https://nettavis.test/artikkel/1"
    assert row["trigger_type"] == "DIRECT_SOURCE_LOOKUP"
    assert row["scope_area"] == "WEB_MEDIA"


async def test_original_url_bridge_completes_through_safe_fetcher(
    nb_pipeline_client,
) -> None:
    """NB COMPLETED -> PENDING web_document_fetch -> web_fetch COMPLETED.

    The bridged lead runs through the existing gated web_fetch executor with
    only the fetch transport faked; scope/trigger/provenance gates are real.
    """
    from apps.api.app.services.url_canonicalization import FetchResult

    async def fake_fetch(url: str) -> FetchResult:
        assert url == "https://nettavis.test/artikkel/1"
        return FetchResult(
            url=url,
            final_url=url,
            content="<html><body>Nettavis artikkeltekst</body></html>",
            content_type="text/html",
            status_code=200,
            metadata={},
            error=None,
        )

    http, created, factory = nb_pipeline_client
    investigation_id = await _create_web_media_company(http, created, name="Bro Chain AS")
    lead_id = await _admit_lead(
        http, investigation_id, query="Bro Chain", scope_area="WEB_MEDIA"
    )
    lead = await _lead_from_row(factory, investigation_id, lead_id)
    async with factory() as session:
        assert (
            await execute_nb_media_lead(
                session,
                uuid.UUID(investigation_id),
                uuid.UUID(lead_id),
                lead,
                client=_OriginalUrlFakeClient(),
            )
            == "COMPLETED"
        )
        await session.commit()

    rows = await _bridged_fetch_rows(factory, investigation_id)
    assert len(rows) == 1 and rows[0]["status"] == "PENDING"

    async with factory() as session:
        final = await execute_lead(
            session,
            uuid.UUID(investigation_id),
            rows[0]["id"],
            ExecutorTools(web_fetch=fake_fetch),
        )
        await session.commit()
    assert final == "COMPLETED"

    async with factory() as session:
        stored_url = await session.scalar(
            text(
                "SELECT original_url FROM documents "
                "WHERE original_url = 'https://nettavis.test/artikkel/1'"
            )
        )
    assert stored_url == "https://nettavis.test/artikkel/1"


async def test_original_url_bridge_rerun_proposes_nothing_new(
    nb_pipeline_client,
) -> None:
    """A second NB pass over the same URLs proposes no duplicate fetch leads."""
    http, created, factory = nb_pipeline_client
    investigation_id = await _create_web_media_company(http, created, name="Bro Redo AS")
    for query in ("Bro Redo", "Bro Redo"):
        lead_id = await _admit_lead(
            http, investigation_id, query=query, scope_area="WEB_MEDIA"
        )
        lead = await _lead_from_row(factory, investigation_id, lead_id)
        async with factory() as session:
            assert (
                await execute_nb_media_lead(
                    session,
                    uuid.UUID(investigation_id),
                    uuid.UUID(lead_id),
                    lead,
                    client=_OriginalUrlFakeClient(),
                )
                == "COMPLETED"
            )
            await session.commit()

    rows = await _bridged_fetch_rows(factory, investigation_id)
    assert len(rows) == 1, [dict(row) for row in rows]


async def test_original_url_bridge_blocked_without_web_media(
    nb_pipeline_client,
) -> None:
    """Without WEB_MEDIA the bridge proposal is BLOCKED, never PENDING."""
    http, created, factory = nb_pipeline_client
    investigation_id = await _create_company(http, created, name="Bro Blocked AS")
    lead_id = await _admit_lead(http, investigation_id, query="Bro Blocked")
    lead = await _lead_from_row(factory, investigation_id, lead_id)
    async with factory() as session:
        assert (
            await execute_nb_media_lead(
                session,
                uuid.UUID(investigation_id),
                uuid.UUID(lead_id),
                lead,
                client=_OriginalUrlFakeClient(),
            )
            == "COMPLETED"
        )
        await session.commit()

    rows = await _bridged_fetch_rows(factory, investigation_id)
    assert len(rows) == 1, [dict(row) for row in rows]
    assert rows[0]["status"] == "BLOCKED"
    assert rows[0]["blocked_reason"] == "module_disabled"


async def test_wrongly_wired_raw_client_fails_closed(nb_pipeline_client) -> None:
    """A raw transport client (not the adapter bridge) must refuse explicitly.

    Regression: the worker once wired ``NationalLibraryClient()`` where the
    executor protocol belongs, crashing every NB lead with
    ``source_error:AttributeError``. Missing capabilities now refuse with
    ``executor_unavailable`` instead of crashing the pass.
    """
    from apps.api.app.sources.national_library import NationalLibraryClient

    http, created, factory = nb_pipeline_client
    investigation_id = await _create_web_media_company(http, created, name="Wire Probe AS")
    lead_id = await _admit_lead(
        http, investigation_id, query="Wire Probe", scope_area="WEB_MEDIA"
    )
    lead = await _lead_from_row(factory, investigation_id, lead_id)
    async with factory() as session:
        status = await execute_nb_media_lead(
            session,
            uuid.UUID(investigation_id),
            uuid.UUID(lead_id),
            lead,
            client=NationalLibraryClient(),
        )
        await session.commit()
    assert status == "FAILED"

    async with factory() as session:
        reason = await session.scalar(
            text("SELECT blocked_reason FROM leads WHERE id = CAST(:id AS uuid)"),
            {"id": lead_id},
        )
    assert reason == "executor_unavailable"


async def test_media_identity_match_bridges_to_verified_claim(nb_pipeline_client) -> None:
    """A corroborated company mention becomes MATCH and a verified claim."""
    from apps.api.app.domain.models import SourceRegistryRecord
    from apps.api.app.repositories import claims_evidence
    from apps.api.app.repositories import media_mentions as mention_store
    from apps.api.app.services.executors import nb_media as executor

    http, created, factory = nb_pipeline_client
    investigation_id = await _create_company(http, created, name="Match Probe AS")
    iid = uuid.UUID(investigation_id)
    excerpt = "Match Probe AS (org.nr. 974 760 673) er omtalt i denne artikkelen."

    async with factory() as session:
        await claims_evidence.upsert_source(
            session,
            SourceRegistryRecord(
                id="test_media_identity",
                name="Test media identity source",
                evidence_tier=2,
                access_class="TEST",
                base_url="https://example.test",
            ),
        )
        digest = hashlib.sha256(f"media-identity:{investigation_id}".encode()).hexdigest()
        document_id = await claims_evidence.upsert_document(
            session,
            source_id="test_media_identity",
            original_url="https://example.test/article",
            canonical_url="https://example.test/article",
            mime_type="text/plain",
            sha256=digest,
            raw_storage_key=None,
            extracted_text=excerpt,
            parser_metadata={"test": "media_identity"},
        )
        await claims_evidence.attach_document(
            session, iid, document_id, reason="media_identity_test"
        )
        evidence_id = await claims_evidence.store_evidence(
            session,
            document_id,
            "article_excerpt",
            {"test": "media_identity"},
            excerpt,
            {"target_validated": True},
        )
        mention_id = await mention_store.upsert_media_mention(
            session,
            investigation_id=iid,
            target_query="Match Probe AS",
            publication="Testavisen",
            text_excerpt=excerpt,
            text_availability="PARTIAL_CONTEXT",
            identity_state="UNRESOLVED",
            source_url="https://example.test/article",
            evidence_id=evidence_id,
        )
        state, claim_id, claim_status = await executor._resolve_and_verify_mention(
            session,
            iid,
            mention_id=mention_id,
            target_query="Match Probe AS",
            text_excerpt=excerpt,
            evidence_id=evidence_id,
            publication="Testavisen",
            published_at=None,
            page_urn="URN:NBN:test:page:1",
            source_url="https://example.test/article",
        )
        await session.commit()

        stored_state = await session.scalar(
            text("SELECT identity_state FROM media_mentions WHERE id = :id"),
            {"id": mention_id},
        )
        stored_claim = (
            await session.execute(
                text("SELECT predicate, status FROM claims WHERE id = :id"),
                {"id": claim_id},
            )
        ).mappings().one()

    assert state == "MATCH"
    assert claim_id is not None
    assert claim_status == "SUPPORTED"
    assert stored_state == "MATCH"
    assert stored_claim["predicate"] == "media_mention"
    assert stored_claim["status"] == "SUPPORTED"
