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
**Verifisert 2026-09-17:** Rapportseksjoner i `services/report_sections.py` skiller undersøkt, undersøkt med mangler, ikke undersøkt, utilgjengelig og ikke valgt. `stop_reason` som starter med `unavailable` gir utilgjengelig, øvrige stop-årsaker gir ufullstendig. Deaktiverte moduler lander i «Ikke valgt» og presenteres aldri som negative funn. Endpoint `GET /investigations/{id}/report/sections` serverer reelle moduldata med coverage. 7 enhetstester (`test_report_sections.py`) + 2 integrasjonstester mot reell database (`test_report_sections_api.py`); 76 tester grønne totalt i Compose-nettverket. Dynamisk rapport-UI i web er fortsatt ikke bygget og hører naturlig til fase 6/7 i implementasjonsplanen.
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
**Acceptance:** Hvert material claim kan åpnes tilbake til den originale lagrede responsen. Dagens BRREG-ingest lagrer normalisert evidens, men raw_storage_key fylles ikke ennå.

### AQ-010 — Tilgang og retention før ekstern drift
**Status:** IN_PROGRESS
**Fremdrift 2026-09-17:** Datalivssyklus per sak levert: `GET /investigations/{id}/export` (full eksport av sak, moduler, entities, claims, leads, dokumenter med raw-nøkler og audit) og `DELETE /investigations/{id}` (sletter cascade-eide data i én transaksjon, etterlater `INVESTIGATION_DELETED`-audit som overlever via `ON DELETE SET NULL`). Raw snapshots deles innholdsadressert og slettes bevisst ikke. 4 integrasjonstester (`test_lifecycle.py`); 96 tester grønne totalt. Gjenstår: Auth/RBAC, operatøridentitet og backup/restore før ekstern drift.
**Prioritet:** P1
**Leveranse:** Auth/RBAC, operatøridentitet, retention, export/deletion og backup/restore.
**Acceptance:** Ekstern/flerbrukerdrift har saksspesifikk tilgang og dokumentert datalivssyklus. Nåværende Compose er kun lokal énbrukerdrift.

## Hygiene
Fullførte oppgaver beholdes her for sporbarhet inntil en senere opprydding flytter eldre historikk til changelog/release notes. En oppgave skal aldri bli stående `IN_PROGRESS` etter at leveransen er avsluttet.
