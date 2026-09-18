# Arkitektur

## Prinsipp
`user scope -> LLM suggests -> policy/scope gate -> tools retrieve -> code normalizes/calculates -> evidence supports -> verifier checks -> human decides`.

`docs/INVESTIGATION_SCOPE.md` er autoritativ for hva en investigation får undersøke. `docs/SEARCH_TRIGGERS.md` er autoritativ for når og hvorfor systemet får søke videre.

## Logical view
```text
Next.js UI
   |
Investigation scope + expansion policy
   |
FastAPI Investigation API
   |
Orchestrator -----------------------------+
   |                                      |
   +-> Scope Gate / Source Router         |
   |      |                               |
   |      +-> Source adapters -> raw evidence
   |      +-> Search/crawl ----> raw evidence
   |      +-> Documents -------> raw evidence
   |                                      |
                         extraction       |
                             |            |
                      entity resolution   |
                             |            |
              +--------------+---------+  |
              |                        |  |
          entity graph              claims|
              |                        |  |
              +------ lead frontier <--+  |
                          |             |
                    Trigger Evaluator   |
                          |             |
                scope/policy/budget gate|
                          |             |
                    verification -------+
                          |
                  report JSON -> HTML/PDF
```

## Scope gate
Før enhver research-action må scheduler/orchestrator kontrollere:
- aktiv scope-modul,
- expansion policy og relation depth,
- konkret `information_need`,
- policy/tilgang,
- budsjett og dedup/loop-state.

Discovery av en entity gir ikke automatisk rett til å undersøke den videre. Relaterte entities kan beholdes som `CONTEXT_ONLY`.

## Trigger evaluator
Nye funn, konflikter eller manglende evidens kan opprette nye leads gjennom eksplisitte trigger classes i `SEARCH_TRIGGERS.md`. Trigger evaluator skal også kunne konkludere `STOP` når informasjonen er tilstrekkelig, sporet er utenfor scope eller nye treff ikke gir informasjonsverdi.

Verifier kan opprette et målrettet verification lead når en material claim mangler nødvendig evidens. Den skal ikke starte generell bred research på egen hånd.

## Services
### web
Next.js/TypeScript, Tailwind/shadcn, TanStack Query, Cytoscape.js.

### api
FastAPI, Pydantic, SQLAlchemy/asyncpg. Eier domene-API, authorization, investigation scope, policies og read models.

### worker
Købaserte jobs for bulkimport, search, fetch, extract, resolve, verify, analyse og rapport. Jobs mottar eksplisitt scope/module/lead-kontekst.

### PostgreSQL
Canonical state for investigations, scope/module runs, entities, relationships, sources, documents, evidence, claims, leads og audit. pgvector kun for retrieval/candidate generation.

### Redis
Queue, distributed locks, kortvarig cache og rate limiting.

### object/raw store
MVP kan bruke lokalt filvolum. Senere S3/MinIO. Raw evidence adresseres med hash og skal være immutable snapshots.

## State machine
`CREATED -> IDENTIFYING -> RESEARCHING -> VERIFYING -> REPORTING -> REVIEW_REQUIRED -> FINAL`.
Feiltilstander er resumable og jobber skal være idempotente.

Scope-endring er en auditert state-endring som kan åpne/lukke modul-leads uten å slette tidligere evidens automatisk.

## Investigation frontier
Leads har type, value/entity_id, reason, `scope_area`, `trigger_type`, `information_need`, source claim, priority, depth og status. Scheduler velger høyest forventet informasjonsverdi innen scope, policy og budsjett.

## Budgets
Konfigurer per investigation: max depth, max relation depth, max URLs, max per-domain fetches, max wall-clock, max model calls/tokens og max unresolved leads. Budgets finnes for stabilitet selv når API-et er gratis.

## Coverage
Hver aktiv scope-modul fører coverage ledger med kilder/providers forsøkt, query classes, dokumenter, tidsrom, stop reason og kjente gaps. Dette brukes i rapportens metode/søkeomfang.

## Canonical vs projections
PostgreSQL er canonical. Cytoscape-data, embeddings, fulltekstindeks og eventuelle fremtidige graph databases er projections som kan bygges på nytt.

## Provider abstraction
`LLMProvider`, `EmbeddingProvider`, `SearchProvider`, `CrawlerProvider`, `SourceAdapter`, `ObjectStore`. Ingen business logic skal anta én leverandør.


## Implementert grunnmur og videre grenser

Den kjørbare vertikale flyten er `Next.js → FastAPI → scope/audit → PostgreSQL`. `/ready` kontrollerer databaseskjema og Redis. Compose kjører Alembic som en egen oppstartsjobb. Pydantic validerer modell-/kilde-/policy-YAML før API starter. NIM-nøkkel kreves først ved inferens.

Investigations opprettes med eksplisitte moduler (standard ingen). Scope-oppdatering er én transaksjon med before/after-audit og bevaring av eksisterende coverage/evidens. Innhentingsruten låser samme investigation-rad mens autorisasjon og innhenting pågår, slik at scope-endringer og nye actions serialiseres. Urelaterte investigations blokkerer ikke hverandre.

BRREG-ingest tillates foreløpig bare for et entydig company/organization-mål med ett `known_orgnrs` og aktiv `BUSINESS_ROLES`. Generiske BRREG GET-ruter er manuelle registeroppslag, ikke del av en automatisk investigation. Utvidelse til relaterte entities krever senere scheduler/materiality-workflow; discovery eller et oppgitt personnavn gir ingen autorisasjon.

