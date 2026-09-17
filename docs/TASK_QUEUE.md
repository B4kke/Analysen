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
**Prioritet:** P0
**Avhenger av:** AQ-005, AQ-011
**Leveranse:** Deterministisk trigger-evaluator (`FOLLOW_UP_LEAD`, `VERIFICATION_LEAD`, `CONTEXT_ONLY`, `BLOCKED_BY_SCOPE`, `STOP_*`) og frontier-velger som ordner PENDING-leads etter prioritet innen scope/budsjett. Ingen live innhenting — eksekutor kommer senere.
**Acceptance:** Relasjonsforslag uten verifisert relasjon blir `CONTEXT_ONLY`, aldri auto-kjøring; contradiction gir målrettet verifikasjon; løkker og budsjett stopper deterministisk.

## Hygiene
Fullførte oppgaver beholdes her for sporbarhet inntil en senere opprydding flytter eldre historikk til changelog/release notes. En oppgave skal aldri bli stående `IN_PROGRESS` etter at leveransen er avsluttet.
