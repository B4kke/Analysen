"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { TargetInput, TargetType, formatApiDetail } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const modules = [
  ["WEB_MEDIA", "Web og medier", "Offentlig web, aviser, medier og fagkilder"],
  ["BUSINESS_ROLES", "Virksomhetsroller", "Roller, styreverv og grunnkontekst"],
  ["COMPANY_NETWORK", "Selskapsrelasjoner", "Konsern, eierskap og selskapsnettverk"],
  ["FINANCIALS", "Regnskap og økonomi", "Årsregnskap, nøkkeltall og økonomiske signaler"],
  ["ANNOUNCEMENTS_STATUS", "Kunngjøringer og status", "Offentlige kunngjøringer og registrert virksomhetsstatus"],
  ["HISTORICAL_WEB", "Historiske nettsider", "Tidligere versjoner og arkiverte nettsider"],
  ["DOMAINS_DIGITAL", "Domener og digitalt fotavtrykk", "Domener og offentlig digital infrastruktur"],
  ["PUBLIC_PROFILES", "Offentlige profiler", "Offentlig tilgjengelige profiler og presentasjoner"],
  ["SANCTIONS", "Sanksjonskontroll", "Offisielle sanksjonslister"],
] as const;

const splitValues = (value: string) =>
  value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);

type SubmitStage = "idle" | "creating" | "starting";

