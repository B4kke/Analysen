"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ClaimState,
  EvidenceState,
  InvestigationDetail,
  ResearchStatus,
  formatApiDetail,
  formatDate,
  safeHttpUrl,
} from "../../types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const activeStatuses: ResearchStatus[] = ["REQUESTED", "ENQUEUED", "RUNNING"];
const TERMINAL_LEAD = ["COMPLETED", "BLOCKED", "FAILED"];

const moduleLabel: Record<string, string> = {
  WEB_MEDIA: "Web og medier",
  BUSINESS_ROLES: "Virksomhetsroller",
  COMPANY_NETWORK: "Selskapsrelasjoner",
  FINANCIALS: "Regnskap og økonomi",
  ANNOUNCEMENTS_STATUS: "Kunngjøringer og status",
  HISTORICAL_WEB: "Historiske nettsider",
  DOMAINS_DIGITAL: "Domener og digitalt fotavtrykk",
  PUBLIC_PROFILES: "Offentlige profiler",
  SANCTIONS: "Sanksjonskontroll",
};

const moduleStatusLabel: Record<string, string> = {
  NOT_STARTED: "Ikke startet",
  IN_PROGRESS: "Pågår",
  COMPLETE: "Fullført",
  PARTIAL: "Delvis",
  BLOCKED: "Blokkert",
};

const claimLabel: Record<string, string> = {
  SUPPORTED: "Støttet",
  PARTIALLY_SUPPORTED: "Delvis støttet",
  CONTRADICTED: "Motsagt",
  INSUFFICIENT_EVIDENCE: "Ikke verifisert",
  UNVERIFIED_LEAD: "Uverifisert spor",
};

const researchView: Record<
  ResearchStatus,
  { title: string; description: string; tone: string; action: string }
> = {
  NOT_STARTED: {
    title: "Research er ikke startet",
    description: "Saken er opprettet, men ingen worker-jobb er sendt ennå.",
    tone: "idle",
    action: "Start søk og analyse",
  },
  ACTIVITY_RECORDED: {
    title: "Det finnes lagret aktivitet",
    description:
      "Saken har data fra tidligere handlinger, men det finnes ikke et registrert research-pass som kjører nå.",
    tone: "idle",
    action: "Start søk og analyse",
  },
  REQUESTED: {
    title: "Startforespørselen er lagret",
    description: "API-et har registrert start. Det venter fortsatt på bekreftelse fra køsystemet.",
    tone: "queued",
    action: "Venter på købekreftelse",
  },
  ENQUEUED: {
    title: "Jobben er købekreftet",
    description: "Research-jobben ligger i kø og venter på at en worker skal starte den.",
    tone: "queued",
    action: "Venter på worker",
  },
  RUNNING: {
    title: "Research kjører",
    description:
      "En worker har registrert at dette research-passet er startet. Siden oppdateres automatisk når nye data lagres.",
    tone: "running",
    action: "Research kjører",
  },
  COMPLETED: {
    title: "Research-passet er fullført",
    description:
      "Dette passet er ferdig. Det betyr ikke nødvendigvis at alle mulige spor er undersøkt; se moduldekningen under.",
    tone: "complete",
    action: "Kjør nytt research-pass",
  },
  FAILED: {
    title: "Research-passet feilet",
    description: "Siste pass nådde en terminal feiltilstand. Feilkoden vises under.",
    tone: "failed",
    action: "Prøv research på nytt",
  },
};

