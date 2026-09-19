"""Renderer tests for HTML/PDF report output (AQ-027 slice).

Pure tests: ReportDocument fixtures are built inline, no database needed.
AQ-031 additions: media mention HTML/PDF parity (same media mention
semantics in both outputs), UNAVAILABLE mentions showing metadata + direct
NB link and never fabricated full text, and escaping inside media mentions.
"""

import html
import re
import zlib
from datetime import date, datetime
from uuid import UUID

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.domain.nb_media import NBTextAvailability
from apps.api.app.domain.report import (
    ContextEntity,
    CoverageEntry,
    MediaMention,
    ReportCitation,
    ReportDocument,
    ReportFinding,
    UnverifiedLead,
)
from apps.api.app.services.report_render import render_report_html, render_report_pdf

_PAYLOAD = '<script>alert("x")</script>'
_GENERATED = datetime(2026, 1, 15, 12, 0, 0)
# Unique marker proving the UNAVAILABLE mention's stored excerpt is never
# rendered: text availability UNAVAILABLE shows metadata + link only.
_UNAVAILABLE_TEXT = "UNAVAILABLE-utdrag-skal-aldri-vises-i-rapporten"
# Escaped em-markup forms, built via html.escape so the entities are
# never hand-typed.
_ESC_EM = html.escape("<em>", quote=True)
_ESC_EM_END = html.escape("</em>", quote=True)


def _citation(*, with_url: bool, excerpt: str | None = None) -> ReportCitation:
    return ReportCitation(
        claim_id=UUID(int=1),
        evidence_id=UUID(int=2),
        document_id=UUID(int=3),
        source_id="brreg",
        excerpt=excerpt,
        url="https://example.com/kilde" if with_url else None,
        fetched_at=_GENERATED,
        sha256="abcdef1234567890",
    )


def _full_doc() -> ReportDocument:
    findings = [
        ReportFinding(
            predicate=f"predicate-{status.value} {_PAYLOAD}",
            value={"nøkkel": f'verdi "sitat" {_PAYLOAD}'},
            status=status,
            subject_name=f"Subjekt {_PAYLOAD}" if status == ClaimStatus.SUPPORTED else None,
            citations=[_citation(with_url=True, excerpt=f"utdrag {_PAYLOAD}")],
        )
        for status in (
            ClaimStatus.SUPPORTED,
            ClaimStatus.PARTIALLY_SUPPORTED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.INSUFFICIENT_EVIDENCE,
            ClaimStatus.UNVERIFIED_LEAD,
        )
    ]
    # A citation without URL must render as text, never as a dead link.
    findings[0].citations.append(_citation(with_url=False, excerpt="tekstutdrag uten url"))
    findings[1].value = None
    findings[2].citations = []
    media_mentions = [
        # Partial context (DH-lab/concordance-like): lawful excerpt, never full text.
        MediaMention(
            publication="Hadeland",
            published_at=date(2007, 8, 6),
            page_number=23,
            headline=f"Overskrift {_PAYLOAD}",
            summary=None,
            text_excerpt=f"… <em>Ola {_PAYLOAD} Nordmann</em> …",
            text_availability=NBTextAvailability.PARTIAL_CONTEXT,
            identity_state="UNRESOLVED",
            issue_urn="URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806",
            page_urn="URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23",
            source_url=None,
            access_class="PUBLIC_VIEW_ONLY",
            license_code="CC0",
            image_document_id=None,
            image_embeddable=False,
            target_query="Ola Nordmann",
        ),
        # Unavailable: metadata + direct NB link; the stored excerpt must stay hidden.
        MediaMention(
            publication="Romerikes Blad",
            published_at=date(2026, 5, 19),
            page_number=30,
            headline=None,
            summary=None,
            text_excerpt=_UNAVAILABLE_TEXT,
            text_availability=NBTextAvailability.UNAVAILABLE,
            identity_state="UNRESOLVED",
            issue_urn="URN:NBN:no-nb_digavis_romerikesblad_null_rb_20260519",
            page_urn="URN:NBN:no-nb_digavis_romerikesblad_null_rb_20260519_30",
            source_url="https://www.nb.no/items/URN:NBN:no-nb_digavis_romerikesblad_null_rb_20260519",
            access_class="NB_ONLY",
            license_code=None,
            image_document_id=None,
            image_embeddable=False,
            target_query="Ola Nordmann",
        ),
    ]
    return ReportDocument(
        investigation_id=UUID(int=10),
        target_name=f"Ola {_PAYLOAD} Nordmann",
        target_type="person",
        purpose="Testformål",
        generated_at=_GENERATED,
        expansion_policy="DIRECT_ONLY",
        max_relation_depth=1,
        scope_modules=["WEB_MEDIA"],
        findings=findings,
        media_mentions=media_mentions,
        unverified_leads=[
            UnverifiedLead(
                predicate=None,
                information_need=f"trenger mer {_PAYLOAD}",
                reason="begrunnelse",
            )
        ],
        context_entities=[
            ContextEntity(name=f"Kontekst {_PAYLOAD}", entity_schema="Organization", relation=None)
        ],
        coverage=[
            CoverageEntry(
                module="WEB_MEDIA",
                enabled=True,
                status="COMPLETE",
                outcome="Undersøkt",
                stop_reason=None,
                providers=["searxng"],
                query_count=3,
                document_count=2,
            )
        ],
    )


