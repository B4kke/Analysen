# Task queue

Dette er prosjektets kanoniske arbeidskø for AI-agenter. Ikke opprett parallelle TODO-lister i tilfeldige dokumenter.

## Statusregler
Tillatte statuser:
- `READY`: avgrenset og klar til arbeid.
- `IN_PROGRESS`: én agent arbeider aktivt på oppgaven.
- `BLOCKED`: kan ikke fullføres uten eksplisitt avhengighet; blocker skal beskrives.
- `DONE`: acceptance criteria er oppfylt og nødvendige docs/tests er oppdatert.
- `CANCELLED`: bevisst tatt ut av scope med begrunnelse.

## Arbeidsregel
1. Velg høyest prioriterte `READY`-oppgave uten blocker.
2. Endre til `IN_PROGRESS` før større arbeid starter.
3. Fullfør hele den avgrensede oppgaven før ny oppgave startes.
4. Hvis reell blocker oppstår: sett `BLOCKED`, dokumenter nøyaktig blocker og velg deretter neste `READY`.
5. Når ferdig: verifiser acceptance criteria, oppdater relevante docs/tests, sett `DONE` og skriv én kort linje i `WORKLOG.md`.
6. Nye funn legges som nye `READY`-oppgaver; ikke gjør dem halvveis som sidearbeid.

## Definition of done
En oppgave kan bare settes `DONE` når:
- avtalt scope er implementert/dokumentert,
- ingen kjente halvferdige grener er skjult bak TODO/FIXME,
- relevante tester/valideringer er kjørt eller eksplisitt markert ikke kjørbare,
- dokumentasjon og source-of-truth er synkronisert,
- nye arkitekturvalg er ført i `DECISIONS.md`,
- eventuelle oppfølgingsoppgaver er lagt separat i køen.

## Aktiv kø

### AQ-001 — Scope-first investigation contract
**Status:** DONE
**Prioritet:** P0
**Leveranse:** Canonical scope-modell og expansion policy dokumentert i `INVESTIGATION_SCOPE.md` og kryssreferert i arkitekturen.
**Acceptance:** Moduler, expansion policy, materialitet, relation depth og report semantics er eksplisitte.

### AQ-002 — Trigger-driven follow-up research
**Status:** DONE
**Prioritet:** P0
**Leveranse:** Canonical trigger/query/source-routing/stop-regler dokumentert i `SEARCH_TRIGGERS.md`.
**Acceptance:** Verifier-triggered retry, coverage ledger og dataminimering i queries er definert.

### AQ-003 — Propagate scope/trigger contracts through docs
**Status:** DONE
**Prioritet:** P0
**Leveranse:** `ARCHITECTURE`, `DATA_MODEL`, `AGENT_ORCHESTRATION`, `SEARCH_CRAWLING`, `ENTITY_RESOLUTION`, `FINANCIAL_ANALYSIS`, `UI_UX`, `REPORTING`, `API`, `TESTING`, `IMPLEMENTATION_PLAN`, `README`, `DECISIONS` og `AGENTS.md` er synkronisert med canonical scope/trigger-regler.
**Acceptance:** Ingen av de oppdaterte canonical dokumentene beskriver generell auto-ekspansjon i konflikt med scope/trigger-kontraktene.

### AQ-004 — Implement investigation scope in API/schema
**Status:** DONE
**Verifisert 2026-09-17:** Typed scope-moduler, expansion policy, relasjonsdybde, modulrader med coverage og lead/search-metadata er i API og database. Scope-endringer lagres i én transaksjon med before/after-audit. Regresjonstester viser at innsnevring blokkerer ventende leads utenfor scope med `module_disabled`, bevarer coverage/status, og at en scope-endring som ikke kan auditeres rulles helt tilbake. 50 tester passerer i Compose-nettverket, inkludert denne regresjonssuiten. Planner/lead-generering gjenstår i AQ-005.
**Prioritet:** P0
**Avhenger av:** AQ-003
**Leveranse:** Typed scope modules, expansion policy, max relation depth, module-run/coverage state og lead/search metadata i API/datamodell/database.
**Acceptance:** Deaktivert modul kan ikke planlegges/kalles; scope-endringer auditeres.

