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

# Shared vocabulary for media mentions (AQ-031): both the HTML and the PDF
# renderer use these labels so the two outputs describe the same semantics.
# Concordance text is labeled PARTIAL_CONTEXT and is never "full artikkeltekst".
_TEXT_AVAILABILITY_LABEL_NB: dict[NBTextAvailability, str] = {
    NBTextAvailability.FULL: "Full artikkeltekst",
    NBTextAvailability.PARTIAL_CONTEXT: "Kontekstutdrag (ikke full artikkeltekst)",
    NBTextAvailability.UNAVAILABLE: "Kun metadata (fulltekst ikke tilgjengelig)",
}

_MEDIA_IDENTITY_NOTE = (
    "Medienevnter er ikke identitetsbevis: navntreff i aviser er nevnelser, "
    "og identitetsstatus er oppgitt per nevning."
)

# Empty-state note when the media module was never selected (AQ-031/Norwegian
# report semantics): absence of mentions must never read as a negative
# finding. Used only when the document provably deselects WEB_MEDIA; unknown
# or investigated-but-empty documents keep the existing "Ingen medienevnter."
# text so empty reports stay stable.
_MEDIA_NOT_SELECTED_NOTE = (
    "Mediemodulen (WEB_MEDIA) er ikke valgt for denne undersøkelsen. "
    "Fravær av medienevnter er ikke et negativt funn."
)

_MEDIA_ACCESS_NOTE_UNAVAILABLE = (
    "Innholdet er tilgangsbegrenset: rapporten viser kun metadata og lenke; "
    "fulltekst kan ikke vises eller kopieres her. Åpne kilden hos "
    "Nasjonalbiblioteket for videre lesing."
)

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


def _web_media_not_selected(doc: ReportDocument) -> bool:
    """True only when the document provably deselects the WEB_MEDIA module.

    Coverage wins over scope: an explicit disabled/IKKE_VALGT WEB_MEDIA entry
    means not selected even if scope lists differ. An enabled WEB_MEDIA entry
    means selected. With no WEB_MEDIA coverage entry, a non-empty
    ``scope_modules`` without WEB_MEDIA means not selected. Empty scope with
    no coverage is unknown (conservative False) so bare empty reports keep
    their existing text.
    """
    for entry in doc.coverage or []:
        if entry.module == "WEB_MEDIA":
            return not entry.enabled or entry.outcome == "IKKE_VALGT"
    if doc.scope_modules:
        return "WEB_MEDIA" not in doc.scope_modules
    return False


def _nb_item_url(urn: str | None) -> str | None:
    """Direct NB item URL for a URN:NBN identifier, or None.

    Only URN-shaped identifiers are turned into links; a missing or foreign
    URN never becomes a fabricated URL.
    """
    if not urn or not urn.upper().startswith("URN:NBN:"):
        return None
    return f"https://www.nb.no/items/{urn}"


def _media_mention_link(mention: MediaMention) -> tuple[str, str] | None:
    """Direct source link for a mention: (url, link text) or None.

    A stored ``source_url`` wins; otherwise the NB item URL is built from
    the page or issue URN. Mentions without any locator stay linkless
    instead of getting an invented URL.
    """
    if mention.source_url:
        return mention.source_url, "Åpne kilden"
    urn_url = _nb_item_url(mention.page_urn) or _nb_item_url(mention.issue_urn)
    if urn_url:
        return urn_url, "Åpne kilden hos Nasjonalbiblioteket"
    return None


def _media_mention_meta(mention: MediaMention) -> list[str]:
    """Shared metadata lines for HTML and PDF media mention rendering."""
    parts: list[str] = []
    if mention.publication:
        parts.append(f"Publikasjon: {mention.publication}")
    if mention.published_at:
        parts.append(f"Dato: {mention.published_at.isoformat()}")
    if mention.page_number is not None:
        parts.append(f"Side: {mention.page_number}")
    if mention.access_class:
        parts.append(f"Tilgangsklasse: {mention.access_class}")
    if mention.license_code:
        parts.append(f"Lisens: {mention.license_code}")
    if mention.identity_state:
        parts.append(f"Identitetsstatus: {mention.identity_state}")
    if mention.issue_urn:
        parts.append(f"Issue URN: {mention.issue_urn}")
    if mention.page_urn:
        parts.append(f"Side URN: {mention.page_urn}")
    if mention.xywh_anchors:
        parts.append(f"Tekstanker: {', '.join(mention.xywh_anchors)}")
    # The page image itself is never rendered (no image bytes are available
    # here, so an <img>/crop could only ever be broken): a lawfully embeddable
    # derived image is referenced as a stored document instead.
    if mention.image_embeddable and mention.image_document_id:
        parts.append(f"Artikkelbilde lagret som dokument: {mention.image_document_id}")
    return parts


def _media_mention_text(mention: MediaMention) -> str | None:
    """Shared text selection for HTML and PDF: lawful stored text, or None.

    ``UNAVAILABLE`` mentions return None: those rows show metadata, the
    explicit access explanation and the direct NB link only — never text
    that would read as available full article text. Concordance/context
    excerpts stay labeled ``PARTIAL_CONTEXT``, never "full artikkeltekst".
    """
    if mention.text_availability is NBTextAvailability.UNAVAILABLE:
        return None
    return mention.text_excerpt or mention.summary or None