def _empty_doc() -> ReportDocument:
    return ReportDocument(
        investigation_id=UUID(int=11),
        target_name="Tom",
        target_type="person",
        purpose="Tom rapport",
        generated_at=_GENERATED,
        expansion_policy="DIRECT_ONLY",
        max_relation_depth=0,
        scope_modules=[],
        findings=[],
        unverified_leads=[],
        context_entities=[],
        coverage=[],
    )


def test_html_escapes_payload() -> None:
    out = render_report_html(_full_doc())
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_html_renders_all_finding_states() -> None:
    out = render_report_html(_full_doc())
    for status in (
        "SUPPORTED",
        "PARTIALLY_SUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT_EVIDENCE",
        "UNVERIFIED_LEAD",
    ):
        assert status in out


def test_html_citations_with_url_become_links_without_url_do_not() -> None:
    out = render_report_html(_full_doc())
    assert '<a href="https://example.com/kilde">' in out
    # Four URL citations in the findings (one finding has no citations, one
    # citation has no URL) plus two media mention links (one from the stored
    # source_url, one built from the URN:NBN page locator), no other links.
    assert out.count("<a ") == 6
    assert "tekstutdrag uten url" in out


def test_html_leads_section_separate_from_findings() -> None:
    out = render_report_html(_full_doc())
    assert "Uavklarte spor" in out
    assert "Vesentlige funn" in out
    assert out.index('id="spor"') > out.index('id="funn"')
    assert out.index("trenger mer") > out.index('id="spor"')


def test_html_context_entities_carry_disclaimer() -> None:
    out = render_report_html(_full_doc())
    assert "ikke bakgrunnssjekket" in out
    assert "Kontekst" in out


def test_html_lang_and_no_javascript() -> None:
    out = render_report_html(_full_doc())
    assert 'lang="nb"' in out
    assert "<script" not in out.lower()


def test_html_handles_empty_document() -> None:
    out = render_report_html(_empty_doc())
    assert "Ingen funn." in out
    assert "Ingen dekningsdata." in out
    assert "Ingen medienevnter." in out


def test_pdf_starts_with_pdf_and_non_empty() -> None:
    data = render_report_pdf(_full_doc())
    assert data[:4] == b"%PDF"
    assert len(data) > 500


def test_pdf_deterministic_across_renders() -> None:
    assert render_report_pdf(_full_doc()) == render_report_pdf(_full_doc())


