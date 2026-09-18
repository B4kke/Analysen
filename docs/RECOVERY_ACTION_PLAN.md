# Recovery action plan — fra grunnmur til reell MVP

Dette dokumentet styrer reparasjon og integrasjon etter kodegjennomgangen 2026-09-18. Målet er ikke flere isolerte komponenter, men én etterprøvbar vertikal kjede.

## Arbeidsmodell i OpenCode2

Primær agent er `analysen-orchestrator`.

For større oppgaver skal orchestratoren som standard bruke 2–5 sub-agents samtidig når fil-/kontrakt-eierskap kan skilles. Integrator/orchestrator eier felles kontrakter, task-status og endelig verifisering.

Før en P0 settes DONE skal `integration-reviewer` kjøres read-only mot endringene.

### Subagents og eierskap

| Agent | Primært ansvar |
|---|---|
| `db-provenance` | Alembic, SQL, repository-kontrakter, claims/evidence, raw provenance |
| `research-runtime` | SearXNG, crawling/fetch, research deps, SSRF/redirect, robots/rate limits |
| `research-orchestration` | planner -> leads -> frontier -> trigger -> source router -> executor -> checkpoint |
| `entity-resolution` | kandidatgenerering, negative signals, merge/split og resolution states |
| `verification` | claim/evidence entailment, contradictions, missing-information feedback |
| `ui-reporting` | API/web-kontrakter, live state, evidence UX, report JSON/HTML/PDF |
| `integration-reviewer` | read-only adversarial review av acceptance og E2E |

## Wave 0 — stopp falsk fremdrift

Kjør først. Ikke bygg AQ-022/finans videre før disse kontraktene er stabile.

### 0A — Claims/evidence schema recovery
**Agent:** `db-provenance`

Problemer som skal rettes:
- 0001 oppretter tabeller som 0003 forsøker å "opprette" på nytt med andre kolonner.
- repository forventer felt/constraints som ikke garanteres av migrert skjema.
- claim/evidence-statusnavn er inkonsistente mellom SQL og Pydantic.
- claim_evidence/aliases/fingerprint-kontrakter må harmoniseres.

**Exit:**
- fresh baseline -> alembic head fungerer,
- repeat upgrade er idempotent,
- legacy-upgrade fixture fungerer,
- ekte repository-roundtrip: Source -> Document -> Evidence -> Claim -> ClaimEvidence,
- SHA/provenance roundtrip er verifisert.

### 0B — Research runtime recovery
**Agent:** `research-runtime`
**Kjøres parallelt med 0A.**

Problemer:
- standard Docker runtime installerer ikke research dependencies,
- web raw-store lagrer URL i stedet for fetched content,
- robots/rate/content-size er konfigurert men ikke håndhevet,
- redirect/final destination må SSRF-valideres,
- Playwright/browser runtime må faktisk være kjørbar.

**Exit:**
- worker/API research image har nødvendige pakker/binaries,
- local fixture-server tester HTML, redirect, private redirect block, oversize og failure,
- raw snapshot hasher de bytes/content som faktisk ble hentet,
- snippets forblir discovery-only.

### 0C — Adversarial baseline review
**Agent:** `integration-reviewer`
**Kjøres parallelt read-only.**

Lever en kort liste over andre P0-kontraktbrudd som må inn i task-køen. Ingen endringer.

## Wave 1 — koble motoren sammen

Starter når 0A/0B er integrert.

### 1A — Planner inn i research-loop
**Agent:** `research-orchestration`

Bygg den manglende kjeden:
- ny/tom frontier kan trigge typed planner,
- proposals -> lead gate -> persist,
- frontier bruker investigation.max_relation_depth,
- stop/budget/repeated-loop blir deterministiske.

### 1B — Source router + typed executors
**Agent:** `research-orchestration` eller egen child-session
**Kan parallelliseres delvis med 1A hvis kontraktene fryses først.**

Første executor-sett:
1. BRREG target organization,
2. BRREG roles/relationships der scope tillater,
3. SearXNG discovery,
4. fetch web document,
5. PDF/document processing.

Source router må være allowlisted og typed. Ingen modell får velge vilkårlig tool.

### 1C — UI/API contract repair
**Agent:** `ui-reporting`
**Kjøres parallelt med 1A/1B når request-shapes er låst.**

Fiks blant annet:
- `known_orgnrs` og `known_organizations` som arrays,
- statiske "Research er ikke startet"/"Ingen funn" mot reell state,
- vis worker/module/claim/evidence state,
- mobile regression gate.

## Wave 2 — identitet, verifikasjon og finans

### 2A — Entity resolution
**Agent:** `entity-resolution`
**Avhenger av:** stabilt schema/provenance.

Implementer AQ-022 med norske gold fixtures og hard negatives.

### 2B — Verifier
**Agent:** `verification`
**Kan kjøres parallelt med 2A etter claim-statuskontrakt er stabil.**

- evidence entailment,
- contradiction state,
- typed missing_information,
- trigger-gated follow-up,
- citation gate.

### 2C — Finans claims
**Agent:** `db-provenance` + `verification` eller egen finans-child-session
**Avhenger av:** document/PDF runtime + claim pipeline.

Koble eksisterende deterministiske ratios/year-over-year/auditor extraction til claims + evidence. Ingen LLM-beregning.

## Wave 3 — ekte sluttprodukt

### 3A — Full report pipeline
**Agent:** `ui-reporting`

`verified claims + coverage -> report JSON -> HTML -> PDF`

Må inkludere:
- mål/identitetsgrunnlag,
- scope og coverage,
- dokumenterte funn,
- contradictions,
- unresolved,
- evidence/citations,
- eksplisitt ikke-undersøkt.

### 3B — End-to-end investigation proof
**Agent:** `research-orchestration`
**Reviewer:** `integration-reviewer`

Lag minst én kontrollert company-case og én person/identity-case med ekte PostgreSQL/worker/state transitions og mocked kun external network/model boundary.

Minimum:
`create -> planner -> admitted lead -> source router -> fetch -> raw -> document -> evidence -> claim -> verifier -> coverage -> report API/UI`

Rerun må være idempotent.

## Merge-/DONE-gates

Ingen P0 kan settes DONE før:
- relevante unit tests er grønne,
- migrasjon/runtime/integration test er kjørt der det er relevant,
- docs/API/schema-kontrakter er synkronisert,
- integration-reviewer har ingen åpne high-severity funn,
- TASK_QUEUE og WORKLOG beskriver faktisk tilstand.

## Prioritert rekkefølge

1. AQ-020 — claims/evidence schema recovery
2. AQ-021 — research runtime/crawler recovery
3. AQ-023 — planner integrated into research loop
4. AQ-024 — typed source router + executor expansion
5. AQ-025 — UI/API contract and live-state repair
6. AQ-022 — entity resolution
7. AQ-026 — verifier and citation gate
8. AQ-019 — financial claims/evidence integration
9. AQ-027 — full report pipeline
10. AQ-028 — end-to-end MVP proof

AQ-020 og AQ-021 skal starte samtidig via separate subagents.