### AQ-005 — Implement planner/lead scope gates
**Status:** DONE
**Verifisert 2026-09-17:** Deterministisk lead-admission ligger i `services/lead_gate.py` og håndheves i `POST /api/v1/investigations/{id}/leads`. Passive discovery-triggere kan aldri bli `PENDING`; de lagres som `BLOCKED/passive_trigger_requires_review`. Utenfor scope, uverifisert relasjon, for dyp relasjon og manglende materialitet avvises deterministisk. Hvert forslag auditlogges (`LEAD_PROPOSED`); audit-feil ruller transaksjonen tilbake. Scope-innsnevring blokkerer ventende leads i samme transaksjon som tidligere. Ende-til-ende-tester i `tests/integration/test_lead_proposals.py` viser adgang, refusjon, blokkering utenfor scope og blokkering etter innsnevring. 67 tester passerer i Compose-nettverket; nettlesersmoke består. NIM-planner kobles senere bak samme rute.
**Prioritet:** P0
**Avhenger av:** AQ-004
**Leveranse:** Planner/lead generator får scope, expansion state, information need og source capabilities; blocked actions avvises deterministisk.
**Acceptance:** Discovery alene kan ikke autorisere ekspansjon.

### AQ-006 — Coverage ledger and dynamic report/UI
**Status:** DONE
**Verifisert 2026-09-17:** Rapportseksjoner i `services/report_sections.py` skiller undersøkt, undersøkt med mangler, ikke undersøkt, utilgjengelig og ikke valgt. `stop_reason` som starter med `unavailable` gir utilgjengelig, øvrige stop-årsaker gir ufullstendig. Deaktiverte moduler lander i «Ikke valgt» og presenteres aldri som negative funn. Endpoint `GET /investigations/{id}/report/sections` serverer reelle moduldata med coverage. 7 enhetstester (`test_report_sections.py`) + 2 integrasjonstester mot reell database (`test_report_sections_api.py`); 76 tester grønne totalt i Compose-nettverket. Dynamisk dekningsrapport-UI ble deretter levert i AQ-016; full rapportgenerering gjenstår i AQ-027.
**Prioritet:** P1
**Avhenger av:** AQ-004
**Leveranse:** Per-module coverage, stop reason, not-investigated state, dynamic report sections og context-only graph state.
**Acceptance:** Rapport kan skille undersøkt, ikke undersøkt, ufullstendig og utilgjengelig.

### AQ-007 — Search-trigger eval suite
**Status:** DONE
**Verifisert 2026-09-17:** `tests/test_trigger_eval.py` fanger firma-/person-autoekspansjon uten aktivt scope (parametrised over modul/trigger), kryss-modul-«scope-riding» (WEB_MEDIA-funn kan ikke autorisere COMPANY_NETWORK), CONTEXT_ONLY-autoekspansjon, passive sanksjonsmatch som aldri auto-kjører, målrettet CONTRADICTION fremfor bred søking, FINANCIAL_ANOMALY som krever valgt modul + materialitet med dokumentert årsak, TEMPORAL_GAP kun i valgt HISTORICAL_WEB, budsjett-/kildestop og relasjonsløkke utover dybdelimit. 14 tester; 92 grønne totalt i Compose-nettverket. Eval-suite er deterministisk uten modellkall; NIM-modellens egen trigger-kvalitet evalueres separat når planneren kobles.
**Prioritet:** P1
**Avhenger av:** AQ-005
**Leveranse:** Tester for trigger selection, scope blocking, contradiction retry, no-loop og no-unnecessary-expansion.
**Acceptance:** Test-suite fanger firma-/person-autoekspansjon uten aktivt scope.

### AQ-008 — Kjørbar lokal grunnmur
**Status:** DONE
**Verifisert 2026-09-17:** Bind-mount-avhengigheten er fjernet med innebygd SearXNG-konfigurasjon og navngitt appvolum. Isolert Compose starter alle tjenester, migrering kjører også ved gjentatt oppstart, worker-prosessene starter med registrerte actors. 48 tester passerer i Compose-nettverket (inkludert PostgreSQL-integrasjon), samt Ruff, mypy, TypeScript og Docker-webbygg. Headless Chromium oppretter en syntetisk investigation, åpner og laster detaljsiden på nytt, verifiserer lagret scope og skiller uvalgte moduler fra uutførte valgte moduler. Ingen live research-/bulkimport-jobb er kjørt. Se `TESTING.md` og `DEPLOYMENT.md` for kommandoer og datamigreringshensyn.
**Prioritet:** P0
**Leveranse:** Versjonerte migreringer, validerte konfigurasjoner, fungerende Redis-worker, Compose healthchecks/oppstartsrekkefølge, låste avhengigheter, investigation-skjema i web og CI.
**Acceptance:** Ren database kan migreres; gjentatt upgrade er trygg; API gir korrekt readiness; web oppretter/leser reell investigation med scope; integrerte tester og bygg passerer. Dette er grunnmur, ikke ferdig autonom research-/rapportmotor.

