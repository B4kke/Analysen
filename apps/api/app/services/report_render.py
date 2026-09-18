"""Deterministic HTML and PDF report renderers (AQ-027 slice).

Both renderers consume the same ReportDocument and add presentation only:
no new facts, no LLM calls, no clock reads. Displayed timestamps come from
the document itself (generated_at, fetched_at), so identical input documents
produce identical output.
"""

from __future__ import annotations

import html
import json
from typing import Any

from fpdf import FPDF
from fpdf.enums import WrapMode, XPos, YPos

from apps.api.app.domain.models import ClaimStatus
from apps.api.app.domain.report import (
    ContextEntity,
    CoverageEntry,
    ReportCitation,
    ReportDocument,
    ReportFinding,
    UnverifiedLead,
)

_FINDING_GROUP_ORDER: tuple[ClaimStatus, ...] = (
    ClaimStatus.SUPPORTED,
    ClaimStatus.PARTIALLY_SUPPORTED,
    ClaimStatus.CONTRADICTED,
    ClaimStatus.INSUFFICIENT_EVIDENCE,
    ClaimStatus.UNVERIFIED_LEAD,
)

_STATUS_LABEL_NB: dict[ClaimStatus, str] = {
    ClaimStatus.SUPPORTED: "Understøttet",
    ClaimStatus.PARTIALLY_SUPPORTED: "Delvis understøttet",
    ClaimStatus.CONTRADICTED: "Motsagt",
    ClaimStatus.INSUFFICIENT_EVIDENCE: "Utilstrekkelig belegg",
    ClaimStatus.UNVERIFIED_LEAD: "Uverifisert spor",
}

_CONTEXT_DISCLAIMER = "Enhetene nedenfor er kun nevnt som kontekst og er ikke bakgrunnssjekket."

_CSS = (
    "body{font-family:sans-serif;max-width:70em;margin:2em auto;padding:0 1em;"
    "color:#111;line-height:1.5}"
    "table{border-collapse:collapse;width:100%;margin:1em 0}"
    "th,td{border:1px solid #999;padding:0.4em;text-align:left;vertical-align:top}"
    "th{background:#eee}"
    ".badge{display:inline-block;padding:0.1em 0.5em;border-radius:0.5em;"
    "background:#eee;border:1px solid #999;font-size:0.9em}"
    ".finding{border:1px solid #ccc;margin:1em 0;padding:0.5em 1em}"
    "pre{background:#f6f6f6;padding:0.5em;white-space:pre-wrap;word-wrap:break-word}"
    ".cite-meta{color:#555;font-size:0.9em}"
)


def _esc(value: Any | None) -> str:
    """Escape user/model-derived text for HTML; None renders as dash."""
    if value is None:
        return "–"
    return html.escape(str(value), quote=True)


def _value_json(value: Any) -> str:
    """Render a finding value as JSON text; never raises on odd values."""
    if value is None:
        return "–"
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _citation_html(citation: ReportCitation) -> str:
    meta: list[str] = []
    if citation.source_id:
        meta.append(f"Kilde: {_esc(citation.source_id)}")
    if citation.sha256:
        meta.append(f"SHA: {_esc(citation.sha256[:8])}")
    if citation.fetched_at:
        meta.append(f"Hentet: {_esc(citation.fetched_at.isoformat())}")
    meta_html = f'<div class="cite-meta">{" · ".join(meta)}</div>' if meta else ""
    if citation.url:
        link_text = citation.excerpt or citation.url
        href = html.escape(citation.url, quote=True)
        return (
            f'<li class="citation"><a href="{href}">'
            f"{html.escape(link_text, quote=True)}</a>{meta_html}</li>"
        )
    text = citation.excerpt or citation.source_id or "Kilde uten URL"
    return f'<li class="citation"><span>{html.escape(text, quote=True)}</span>{meta_html}</li>'


