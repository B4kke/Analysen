"""Report endpoint contract tests (AQ-027/AQ-031).

Two layers:

1. Pure contract tests (no database): ``report.json``, ``report.html`` and
   ``report.pdf`` are exercised with a stubbed report builder, proving the
   ``ReportDocument`` response contract exposes ``media_mentions`` and that
   HTML/PDF render from the same canonical document.
2. Opt-in database test (``TEST_DATABASE_URL``): a media mention stored
   through the canonical ``media_mentions`` repository flows through the
   real builder into ``report.json``.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from uuid import UUID

import httpx
import pytest

from apps.api.app.domain.nb_media import NBTextAvailability
from apps.api.app.domain.report import MediaMention, ReportDocument

_IID = UUID(int=10)
_GENERATED = datetime(2026, 1, 15, 12, 0, 0)


def _document(investigation_id: UUID) -> ReportDocument:
    return ReportDocument(
        investigation_id=investigation_id,
        target_name="Rapport Routes AS",
        target_type="company",
        purpose="Testformål",
        generated_at=_GENERATED,
        expansion_policy="DIRECT_RELATIONS",
        max_relation_depth=1,
        scope_modules=["WEB_MEDIA"],
        findings=[],
        media_mentions=[
            MediaMention(
                publication="Hadeland",
                published_at=date(2007, 8, 6),
                page_number=23,
                headline="Overskrift fra avis",
                summary=None,
                text_excerpt="… <em>Rapport Routes AS</em> …",
                text_availability=NBTextAvailability.PARTIAL_CONTEXT,
                identity_state="UNRESOLVED",
                issue_urn="URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806",
                page_urn="URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23",
                source_url=None,
                access_class="PUBLIC_VIEW_ONLY",
                license_code="CC0",
                image_document_id=None,
                image_embeddable=False,
                target_query="Rapport Routes AS",
            )
        ],
        unverified_leads=[],
        context_entities=[],
        coverage=[],
    )


@pytest.fixture
async def stub_client(monkeypatch) -> AsyncIterator[httpx.AsyncClient]:
    """Report endpoints with a stubbed builder: no database is touched."""
    from apps.api.app.core.database import get_db_session
    from apps.api.app.main import app
    from apps.api.app.services import report_build

    async def override_session():
        return None

    async def stub_document(session, investigation_id):
        return _document(investigation_id)

    app.dependency_overrides[get_db_session] = override_session
    monkeypatch.setattr(report_build, "build_report_document", stub_document)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_report_json_contains_media_mentions(stub_client) -> None:
    response = await stub_client.get(f"/api/v1/investigations/{_IID}/report.json")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert str(payload["investigation_id"]) == str(_IID)
    assert isinstance(payload["media_mentions"], list)
    assert len(payload["media_mentions"]) == 1
    mention = payload["media_mentions"][0]
    for key in (
        "publication",
        "published_at",
        "page_number",
        "headline",
        "summary",
        "text_excerpt",
        "text_availability",
        "identity_state",
        "issue_urn",
        "page_urn",
        "source_url",
        "access_class",
        "license_code",
        "image_document_id",
        "image_embeddable",
        "target_query",
        "citations",
        "xywh_anchors",
    ):
        assert key in mention, key
    # published_at is a date (not a datetime) in the JSON contract.
    assert mention["published_at"] == "2007-08-06"
    assert mention["text_availability"] == "PARTIAL_CONTEXT"
    assert mention["identity_state"] == "UNRESOLVED"
    assert mention["page_urn"] == "URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23"
    assert mention["image_embeddable"] is False
    # The stubbed mention has no stored evidence or anchors: nothing fabricated.
    assert mention["citations"] == []
    assert mention["xywh_anchors"] == []


async def test_report_html_renders_media_mentions_from_same_document(stub_client) -> None:
    response = await stub_client.get(f"/api/v1/investigations/{_IID}/report.html")
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert 'lang="nb"' in response.text
    assert '<section id="medienevnter"><h2>Medienevnter</h2>' in response.text
    assert "Kontekstutdrag (ikke full artikkeltekst)" in response.text
    assert "Rapport Routes AS" in response.text


async def test_report_pdf_renders_media_mentions_from_same_document(stub_client) -> None:
    response = await stub_client.get(f"/api/v1/investigations/{_IID}/report.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


async def test_report_endpoints_404_for_unknown_investigation(
    stub_client, monkeypatch
) -> None:
    from apps.api.app.repositories.investigations import InvestigationNotFound
    from apps.api.app.services import report_build

    async def raise_not_found(session, investigation_id):
        raise InvestigationNotFound(f"no investigation {investigation_id}")

    monkeypatch.setattr(report_build, "build_report_document", raise_not_found)
    missing = uuid.uuid4()
    for suffix in ("report.json", "report.html", "report.pdf"):
        response = await stub_client.get(f"/api/v1/investigations/{missing}/{suffix}")
        assert response.status_code == 404, suffix


# ---------------------------------------------------------------------------
# Opt-in database test: canonical repository -> real builder -> report.json
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for integration tests",
)
async def test_report_json_contains_stored_media_mentions(
    monkeypatch, tmp_path
) -> None:
    test_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", test_url)

    from apps.api.app.core import config, database

    config.get_settings.cache_clear()
    from apps.api.app.main import app

    factory = database.get_session_factory()
    investigation_id: uuid.UUID | None = None

    async def override_session():
        async with factory() as session:
            yield session

    from apps.api.app.core.database import get_db_session

    app.dependency_overrides[get_db_session] = override_session
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            payload = {
                "target": {
                    "type": "person",
                    "name": "Medievnt Rapport Probe",
                    "birth_year": 1980,
                },
                "purpose": "Verify media mentions in report.json",
                "scope_modules": ["WEB_MEDIA"],
                "expansion_policy": "DIRECT_RELATIONS",
                "max_relation_depth": 1,
            }
            response = await http.post("/api/v1/investigations", json=payload)
            assert response.status_code == 201, response.text
            investigation_id = uuid.UUID(response.json()["id"])

            from apps.api.app.repositories import media_mentions as store

            page_urn = f"URN:NBN:no-nb_digavis_probe_null_probe_20260101_{investigation_id.hex[:8]}"
            async with factory() as session:
                await store.upsert_media_mention(
                    session,
                    investigation_id=investigation_id,
                    target_query="Medievnt Rapport Probe",
                    publication="Hadeland",
                    published_at=date(2007, 8, 6),
                    page_number=23,
                    issue_urn="URN:NBN:no-nb_digavis_probe_null_probe_20260101",
                    page_urn=page_urn,
                    headline="Overskrift fra avis",
                    text_excerpt="… <em>Medievnt Rapport Probe</em> …",
                    text_availability="PARTIAL_CONTEXT",
                    identity_state="UNRESOLVED",
                    access_class="PUBLIC_VIEW_ONLY",
                    license_code="CC0",
                )
                await session.commit()

            report_response = await http.get(
                f"/api/v1/investigations/{investigation_id}/report.json"
            )
            assert report_response.status_code == 200, report_response.text
            body = report_response.json()
            mentions = [m for m in body["media_mentions"] if m["page_urn"] == page_urn]
            assert len(mentions) == 1, body["media_mentions"]
            mention = mentions[0]
            assert mention["publication"] == "Hadeland"
            assert mention["published_at"] == "2007-08-06"
            assert mention["page_number"] == 23
            assert mention["text_availability"] == "PARTIAL_CONTEXT"
            assert mention["identity_state"] == "UNRESOLVED"
            assert mention["text_excerpt"] == "… <em>Medievnt Rapport Probe</em> …"
            assert mention["access_class"] == "PUBLIC_VIEW_ONLY"
            assert mention["license_code"] == "CC0"
            assert mention["image_embeddable"] is False
            # No stored evidence or anchors for this mention: nothing fabricated.
            assert mention["citations"] == []
            assert mention["xywh_anchors"] == []

            html_response = await http.get(
                f"/api/v1/investigations/{investigation_id}/report.html"
            )
            assert html_response.status_code == 200, html_response.text
            assert "Kontekstutdrag (ikke full artikkeltekst)" in html_response.text
            assert "Medievnt Rapport Probe" in html_response.text
    finally:
        app.dependency_overrides.clear()
        if investigation_id is not None:
            from apps.api.app.repositories import investigations as investigations_repo

            async with factory() as session:
                await investigations_repo.delete_investigation(session, investigation_id)
                await session.commit()
        await database.dispose_database()
        config.get_settings.cache_clear()