### AQ-009 — Immutable raw evidence og komplett provenance
**Status:** DONE
**Verifisert 2026-09-17:** Hash-adressert raw store (`services/raw_store.py`) skriver originalrespons til `RAW_EVIDENCE_DIR` som `sha256/xx/yy/<digest>` før normalisering. Innholdet er immutable: eksisterende snapshot overskrives aldri, skriving er atomisk via temp-fil + rename. BRREG-ingest fyller nå `raw_storage_key` på dokumentraden, og nøkkelen peker på bytes som hasher til dokumentets `sha256`. Integrasjonstester (`test_raw_evidence.py`) verifiserer at lagret innhold hash-identisk er med payloaden og at gjentatt ingest av samme payload ikke lager duplikater. 78 tester grønne i Compose-nettverket; Ruff/mypy rene; nettlesersmoke består. Full kildeviewer i web og provenance for øvrige kilder er videre arbeid i fase 6.
**Prioritet:** P0
**Leveranse:** Lagre originalrespons før normalisering/LLM, hash-adressert object store, bevar hentetid per snapshot, full kildeviewer og provenance-kontrakttester.
**Acceptance:** Hvert material claim kan spores til lagret kildebelegg og originalsnapshot. BRREG-ingest fyller raw_storage_key med immutable canonical JSON; web-fetch bevarer originale HTTP-bytes.

### AQ-010 — Tilgang og retention før ekstern drift
**Status:** DONE
**Verifisert 2026-09-17:** Auth/RBAC er eksplisitt avvist per ADR-017 (lokal én-operatør-drift, loopback, fast `local-operator`-aktør). Levert i stedet: per-sak eksport (`GET /investigations/{id}/export`), auditert sletting (`DELETE /investigations/{id}` med overlevende `INVESTIGATION_DELETED`-spor) og backup/restore-runbook med verifisert roundtrip (dump → scratch-restore → identiske tellinger: 11 saker, 275 audit-rader, skjema 0002_scope). 4 integrasjonstester (`test_lifecycle.py`); 96 tester grønne totalt.
**Prioritet:** P1
**Leveranse:** Auth/RBAC, operatøridentitet, retention, export/deletion og backup/restore.
**Acceptance:** Ekstern/flerbrukerdrift har saksspesifikk tilgang og dokumentert datalivssyklus. Nåværende Compose er kun lokal énbrukerdrift.

### AQ-011 — NIM planner som forslagsgiver bak lead-gaten
**Status:** DONE
**Verifisert 2026-09-18:** Live NIM-kall mot `nvidia/nemotron-3-super-120b-a12b` med syntetisk kontekst. Første svar var skjemainvalid (`trigger_type: DIRECT_RELATION`, `priority: "high"`) og ble avvist av Pydantic-laget før lagring — deretter skjerpet `prompts/planner.md` med eksakte enum-verdier. Andre kall ga 3 skjemagyldige forslag; gaten slapp 1 gjennom (`WEAK_SOURCE_ONLY` → PENDING) og nektet 2 med presise årsaker (`MEDIA_CORROBORATION` → `passive_trigger_requires_review`, relasjonsforslag uten verifisert relasjon → `invalid_target`). Alt auditlogget (`LEAD_PROPOSED`). Testdata slettet via `DELETE` (204, deretter 404). Nøkkelen ble kun brukt som miljøvariabel og er ikke lagret i repoet.
**Prioritet:** P0
**Leveranse:** Typed planlegger-forslag (`domain/planner.py`), modell-uavhengig planlegger-tjeneste (`services/planner.py`) med Pydantic-validering, deterministisk dedup/cap, modellnavn fra `config/models.yaml`, og live-probe (`scripts/plan_probe.py`).
**Acceptance:** Skjemagyldig output når gaten; skjemainvalid output avvises før lagring; live NIM-kall verifisert mot syntetisk kontekst (se Verifisert-notat over).
**Fremdrift 2026-09-18:** Domene, tjeneste og 9 enhetstester på plass (fake provider). Dataminimering: modellen ser kun måltype/navn, scope, leads og budsjetter — aldri fødselsdata, identifikatorer eller raw evidence.