def _finding_html(finding: ReportFinding) -> str:
    label = _STATUS_LABEL_NB.get(finding.status, finding.status.value)
    subject = f' <span class="subject">{_esc(finding.subject_name)}</span>'
    cites = "".join(_citation_html(c) for c in finding.citations or [])
    cites_html = f'<ul class="citations">{cites}</ul>' if cites else "<p>Ingen kilder.</p>"
    return (
        '<article class="finding">'
        f"<h4>{_esc(finding.predicate)}</h4>"
        f'<p><span class="badge">{_esc(label)} ({_esc(finding.status.value)})</span>'
        f"{subject}</p>"
        f"<pre>{_esc(_value_json(finding.value))}</pre>"
        f"{cites_html}</article>"
    )


def _lead_html(lead: UnverifiedLead) -> str:
    parts = ['<li class="lead">']
    if lead.predicate:
        parts.append(f"<strong>{_esc(lead.predicate)}</strong>")
    parts.append(f"<div>Informasjonsbehov: {_esc(lead.information_need)}</div>")
    if lead.reason:
        parts.append(f"<div>Begrunnelse: {_esc(lead.reason)}</div>")
    parts.append("</li>")
    return "".join(parts)


def _context_html(entity: ContextEntity) -> str:
    name = _esc(entity.name)
    return (
        f"<li>{name} ({_esc(entity.entity_schema)})"
        + (f" – {_esc(entity.relation)}" if entity.relation else "")
        + "</li>"
    )


def _coverage_row_html(entry: CoverageEntry) -> str:
    providers = ", ".join(entry.providers) if entry.providers else "–"
    stop = entry.stop_reason if entry.stop_reason else "–"
    return (
        "<tr>"
        f"<td>{_esc(entry.module)}</td>"
        f"<td>{'Ja' if entry.enabled else 'Nei'}</td>"
        f"<td>{_esc(entry.status)}</td>"
        f"<td>{_esc(entry.outcome)}</td>"
        f"<td>{_esc(providers)}</td>"
        f"<td>{_esc(entry.query_count)}</td>"
        f"<td>{_esc(entry.document_count)}</td>"
        f"<td>{_esc(stop)}</td>"
        "</tr>"
    )