def test_pdf_handles_empty_document_and_long_strings() -> None:
    doc = _empty_doc()
    doc.target_name = "x" * 5000
    doc.unverified_leads = [
        UnverifiedLead(predicate=None, information_need="y" * 5000, reason=None)
    ]
    doc.context_entities = [ContextEntity(name=None, entity_schema="Person", relation=None)]
    doc.media_mentions = [
        MediaMention(
            publication="z" * 5000,
            published_at=None,
            page_number=None,
            headline=None,
            summary=None,
            text_excerpt=None,
            text_availability=NBTextAvailability.UNAVAILABLE,
            identity_state=None,
            issue_urn=None,
            page_urn=None,
            source_url=None,
            access_class=None,
            license_code=None,
            image_document_id=None,
            image_embeddable=False,
            target_query=None,
        )
    ]
    data = render_report_pdf(doc)
    assert data[:4] == b"%PDF"
    assert len(data) > 0


# ---------------------------------------------------------------------------
# Media mentions (AQ-031): HTML/PDF parity and fail-closed text handling
# ---------------------------------------------------------------------------


def _pdf_text_content(data: bytes) -> str:
    """Decompress fpdf2 content streams so PDF text semantics can be asserted.

    fpdf2 escapes ``\\``, ``(`` and ``)`` inside shown strings; those escapes
    are undone here so assertions can use the plain text.
    """
    parts: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        blob = match.group(1)
        try:
            parts.append(zlib.decompress(blob).decode("latin-1"))
        except Exception:
            parts.append(blob.decode("latin-1", errors="replace"))
    content = "\n".join(parts)
    return re.sub(r"\\([()\\])", r"\1", content)


def _full_doc_pdf_text() -> str:
    return _pdf_text_content(render_report_pdf(_full_doc()))


def test_html_renders_media_mentions_with_availability_and_identity() -> None:
    out = render_report_html(_full_doc())
    assert '<section id="medienevnter"><h2>Medienevnter</h2>' in out
    assert "Kontekstutdrag (ikke full artikkeltekst)" in out
    assert "PARTIAL_CONTEXT" in out
    assert "UNAVAILABLE" in out
    assert "Kun metadata (fulltekst ikke tilgjengelig)" in out
    assert "Publikasjon: Hadeland" in out
    assert "Dato: 2007-08-06" in out
    assert "Side: 23" in out
    assert "Identitetsstatus: UNRESOLVED" in out
    assert "ikke identitetsbevis" in out
    assert "Tilgangsklasse: PUBLIC_VIEW_ONLY" in out
    assert "Lisens: CC0" in out
    # Summary counts the mentions too.
    assert "<tr><td>Medienevnter</td><td>2</td></tr>" in out


def test_html_unavailable_mention_shows_metadata_and_link_never_text() -> None:
    out = render_report_html(_full_doc())
    # The direct NB link is rendered (stored source_url wins).
    nb_link = '<a href="https://www.nb.no/items/URN:NBN:no-nb_digavis_romerikesblad_null_rb_20260519">'
    assert nb_link in out
    # The explicit access explanation is shown, never fabricated full text.
    assert "tilgangsbegrenset" in out
    assert "fulltekst kan ikke vises eller kopieres her" in out
    assert _UNAVAILABLE_TEXT not in out


def test_html_media_mention_text_rendered_only_when_available() -> None:
    out = render_report_html(_full_doc())
    # The PARTIAL_CONTEXT excerpt is shown, escaped inside <pre> (the <em>
    # markup in the stored excerpt is escaped like any other text).
    assert f"<pre>… {_ESC_EM}Ola" in out


def test_html_media_mention_escaping() -> None:
    out = render_report_html(_full_doc())
    # Headline and text excerpt are escaped inside the media mention; the
    # raw payload never reaches the HTML output.
    escaped = html.escape(_PAYLOAD, quote=True)
    assert f"Overskrift {escaped}" in out
    assert f"<pre>… {_ESC_EM}Ola {escaped} Nordmann{_ESC_EM_END} …" in out