### AQ-012 — Trigger evaluator og frontier-valg
**Status:** DONE
**Verifisert 2026-09-18:** `services/trigger_evaluator.py` + `services/frontier.py` med typed beslutninger (`domain/trigger_eval.py`). Uverifiserte relasjoner og passive triggere blir `CONTEXT_ONLY`; contradiction på målet gir `VERIFICATION_LEAD`; finansanomalier krever valgt FINANCIALS + materialitet; besvarte/uttømte spørsmål og budsjett gir eksplisitte `STOP_*`. Frontier velger høyeste prioritet blant PENDING innen dybde. 13 tester (`test_trigger_decisions.py`); 118 grønne i Compose-nettverket. Eksekutor (faktisk innhenting) er neste steg.
**Prioritet:** P0
**Avhenger av:** AQ-005, AQ-011
**Leveranse:** Deterministisk trigger-evaluator (`FOLLOW_UP_LEAD`, `VERIFICATION_LEAD`, `CONTEXT_ONLY`, `BLOCKED_BY_SCOPE`, `STOP_*`) og frontier-velger som ordner PENDING-leads etter prioritet innen scope/budsjett. Ingen live innhenting — eksekutor kommer senere.
**Acceptance:** Relasjonsforslag uten verifisert relasjon blir `CONTEXT_ONLY`, aldri auto-kjøring; contradiction gir målrettet verifikasjon; løkker og budsjett stopper deterministisk.

### AQ-013 — Lead-eksekutor for valgte leads
**Status:** DONE
**Verifisert 2026-09-18:** `services/lead_executor.py` + `POST /investigations/{id}/leads/{lead_id}/execute` kjører `brreg_organization_lookup` mot eksplisitt mål: PENDING → RUNNING → COMPLETED med evidence/claims, coverage-økning og `LEAD_EXECUTED`-audit. Innsnevret scope blokkerer før fetch (`module_disabled`, fetch aldri kalt); ukjent lead-type → FAILED `unsupported_lead_type`; kildefeil → FAILED `source_error:*`; gjenkjøring henter ikke på nytt. 6 integrasjonstester (`test_lead_execution.py`); 125 grønne totalt i Compose-nettverket.
**Prioritet:** P0
**Avhenger av:** AQ-012
**Leveranse:** Eksekutor som kjører valgt frontier-lead (BRREG-måloppslag først) gjennom lead-gaten ved verktøygrensen, lagrer evidence, oppdaterer lead-status/coverage og auditerer. Støttede lead-typer eksplisitt allowlisted; alt annet avvises.
**Acceptance:** PENDING → RUNNING → COMPLETED/FAILED med coverage-oppdatering; innsnevret scope blokkerer før fetch; feil hos kilde gir FAILED med årsak, aldri stille suksess.

### AQ-014 — Mobiltilgang på samme nett via Docker
**Status:** DONE
**Verifisert 2026-09-18:** `BIND_ADDRESS` (default loopback) binder web/API på LAN ved opt-in; CORS-validering godtar kun loopback + RFC1918 (offentlige verter, wildcard og https avvises — testet). Separat LAN-stack verifisert: web 200 og API ready på LAN-IP, preflight fra LAN-opprinnelse 200, fra offentlig opprinnelse 400, og web-bundel peker på LAN-API-URL (gjenoppbygd med `--build-arg`, dokumentert at `up --build` mister ad-hoc args). Postgres/Redis/SearXNG forblir på loopback. Oppskrift + advarsel (kun klarerte nett, ingen auth) i `DEPLOYMENT.md`.
**Prioritet:** P1
**Leveranse:** Opt-in LAN-binding (`BIND_ADDRESS`), CORS for private nettadresser (RFC1918), dokumentert oppskrift for mobil på samme nett. Default forblir loopback.
**Acceptance:** Web og API svarer på maskinens LAN-IP; CORS-preflight fra LAN-opprinnelse passerer; web-bundel peker på LAN-API-URL. Kun klarerte nett — ingen auth per ADR-017.

