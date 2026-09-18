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
**Status:** READY  
**Prioritet:** P0  
**Avhenger av:** AQ-003  
**Leveranse:** Typed scope modules, expansion policy, max relation depth, module-run/coverage state og lead/search metadata i API/datamodell/database.  
**Acceptance:** Deaktivert modul kan ikke planlegges/kalles; scope-endringer auditeres.

### AQ-005 — Implement planner/lead scope gates
**Status:** READY  
**Prioritet:** P0  
**Avhenger av:** AQ-004  
**Leveranse:** Planner/lead generator får scope, expansion state, information need og source capabilities; blocked actions avvises deterministisk.  
**Acceptance:** Discovery alene kan ikke autorisere ekspansjon.

### AQ-006 — Coverage ledger and dynamic report/UI
**Status:** READY  
**Prioritet:** P1  
**Avhenger av:** AQ-004  
**Leveranse:** Per-module coverage, stop reason, not-investigated state, dynamic report sections og context-only graph state.  
**Acceptance:** Rapport kan skille undersøkt, ikke undersøkt, ufullstendig og utilgjengelig.

### AQ-007 — Search-trigger eval suite
**Status:** READY  
**Prioritet:** P1  
**Avhenger av:** AQ-005  
**Leveranse:** Tester for trigger selection, scope blocking, contradiction retry, no-loop og no-unnecessary-expansion.  
**Acceptance:** Test-suite fanger firma-/person-autoekspansjon uten aktivt scope.

### AQ-008 — Nasjonalbiblioteket + norske åpne kilder
**Status:** DONE  
**Prioritet:** P0  
**Bestilt eksplisitt:** 2026-09-18  
**Leveranse:** Implementer rettighetsbevisst adapter for Nasjonalbibliotekets katalog/fulltekstsøk, item-oppslag og tillatte OCR-fragmenter. Dokumenter og prioriter ytterligere norske åpne kilder med tilgangs-/lisensstatus og konkrete brukstilfeller.  
**Acceptance:** NB-search gir typed resultater; begrenset materiale kan ikke hentes som OCR-evidence via adapteren; source-config og source-routing er oppdatert; kontrakttester dekker åpent og begrenset materiale; nye kilder er kategorisert som aktive kandidater eller senere adaptere uten å late som de allerede er implementert.

### AQ-009 — Høyverdige norske no-key-adaptere
**Status:** READY  
**Prioritet:** P1  
**Avhenger av:** AQ-004  
**Leveranse:** Typed adapters + fixtures/contract-tests for Finanstilsynets virksomhetsregister, Arbeidstilsynets bemannings-/renholdsregistre, DiBK sentral godkjenning og Kartverkets adresse-API.  
**Acceptance:** Hver adapter har eksplisitt capability/access/retention-policy; orgnr/adresse normaliseres deterministisk; source config aktiveres først når kontrakttestene er grønne; sektorregistre kalles bare ved relevant scope/trigger.

### AQ-010 — Norske API-er med nøkkel/registrering
**Status:** READY  
**Prioritet:** P2  
**Leveranse:** Klientkontrakter og secret-konfig for Patentstyret, Doffin Public API og eInnsyn, uten hardkodede credentials.  
**Acceptance:** Unit/fixture-tests fungerer uten secrets; live smoke-tests er eksplisitt optional/secret-gated; ingen source markeres aktiv uten nødvendig operatørkonfig.

### AQ-011 — Norske sektor-/asset-/tilskuddskilder
**Status:** READY  
**Prioritet:** P2  
**Avhenger av:** AQ-004  
**Leveranse:** Prioriter og implementer relevante adapters for Mattilsynet Smilefjes, Fiskeridirektoratet, Luftfartstilsynets luftfartøyregister, Tilskudd.no og Sokkeldirektoratet.  
**Acceptance:** Kildene er trigger-/sektorstyrte, ikke default person-sweep; claims beholder dato/status/proveniens og fravær i et nisjeregister tolkes ikke som bevis på fravær.

## Hygiene
Fullførte oppgaver beholdes her for sporbarhet inntil en senere opprydding flytter eldre historikk til changelog/release notes. En oppgave skal aldri bli stående `IN_PROGRESS` etter at leveransen er avsluttet.
