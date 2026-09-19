"use client";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ContextEntity, CoverageEntry, MediaMention, ReportCitation, ReportDocument, ReportFinding, UnverifiedLead, formatApiDetail, formatDate, nbItemUrl, safeHttpUrl } from "../../../types";

type Coverage = {
  providers: string[];
  query_classes: string[];
  query_count: number;
  document_count: number;
  gaps: string[];
  unavailable_sources: string[];
  endpoints?: string[];
  candidate_count?: number;
  located_count?: number;
  concordance_count?: number;
  fulltext_count?: number;
  restricted_count?: number;
  fetched_count?: number;
  time_from?: string | null;
  time_to?: string | null;
};
type SectionEntry = { module: string; status: string; stop_reason: string | null; coverage: Coverage };
type Sections = Record<string, SectionEntry[]>;
const SECTION_ORDER = ["Undersøkt", "Undersøkt med mangler", "Ikke undersøkt", "Utilgjengelig", "Ikke valgt"];
const SECTION_HELP: Record<string, string> = {
  "Undersøkt": "Moduler med fullført dekning.",
  "Undersøkt med mangler": "Moduler med kjent ufullstendig dekning og stoppårsak.",
  "Ikke undersøkt": "Valgte moduler der research ikke er startet.",
  "Utilgjengelig": "Moduler der kilder var utilgjengelige eller blokkerte.",
  "Ikke valgt": "Områder du ikke valgte. Fravær av funn her er ikke et negativt funn.",
};
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TEXT_AVAILABILITY_LABEL: Record<string, string> = {
  FULL: "Full artikkeltekst",
  PARTIAL_CONTEXT: "Kontekstutdrag (ikke full artikkeltekst)",
  UNAVAILABLE: "Kun metadata (fulltekst ikke tilgjengelig)",
};
const IDENTITY_LABEL: Record<string, string> = {
  MATCH: "Identitet bekreftet",
  PROBABLE_MATCH: "Sannsynlig identitet",
  UNRESOLVED: "Identitet uavklart",
  NOT_MATCH: "Ikke samme enhet",
};
const ACCESS_NOTE_UNAVAILABLE = "Innholdet er tilgangsbegrenset: rapporten viser kun metadata og lenke; fulltekst kan ikke vises eller kopieres her. Åpne kilden hos Nasjonalbiblioteket for videre lesing.";

function availabilityLabel(mention: MediaMention): string {
  return TEXT_AVAILABILITY_LABEL[mention.text_availability] ?? mention.text_availability;
}
function identityLabel(mention: MediaMention): string {
  return mention.identity_state ? (IDENTITY_LABEL[mention.identity_state] ?? mention.identity_state) : "Ikke oppgitt";
}