### AQ-015 — Worker-basert research-loop
**Status:** DONE
**Verifisert 2026-09-18:** `services/research_loop.py` kjører én avgrenset pass: frontier-valg → trigger-evaluator → eksekutor, til frontier er tom, budsjett oppbrukt eller maks leads nådd. Evaluator-nekt (CONTEXT_ONLY/BLOCKED_BY_SCOPE) parkerer leadet som BLOCKED med årsak; hvert lead committes separat; passet auditerer `RESEARCH_PASS_COMPLETED`-sammendrag. Dramatiq-actor + `POST /investigations/{id}/research/run` (202, uten sideeffekter i test via patchet send). 6 integrasjonstester (`test_research_loop.py`, fake fetch — ingen live-kall); 131 grønne totalt i Compose-nettverket.
**Prioritet:** P0
**Avhenger av:** AQ-013
**Leveranse:** Dramatiq-actor + `POST /investigations/{id}/research/run` (202) som kjører én avgrenset research-pass over admitted frontier.
**Acceptance:** En pass fullfører kjedede PENDING-leads, stopper deterministisk, rører aldri BLOCKED-leads, og gjør ingen live-kall i tester.

### AQ-016 — Rapport-UI i web
**Status:** DONE
**Verifisert 2026-09-18:** Rapportside `/investigations/[id]/report` rendrer de fem seksjonene fra API-et med tellinger, coverage (søk/dokumenter/kilder) og stoppårsaker; «Ikke valgt» forklarer eksplisitt at fravær av funn ikke er negativt funn. Lenket fra detaljsiden. Nettlesersmoke dekker opprettelse → detalj → reload → rapport med seksjonsoverskrifter og modulnavn.
**Prioritet:** P1
**Avhenger av:** AQ-006
**Leveranse:** Rapportside per investigation som rendrer de fem seksjonene fra `GET /report/sections` med coverage og stop-årsaker, lenket fra detaljsiden.
**Acceptance:** Siden skiller undersøkt/ufullstendig/ikke undersøkt/utilgjengelig/ikke valgt; uvalgte moduler presenteres aldri som negative funn; nettlesersmoke dekker siden.

### AQ-017 — Research-start fra UI-et
**Status:** DONE
**Verifisert 2026-09-18:** «Start research-pass»-knapp på detaljsiden legger worker-pass på kø via `POST /research/run` og viser status. Hjemmesidens utdaterte «orkestratoren kommer senere»-tekst oppdatert. Smoke dekker kølegging. Sidespor avdekket at nativ API serverte gammel kode uten research-ruten (404 → «Not Found» i UI); dokumentert restart-krav i `DEPLOYMENT.md`.
**Prioritet:** P0
**Avhenger av:** AQ-013
**Leveranse:** Dramatiq-actor + `POST /investigations/{id}/research/run` (202) som kjører én avgrenset research-pass: frontier-valg → trigger-evaluator → eksekutor, til frontier er tom, budsjett oppbrukt eller maks leads nådd. Hvert lead committes separat; passet auditerer sammendrag.
**Acceptance:** En pass fullfører kjedede PENDING-leads, stopper deterministisk, rører aldri BLOCKED-leads, og gjør ingen live-kall i tester (fake fetch).

## Hygiene
Fullførte oppgaver beholdes her for sporbarhet inntil en senere opprydding flytter eldre historikk til changelog/release notes. En oppgave skal aldri bli stående `IN_PROGRESS` etter at leveransen er avsluttet.

### AQ-018 — PDF extraction pipeline
**Status:** DONE
**Verifisert 2026-09-18:** PDF text/layout extraction, table extraction, OCR fallback, deterministic financial ratios, year-over-year analysis, auditor notes/going-concern detection. 18 enhetstester + 6 integrasjonstester (`test_pdf_extraction.py`); 131 tester grønne i Compose-nettverket. Raw snapshots i object store bevares via hash-adressert `raw_store`.

### AQ-019 — Finansanalyse-modul
**Status:** DONE
**Verifisert 2026-09-19:** `services/financial_claims.py` mapper deterministisk ratios/YoY/revisjonsnotater/going-concern til claims (aldri negative funn ved manglende omtale) og persisterer via `claims_evidence.upsert_claim`. 6 tester; dekkes av full suite (291 grønne).
**Avhenger av:** AQ-018, AQ-020, AQ-021
**Leveranse:** Finansielle nøkkeltall (profitability, liquidity, solvency, efficiency), år-over-år analyse, regnskapsuttrekk, revisjonsmerknader, going-concern deteksjon — alt som claims med evidence.
**Acceptance:** Nøkkeltall beregnes deterministisk i kode (ingen LLM); år-over-år forandringer med null-base håndtering; revisjonsmerknader og going-concern detekteres og lagres som claims.

