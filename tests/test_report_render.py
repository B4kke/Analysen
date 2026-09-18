"""Renderer tests for HTML/PDF report output (AQ-027 slice).

Pure tests: ReportDocument fixtures are built inline, no database needed.
"""

from datetime import datetime
from uuid import UUID

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.domain.report import (
    ContextEntity,
    CoverageEntry,
    ReportCitation,
    ReportDocument,
    ReportFinding,
    UnverifiedLead,
)
from apps.api.app.services.report_render import render_report_html, render_report_pdf

_PAYLOAD = '<script>alert("x")</script>'
_GENERATED = datetime(2026, 1, 15, 12, 0, 0)


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
    # Four URL citations in the fixture (one finding has no citations,
    # one citation has no URL), no other links on the page.
    assert out.count("<a ") == 4
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
    data = render_report_pdf(doc)
    assert data[:4] == b"%PDF"
    assert len(data) > 0