def _media_mention_html(mention: MediaMention) -> str:
    """One media mention: metadata, lawful text and direct source link.

    Text is only rendered for ``FULL`` and ``PARTIAL_CONTEXT``; an
    ``UNAVAILABLE`` mention shows metadata, the explicit access explanation
    and the direct NB link — never fabricated full text or a broken image.
    """
    label = _TEXT_AVAILABILITY_LABEL_NB.get(
        mention.text_availability, mention.text_availability.value
    )
    parts = ['<article class="media-mention">']
    if mention.headline:
        parts.append(f"<h4>{_esc(mention.headline)}</h4>")
    parts.append(
        f'<p><span class="badge">{_esc(label)} '
        f"({_esc(mention.text_availability.value)})</span></p>"
    )
    meta = _media_mention_meta(mention)
    if meta:
        parts.append(f'<div class="cite-meta">{" · ".join(_esc(part) for part in meta)}</div>')
    if mention.text_availability is NBTextAvailability.UNAVAILABLE:
        parts.append(f'<p class="cite-meta">{_esc(_MEDIA_ACCESS_NOTE_UNAVAILABLE)}</p>')
    else:
        shown = _media_mention_text(mention)
        parts.append(
            f"<pre>{_esc(shown)}</pre>" if shown else "<p>Ingen lagret tekstutdrag.</p>"
        )
    link = _media_mention_link(mention)
    if link:
        href = html.escape(link[0], quote=True)
        parts.append(f'<p><a href="{href}">{html.escape(link[1], quote=True)}</a></p>')
    cites = "".join(_citation_html(c) for c in mention.citations or [])
    if cites:
        parts.append(f'<ul class="citations">{cites}</ul>')
    parts.append("</article>")
    return "".join(parts)


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
        f"<tr><td>Medienevnter</td><td>{len(doc.media_mentions or [])}</td></tr>"
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

    mentions = doc.media_mentions or []
    if not mentions:
        if _web_media_not_selected(doc):
            mentions_html = (
                f"<p>{_esc(_MEDIA_IDENTITY_NOTE)}</p>"
                f"<p>{_esc(_MEDIA_NOT_SELECTED_NOTE)}</p>"
            )
        else:
            mentions_html = (
                f"<p>{_esc(_MEDIA_IDENTITY_NOTE)}</p><p>Ingen medienevnter.</p>"
            )
    else:
        mentions_html = (
            f"<p>{_esc(_MEDIA_IDENTITY_NOTE)}</p>"
            f"{''.join(_media_mention_html(mention) for mention in mentions)}"
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
        '<section id="medienevnter"><h2>Medienevnter</h2>'
        f"{mentions_html}</section>"
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


def _pdf_media_mention(pdf: FPDF, mention: MediaMention) -> None:
    """One media mention in the PDF: same semantics as the HTML renderer.

    Text is only rendered for ``FULL`` and ``PARTIAL_CONTEXT``; an
    ``UNAVAILABLE`` mention shows metadata, the explicit access explanation
    and the direct NB link — never fabricated full text or a broken image.
    """
    label = _TEXT_AVAILABILITY_LABEL_NB.get(
        mention.text_availability, mention.text_availability.value
    )
    _pdf_section(pdf, f"{label} ({mention.text_availability.value})")
    if mention.headline:
        _pdf_body(pdf, f"Overskrift: {mention.headline}")
    for part in _media_mention_meta(mention):
        _pdf_body(pdf, part)
    if mention.text_availability is NBTextAvailability.UNAVAILABLE:
        _pdf_body(pdf, _MEDIA_ACCESS_NOTE_UNAVAILABLE)
    else:
        shown = _media_mention_text(mention)
        _pdf_body(pdf, f"Tekst: {shown}" if shown else "Ingen lagret tekstutdrag.")
    link = _media_mention_link(mention)
    if link:
        _pdf_body(pdf, f"URL: {link[0]}")
    for citation in mention.citations or []:
        _pdf_body(pdf, f"Kildebelegg: {citation.excerpt or citation.source_id or '-'}")
        if citation.url:
            _pdf_body(pdf, f"Kilde-URL: {citation.url}")
        if citation.sha256:
            _pdf_body(pdf, f"Kilde-SHA: {citation.sha256[:8]}")


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
    _pdf_body(pdf, f"Medienevnter: {len(doc.media_mentions or [])}")

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

    _pdf_section(pdf, "Medienevnter")
    mentions = doc.media_mentions or []
    if not mentions:
        _pdf_body(pdf, _MEDIA_IDENTITY_NOTE)
        if _web_media_not_selected(doc):
            _pdf_body(pdf, _MEDIA_NOT_SELECTED_NOTE)
        else:
            _pdf_body(pdf, "Ingen medienevnter.")
    for mention in mentions:
        _pdf_media_mention(pdf, mention)

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