### AQ-020 — Claims/Evidence pipeline og provenance
**Status:** DONE
**Prioritet:** P0
**Verifisert 2026-09-18:** Fresh/legacy/gjentatt migrering og ekte PostgreSQL repository-roundtrip passerer. Canonical statuser, evidens fra riktig sak, kompatible supports/contradicts-koblinger, immutable første dokumentprovenance, alias-duplikater og evidence-baserte relationships er kontrollert med regresjonstester og uavhengig Luna-review. Samlet reparasjonssuite: 247 tester mot isolert PostgreSQL/Redis; web-fetch-kontrakt og runtime-image ferdigstilles separat i AQ-021. Multi-subject claim-fingerprint er særskilt oppfølging AQ-030.
**Agent:** `db-provenance`
**Reopened 2026-09-18 etter kodeaudit, bekreftet av orchestrator:** Baseline/0003 er inkonsistente (0001 oppretter allerede sources/documents/evidence/claims/claim_evidence/entities/aliases/relationships; 0003s `CREATE TABLE IF NOT EXISTS` er stille no-ops). Grønn suite dekket aldri det nye repoet. Reparasjonen bruker: `0004_claims_reconcile` (ALTERs + backfill, dropper duplikat-tabellen `entity_relations`), repo omskrevet mot kanonisk skjema (fingerprint, normalized_alias, relation-mapping), roundtrip-test verifisert.
**Leveranse:** Reparert Alembic-kjede og én canonical Source -> Document -> Evidence -> Claim -> ClaimEvidence-kontrakt med immutable raw provenance.
**Acceptance:** Fresh og legacy database migrerer til head; gjentatt upgrade er trygg; ekte PostgreSQL repository-roundtrip passerer; claim/evidence-status og constraints er konsistente mellom SQL/Pydantic/repository; stored raw bytes hasher til dokumentets SHA.

### AQ-021 — SearXNG discovery og dokumentfetch
**Status:** DONE
**Prioritet:** P0
**Verifisert 2026-09-18:** Bygget API/worker research-runtime med låste avhengigheter og Chromium; 5/5 ekte Trafilatura/Crawl4AI/Playwright-regresjoner passerer uten nettverk og uten skip (Luna). Java, PDF-biblioteker og norsk OCR verifisert. Lokalt web-fixture går gjennom uendret fetch-resultat til ekte PostgreSQL Document/Evidence med URL/tid/raw hash. 11 ingest-gate-tester avviser discovery-only, corrupt raw, feil metadata og kildepolicy før SQL.
**Agent:** `research-runtime`
**Reopened 2026-09-18 etter kodeaudit, delvis utbedret:** `_store_raw`-buggen (lagret URL i stedet for innhold) er fikset og testet. Fullført: per-hop revalidering, robots/rate/concurrency/request-/sidebudsjett, DNS/IP-pinnet transport, streaminggrenser og research-deps/browser i runtime-image.
**Leveranse:** Kjørbar research-runtime med SearXNG discovery, sikker fetch-waterfall, immutable raw web snapshots og eksplisitte crawl-budsjetter.
**Acceptance:** Docker worker/API-path som kjører research har nødvendige pakker/browser; local fixture integration dekker redirect/private redirect/content limit/failure; fetched content lagres og hash-verifiseres; snippets kan aldri bli evidence.

### AQ-022 — Entity resolution med negative signals
**Status:** DONE
**Verifisert 2026-09-19:** `services/entity_resolution.py` utvidet med fødselsår-konflikt som hard negative, geografisk mismatch-penalty (-0.25) og strukturell name-only-cap under PROBABLE_MATCH-terskel. `repositories/entity_resolution.py` persisterer scorer-kandidater med negative signaler; manuell review via `GET/POST .../resolution/...` tillater kun PROBABLE_MATCH → MATCH/NOT_MATCH og UNRESOLVED → NOT_MATCH (ellers 409), alt auditert. 11 scoring-enhetstester + 7 review-integrasjonstester; 188 grønne totalt i Compose. Kandidat-tabellen er ny (ingen baseline-konflikt); entities-innsetting bruker kun nullable kolonner. Fikset samtidig `_store_raw`-bug og versjonsavhengig `canonicalize_url`-oppførsel.