def render_report_html(doc: ReportDocument) -> str:
    """Render a self-contained Norwegian HTML page for a ReportDocument."""
    counts = {status: 0 for status in _FINDING_GROUP_ORDER}
    for finding in doc.findings or []:
        if finding.status in counts:
            counts[finding.status] += 1
    total_findings = sum(counts.values())
    coverage = doc.coverage or []
    enabled = sum(1 for entry in coverage if entry.enabled)
    queries = sum(entry.query_count for entry in coverage)
    documents = sum(entry.document_count for entry in coverage)

    summary_rows = "".join(
        f"<tr><td>{_esc(_STATUS_LABEL_NB[s])} ({_esc(s.value)})</td><td>{counts[s]}</td></tr>"
        for s in _FINDING_GROUP_ORDER
    )
    summary = (
        "<table><thead><tr><th>Status</th><th>Antall</th></tr></thead>"
        f"<tbody>{summary_rows}"
        f"<tr><td>Totalt antall funn</td><td>{total_findings}</td></tr>"
        f"<tr><td>Dekningsmoduler (aktiverte/total)</td><td>{enabled}/{len(coverage)}</td></tr>"
        f"<tr><td>Spørringer totalt</td><td>{queries}</td></tr>"
        f"<tr><td>Dokumenter totalt</td><td>{documents}</td></tr>"
        f"<tr><td>Uavklarte spor</td><td>{len(doc.unverified_leads or [])}</td></tr>"
        f"<tr><td>Kontekstenheter</td><td>{len(doc.context_entities or [])}</td></tr>"
        "</tbody></table>"
    )

    groups: list[str] = []
    for status in _FINDING_GROUP_ORDER:
        items = [f for f in doc.findings or [] if f.status == status]
        if not items:
            continue
        label = _STATUS_LABEL_NB.get(status, status.value)
        body = "".join(_finding_html(f) for f in items)
        groups.append(f"<h3>{_esc(label)} ({_esc(status.value)})</h3>{body}")
    findings_html = "".join(groups) if groups else "<p>Ingen funn.</p>"

    leads = doc.unverified_leads or []
    leads_html = (
        f"<ul>{''.join(_lead_html(lead) for lead in leads)}</ul>"
        if leads
        else "<p>Ingen uavklarte spor.</p>"
    )

    entities = doc.context_entities or []
    context_html = (
        f"<p>{_esc(_CONTEXT_DISCLAIMER)}</p><ul>{''.join(_context_html(e) for e in entities)}</ul>"
        if entities
        else f"<p>{_esc(_CONTEXT_DISCLAIMER)}</p><p>Ingen kontekstopplysninger.</p>"
    )

    coverage_html = (
        "<table><thead><tr><th>Modul</th><th>Aktivert</th><th>Status</th>"
        "<th>Utfall</th><th>Kilder</th><th>Spørringer</th>"
        "<th>Dokumenter</th><th>Stopårsak</th></tr></thead>"
        f"<tbody>{''.join(_coverage_row_html(e) for e in coverage)}</tbody></table>"
        if coverage
        else "<p>Ingen dekningsdata.</p>"
    )

    scope_modules = ", ".join(doc.scope_modules) if doc.scope_modules else "–"
    return (
        "<!DOCTYPE html>"
        '<html lang="nb">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>Rapport: {_esc(doc.target_name)}</title>"
        f"<style>{_CSS}</style>"
        "</head>"
        "<body>"
        "<header>"
        f"<h1>Rapport: {_esc(doc.target_name)}</h1>"
        f"<p>Type: {_esc(doc.target_type)}</p>"
        f"<p>Formål: {_esc(doc.purpose)}</p>"
        f"<p>Generert: {_esc(doc.generated_at.isoformat())}</p>"
        f"<p>Undersøkelse: {_esc(doc.investigation_id)}</p>"
        f"<p>Ekspansjonspolicy: {_esc(doc.expansion_policy)} "
        f"(dybde {doc.max_relation_depth})</p>"
        f"<p>Moduler: {_esc(scope_modules)}</p>"
        "</header>"
        '<section id="sammendrag"><h2>Sammendrag</h2>'
        f"{summary}</section>"
        '<section id="funn"><h2>Vesentlige funn</h2>'
        f"{findings_html}</section>"
        '<section id="spor"><h2>Uavklarte spor</h2>'
        f"{leads_html}</section>"
        '<section id="kontekst"><h2>Kontekst</h2>'
        f"{context_html}</section>"
        '<section id="metode"><h2>Metode og dekning</h2>'
        f"{coverage_html}</section>"
        "</body>"
        "</html>"
    )


def _pdf_text(value: Any | None) -> str:
    """Render text with the PDF core font; never raises on None/unicode."""
    if value is None:
        return "-"
    text = value if isinstance(value, str) else str(value)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_section(pdf: FPDF, title: str) -> None:
    pdf.set_font("helvetica", "B", 12)
    pdf.multi_cell(
        w=0,
        text=_pdf_text(title),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        wrapmode=WrapMode.CHAR,
    )


def _pdf_body(pdf: FPDF, text: Any | None) -> None:
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(
        w=0,
        text=_pdf_text(text),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        wrapmode=WrapMode.CHAR,
    )