function coverageDetail(coverage: Coverage): string | null {
  const parts: string[] = [];
  const num = (value: number | undefined) => typeof value === "number" && value > 0;
  if (num(coverage.candidate_count)) parts.push(`Kandidater: ${coverage.candidate_count}`);
  if (num(coverage.located_count)) parts.push(`Lokalisert: ${coverage.located_count}`);
  if (num(coverage.concordance_count)) parts.push(`Konkordanser: ${coverage.concordance_count}`);
  if (num(coverage.fulltext_count)) parts.push(`Fulltekst: ${coverage.fulltext_count}`);
  if (num(coverage.restricted_count)) parts.push(`Begrenset: ${coverage.restricted_count}`);
  if (num(coverage.fetched_count)) parts.push(`Hentet: ${coverage.fetched_count}`);
  if ((coverage.endpoints ?? []).length > 0) parts.push(`Endepunkt: ${coverage.endpoints!.join(", ")}`);
  if ((coverage.query_classes ?? []).length > 0) parts.push(`Spørringsklasse: ${coverage.query_classes!.join(", ")}`);
  if (coverage.time_from || coverage.time_to) parts.push(`Tidsrom: ${coverage.time_from ?? "–"}–${coverage.time_to ?? "–"}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function MediaMentionCard({ mention }: { mention: MediaMention }) {
  const unavailable = mention.text_availability === "UNAVAILABLE";
  const storedText = mention.text_excerpt || mention.summary;
  const linkUrl = safeHttpUrl(mention.source_url) ?? safeHttpUrl(nbItemUrl(mention.page_urn)) ?? safeHttpUrl(nbItemUrl(mention.issue_urn));
  const linkText = mention.source_url ? "Åpne kilden" : "Åpne kilden hos Nasjonalbiblioteket";
  const citation = (mention.citations ?? [])[0];
  const citationUrl = citation ? safeHttpUrl(citation.url) : null;
  return (
    <article className="coverage-row" aria-label="Medienevnt">
      <div>
        <strong>{mention.headline || mention.publication || "Medienevnt"}</strong>
        <span>{availabilityLabel(mention)} · Identitetsstatus: {identityLabel(mention)}</span>
        <span>Publikasjon: {mention.publication ?? "–"} · Dato: {mention.published_at ?? "–"}{mention.page_number != null ? ` · Side: ${mention.page_number}` : ""}{mention.access_class ? ` · Tilgangsklasse: ${mention.access_class}` : ""}{mention.license_code ? ` · Lisens: ${mention.license_code}` : ""}</span>
        {mention.issue_urn ? <span>Issue URN: {mention.issue_urn}</span> : null}
        {mention.page_urn ? <span>Side URN: {mention.page_urn}</span> : null}
        {(mention.xywh_anchors ?? []).length > 0 ? <span>Tekstanker: {mention.xywh_anchors.join(", ")}</span> : null}
        {mention.image_embeddable && mention.image_document_id ? <span>Artikkelbilde lagret som dokument: {mention.image_document_id} (vises ikke direkte i rapporten)</span> : null}
        {!unavailable && storedText ? <span className="mention-text">{storedText}</span> : null}
        {!unavailable && !storedText ? <span className="mention-note">Ingen lagret tekstutdrag.</span> : null}
        {unavailable ? <span className="mention-note">{ACCESS_NOTE_UNAVAILABLE}</span> : null}
        {citation && citationUrl ? <span>Kildebelegg: <a href={citationUrl}>{citation.excerpt ?? citationUrl}</a>{citation.sha256 ? ` · SHA: ${citation.sha256.slice(0, 8)}` : ""}</span> : null}
        {linkUrl ? <a href={linkUrl}>{linkText}</a> : null}
      </div>
      <span className="status-dot" role="img" aria-label={availabilityLabel(mention)} />
    </article>
  );
}

const FINDING_STATUS_LABEL: Record<string, string> = {
  SUPPORTED: "Understøttet",
  PARTIALLY_SUPPORTED: "Delvis understøttet",
  CONTRADICTED: "Motsagt",
  INSUFFICIENT_EVIDENCE: "Utilstrekkelig belegg",
  UNVERIFIED_LEAD: "Uverifisert spor",
};

function formatFindingValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? "–";
  } catch {
    return String(value);
  }
}

function FindingCard({ finding }: { finding: ReportFinding }) {
  const statusLabel = FINDING_STATUS_LABEL[finding.status] ?? finding.status;
  const citations = finding.citations ?? [];
  return (
    <article className="coverage-row" aria-label="Funn">
      <div>
        <strong>{finding.predicate}</strong>
        <span>Status: {statusLabel} ({finding.status}){finding.subject_name ? ` · Gjelder: ${finding.subject_name}` : ""}</span>
        <span className="mention-text">{formatFindingValue(finding.value)}</span>
        {citations.length === 0 ? <span className="mention-note">Ingen lagrede kilder til dette funnet.</span> : citations.map((citation: ReportCitation, index: number) => {
          const citationUrl = safeHttpUrl(citation.url);
          const linkText = citation.excerpt ?? citation.url ?? "Kilde uten URL";
          return <span key={`${citation.evidence_id || citation.document_id || "kilde"}-${index}`}>Kildebelegg: {citationUrl ? <a href={citationUrl}>{linkText}</a> : linkText}{citation.sha256 ? ` · SHA: ${citation.sha256.slice(0, 8)}` : ""}{citation.fetched_at ? ` · Hentet: ${formatDate(citation.fetched_at)}` : ""}</span>;
        })}
      </div>
      <span className="status-dot" role="img" aria-label={statusLabel} />
    </article>
  );
}

function LeadRow({ lead }: { lead: UnverifiedLead }) {
  return (
    <div className="coverage-row">
      <div>
        <strong>{lead.predicate ?? "Uavklart spor"}</strong>
        <span>Informasjonsbehov: {lead.information_need}</span>
        {lead.reason ? <span>Begrunnelse: {lead.reason}</span> : null}
      </div>
      <span className="status-dot" role="img" aria-label="Uavklart spor" />
    </div>
  );
}

function ContextRow({ entity }: { entity: ContextEntity }) {
  return (
    <div className="coverage-row">
      <div>
        <strong>{entity.name ?? "Navn ikke oppgitt"}</strong>
        <span>Type: {entity.entity_schema}{entity.relation ? ` · Relasjon: ${entity.relation}` : ""}</span>
      </div>
      <span className="status-dot" role="img" aria-label="Kontekst" />
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [sections, setSections] = useState<Sections | null>(null);
  const [report, setReport] = useState<ReportDocument | null>(null);
  const [reportError, setReportError] = useState("");
  const [error, setError] = useState("");
  const loadSections = useCallback((signal?: AbortSignal) => { setError(""); fetch(`${API_BASE}/api/v1/investigations/${id}/report/sections`, { signal }).then(async (response) => { const payload = await response.json().catch(() => null); if (!response.ok) throw new Error(formatApiDetail(payload?.detail) || "Fant ikke rapporten."); setSections(payload); }).catch((caught) => { if (signal?.aborted) return; setError(caught instanceof Error ? caught.message : "Kunne ikke laste rapporten."); }); }, [id]);
  const loadReport = useCallback((signal?: AbortSignal) => { setReportError(""); fetch(`${API_BASE}/api/v1/investigations/${id}/report.json`, { signal }).then(async (response) => { const payload = await response.json().catch(() => null); if (!response.ok) throw new Error(formatApiDetail(payload?.detail) || "Fant ikke full rapporten."); setReport(payload); }).catch((caught) => { if (signal?.aborted) return; setReportError(caught instanceof Error ? caught.message : "Kunne ikke laste full rapporten."); }); }, [id]);
  useEffect(() => { const controller = new AbortController(); loadSections(controller.signal); loadReport(controller.signal); return () => controller.abort(); }, [loadSections, loadReport]);
  const mentions = report?.media_mentions ?? [];
  const findings = report?.findings ?? [];
  const leads = report?.unverified_leads ?? [];
  const contextEntities = report?.context_entities ?? [];
  // Norwegian report semantics (media section only): an empty mention list
  // must not read as a negative finding when WEB_MEDIA was never selected.
  // Coverage from /report/sections wins; the full-report coverage is the
  // fallback; a non-empty scope without WEB_MEDIA is the last signal.
  const webMediaNotSelected = (() => {
    const notSelected = sections?.["Ikke valgt"] ?? [];
    if (notSelected.some((item) => item.module === "WEB_MEDIA")) return true;
    const entry = report?.coverage?.find((item) => item.module === "WEB_MEDIA");
    if (entry) return !entry.enabled || entry.outcome === "IKKE_VALGT";
    if (report && report.scope_modules.length > 0) return !report.scope_modules.includes("WEB_MEDIA");
    return false;
  })();
  if (error) return <main className="detail-shell"><a className="back-link" href={`/investigations/${id}`}>← Tilbake til undersøkelsen</a><div className="state-card"><h1>Kunne ikke åpne rapporten</h1><p>{error}</p></div></main>;
  if (!sections) return <main className="detail-shell"><p className="loading-state">Laster rapport …</p></main>;
  return <main className="detail-shell"><header className="detail-top"><a className="brand" href="/"><span className="brand-mark">A</span> ANALYSEN</a><a className="back-link" href={`/investigations/${id}`}>← Tilbake til undersøkelsen</a></header><div className="detail-heading"><p className="eyebrow">RAPPORT · DEKNING OG MEDIENEVNTER</p><h1>Dekningsrapport</h1><p>Hva som er undersøkt, hva som mangler, og hva som aldri ble valgt. Ingen påstander uten evidens; ingen negative funn fra uvalgte områder. Medienevnter er navntreff i media, ikke identitetsbevis; kontekstutdrag er ikke full artikkeltekst.</p>{report ? <section className="summary-grid" key="rapport-sammendrag"><div><span>Rapport for</span><strong>{report.target_name}</strong></div><div><span>Generert</span><strong>{formatDate(report.generated_at)}</strong></div></section> : null}</div><section className="coverage-section" key="funn"><div className="coverage-title"><div><p className="eyebrow">FUNN</p><h2>Vesentlige funn ({findings.length})</h2></div></div><p className="field-help">Funn er påstander med kildebelegg og status. Hvert funn viser verdi, status og lenker til lagret evidens. Uavklarte spor listes separat nedenfor og er ikke funn.</p>{reportError ? <p className="not-running">Kunne ikke laste full rapport ({reportError}). Ingen funnstatus kan vises før rapporten er lastet.</p> : report === null ? <p className="loading-state">Laster full rapport …</p> : findings.length === 0 ? <p className="not-running">Ingen lagrede funn med evidensbelegg for denne undersøkelsen ennå. Fravær av funn er ikke et negativt funn for områder som ikke er undersøkt.</p> : <div className="coverage-list">{findings.map((finding, index) => <FindingCard finding={finding} key={`${finding.predicate}-${finding.subject_name ?? ""}-${index}`} />)}</div>}</section><section className="coverage-section" key="medienevnter"><div className="coverage-title"><div><p className="eyebrow">MEDIENEVNTER</p><h2>Medienevnter ({mentions.length})</h2></div></div><p className="field-help">Medienevnter fra Nasjonalbiblioteket vises med tilgangsstatus og identitetsstatus. Kontekstutdrag er ikke full artikkeltekst, og tilgangsbegrenset innhold vises kun som metadata med direkte lenke.</p>{reportError ? <p className="not-running">Kunne ikke laste full rapport ({reportError}). Ingen medienevnt-status kan vises før rapporten er lastet.</p> : report === null ? <p className="loading-state">Laster full rapport …</p> : mentions.length === 0 ? (webMediaNotSelected ? <p className="not-running">Mediemodulen (WEB_MEDIA) er ikke valgt for denne undersøkelsen. Fravær av medienevnter er ikke et negativt funn.</p> : <p className="not-running">Ingen lagrede medienevnter for denne undersøkelsen.</p>) : <div className="coverage-list">{mentions.map((mention) => <MediaMentionCard mention={mention} key={`${mention.page_urn || mention.issue_urn || mention.publication || "nevnt"}-${mention.published_at || ""}`} />)}</div>}</section><section className="coverage-section" key="spor"><div className="coverage-title"><div><p className="eyebrow">SPOR</p><h2>Uavklarte spor ({leads.length})</h2></div></div><p className="field-help">Uavklarte spor er ikke funn. De beskriver hva som mangler for å verifisere en påstand.</p>{reportError ? <p className="not-running">Kunne ikke laste full rapport ({reportError}). Ingen sporstatus kan vises før rapporten er lastet.</p> : report === null ? <p className="loading-state">Laster full rapport …</p> : leads.length === 0 ? <p className="not-running">Ingen uavklarte spor.</p> : <div className="coverage-list">{leads.map((lead, index) => <LeadRow lead={lead} key={`${lead.predicate ?? "spor"}-${index}`} />)}</div>}</section><section className="coverage-section" key="kontekst"><div className="coverage-title"><div><p className="eyebrow">KONTEKST</p><h2>Kontekst ({contextEntities.length})</h2></div></div><p className="field-help">Enhetene nedenfor er kun nevnt som kontekst og er ikke bakgrunnssjekket. Navn her er ikke undersøkt som egne mål.</p>{reportError ? <p className="not-running">Kunne ikke laste full rapport ({reportError}). Ingen kontekststatus kan vises før rapporten er lastet.</p> : report === null ? <p className="loading-state">Laster full rapport …</p> : contextEntities.length === 0 ? <p className="not-running">Ingen kontekstopplysninger.</p> : <div className="coverage-list">{contextEntities.map((entity, index) => <ContextRow entity={entity} key={`${entity.name ?? "kontekst"}-${entity.entity_schema}-${index}`} />)}</div>}</section>{SECTION_ORDER.map((section) => <section className="coverage-section" key={section}><div className="coverage-title"><div><p className="eyebrow">{section.toUpperCase()}</p><h2>{section} ({(sections[section] || []).length})</h2></div></div><p className="field-help">{SECTION_HELP[section]}</p>{(sections[section] || []).length === 0 ? <p className="not-running">Ingen moduler i denne kategorien.</p> : <div className="coverage-list">{(sections[section] || []).map((item) => <div className="coverage-row" key={item.module}><div><strong>{item.module.replaceAll("_", " ")}</strong><span>Status: {item.status}{item.stop_reason ? ` · Stoppårsak: ${item.stop_reason}` : ""}</span>{(item.coverage.query_count > 0 || item.coverage.document_count > 0 || item.coverage.providers.length > 0) && <span>Søk: {item.coverage.query_count} · Dokumenter: {item.coverage.document_count}{item.coverage.providers.length > 0 ? ` · Kilder: ${item.coverage.providers.join(", ")}` : ""}</span>}{coverageDetail(item.coverage) && <span>{coverageDetail(item.coverage)}</span>}</div><span className="status-dot" role="img" aria-label={section} /></div>)}</div>}</section>)}</main>;
}