### AQ-023 — Planner integrert i research-loop
**Status:** DONE
**Verifisert 2026-09-19:** Tom frontier trigger én planner-kall per pass; forslag valideres (skjemainvalid → `planner_output_rejected`), duplikater av alle eksisterende leads hoppes over, resten innvilges via gaten. 4 nye integrasjonstester (plan→admit→execute, invalid-output-stopp, rerun-dedup, out-of-scope-blokk); `ResearchPassSummary` utvidet med `planned` (default 0, bakoverkompatibel). Fant og fikset kontraktsdrift: API-modellen droppet `planned` ved lesing. 291 grønne totalt i Compose.
**Avhenger av:** AQ-020
**Leveranse:** Ny/tom investigation kan gå fra stored scope til typed planner proposals, deterministisk lead admission, frontier/trigger-evaluering og checkpointed pass.
**Acceptance:** En tom frontier kan planlegge lovlige leads; schema-invalid planner-output avvises; `max_relation_depth` kommer fra investigation; budget/repeated-loop/STOP er deterministiske; restart/rerun dupliserer ikke terminalt arbeid.
**Recovery etter AQ-025:** Durable outbox for REQUESTED→publish, hard-crash/stale RUNNING, korrelert replay av job_id og terminal-jobb-dedup må være eksplisitt. Ikke gjetting av jobbliveness eller stille nullstilling av aktivitet.

### AQ-024 — Typed source router og executor-utvidelse
**Status:** DONE
**Verifisert 2026-09-19:** `services/source_router.py` ruter hver lead-type til nøyaktig én executor; `ExecutorTools`-bundle injiserer capabilities (manglende verktøy → `executor_unavailable`, aldri krasj). Nye executors: SearXNG-discovery (kun metadata, snippets aldri evidence), web-fetch (immutable raw snapshots, ingen claims), PDF-prosessering (ekstraksjon til dokumentet). 7 router-tester + 5/5/6 executor-tester + 4 dispatch-integrasjonstester; 324 grønne totalt i Compose. Levert av 3 subagents + orchestrator-dispatch, integrert verifisert samlet.
**Avhenger av:** AQ-020, AQ-021, AQ-023, AQ-030
**Leveranse:** Allowlisted source router og executors for BRREG target/roles, SearXNG discovery, web document fetch og PDF/document processing.
**Acceptance:** Lead type rutes eksplisitt til én executor; ingen arbitrary tool execution; alle fetch-paths går gjennom scope/trigger/provenance/coverage; source-feil gir eksplisitt FAILED/BLOCKED/coverage state.

### AQ-025 — UI/API-kontrakter og live investigation-state
**Status:** DONE
**Prioritet:** P0
**Verifisert 2026-09-18:** Korrelert pass-state og konsistent PostgreSQL-detaljsnapshot, faktiske leads/entities/claims/evidence og dokumenttellinger, saksgatet hash-verifisert råkildenedlasting og korrekt opprettelsesskjema. UI beholder data ved refresh-feil, forkaster gamle svar og avventer hver automatisk poll. Uavhengig integration-review godkjent. 281 tester uten skip i research-runtime med ekte PostgreSQL/Redis; Ruff, mypy (67 filer), TypeScript, produksjonsbygg og Chromium company/person/domain/report/stale/provenance-smoke ved 390 px passerer. Fem sekunders GET-latens med faktisk worker-fullføring passerer uten reload.
**Agent:** `ui-reporting`
**Avhenger av:** AQ-004
**Leveranse:** Reparer frontend request-shapes og erstatt statiske placeholder-states med reell worker/module/claim/evidence state.
**Acceptance:** `known_orgnrs`/`known_organizations` sendes som arrays; web kan opprette company/person targets med valgfrie felter; detaljsiden viser faktisk state og sier aldri "ikke startet"/"ingen funn" i strid med database; mobil smoke passerer.

### AQ-026 — Verifier, contradiction og citation gate
**Status:** DONE
**Verifisert 2026-09-19:** Deterministisk verifier (`services/verifier.py`, subagent-leveranse): citation-gate (aldri SUPPORTED uten reell evidensrad), contradiction-par på samme subject, missing-information needs. Ruter: `POST claims/{id}/verify`, `GET contradictions`, `POST claims/{id}/verification-lead` (CONTRADICTION/WEAK_SOURCE_ONLY gjennom gaten). Sannferdig relasjonskontrakt: PARTIALLY_SUPPORTED aksepterer `context`-relasjon (repo-regel oppdatert, workaround fjernet). 29 enhetstester + 16 integrasjonstester; 369 grønne totalt i Compose.
**Avhenger av:** AQ-020, AQ-023
**Leveranse:** Evidence-entailment verifier med typed status, contradiction handling og missing-information feedback som går tilbake gjennom trigger/scope gate.
**Acceptance:** Material claim uten evidence kan ikke bli supported/reviewed; invalid modelloutput failer lukket; contradiction genererer målrettet verification need; SQL/Pydantic/report-status er konsistente.