def test_html_no_img_tags_even_when_image_embeddable() -> None:
    doc = _full_doc()
    doc.media_mentions.append(
        MediaMention(
            publication="Aftenposten",
            published_at=date(1994, 12, 16),
            page_number=72,
            headline=None,
            summary=None,
            text_excerpt=None,
            text_availability=NBTextAvailability.UNAVAILABLE,
            identity_state="UNRESOLVED",
            issue_urn=None,
            page_urn=None,
            source_url=None,
            access_class="PUBLIC_VIEW_ONLY",
            license_code=None,
            image_document_id=UUID(int=43),
            image_embeddable=True,
            target_query="Ola Nordmann",
        )
    )
    out = render_report_html(doc)
    # No image bytes are available to a renderer: never a broken image.
    assert "<img" not in out.lower()
    # The lawfully embeddable image is referenced as a stored document.
    assert f"Artikkelbilde lagret som dokument: {UUID(int=43)}" in out


def test_html_media_mention_without_urn_or_url_stays_linkless() -> None:
    doc = _full_doc()
    doc.media_mentions = [doc.media_mentions[0]]
    doc.media_mentions[0].source_url = None
    doc.media_mentions[0].page_urn = "not-an-urn"
    doc.media_mentions[0].issue_urn = "not-an-urn"
    out = render_report_html(doc)
    # A foreign/missing URN never becomes a fabricated URL.
    assert "https://www.nb.no/items/" not in out
    assert "Åpne kilden" not in out


def test_pdf_renders_same_media_mention_semantics_as_html() -> None:
    pdf_text = _full_doc_pdf_text()
    assert "Medienevnter" in pdf_text
    assert "Overskrift: Overskrift" in pdf_text
    assert "Publikasjon: Hadeland" in pdf_text
    assert "Dato: 2007-08-06" in pdf_text
    assert "Side: 23" in pdf_text
    assert "Kontekstutdrag (ikke full artikkeltekst) (PARTIAL_CONTEXT)" in pdf_text
    assert "Kun metadata (fulltekst ikke tilgjengelig) (UNAVAILABLE)" in pdf_text
    assert "Identitetsstatus: UNRESOLVED" in pdf_text
    nb_url = "URL: https://www.nb.no/items/URN:NBN:no-nb_digavis_romerikesblad_null_rb_20260519"
    assert nb_url in pdf_text
    assert "Side URN: URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23" in pdf_text
    assert "Medienevnter: 2" in pdf_text
    # The PARTIAL_CONTEXT text is rendered in the PDF too. The ellipsis is a
    # latin-1 replacement character in the PDF core font (existing pattern).
    assert "Tekst: ? <em>Ola" in pdf_text


def test_pdf_unavailable_mention_never_fabricates_text() -> None:
    pdf_text = _full_doc_pdf_text()
    assert "tilgangsbegrenset" in pdf_text
    assert _UNAVAILABLE_TEXT not in pdf_text


def test_pdf_and_html_agree_on_media_mention_count() -> None:
    html_out = render_report_html(_full_doc())
    assert "<tr><td>Medienevnter</td><td>2</td></tr>" in html_out
    assert "Medienevnter: 2" in _full_doc_pdf_text()


def _not_selected_doc() -> ReportDocument:
    doc = _empty_doc()
    doc.scope_modules = ["BUSINESS_ROLES"]
    doc.coverage = [
        CoverageEntry(
            module="WEB_MEDIA",
            enabled=False,
            status="NOT_STARTED",
            outcome="IKKE_VALGT",
            stop_reason=None,
            providers=[],
            query_count=0,
            document_count=0,
        )
    ]
    return doc


def test_html_empty_media_when_not_selected_is_not_a_negative_finding() -> None:
    out = render_report_html(_not_selected_doc())
    assert "ikke valgt" in out
    assert "ikke et negativt funn" in out
    assert "Ingen medienevnter." not in out