export default function Home() {
  const router = useRouter();
  const [targetType, setTargetType] = useState<TargetType>("person");
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [birthYear, setBirthYear] = useState("");
  const [place, setPlace] = useState("");
  const [knownOrganizations, setKnownOrganizations] = useState("");
  const [orgnr, setOrgnr] = useState("");
  const [purpose, setPurpose] = useState("");
  const [selectedModules, setSelectedModules] = useState<string[]>([]);
  const [expansionPolicy, setExpansionPolicy] = useState("CONTEXT_ONLY");
  const [maxRelationDepth, setMaxRelationDepth] = useState("0");
  const [error, setError] = useState("");
  const [submitStage, setSubmitStage] = useState<SubmitStage>("idle");

  const isSubmitting = submitStage !== "idle";
  const willStartResearch = selectedModules.length > 0;

  function toggleModule(module: string) {
    setSelectedModules((current) =>
      current.includes(module) ? current.filter((item) => item !== module) : [...current, module],
    );
  }

  function changeTargetType(value: TargetType) {
    setTargetType(value);
    const contextOnly = value === "person" || value === "domain";
    setExpansionPolicy(contextOnly ? "CONTEXT_ONLY" : "DIRECT_RELATIONS");
    setMaxRelationDepth(contextOnly ? "0" : "1");
    if (value !== "person") {
      setBirthDate("");
      setBirthYear("");
    }
  }

  async function createInvestigation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!name.trim()) {
      setError("Fyll inn navn før du starter undersøkelsen.");
      return;
    }
    if (targetType === "person" && birthYear.trim() && !/^\d{4}$/.test(birthYear.trim())) {
      setError("Fødselsår må være et firesifret årstall.");
      return;
    }

    setSubmitStage("creating");
    const target: TargetInput = {
      type: targetType,
      name: name.trim(),
      known_orgnrs: [],
      known_organizations: [],
    };
    if (targetType === "person") {
      if (birthDate) target.birth_date = birthDate;
      if (birthYear.trim()) target.birth_year = Number(birthYear);
    }
    if (place.trim()) target.place = place.trim();
    if (targetType === "person") {
      target.known_organizations = splitValues(knownOrganizations);
    } else if (targetType !== "domain") {
      target.known_orgnrs = splitValues(orgnr).map((value) => value.replace(/\s+/g, ""));
    }

    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(`${API_BASE}/api/v1/investigations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          target,
          purpose: purpose.trim(),
          scope_modules: selectedModules,
          expansion_policy: expansionPolicy,
          max_relation_depth: Number(maxRelationDepth),
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(formatApiDetail(payload?.detail) || "Kunne ikke opprette undersøkelsen.");
      }
      const id = payload?.id || payload?.uuid;
      if (!id) throw new Error("API-et returnerte ingen undersøkelses-ID.");

      if (willStartResearch) {
        setSubmitStage("starting");
        const startResponse = await fetch(`${API_BASE}/api/v1/investigations/${id}/research/run`, {
          method: "POST",
        });
        const startPayload = await startResponse.json().catch(() => null);
        if (!startResponse.ok && startResponse.status !== 409) {
          const warning =
            formatApiDetail(startPayload?.detail) ||
            "Saken ble opprettet, men research kunne ikke startes automatisk.";
          window.sessionStorage.setItem(`analysen:start-warning:${id}`, warning);
        }
      }

      router.push(`/investigations/${id}`);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        setError("Forespørselen tidsavbrøt etter 30 sekunder. API-et svarer ikke – prøv igjen.");
      } else {
        setError(caught instanceof Error ? caught.message : "Noe gikk galt. Prøv igjen.");
      }
      setSubmitStage("idle");
    } finally {
      window.clearTimeout(timer);
    }
  }

  const submitLabel =
    submitStage === "creating"
      ? "Oppretter sak …"
      : submitStage === "starting"
        ? "Starter søk …"
        : willStartResearch
          ? "Opprett og start undersøkelse"
          : "Opprett uten research";

  return (
    <main className="site-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Analysen hjem">
          <span className="brand-mark">A</span> ANALYSEN
        </a>
        <span className="topbar-note">Kildebevisst OSINT</span>
      </header>

      <div className="page-grid">
        <section className="intro">
          <p className="eyebrow">NY UNDERSØKELSE</p>
          <h1>Velg hva som skal undersøkes.</h1>
          <p className="intro-copy">
            Velg mål og søkeområder. Når minst ett område er valgt, opprettes saken og research
            startes automatisk.
          </p>
          <div className="principles" aria-label="Prinsipper">
            <div><span>01</span><p>Primærkilder først</p></div>
            <div><span>02</span><p>Tydelig status mens søket kjører</p></div>
            <div><span>03</span><p>Alle påstander kan etterprøves</p></div>
          </div>
        </section>

        <form className="investigation-form" onSubmit={createInvestigation} noValidate>
          <div className="form-section">
            <div className="section-heading">
              <span>01</span>
              <div><h2>Mål</h2><p>Hvem eller hva skal undersøkes?</p></div>
            </div>
            <div className="field-grid two-col">
              <label>
                Type
                <select value={targetType} onChange={(event) => changeTargetType(event.target.value as TargetType)}>
                  <option value="person">Person</option>
                  <option value="organization">Organisasjon</option>
                  <option value="company">Virksomhet</option>
                  <option value="domain">Domene</option>
                </select>
              </label>
              <label>
                Navn eller identifikator <span className="required">*</span>
                <input required minLength={3} value={name} onChange={(event) => setName(event.target.value)} placeholder="For eksempel Kari Nordmann" />
              </label>
              {targetType === "person" && (
                <>
                  <label>
                    Fødselsdato <span className="optional">valgfritt</span>
                    <input type="date" value={birthDate} onChange={(event) => setBirthDate(event.target.value)} />
                  </label>
                  <label>
                    Fødselsår <span className="optional">valgfritt</span>
                    <input inputMode="numeric" value={birthYear} onChange={(event) => setBirthYear(event.target.value)} placeholder="For eksempel 1984" />
                  </label>
                </>
              )}
            </div>
            <label>
              Sted <span className="optional">valgfritt</span>
              <input value={place} onChange={(event) => setPlace(event.target.value)} placeholder="Kommune eller land" />
            </label>
            {targetType === "person" ? (
              <label>
                Kjente virksomheter <span className="optional">valgfritt, komma eller linjeskift</span>
                <textarea rows={2} value={knownOrganizations} onChange={(event) => setKnownOrganizations(event.target.value)} placeholder="Navn på virksomhet" />
              </label>
            ) : targetType === "domain" ? null : (
              <label>
                Organisasjonsnummer <span className="optional">valgfritt, komma eller linjeskift</span>
                <textarea rows={2} value={orgnr} onChange={(event) => setOrgnr(event.target.value)} placeholder="For eksempel 987 654 321" />
              </label>
            )}
          </div>

          <div className="form-section">
            <div className="section-heading">
              <span>02</span>
              <div><h2>Hva skal undersøkes?</h2><p>Velg områdene som faktisk skal søkes.</p></div>
            </div>
            <label>
              Formål <span className="optional">valgfritt</span>
              <textarea value={purpose} onChange={(event) => setPurpose(event.target.value)} rows={3} placeholder="Hva vil du avklare?" />
            </label>
            <fieldset>
              <legend>Undersøkelsesområder</legend>
              <p className="field-help">
                Minst ett valgt område betyr at research startes automatisk etter opprettelse.
              </p>
              <div className="module-list">
                {modules.map(([module, label, description]) => (
                  <label className={`module-option ${selectedModules.includes(module) ? "selected" : ""}`} key={module}>
                    <input type="checkbox" checked={selectedModules.includes(module)} onChange={() => toggleModule(module)} />
                    <span><strong>{label}</strong><small>{description}</small></span>
                  </label>
                ))}
              </div>
              <p className={willStartResearch ? "start-hint start-hint--ready" : "start-hint start-hint--idle"} role="status">
                {willStartResearch
                  ? `${selectedModules.length} område${selectedModules.length === 1 ? "" : "r"} valgt. Søk og analyse starter automatisk.`
                  : "Ingen områder valgt. Saken kan opprettes, men det starter ingen research."}
              </p>
            </fieldset>
          </div>

          <div className="form-section">
            <div className="section-heading">
              <span>03</span>
              <div><h2>Relasjoner</h2><p>Sett en grense for hvor langt spor kan følges.</p></div>
            </div>
            <div className="field-grid two-col">
              <label>
                Hvor langt kan research utvides?
                <select value={expansionPolicy} onChange={(event) => setExpansionPolicy(event.target.value)}>
                  <option value="CONTEXT_ONLY">Kun mål og nødvendig kontekst</option>
                  <option value="DIRECT_RELATIONS">Direkte relasjoner</option>
                  <option value="MATERIAL_RELATIONS">Vesentlige relasjoner automatisk</option>
                </select>
              </label>
              <label>
                Maks relasjonsdybde
                <select value={maxRelationDepth} onChange={(event) => setMaxRelationDepth(event.target.value)}>
                  <option value="0">0 — kun mål</option>
                  <option value="1">1 — direkte</option>
                  <option value="2">2 — to ledd</option>
                  <option value="3">3 — tre ledd</option>
                </select>
              </label>
            </div>
            <p className="privacy-note">
              <span aria-hidden="true">◌</span>
              Identitetsavklaring begrenses til det som er nødvendig for å skille riktige kilder fra feil person eller virksomhet.
            </p>
          </div>

          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="form-actions">
            <button className="submit-button" type="submit" disabled={isSubmitting}>
              {submitLabel}<span aria-hidden="true">→</span>
            </button>
            <p>
              {willStartResearch
                ? "Du sendes videre til en live statusside når saken er opprettet."
                : "Du kan velge søkeområder og starte research senere fra saken."}
            </p>
          </div>
        </form>
      </div>
    </main>
  );
}