`Lead`, `SearchMetadata`, module coverage og expansion states har typed kontrakter og databasestruktur. Deterministisk frontier/trigger-evaluator, BRREG target-executor, avgrenset worker-pass med integrert NIM-planner og dekningsrapport er implementert. Flere source executors, entailment-verifier og full rapportmotor gjenstår i arbeidskøen.

## Lead admission (AQ-005)

Planner/LLM kan bare foreslå leads via `POST /api/v1/investigations/{id}/leads`. Ruten låser investigation-rad og kjører deterministisk admission i `services/lead_gate.py` før lagring. Passive discovery-triggere (`NEW_VERIFIED_ALIAS`, `MEDIA_CORROBORATION`, `SANCTIONS_CANDIDATE`) lagres aldri som kjørbare; de blir `BLOCKED/passive_trigger_requires_review`. Refuserte leads lagres som `BLOCKED` med gate-årsak og audit; `LEAD_PROPOSED` audit er ikke frivillig — en transaksjon uten audit rulles tilbake. Scope-innsnevring blokkerer fortsatt ventende leads samme transaksjon. Det finnes ingen rute som oppretter `PENDING`-leads utenom gaten; NIM-planneren er koblet som én av flere forslagsgivere bak samme rute og brukes av worker-passet ved tom frontier (AQ-023).

## Trigger evaluator, frontier og eksekutor (AQ-012/AQ-013)

`services/trigger_evaluator.py` ruter hvert forslag til én typed beslutning: `FOLLOW_UP_LEAD`, `VERIFICATION_LEAD`, `CONTEXT_ONLY`, `BLOCKED_BY_SCOPE` eller `STOP_*`. Uverifiserte relasjoner og passive triggere blir `CONTEXT_ONLY` — aldri auto-kjøring. Contradiction gir målrettet `VERIFICATION_LEAD` på samme entity. `services/frontier.py` velger høyeste prioritet blant `PENDING`-leads innen dybde og budsjett. `services/lead_executor.py` kjører valgte leads via `POST /investigations/{id}/leads/{lead_id}/execute`: lead-typen rutes via `services/source_router.py` til nøyaktig én executor (`brreg_organization_lookup`, `searxng_discovery`, `web_document_fetch`, `pdf_document_process`). SearXNG-discovery persisterer kun søkemetadata (snippets blir aldri evidence); web-fetch lagrer immutable raw snapshots uten claims; PDF-prosessering ekstraherer tekst/tabeller til dokumentet. Gaten sjekkes på nytt ved verktøygrensen, og hvert utfall (COMPLETED/BLOCKED/FAILED) oppdaterer status, coverage og audit. Evaluator, velger og eksekutor er deterministiske og modellfrie.

## Research-loop (AQ-015/AQ-023)

`services/research_loop.py` kjører én avgrenset pass per kall: velg høyeste prioritet fra frontier, evaluer trigger, kjør eller parker leadet, commit separat per lead, stopp ved tom frontier/oppbrukt budsjett/nådd lead-cap. Ved tom frontier spør passet NIM-planneren én gang: forslag valideres mot typed skjema, duplikater av eksisterende leads (pending eller terminale) hoppes over, og resten innvilges gjennom den deterministiske gaten før loopen fortsetter. Skjemainvalid output og planner-feil stopper passet med eksplisitt årsak, aldri krasj. Passet auditerer `RESEARCH_PASS_COMPLETED` med sammendrag inklusiv `planned`-telling. `POST /investigations/{id}/research/run` legger passet på Dramatiq-køen (202); workeren kjører med live BRREG-adapter og live planner når NIM-nøkkel er konfigurert, ellers uten planner. Evaluator-nektede leads parkeres som `BLOCKED` med årsak slik at passet terminerer; de kan foreslås på nytt ved scope-endring.

## Research-runtime og provenance (AQ-020/AQ-021/AQ-029)

API/worker bygges med en research-lås som bevarer runtime-pinnene, med native dokumentbiblioteker og Chromium. Originale bytes går i hash-adressert raw store før ekstraksjon; første Document-provenance bevares ved gjenbruk. Trafilatura/Crawl4AI ekstraherer offline. Browseren har ingen selvstendig nettverkstilgang: ressursene hentes gjennom samme offentlige IP-pinnede, robots-/budsjettkontrollerte HTTP-grense (ADR-019). Web-ingest validerer raw bytes/hash/nøkkel/tid/URL og konfigurert non-discovery source før canonical Document/Evidence skrives. Ingen claim opprettes automatisk av dokument-ingest. Readiness kontrollerer pakket Alembic-head, ikke en hardkodet tidligere migrering.

## Observérbar undersøkelse (AQ-025)

Korrelert passlivssyklus ligger i canonical audit, adskilt fra moduldekning og claimstatus (ADR-020). Detalj-GET leser metadata, moduler, entities, leads, claims/citations, dokument/evidens-tellinger og lagret research-state i ett konsistent snapshot. Web poller aktive pass; source-originaler serveres som hash-verifiserte case-attachments. Et pass uten innvilgede leads gir en ærlig tom-frontier summary. Automatisk planner/router/verifier er fortsatt avgrensede køoppgaver, ikke simulert UI-fremdrift.