### AQ-027 — Full report pipeline
**Status:** DONE
**Verifisert 2026-09-19:** `domain/report.py` som felles kontrakt; `services/report_build.py` bygger deterministisk report-JSON fra claims+coverage (UNVERIFIED_LEAD aldri funn, context-only kun navn); `services/report_render.py` rendrer samme dokument til HTML (lang=nb, escapet, ingen JS) og PDF (fpdf2, deterministisk). Ruter `GET report.json/.html/.pdf` med 404-oppførsel. 22 builder-tester + 10 renderer-tester + endpoint-tester; fpdf2 låst i requirements.lock. Levert av 2 subagents parallelt, integrert verifisert samlet.
**Avhenger av:** AQ-019, AQ-025, AQ-026
**Leveranse:** `verified claims + coverage -> report JSON -> HTML -> PDF` med norsk standardrapport og klikkbar provenance.
**Acceptance:** Rapport skiller supported/partial/contradicted/insufficient og investigated/not-investigated; hver material finding har evidence; context-only entities fremstilles ikke som full research; HTML/PDF kommer fra samme report JSON.

### AQ-028 — End-to-end MVP proof
**Status:** DONE
**Verifisert 2026-09-19:** `tests/integration/test_e2e_mvp.py` beviser hele kjeden mot ekte PostgreSQL (fakes kun på nettverk/modell-grensen): company-case (create → planner → gate → frontier → router → fetch → raw → document → evidence → claim → verifier → coverage → report.json med citation url+sha) og person-case (negative signaler + manuell MATCH-review + 409 ved tvang), begge med rerun-idempotens. 406 grønne totalt i Compose.
**Reviewer:** `integration-reviewer`
**Avhenger av:** AQ-020, AQ-021, AQ-022, AQ-023, AQ-024, AQ-025, AQ-026
**Leveranse:** Reell vertical integration suite for minst én company-case og én person/identity-case.
**Acceptance:** `create -> planner -> gate -> frontier -> source router -> fetch -> raw -> document -> evidence -> claim -> verifier -> coverage -> report API/UI` passerer mot ekte PostgreSQL/worker-state. Bare external network/model boundary kan fakes. Rerun er idempotent.


### AQ-029 — Readiness følger pakket migreringshead
**Status:** DONE
**Prioritet:** P0
**Verifisert 2026-09-18:** Settings bruker pakket Alembic-head med eksplisitt miljøoverstyring. Unit-tester av eldre/ukjent revisjon og ekte PostgreSQL-readiness på head passerer. Ingen eksisterende brukerdata eller kjørende prosjektstack er endret.
**Leveranse:** Fjern foreldet default `0002_scope`; avled forventet schema fra pakkens Alembic-head og behold eksplisitt konfigurasjonsoverstyring.
**Acceptance:** Gjeldende head er ready, eldre/ukjent schema feiler lukket; runtime- og ekte PostgreSQL-sjekk passerer uten endringer i eksisterende prosjektdata.

### AQ-030 — Claim-dedup på tvers av subjects
**Status:** DONE
**Verifisert 2026-09-19:** Fingerprint inkluderer kanonisk subject-segment (`claims_evidence.claim_fingerprint` + BRREG-forfatter samlet); migrering 0005 recomputer eksisterende fingerprints på plass (frossen formel, IDer og evidenslenker bevart). 3 fingerprint-enhetstester, 2 subject-integrasjonstester (separate claims + idempotent re-ingest), legacy-migreringstest med lenkebevaring. 0004-testene pint til 0004 der de isolerer den migreringen. 297 grønne totalt i Compose.
**Leveranse:** Inkluder canonical subject-identitet i claim-fingerprint og migrer eksisterende fingerprints uten å miste evidenskoblinger.
**Acceptance:** To forskjellige entities med samme predicate/verdi i én investigation beholder separate claims; re-ingest av samme subject er idempotent. Multi-entity source routing skal ikke aktiveres før denne kontrakten er verifisert. Dagens executor er begrenset til ett eksplisitt BRREG-mål.
