"use client";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
type Coverage = { providers: string[]; query_classes: string[]; query_count: number; document_count: number; gaps: string[]; unavailable_sources: string[] };
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
function formatApiDetail(detail: unknown): string { if (Array.isArray(detail)) { const text = detail.map((item) => typeof item === "string" ? item : (item as { msg?: string } | null)?.msg).filter(Boolean).join(" "); if (text) return text; try { return JSON.stringify(detail); } catch { return ""; } } if (typeof detail === "string") return detail; if (detail === null || detail === undefined) return ""; try { return JSON.stringify(detail); } catch { return ""; } }
export default function ReportPage() {
  const { id } = useParams<{ id: string }>(); const [sections, setSections] = useState<Sections | null>(null); const [error, setError] = useState("");
  const loadSections = useCallback((signal?: AbortSignal) => { setError(""); fetch(`${API_BASE}/api/v1/investigations/${id}/report/sections`, { signal }).then(async (response) => { const payload = await response.json().catch(() => null); if (!response.ok) throw new Error(formatApiDetail(payload?.detail) || "Fant ikke rapporten."); setSections(payload); }).catch((caught) => { if (signal?.aborted) return; setError(caught instanceof Error ? caught.message : "Kunne ikke laste rapporten."); }); }, [id]);
  useEffect(() => { const controller = new AbortController(); loadSections(controller.signal); return () => controller.abort(); }, [loadSections]);
  if (error) return <main className="detail-shell"><a className="back-link" href={`/investigations/${id}`}>← Tilbake til undersøkelsen</a><div className="state-card"><h1>Kunne ikke åpne rapporten</h1><p>{error}</p></div></main>;
  if (!sections) return <main className="detail-shell"><p className="loading-state">Laster rapport …</p></main>;
  return <main className="detail-shell"><header className="detail-top"><a className="brand" href="/"><span className="brand-mark">A</span> ANALYSEN</a><a className="back-link" href={`/investigations/${id}`}>← Tilbake til undersøkelsen</a></header><div className="detail-heading"><p className="eyebrow">RAPPORT · DEKNING PER OMRÅDE</p><h1>Dekningsrapport</h1><p>Hva som er undersøkt, hva som mangler, og hva som aldri ble valgt. Ingen påstander uten evidens; ingen negative funn fra uvalgte områder.</p></div>{SECTION_ORDER.map((section) => <section className="coverage-section" key={section}><div className="coverage-title"><div><p className="eyebrow">{section.toUpperCase()}</p><h2>{section} ({(sections[section] || []).length})</h2></div></div><p className="field-help">{SECTION_HELP[section]}</p>{(sections[section] || []).length === 0 ? <p className="not-running">Ingen moduler i denne kategorien.</p> : <div className="coverage-list">{(sections[section] || []).map((item) => <div className="coverage-row" key={item.module}><div><strong>{item.module.replaceAll("_", " ")}</strong><span>Status: {item.status}{item.stop_reason ? ` · Stoppårsak: ${item.stop_reason}` : ""}</span>{(item.coverage.query_count > 0 || item.coverage.document_count > 0 || item.coverage.providers.length > 0) && <span>Søk: {item.coverage.query_count} · Dokumenter: {item.coverage.document_count}{item.coverage.providers.length > 0 ? ` · Kilder: ${item.coverage.providers.join(", ")}` : ""}</span>}</div><span className="status-dot" role="img" aria-label={section} /></div>)}</div>}</section>)}</main>;
}