def test_html_empty_media_when_investigated_keeps_default_text() -> None:
    doc = _empty_doc()
    doc.scope_modules = ["WEB_MEDIA"]
    doc.coverage = [
        CoverageEntry(
            module="WEB_MEDIA",
            enabled=True,
            status="NOT_STARTED",
            outcome="IKKE_UNDERSØKT",
            stop_reason=None,
            providers=[],
            query_count=0,
            document_count=0,
        )
    ]
    assert "Ingen medienevnter." in render_report_html(doc)


def test_pdf_empty_media_when_not_selected_is_not_a_negative_finding() -> None:
    pdf_text = _pdf_text_content(render_report_pdf(_not_selected_doc()))
    assert "ikke valgt" in pdf_text
    assert "ikke et negativt funn" in pdf_text
    assert "Ingen medienevnter." not in pdf_text


def _cited_mention() -> MediaMention:
    return MediaMention(
        publication="Hadeland",
        published_at=date(2007, 8, 6),
        page_number=23,
        headline="Overskrift fra avis",
        summary=None,
        text_excerpt="… <em>Ola Nordmann</em> …",
        text_availability=NBTextAvailability.PARTIAL_CONTEXT,
        identity_state="UNRESOLVED",
        issue_urn="URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806",
        page_urn="URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23",
        source_url=None,
        access_class="PUBLIC_VIEW_ONLY",
        license_code="CC0",
        image_document_id=UUID(int=44),
        image_embeddable=False,
        target_query="Ola Nordmann",
        citations=[
            ReportCitation(
                claim_id=None,
                evidence_id=UUID(int=45),
                document_id=UUID(int=44),
                source_id="nb_catalog",
                excerpt="Kildeutdrag fra crop",
                url="nb:URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23",
                fetched_at=None,
                sha256="ab12cd34" * 8,
            )
        ],
    )


def test_html_media_mention_citation_renders_clickable_provenance() -> None:
    doc = _empty_doc()
    doc.media_mentions = [_cited_mention()]
    out = render_report_html(doc)
    assert '<a href="nb:URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23">' in out
    assert "Kildeutdrag fra crop" in out
    assert "Kilde: nb_catalog" in out
    assert "SHA: ab12cd34" in out


def test_pdf_media_mention_citation_renders_provenance() -> None:
    doc = _empty_doc()
    doc.media_mentions = [_cited_mention()]
    pdf_text = _pdf_text_content(render_report_pdf(doc))
    assert "Kildebelegg: Kildeutdrag fra crop" in pdf_text
    assert "Kilde-URL: nb:URN:NBN:no-nb_digavis_hadeland_null_hadeland_20070806_23" in pdf_text
    assert "Kilde-SHA: ab12cd34" in pdf_text


def test_html_media_mention_without_citations_renders_no_citation_list() -> None:
    doc = _empty_doc()
    mention = _cited_mention()
    mention.citations = []
    doc.media_mentions = [mention]
    out = render_report_html(doc)
    assert '<ul class="citations">' not in out


def test_html_media_mention_anchors_render_in_meta() -> None:
    doc = _empty_doc()
    mention = _cited_mention()
    mention.xywh_anchors = ["xywh=1200,800,400,50", "xywh=1250,860,350,45"]
    doc.media_mentions = [mention]
    out = render_report_html(doc)
    assert "Tekstanker: xywh=1200,800,400,50, xywh=1250,860,350,45" in out


def test_html_media_mention_without_anchors_renders_no_anchor_line() -> None:
    doc = _empty_doc()
    doc.media_mentions = [_cited_mention()]
    assert "Tekstanker" not in render_report_html(doc)


def test_pdf_media_mention_anchors_render_in_meta() -> None:
    doc = _empty_doc()
    mention = _cited_mention()
    mention.xywh_anchors = ["xywh=1200,800,400,50"]
    doc.media_mentions = [mention]
    pdf_text = _pdf_text_content(render_report_pdf(doc))
    assert "Tekstanker: xywh=1200,800,400,50" in pdf_text