function valueText(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function coverageText(coverage: InvestigationDetail["modules"][number]["coverage"]): string {
  const parts: string[] = [];
  if (coverage.query_count !== undefined) parts.push(`${coverage.query_count} søk`);
  if (coverage.document_count !== undefined) parts.push(`${coverage.document_count} dokumenter`);
  if (coverage.providers?.length) parts.push(`kilder: ${coverage.providers.join(", ")}`);
  if (coverage.query_classes?.length) parts.push(`søketyper: ${coverage.query_classes.join(", ")}`);
  const positive = (value: number | undefined | null) => typeof value === "number" && value > 0;
  if (positive(coverage.candidate_count)) parts.push(`kandidater: ${coverage.candidate_count}`);
  if (positive(coverage.located_count)) parts.push(`lokalisert: ${coverage.located_count}`);
  if (positive(coverage.restricted_count)) parts.push(`begrenset: ${coverage.restricted_count}`);
  if (positive(coverage.fetched_count)) parts.push(`hentet: ${coverage.fetched_count}`);
  if (coverage.time_from || coverage.time_to) {
    parts.push(`tidsrom: ${coverage.time_from ?? "–"}–${coverage.time_to ?? "–"}`);
  }
  if (coverage.gaps?.length) parts.push(`mangler: ${coverage.gaps.join(", ")}`);
  if (coverage.unavailable_sources?.length) {
    parts.push(`utilgjengelig: ${coverage.unavailable_sources.join(", ")}`);
  }
  return parts.join(" · ");
}

function lastResearchTimestamp(research: InvestigationDetail["research"]): string | null {
  return research.completed_at || research.started_at || research.enqueued_at || research.requested_at;
}

type StepState = "done" | "active" | "todo" | "failed";
type FlowStep = { label: string; state: StepState; detail: string | null };

function researchSteps(research: InvestigationDetail["research"]): {
  steps: FlowStep[];
  stageProgress: number;
} {
  const requested = Boolean(research.requested_at) || activeStatuses.includes(research.status) ||
    research.status === "COMPLETED" || research.status === "FAILED";
  const enqueued = Boolean(research.enqueued_at) ||
    ["ENQUEUED", "RUNNING", "COMPLETED"].includes(research.status);
  const started = Boolean(research.started_at) || ["RUNNING", "COMPLETED"].includes(research.status);

  const steps: FlowStep[] = [{ label: "Sak opprettet", state: "done", detail: null }];

  if (research.status === "REQUESTED") {
    steps.push({ label: "Kø", state: "active", detail: "Venter på købekreftelse" });
  } else if (requested) {
    steps.push({
      label: "Kø",
      state: enqueued || started || research.status === "COMPLETED" ? "done" : research.status === "FAILED" ? "failed" : "active",
      detail: enqueued ? "Købekreftet" : research.status === "FAILED" ? "Start feilet" : null,
    });
  } else {
    steps.push({ label: "Kø", state: "todo", detail: null });
  }

  if (research.status === "RUNNING") {
    steps.push({ label: "Worker", state: "active", detail: "Worker har startet" });
  } else if (started || research.status === "COMPLETED") {
    steps.push({ label: "Worker", state: "done", detail: "Worker startet" });
  } else if (research.status === "ENQUEUED") {
    steps.push({ label: "Worker", state: "active", detail: "Venter på ledig worker" });
  } else if (research.status === "FAILED" && research.started_at) {
    steps.push({ label: "Worker", state: "failed", detail: "Feilet under kjøring" });
  } else {
    steps.push({ label: "Worker", state: "todo", detail: null });
  }

  if (research.status === "COMPLETED") {
    steps.push({ label: "Resultat", state: "done", detail: "Pass fullført" });
  } else if (research.status === "FAILED") {
    steps.push({ label: "Resultat", state: "failed", detail: research.error_code || "Pass feilet" });
  } else {
    steps.push({ label: "Resultat", state: "todo", detail: null });
  }

  const stageProgress =
    research.status === "COMPLETED" || research.status === "FAILED"
      ? 100
      : research.status === "RUNNING"
        ? 75
        : research.status === "ENQUEUED"
          ? 50
          : research.status === "REQUESTED"
            ? 38
            : 25;

  return { steps, stageProgress };
}

export default function InvestigationPage() {
  const { id } = useParams<{ id: string }>();
  const [investigation, setInvestigation] = useState<InvestigationDetail | null>(null);
  const investigationRef = useRef<InvestigationDetail | null>(null);
  const requestGeneration = useRef(0);
  const currentId = useRef<string | null>(id);
  currentId.current = id;

  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [runStatus, setRunStatus] = useState("");
  const [runOk, setRunOk] = useState(false);
  const [inflight, setInflight] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState<Date | null>(null);

  const loadInvestigation = useCallback(
    async (signal?: AbortSignal) => {
      if (currentId.current !== id) return;
      const generation = ++requestGeneration.current;
      try {
        const response = await fetch(`${API_BASE}/api/v1/investigations/${id}`, {
          signal,
          cache: "no-store",
        });
        const payload = await response.json().catch(() => null);
        if (signal?.aborted || generation !== requestGeneration.current || currentId.current !== id) {
          return;
        }
        if (!response.ok) {
          throw new Error(formatApiDetail(payload?.detail) || "Fant ikke undersøkelsen.");
        }
        if (!payload) throw new Error("API-et returnerte et ugyldig svar.");
        investigationRef.current = payload as InvestigationDetail;
        setInvestigation(payload as InvestigationDetail);
        setError("");
        setStale(false);
        setLastRefreshAt(new Date());
      } catch (caught) {
        if (signal?.aborted || generation !== requestGeneration.current || currentId.current !== id) {
          return;
        }
        if (investigationRef.current) setStale(true);
        setError(caught instanceof Error ? caught.message : "Kunne ikke oppdatere undersøkelsen.");
      }
    },
    [id],
  );

  useEffect(() => {
    currentId.current = id;
    investigationRef.current = null;
    setInvestigation(null);
    setError("");
    setStale(false);
    setRunStatus("");
    setRunOk(false);
    setInflight(false);
    setLastRefreshAt(null);

    const warningKey = `analysen:start-warning:${id}`;
    const warning = window.sessionStorage.getItem(warningKey);
    if (warning) {
      setRunStatus(`Saken ble opprettet, men automatisk start feilet: ${warning}`);
      window.sessionStorage.removeItem(warningKey);
    }

    const controller = new AbortController();
    void loadInvestigation(controller.signal);
    return () => {
      ++requestGeneration.current;
      currentId.current = null;
      controller.abort();
    };
  }, [id, loadInvestigation]);

  const researchStatus = investigation?.research.status;
  useEffect(() => {
    if (!researchStatus || !activeStatuses.includes(researchStatus)) return;
    let cancelled = false;
    let timer: number;

    const poll = async () => {
      await loadInvestigation();
      if (!cancelled) timer = window.setTimeout(() => void poll(), 2500);
    };

    timer = window.setTimeout(() => void poll(), 2500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [researchStatus, loadInvestigation]);

  async function startResearchPass() {
    if (!investigation || activeStatuses.includes(investigation.research.status) || inflight) return;
    if (!investigation.modules.some((item) => item.enabled)) return;

    setInflight(true);
    setRunStatus("");
    setRunOk(false);
    try {
      const response = await fetch(`${API_BASE}/api/v1/investigations/${id}/research/run`, {
        method: "POST",
      });
      const payload = await response.json().catch(() => null);
      if (currentId.current !== id) return;
      if (!response.ok) {
        throw new Error(formatApiDetail(payload?.detail) || "Kunne ikke starte research.");
      }
      setRunOk(true);
      setRunStatus("Start bekreftet. Research-jobben er sendt til køen.");
    } catch (caught) {
      if (currentId.current === id) {
        setRunStatus(caught instanceof Error ? caught.message : "Noe gikk galt.");
      }
    } finally {
      if (currentId.current === id) {
        setInflight(false);
        void loadInvestigation();
      }
    }
  }

  if (error && !investigation) {
    return (
      <main className="detail-shell">
        <a className="back-link" href="/">← Ny undersøkelse</a>
        <div className="state-card">
          <h1>Kunne ikke åpne undersøkelsen</h1>
          <p>{error}</p>
          <button className="submit-button" onClick={() => void loadInvestigation()}>Prøv igjen</button>
        </div>
      </main>
    );
  }

  if (!investigation) {
    return <main className="detail-shell"><p className="loading-state">Laster undersøkelse …</p></main>;
  }

  const research = investigation.research;
  const isActive = activeStatuses.includes(research.status);
  const view = researchView[research.status];
  const timestamp = lastResearchTimestamp(research);
  const flow = researchSteps(research);
  const modules = investigation.modules || [];
  const enabledModules = modules.filter((item) => item.enabled);
  const completedModules = enabledModules.filter((item) => item.status === "COMPLETE").length;
  const doneLeads = investigation.leads.filter((lead) => TERMINAL_LEAD.includes(lead.status)).length;
  const canStart = enabledModules.length > 0 && !isActive && !inflight;

  const actionLabel = inflight
    ? "Sender startforespørsel …"
    : isActive
      ? view.action
      : view.action;

  return (
    <main className="detail-shell">
      <header className="detail-top">
        <a className="brand" href="/"><span className="brand-mark">A</span> ANALYSEN</a>
        <a className="back-link" href="/">← Ny undersøkelse</a>
      </header>

      <div className="detail-heading">
        <p className="eyebrow">UNDERSØKELSE · {investigation.status}</p>
        <h1>{investigation.target.name}</h1>
        {investigation.purpose ? <p>{investigation.purpose}</p> : <p>Ingen formålsbeskrivelse er registrert.</p>}
      </div>

      <section className={`research-status-card research-status-card--${view.tone}`} aria-live="polite">
        <div className="research-status-main">
          <span className={`activity-indicator ${research.status === "RUNNING" ? "activity-indicator--live" : ""}`} aria-hidden="true" />
          <div>
            <p className="eyebrow">RESEARCHSTATUS</p>
            <h2>{view.title}</h2>
            <p>{view.description}</p>
          </div>
        </div>

        <div className="research-facts">
          <div><span>Status</span><strong>{research.status.replaceAll("_", " ")}</strong></div>
          <div><span>Jobb-ID</span><strong className="id-value">{research.job_id || "Ikke tildelt"}</strong></div>
          <div><span>Siste fasehendelse</span><strong>{formatDate(timestamp)}</strong></div>
          <div><span>Sist lest av UI</span><strong>{lastRefreshAt ? lastRefreshAt.toLocaleTimeString("nb-NO") : "–"}</strong></div>
        </div>

        <div className="research-timeline" aria-label="Research-tidspunkter">
          <span>Forespurt <strong>{formatDate(research.requested_at)}</strong></span>
          <span>Købekreftet <strong>{formatDate(research.enqueued_at)}</strong></span>
          <span>Worker startet <strong>{formatDate(research.started_at)}</strong></span>
          <span>Avsluttet <strong>{formatDate(research.completed_at)}</strong></span>
        </div>

        <div className="research-actions">
          <button className="submit-button" onClick={startResearchPass} disabled={!canStart}>
            {actionLabel}<span aria-hidden="true">→</span>
          </button>
          <button className="secondary-button" onClick={() => void loadInvestigation()}>
            Oppdater nå
          </button>
          {isActive && <span className="auto-refresh-note">Oppdateres automatisk hvert 2,5 sekund</span>}
        </div>

        {enabledModules.length === 0 && (
          <p className="form-error" role="status">
            Ingen søkeområder er valgt i denne saken. Research kan derfor ikke startes.
          </p>
        )}
        {stale && (
          <p className="form-error" role="status">
            Kontakt med API-et feilet. Siste lagrede data beholdes på skjermen.
          </p>
        )}
        {runStatus && (
          <p className={runOk ? "form-success" : "form-error"} role="status">{runStatus}</p>
        )}
        {research.error_code && <p className="form-error">Feilkode: {research.error_code}</p>}
      </section>

      <section className="flow-section" aria-label="Forløp">
        <div className="flow-heading">
          <div><p className="eyebrow">FORLØP</p><h2>Hvor i prosessen er saken?</h2></div>
          <p>Fremdriftslinjen viser fase, ikke prosent av et ukjent totalt research-arbeid.</p>
        </div>
        <ol className="step-bar">
          {flow.steps.map((step) => (
            <li
              key={step.label}
              className={`step step--${step.state}`}
              aria-current={step.state === "active" ? "step" : undefined}
            >
              <strong>{step.label}</strong>
              {step.detail && <span>{step.detail}</span>}
            </li>
          ))}
        </ol>
        <div
          className={`step-meter ${research.status === "RUNNING" ? "step-meter--running" : ""}`}
          role="progressbar"
          aria-valuenow={flow.stageProgress}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Fase i research-passet"
        >
          <i style={{ width: `${flow.stageProgress}%` }} />
        </div>
      </section>

      <section className="summary-grid">
        <div><span>Søkeområder</span><strong>{enabledModules.length}</strong></div>
        <div><span>Ferdige leads</span><strong>{doneLeads} / {investigation.leads.length}</strong></div>
        <div><span>Dokumenter</span><strong>{investigation.document_count}</strong></div>
        <div><span>Evidence</span><strong>{investigation.evidence_count}</strong></div>
      </section>

      <section className="coverage-section">
        <div className="coverage-title">
          <div><p className="eyebrow">SØKEOMRÅDER OG DEKNING</p><h2>Hva er faktisk undersøkt?</h2></div>
          <a className="back-link" href={`/investigations/${id}/report`}>Åpne dekningsrapport →</a>
        </div>

        <div className="coverage-summary">
          <strong>{completedModules} / {enabledModules.length}</strong>
          <span>valgte områder har fullført status</span>
          {research.summary && (
            <span>
              Siste pass: {research.summary.executed} utført · {research.summary.blocked} blokkert · {research.summary.failed} feilet
              {research.summary.stopped_reason ? ` · stopp: ${research.summary.stopped_reason}` : ""}
            </span>
          )}
        </div>

        <div className="coverage-list">
          {modules.length ? (
            modules.map((item) => {
              const statusKey = item.enabled ? item.status : "DISABLED";
              const statusText = item.enabled ? moduleStatusLabel[item.status] || item.status : "Ikke valgt";
              const tone = statusKey.toLowerCase().replaceAll("_", "-");
              return (
                <div className="coverage-row" key={item.module}>
                  <div>
                    <strong>{moduleLabel[item.module] || item.module.replaceAll("_", " ")}</strong>
                    <span>
                      {statusText}
                      {item.stop_reason ? ` · stopp: ${item.stop_reason}` : ""}
                    </span>
                    {coverageText(item.coverage) && <small>{coverageText(item.coverage)}</small>}
                  </div>
                  <span className={`module-status module-status--${tone}`}>{statusText}</span>
                </div>
              );
            })
          ) : (
            <p className="empty-note">Ingen scope-moduler er registrert i denne saken.</p>
          )}
        </div>
      </section>

      <section className="detail-section">
        <div className="section-heading">
          <span>ARBEID</span>
          <div>
            <h2>Leads og identitetskontekst</h2>
            <p>Detaljert arbeidskø og lagrede entities. Dette er teknisk detaljnivå.</p>
          </div>
        </div>

        <div className="detail-list">
          {investigation.leads.map((lead) => (
            <article className="lead-card" key={lead.id}>
              <strong>{lead.lead_type}: {valueText(lead.value)}</strong>
              <span>Status: {lead.status} · prioritet {lead.priority.toFixed(2)} · dybde {lead.depth}</span>
              {lead.reason && <p>{lead.reason}</p>}
              <small>
                Informasjonsbehov: {lead.information_need || "Ikke registrert"} · {lead.scope_area || "uten scope"} · {lead.trigger_type || "uten trigger"}
                {lead.blocked_reason ? ` · blokkert: ${lead.blocked_reason}` : ""}
              </small>
            </article>
          ))}
        </div>
        {investigation.leads.length === 0 && <p className="empty-note">Ingen leads er lagret i denne saken ennå.</p>}

        <div className="detail-list">
          {investigation.entities.map((entity) => (
            <article className="entity-card" key={entity.id}>
              <strong>{entity.canonical_name || "Uten kanonisk navn"}</strong>
              <span>{entity.schema} · oppløsning: {entity.resolution_state} · relasjonsdybde: {entity.relation_depth}</span>
              <small>
                Ekspansjon: {entity.expansion_state}
                {entity.material_reason ? ` · ${entity.material_reason}` : ""}
              </small>
            </article>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <div className="section-heading">
          <span>FUNN</span>
          <div>
            <h2>Påstander og kildebelegg</h2>
            <p>{investigation.document_count} dokumenter · {investigation.evidence_count} evidence-poster</p>
          </div>
        </div>
        {investigation.claims.length ? (
          investigation.claims.map((claim) => (
            <ClaimCard key={claim.id} claim={claim} investigationId={id} />
          ))
        ) : (
          <p className="empty-note">Ingen lagrede påstander ennå.</p>
        )}
      </section>
    </main>
  );
}

function ClaimCard({
  claim,
  investigationId,
}: {
  claim: ClaimState;
  investigationId: string;
}) {
  return (
    <article className="claim-card">
      <div className="claim-header">
        <strong>{claim.predicate}</strong>
        <span className={`claim-status claim-${claim.status.toLowerCase()}`}>
          {claimLabel[claim.status] || claim.status}
        </span>
      </div>
      <p>{valueText(claim.value)}</p>
      <small>Opprettet: {formatDate(claim.created_at)}</small>
      {claim.evidence.length ? (
        <div className="evidence-list">
          {claim.evidence.map((evidence) => {
            const source = safeHttpUrl(evidence.original_url) || safeHttpUrl(evidence.canonical_url);
            return (
              <div className="evidence-card" key={`${evidence.evidence_id}:${evidence.relation}`}>
                <strong>{evidence.relation} · {evidence.source_name || "Ukjent kilde"}</strong>
                {evidence.excerpt && <p>{evidence.excerpt}</p>}
                <small>
                  Locator: {valueText(evidence.locator)} · hentet {formatDate(evidence.fetched_at)} · SHA-256: {evidence.sha256 || "ikke registrert"}
                </small>
                <div className="evidence-links">
                  {source && <a href={source} target="_blank" rel="noreferrer">Åpne originalkilde</a>}
                  {evidence.raw_storage_key && (
                    <a href={`${API_BASE}/api/v1/investigations/${investigationId}/evidence/${encodeURIComponent(evidence.evidence_id)}/raw`}>
                      Last ned lagret råkilde
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="empty-note">Ingen lagret evidence for denne påstanden.</p>
      )}
    </article>
  );
}