def render_report_pdf(doc: ReportDocument) -> bytes:
    """Render the same ReportDocument sections as deterministic PDF bytes."""
    pdf = FPDF()
    pdf.set_creation_date(doc.generated_at)
    pdf.set_creator("Analysen")
    pdf.set_producer("Analysen")
    pdf.set_title(f"Rapport: {doc.target_name}")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.multi_cell(
        w=0,
        text=_pdf_text(f"Rapport: {doc.target_name}"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        wrapmode=WrapMode.CHAR,
    )
    for line in (
        f"Type: {doc.target_type}",
        f"Formål: {doc.purpose}",
        f"Generert: {doc.generated_at.isoformat()}",
        f"Undersøkelse: {doc.investigation_id}",
        f"Ekspansjonspolicy: {doc.expansion_policy} (dybde {doc.max_relation_depth})",
        f"Moduler: {', '.join(doc.scope_modules) if doc.scope_modules else '-'}",
    ):
        _pdf_body(pdf, line)

    counts = {status: 0 for status in _FINDING_GROUP_ORDER}
    for finding in doc.findings or []:
        if finding.status in counts:
            counts[finding.status] += 1
    coverage = doc.coverage or []
    _pdf_section(pdf, "Sammendrag")
    for status in _FINDING_GROUP_ORDER:
        _pdf_body(pdf, f"{_STATUS_LABEL_NB[status]} ({status.value}): {counts[status]}")
    _pdf_body(pdf, f"Totalt antall funn: {sum(counts.values())}")
    _pdf_body(
        pdf,
        f"Dekningsmoduler (aktiverte/total): "
        f"{sum(1 for e in coverage if e.enabled)}/{len(coverage)}",
    )
    _pdf_body(pdf, f"Spørringer totalt: {sum(e.query_count for e in coverage)}")
    _pdf_body(pdf, f"Dokumenter totalt: {sum(e.document_count for e in coverage)}")
    _pdf_body(pdf, f"Uavklarte spor: {len(doc.unverified_leads or [])}")
    _pdf_body(pdf, f"Kontekstenheter: {len(doc.context_entities or [])}")

    _pdf_section(pdf, "Vesentlige funn")
    findings = doc.findings or []
    if not findings:
        _pdf_body(pdf, "Ingen funn.")
    for status in _FINDING_GROUP_ORDER:
        for finding in [f for f in findings if f.status == status]:
            _pdf_section(pdf, f"{_STATUS_LABEL_NB[status]} ({status.value})")
            _pdf_body(pdf, f"Påstand: {finding.predicate}")
            _pdf_body(pdf, f"Verdi: {_value_json(finding.value)}")
            _pdf_body(pdf, f"Subjekt: {finding.subject_name}")
            citations = finding.citations or []
            if not citations:
                _pdf_body(pdf, "Ingen kilder.")
            for citation in citations:
                _pdf_body(pdf, f"Kilde: {citation.excerpt or citation.source_id or '-'}")
                if citation.url:
                    _pdf_body(pdf, f"URL: {citation.url}")
                if citation.sha256:
                    _pdf_body(pdf, f"SHA: {citation.sha256[:8]}")
                if citation.fetched_at:
                    _pdf_body(pdf, f"Hentet: {citation.fetched_at.isoformat()}")

    _pdf_section(pdf, "Uavklarte spor")
    leads = doc.unverified_leads or []
    if not leads:
        _pdf_body(pdf, "Ingen uavklarte spor.")
    for lead in leads:
        if lead.predicate:
            _pdf_body(pdf, f"Spor: {lead.predicate}")
        _pdf_body(pdf, f"Informasjonsbehov: {lead.information_need}")
        if lead.reason:
            _pdf_body(pdf, f"Begrunnelse: {lead.reason}")

    _pdf_section(pdf, "Kontekst")
    _pdf_body(pdf, _CONTEXT_DISCLAIMER)
    entities = doc.context_entities or []
    if not entities:
        _pdf_body(pdf, "Ingen kontekstopplysninger.")
    for entity in entities:
        line = f"{entity.name or '-'} ({entity.entity_schema})"
        if entity.relation:
            line += f" - {entity.relation}"
        _pdf_body(pdf, line)

    _pdf_section(pdf, "Metode og dekning")
    if not coverage:
        _pdf_body(pdf, "Ingen dekningsdata.")
    else:
        pdf.set_font("helvetica", "", 10)
        with pdf.table(first_row_as_headings=True) as table:
            header = table.row()
            for column in (
                "Modul",
                "Aktivert",
                "Status",
                "Utfall",
                "Kilder",
                "Sporringer",
                "Dokumenter",
                "Stopp",
            ):
                header.cell(_pdf_text(column))
            for entry in coverage:
                row = table.row()
                row.cell(_pdf_text(entry.module))
                row.cell(_pdf_text("Ja" if entry.enabled else "Nei"))
                row.cell(_pdf_text(entry.status))
                row.cell(_pdf_text(entry.outcome))
                row.cell(_pdf_text(", ".join(entry.providers) if entry.providers else "-"))
                row.cell(_pdf_text(entry.query_count))
                row.cell(_pdf_text(entry.document_count))
                row.cell(_pdf_text(entry.stop_reason))

    return bytes(pdf.output())
